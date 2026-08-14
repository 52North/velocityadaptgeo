"""Recover a LangGraph agent's control flow from its `StateGraph` wiring calls.

`workflow.py` is the most important file in a LangGraph codebase and the least
legible to a call-graph extractor: `graph.add_node("manager", partial(management_node,
llm=llm))` creates a runtime relationship between a *string* and a function, and
`add_conditional_edges` hides the branch set inside a dict literal. Read as source,
that is five lines of setup; read as structure, it is the whole application.
"""

import ast
import logging
from pathlib import Path

from ..model import Edge, Symbol
from . import DetectContext, DetectResult

logger = logging.getLogger("codebase-guide")

WIRING_METHODS = {
    "add_node", "add_edge", "add_conditional_edges", "set_entry_point",
    "set_finish_point", "add_sequence",
}


class LangGraphDetector:
    """Extracts nodes, edges and conditional branches from `StateGraph` construction."""

    name = "langgraph"

    def detect(self, ctx: DetectContext) -> DetectResult:
        """Find every `StateGraph` in the repo and map its topology. See `Detector.detect`."""
        result = DetectResult()
        for path, repo_relative in ctx.files_containing("StateGraph", (".py",)):
            # Per *file*, not per detector. `run_detectors` already isolates detectors,
            # but at that granularity one unreadable wiring call costs the repo every
            # agent node, every flow and every wiring note - a loss visible only in the
            # log, since the index still builds and still answers. Here it costs one file.
            file_result = DetectResult()
            try:
                self._detect_file(ctx, path, repo_relative, file_result)
            except Exception:
                logger.exception("Could not map the graph wired in %s; skipping it", repo_relative)
                continue
            result.symbols.extend(file_result.symbols)
            result.edges.extend(file_result.edges)
            result.notes.extend(file_result.notes)
        return result

    def _detect_file(
        self,
        ctx: DetectContext,
        path: Path,
        repo_relative: str,
        result: DetectResult,
    ) -> None:
        """Parse one file's graph wiring into symbols, edges and a note."""
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            return

        module_qualname = self._module_of(ctx, repo_relative)
        builders = self._builder_variables(tree)
        if not builders:
            return

        nodes: dict[str, str] = {}          # node name → implementing qualname
        flows: list[tuple[str, str, str]] = []  # (src node, dst node, condition)
        entry: str = ""

        for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
            func = call.func
            if not isinstance(func, ast.Attribute) or func.attr not in WIRING_METHODS:
                continue
            if not (isinstance(func.value, ast.Name) and func.value.id in builders):
                continue

            if func.attr == "add_node":
                name, impl = self._node_registration(call)
                if name:
                    nodes[name] = ctx.resolve_suffix(impl) if impl else ""
            elif func.attr == "add_edge":
                # Arity-guarded, because the call does not have to be written the way the
                # examples write it: `add_edge(start_key="a", end_key="b")`,
                # `add_edge(*pair)` and `add_edge(START)` all leave fewer than two
                # positional arguments. An unreadable call is skipped, like every other
                # unreadable argument here - it must not cost the file its whole graph.
                args = call.args[:2]
                if len(args) == 2:
                    src, dst = (self._literal(a) for a in args)
                    if src and dst:
                        flows.append((src, dst, ""))
            elif func.attr == "add_sequence":
                steps = self._sequence_steps(call)
                for step_name, step_impl in steps:
                    if not step_name:
                        continue
                    resolved = ctx.resolve_suffix(step_impl) if step_impl else ""
                    # Never downgrade an implementation an `add_node` call already gave us.
                    if resolved or step_name not in nodes:
                        nodes[step_name] = resolved
                flows.extend(self._sequence_flows(steps))
            elif func.attr == "add_conditional_edges":
                flows.extend(self._conditional_edges(call))
            elif func.attr == "set_entry_point":
                entry = self._literal(call.args[0]) if call.args else ""
            elif func.attr == "set_finish_point":
                if target := (self._literal(call.args[0]) if call.args else ""):
                    flows.append((target, "END", ""))

        if not nodes:
            return

        prefix = f"{module_qualname}#" if module_qualname else "graph#"
        for node_name, impl in sorted(nodes.items()):
            result.symbols.append(self._node_symbol(ctx, prefix, node_name, impl, repo_relative))
            if impl:
                result.edges.append(Edge(
                    src=f"{prefix}{node_name}", dst=impl, kind="implements",
                    detail=f"LangGraph node '{node_name}'",
                ))

        for src, dst, condition in flows:
            if src in nodes and (dst in nodes or dst in ("END", "__end__")):
                result.edges.append(Edge(
                    src=f"{prefix}{src}",
                    dst=f"{prefix}{dst}" if dst in nodes else "END",
                    kind="flows_to",
                    detail=condition,
                ))

        result.notes.append(self._note(repo_relative, entry, nodes, flows))

    def _module_of(self, ctx: DetectContext, repo_relative: str) -> str:
        """Qualname of the module symbol for a file, by its recorded path."""
        for qualname, symbol in ctx.code_map.symbols.items():
            if symbol.kind == "module" and symbol.file == repo_relative:
                return qualname
        return ""

    def _builder_variables(self, tree: ast.AST) -> set[str]:
        """Names assigned a `StateGraph(...)`, so unrelated `.add_edge` calls are ignored."""
        builders: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            callee = node.value.func
            name = callee.id if isinstance(callee, ast.Name) else getattr(callee, "attr", "")
            if name in ("StateGraph", "MessageGraph"):
                builders.update(t.id for t in node.targets if isinstance(t, ast.Name))
        return builders

    def _node_registration(self, call: ast.Call) -> tuple[str, str]:
        """Pull (node name, implementing function name) out of an `add_node` call.

        Unwraps the `partial(fn, llm=llm)` idiom and bare lambdas, because the useful
        answer to "what runs at the manager step" is `management_node`, not `partial`.

        Returns:
            (node name, dotted implementation name); either may be "".
        """
        if not call.args:
            return "", ""
        name = self._literal(call.args[0])
        impl_expr = call.args[1] if len(call.args) > 1 else None
        if impl_expr is None:
            # add_node(fn) - the node takes the function's own name.
            return name, name
        return name, self._callable_name(impl_expr)

    def _callable_name(self, node: ast.expr) -> str:
        """Dotted name of the callable an expression ultimately refers to."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Call):
            callee = self._callable_name(node.func)
            # partial(fn, ...) / functools.partial(fn, ...) - the payload is arg 0.
            if callee in ("partial", "functools.partial") and node.args:
                return self._callable_name(node.args[0])
            return callee
        return ""

    def _sequence_steps(self, call: ast.Call) -> list[tuple[str, str]]:
        """Read the ordered steps out of an `add_sequence([...])` call.

        The idiom accepts bare callables, `(name, callable)` pairs, or node names already
        registered elsewhere, and names a bare callable after the function itself - the
        same convention `add_node(fn)` follows. A list built somewhere else
        (`add_sequence(steps)`) is not read at all: a lone `Name` argument is a variable,
        and guessing it is a step would invent a node that does not exist.

        Args:
            call: The `add_sequence` call node.

        Returns:
            (node name, implementation name) per step, in declaration order. Either half
            may be "" when the element cannot be read.
        """
        if not call.args:
            return []
        first = call.args[0]
        if isinstance(first, (ast.List, ast.Tuple)):
            elements = list(first.elts)
        elif len(call.args) > 1:
            elements = list(call.args)
        else:
            return []

        steps: list[tuple[str, str]] = []
        for element in elements:
            if isinstance(element, ast.Tuple) and len(element.elts) == 2:
                steps.append((
                    self._literal(element.elts[0]),
                    self._callable_name(element.elts[1]),
                ))
            elif name := self._literal(element):
                steps.append((name, ""))
            else:
                impl = self._callable_name(element)
                steps.append((impl, impl))
        return steps

    def _sequence_flows(self, steps: list[tuple[str, str]]) -> list[tuple[str, str, str]]:
        """Chain the steps of an `add_sequence` into flow edges.

        `add_sequence` both registers its steps and runs them in the order given, so that
        order is real control flow, and this call is the only place it is written down.
        Consecutive steps are joined only when both are readable: skipping over a step
        nobody can see would assert a hand-off that may not exist.
        """
        flows: list[tuple[str, str, str]] = []
        for (src, _), (dst, _) in zip(steps, steps[1:]):
            if src and dst:
                flows.append((src, dst, "in sequence"))
        return flows

    def _conditional_edges(self, call: ast.Call) -> list[tuple[str, str, str]]:
        """Expand `add_conditional_edges(src, router, {branch: dst})` into flow edges.

        The mapping keys are the router's return values, kept as the edge's `detail`
        so the guide can say *why* a branch is taken, not just that it exists.
        """
        if not call.args:
            return []
        src = self._literal(call.args[0])
        router = self._callable_name(call.args[1]) if len(call.args) > 1 else ""
        mapping = call.args[2] if len(call.args) > 2 else None
        if not (src and isinstance(mapping, ast.Dict)):
            return []

        flows: list[tuple[str, str, str]] = []
        for key, value in zip(mapping.keys, mapping.values):
            branch = self._literal(key) if key is not None else ""
            dst = self._literal(value)
            if dst:
                label = f"when {router} returns '{branch}'" if branch else f"via {router}"
                flows.append((src, dst, label))
        return flows

    def _literal(self, node: ast.expr | None) -> str:
        """String value of a literal or a well-known sentinel (`END`)."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name) and node.id in ("END", "START"):
            return node.id
        if isinstance(node, ast.Attribute) and node.attr in ("END", "START"):
            return node.attr
        return ""

    def _node_symbol(
        self,
        ctx: DetectContext,
        prefix: str,
        node_name: str,
        impl: str,
        file: str,
    ) -> Symbol:
        """Build the searchable symbol for one agent node.

        The implementation's own docstring is copied in so the node is findable by
        what it *does*: a user asking "which step picks the OGC process" should reach
        the `retriever` node, and only `retriever_node`'s docstring says that.
        """
        impl_symbol = ctx.code_map.symbols.get(impl)
        doc = f"LangGraph agent node '{node_name}'."
        if impl_symbol:
            doc += f" Implemented by {impl}."
            if impl_symbol.doc:
                doc += f"\n\n{impl_symbol.doc}"
        return Symbol(
            qualname=f"{prefix}{node_name}",
            kind="agent_node",
            name=node_name,
            file=impl_symbol.file if impl_symbol else file,
            lineno=impl_symbol.lineno if impl_symbol else 1,
            doc=doc,
            signature=f"agent node '{node_name}'",
            tags=["langgraph", "agent-node"],
            extra={"implementation": impl},
        )

    def _note(
        self,
        repo_relative: str,
        entry: str,
        nodes: dict[str, str],
        flows: list[tuple[str, str, str]],
    ) -> str:
        """Render the graph as prose for the architecture digest."""
        lines = [f"Agent graph wired in {repo_relative}:"]
        if entry:
            lines.append(f"  entry point: {entry}")
        for node_name, impl in sorted(nodes.items()):
            lines.append(f"  node {node_name} -> {impl or '(implementation unresolved)'}")
        for src, dst, condition in flows:
            suffix = f"  [{condition}]" if condition else ""
            lines.append(f"  {src} => {dst}{suffix}")
        return "\n".join(lines)
