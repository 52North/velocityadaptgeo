"""Python extractor: docstrings and structure from the AST, never the source body.

Two-phase by necessity. `parse` sees one file and cannot know whether
`from src.llm.state.state import WorkflowState` refers to something in this repo -
that needs the full symbol table, so it is deferred to `link`.
"""

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..model import Edge, Symbol
from . import FileParse

logger = logging.getLogger("codebase-guide")

# Decorators worth tagging: they change what a symbol *is* to a reader, which is
# exactly the sort of thing a new colleague needs pointed out.
NOTABLE_DECORATORS = {
    "tool": "llm-tool",
    "app.get": "http-route",
    "app.post": "http-route",
    "router.get": "http-route",
    "router.post": "http-route",
    "property": "property",
    "staticmethod": "staticmethod",
    "classmethod": "classmethod",
    "dataclass": "dataclass",
    "lru_cache": "cached",
    "pytest.fixture": "test-fixture",
}


@dataclass
class ImportRef:
    """One import statement, still written in the importing file's own terms."""

    importer: str
    dotted: str
    level: int
    names: list[tuple[str, str]] = field(default_factory=list)
    lineno: int = 0


@dataclass
class CallRef:
    """A call site: who calls, and the callee as written (`base.attr` or `name`)."""

    caller: str
    base: str
    attr: str
    lineno: int = 0
    enclosing_class: str = ""


@dataclass
class BaseRef:
    """A class's declared base, as written."""

    subclass: str
    base_name: str


class PythonExtractor:
    """Extracts modules, classes, functions, methods and their relationships."""

    name = "python"
    suffixes = (".py",)

    def parse(self, path: Path, repo_relative: str) -> FileParse:
        """Parse one Python file. See `Extractor.parse`."""
        result = FileParse(path=repo_relative)
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError, ValueError) as exc:
            result.errors.append(f"{repo_relative}: {exc}")
            return result

        module_qualname, is_package = self._module_qualname(repo_relative)
        result.module_qualname = module_qualname

        module_symbol = Symbol(
            qualname=module_qualname,
            kind="module",
            name=module_qualname.rsplit(".", 1)[-1],
            file=repo_relative,
            lineno=1,
            doc=ast.get_docstring(tree) or "",
            extra={"is_package": is_package},
        )
        result.symbols.append(module_symbol)

        imports: list[ImportRef] = []
        calls: list[CallRef] = []
        bases: list[BaseRef] = []

        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.append(self._import_ref(module_qualname, node))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._add_function(result, calls, module_qualname, node, repo_relative)
            elif isinstance(node, ast.ClassDef):
                self._add_class(result, calls, bases, module_qualname, node, repo_relative)

        result.refs = {"imports": imports, "calls": calls, "bases": bases}
        return result

    # ------------------------------------------------------------------ parsing

    def _module_qualname(self, repo_relative: str) -> tuple[str, bool]:
        """Derive a dotted module name from a repo-relative path.

        `pkg/sub/__init__.py` becomes `pkg.sub` and is flagged as a package, so
        relative imports inside it resolve against itself rather than its parent.

        Rooted at the repo rather than at the source root, because two source roots in
        one repo can hold the same inner path - `LangGraph/src` and `ogc_database/src`
        would otherwise both claim the qualname `src`. Import statements written in
        source-root terms are reconnected by `_resolve_module`'s suffix matching.

        Args:
            repo_relative: POSIX path relative to the repository root.

        Returns:
            (dotted module name, is_package).
        """
        parts = Path(repo_relative).with_suffix("").as_posix().split("/")
        is_package = parts[-1] == "__init__"
        if is_package:
            parts = parts[:-1] or ["__init__"]
        return ".".join(p for p in parts if p and p != "."), is_package

    def _add_function(
        self,
        result: FileParse,
        calls: list[CallRef],
        parent_qualname: str,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        file: str,
        kind: str = "function",
        enclosing_class: str = "",
    ) -> None:
        """Record a function or method plus the calls in its body."""
        qualname = f"{parent_qualname}.{node.name}"
        decorators = [self._decorator_name(d) for d in node.decorator_list]
        tags = [NOTABLE_DECORATORS[d] for d in decorators if d in NOTABLE_DECORATORS]
        if isinstance(node, ast.AsyncFunctionDef):
            tags.append("async")

        result.symbols.append(Symbol(
            qualname=qualname,
            kind=kind,
            name=node.name,
            file=file,
            lineno=node.lineno,
            doc=ast.get_docstring(node) or "",
            signature=self._signature(node),
            decorators=[d for d in decorators if d],
            tags=tags,
        ))
        result.edges.append(Edge(src=parent_qualname, dst=qualname, kind="contains"))
        calls.extend(self._call_refs(qualname, node, enclosing_class))

    def _add_class(
        self,
        result: FileParse,
        calls: list[CallRef],
        bases: list[BaseRef],
        module_qualname: str,
        node: ast.ClassDef,
        file: str,
    ) -> None:
        """Record a class, its declared bases, and its methods."""
        qualname = f"{module_qualname}.{node.name}"
        base_names = [self._decorator_name(b) for b in node.bases]
        decorators = [self._decorator_name(d) for d in node.decorator_list]

        result.symbols.append(Symbol(
            qualname=qualname,
            kind="class",
            name=node.name,
            file=file,
            lineno=node.lineno,
            doc=ast.get_docstring(node) or "",
            signature=f"class {node.name}({', '.join(b for b in base_names if b)})",
            decorators=[d for d in decorators if d],
            tags=[NOTABLE_DECORATORS[d] for d in decorators if d in NOTABLE_DECORATORS],
            extra={"bases": [b for b in base_names if b]},
        ))
        result.edges.append(Edge(src=module_qualname, dst=qualname, kind="contains"))

        for base in base_names:
            if base:
                bases.append(BaseRef(subclass=qualname, base_name=base))

        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._add_function(
                    result, calls, qualname, child, file,
                    kind="method", enclosing_class=qualname,
                )

    def _signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        """Render a def line without its body.

        Built by unparsing a stub node so defaults, `*args`, keyword-only arguments
        and annotations come out exactly as written, rather than approximated.

        Args:
            node: The function definition.

        Returns:
            e.g. `async def retriever_node(state: WorkflowState, llm) -> dict`.
        """
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        try:
            stub = ast.FunctionDef(
                name=node.name,
                args=node.args,
                body=[ast.Pass()],
                decorator_list=[],
                returns=node.returns,
                type_comment=None,
                type_params=[],
            )
            rendered = ast.unparse(ast.fix_missing_locations(stub)).splitlines()[0]
            return f"{prefix}{rendered.removeprefix('def').rstrip(':')}"
        except Exception:  # pragma: no cover - unparse is best-effort only
            args = [a.arg for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs]
            return f"{prefix} {node.name}({', '.join(args)})"

    def _decorator_name(self, node: ast.expr) -> str:
        """Dotted name of a decorator, base class, or callee expression."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = self._decorator_name(node.value)
            return f"{base}.{node.attr}" if base else node.attr
        if isinstance(node, ast.Call):
            return self._decorator_name(node.func)
        if isinstance(node, ast.Subscript):
            return self._decorator_name(node.value)
        return ""

    def _import_ref(self, importer: str, node: ast.Import | ast.ImportFrom) -> ImportRef:
        """Normalise `import x` and `from x import y` into one record shape."""
        if isinstance(node, ast.Import):
            return ImportRef(
                importer=importer,
                dotted="",
                level=0,
                names=[(a.name, a.asname or a.name.split(".")[0]) for a in node.names],
                lineno=node.lineno,
            )
        return ImportRef(
            importer=importer,
            dotted=node.module or "",
            level=node.level or 0,
            names=[(a.name, a.asname or a.name) for a in node.names],
            lineno=node.lineno,
        )

    def _call_refs(
        self,
        caller: str,
        node: ast.AST,
        enclosing_class: str,
    ) -> list[CallRef]:
        """Collect call sites in a function body.

        Calls inside nested closures are attributed to the enclosing named function:
        the closure is an implementation detail, but the dependency it creates is not.
        """
        refs: list[CallRef] = []
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            func = child.func
            if isinstance(func, ast.Name):
                refs.append(CallRef(caller, "", func.id, child.lineno, enclosing_class))
            elif isinstance(func, ast.Attribute):
                base = func.value.id if isinstance(func.value, ast.Name) else ""
                refs.append(CallRef(caller, base, func.attr, child.lineno, enclosing_class))
        return refs

    # ------------------------------------------------------------------ linking

    def link(self, symbols: dict[str, Symbol], parses: list[FileParse]) -> list[Edge]:
        """Resolve imports, calls and bases against the symbol table. See `Extractor.link`."""
        modules = {q for q, s in symbols.items() if s.kind == "module"}
        packages = {q for q in modules if symbols[q].extra.get("is_package")}
        simple_names = self._simple_name_index(symbols)

        edges: list[Edge] = []
        for parse in parses:
            aliases = self._alias_map(parse, symbols, modules, packages, edges)
            edges.extend(self._call_edges(parse, symbols, aliases, simple_names))
            edges.extend(self._base_edges(parse, symbols, aliases, simple_names))
        return edges

    def _simple_name_index(self, symbols: dict[str, Symbol]) -> dict[str, list[str]]:
        """Bare identifier → qualnames, for resolving a call with no import in scope."""
        index: dict[str, list[str]] = {}
        for qualname, symbol in symbols.items():
            if symbol.kind in ("function", "class", "method"):
                index.setdefault(symbol.name, []).append(qualname)
        return index

    def _resolve_module(self, dotted: str, modules: set[str], importer: str = "") -> str:
        """Match an import path to a module in this repo.

        Suffix matching is what makes multi-root repos work: code under `LangGraph/`
        imports `src.llm.state.state` because `LangGraph/` is its `PYTHONPATH`, while
        the map keys that module as `LangGraph.src.llm.state.state`.

        It is also how two source roots collide. `src.config` is a module under both
        `ogc_database/` and `codebase_guide/`, and picking the shortest name hands every
        importer in the repo the same one - the same wrong target for all of them. The
        importer's own root decides instead, since that is the root on its `PYTHONPATH`.
        When no candidate shares it and there is more than one, the import is genuinely
        ambiguous and nothing is emitted: a wrong `imports` edge is not a harmless guess,
        it feeds `importance()` and therefore what the briefing calls a key module.

        Args:
            dotted: Import path as written.
            modules: Every module qualname in the repo.
            importer: Qualname of the importing module. Its first segment is the source
                root the import is written against.

        Returns:
            The matched qualname, or "" when the import is external or ambiguous.
        """
        if not dotted:
            return ""
        if dotted in modules:
            return dotted
        suffix = "." + dotted
        candidates = [m for m in modules if m.endswith(suffix)]
        if len(candidates) < 2:
            return candidates[0] if candidates else ""
        root = importer.split(".")[0]
        # Shortest within the importer's own root: still prefers the real module there
        # over a deeper accidental match, which is what the old heuristic was for.
        same_root = [m for m in candidates if m.split(".")[0] == root]
        return min(same_root, key=len) if same_root else ""

    def _resolve_relative(
        self,
        importer: str,
        dotted: str,
        level: int,
        modules: set[str],
        packages: set[str],
    ) -> str:
        """Resolve `from . import x` / `from ..pkg import y` to an absolute qualname."""
        base_parts = importer.split(".")
        if importer not in packages and base_parts:
            base_parts = base_parts[:-1]
        if level > 1:
            base_parts = base_parts[: -(level - 1)] if level - 1 < len(base_parts) else []
        absolute = ".".join([*base_parts, *([dotted] if dotted else [])])
        return self._resolve_module(absolute, modules, importer)

    def _alias_map(
        self,
        parse: FileParse,
        symbols: dict[str, Symbol],
        modules: set[str],
        packages: set[str],
        edges: list[Edge],
    ) -> dict[str, str]:
        """Map each name bound by an import to the repo qualname it refers to.

        Emits the `imports` edges as a side effect, since both come from resolving the
        same statements.

        Returns:
            Local binding name → qualname of a module or symbol in this repo.
        """
        aliases: dict[str, str] = {}
        for ref in parse.refs.get("imports", []):
            if ref.dotted or ref.level:
                target_module = (
                    self._resolve_relative(ref.importer, ref.dotted, ref.level, modules, packages)
                    if ref.level
                    else self._resolve_module(ref.dotted, modules, ref.importer)
                )
                if not target_module:
                    continue
                edges.append(Edge(
                    src=ref.importer, dst=target_module, kind="imports",
                    detail=f"line {ref.lineno}",
                ))
                for name, local in ref.names:
                    member = f"{target_module}.{name}"
                    submodule = self._resolve_module(
                        f"{ref.dotted}.{name}" if ref.dotted else name, modules, ref.importer
                    )
                    if member in symbols:
                        aliases[local] = member
                    elif submodule:
                        aliases[local] = submodule
                        edges.append(Edge(src=ref.importer, dst=submodule, kind="imports"))
            else:
                # Plain `import a.b.c [as d]`
                for name, local in ref.names:
                    target_module = self._resolve_module(name, modules, ref.importer)
                    if target_module:
                        aliases[local] = target_module
                        edges.append(Edge(
                            src=ref.importer, dst=target_module, kind="imports",
                            detail=f"line {ref.lineno}",
                        ))
        return aliases

    def _resolve_callee(
        self,
        ref: CallRef,
        module_qualname: str,
        symbols: dict[str, Symbol],
        aliases: dict[str, str],
        simple_names: dict[str, list[str]],
    ) -> str:
        """Best-effort resolution of one call site to a repo symbol.

        Strict tiers first, guessing last: a name imported into this file beats a
        same-module definition, which beats a globally unique name. An ambiguous bare
        name resolves to nothing rather than to a plausible wrong edge - a guide that
        confidently states the wrong caller is worse than one that says nothing.

        Returns:
            Qualname of the callee, or "" when unresolvable or external.
        """
        if ref.base == "self" and ref.enclosing_class:
            candidate = f"{ref.enclosing_class}.{ref.attr}"
            if candidate in symbols:
                return candidate
            for base in symbols[ref.enclosing_class].extra.get("bases", []):
                resolved_base = aliases.get(base) or ""
                if resolved_base and f"{resolved_base}.{ref.attr}" in symbols:
                    return f"{resolved_base}.{ref.attr}"
            return ""

        if ref.base:
            target = aliases.get(ref.base)
            if target:
                candidate = f"{target}.{ref.attr}"
                if candidate in symbols:
                    return candidate
            return ""

        if ref.attr in aliases and aliases[ref.attr] in symbols:
            return aliases[ref.attr]

        candidate = f"{module_qualname}.{ref.attr}"
        if candidate in symbols:
            return candidate

        matches = simple_names.get(ref.attr, [])
        return matches[0] if len(matches) == 1 else ""

    def _call_edges(
        self,
        parse: FileParse,
        symbols: dict[str, Symbol],
        aliases: dict[str, str],
        simple_names: dict[str, list[str]],
    ) -> list[Edge]:
        """Resolve every call site in one file into `calls` edges."""
        edges: list[Edge] = []
        for ref in parse.refs.get("calls", []):
            dst = self._resolve_callee(ref, parse.module_qualname, symbols, aliases, simple_names)
            if dst and dst != ref.caller and symbols[dst].kind != "module":
                edges.append(Edge(
                    src=ref.caller, dst=dst, kind="calls", detail=f"line {ref.lineno}",
                ))
        return edges

    def _base_edges(
        self,
        parse: FileParse,
        symbols: dict[str, Symbol],
        aliases: dict[str, str],
        simple_names: dict[str, list[str]],
    ) -> list[Edge]:
        """Resolve declared base classes into `inherits` edges."""
        edges: list[Edge] = []
        for ref in parse.refs.get("bases", []):
            head = ref.base_name.split(".")[0]
            dst = aliases.get(ref.base_name) or aliases.get(head) or ""
            if dst not in symbols:
                matches = simple_names.get(ref.base_name.split(".")[-1], [])
                dst = matches[0] if len(matches) == 1 else ""
            if dst in symbols and symbols[dst].kind == "class":
                edges.append(Edge(src=ref.subclass, dst=dst, kind="inherits"))
        return edges
