"""The tools the guide agent uses to look things up.

Five tools, split along the line the whole module is built on: `search_code` finds
where to look (semantics, from doc comments), and `explain_symbol` / `trace_flow` /
`list_module` say how things connect (structure, from the graph). `architecture_overview`
exists so the agent can re-read its briefing after a long conversation.

Every tool returns formatted text rather than JSON. The output is read by an LLM that
then paraphrases it for a newcomer, and prose with locations survives that second pass
better than nested objects do.

Built through a factory rather than declared at module level so a single process can
serve several repositories, each with its own index.
"""

from langchain_core.tools import tool

from .index import GuideIndex

# Beyond this, an "explain" answer stops being an explanation and becomes a dump.
MAX_DOC_CHARS = 1600
MAX_NEIGHBOURS_PER_KIND = 12

_EDGE_PHRASING = {
    "calls": "calls",
    "contains": "contains",
    "imports": "imports",
    "inherits": "inherits from",
    "flows_to": "hands control to",
    "implements": "is implemented by",
    "registers": "registers",
}

_INBOUND_PHRASING = {
    "calls": "called by",
    "contains": "defined in",
    "imports": "imported by",
    "inherits": "subclassed by",
    "flows_to": "reached from",
    "implements": "implements",
    "registers": "registered by",
}


def build_guide_tools(index: GuideIndex) -> list:
    """Create the tool set bound to one repository's index.

    Args:
        index: The open index to query.

    Returns:
        LangChain tools, ready to hand to a `ToolNode`.
    """

    def _clip(text: str, limit: int = MAX_DOC_CHARS) -> str:
        """Truncate long doc comments, saying so rather than trailing off silently."""
        text = (text or "").strip()
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + f"\n[... doc comment truncated at {limit} chars]"

    def _resolve_one(name: str) -> tuple[str, str]:
        """Resolve a user-supplied name to one qualname.

        Returns:
            (qualname, error message). Exactly one of the two is non-empty. Ambiguity
            is reported back as candidates instead of being silently resolved to the
            first match - guessing here is how a guide ends up explaining the wrong
            function with total confidence.
        """
        matches = index.code_map.resolve(name)
        if not matches:
            hits = index.search(name, k=5)
            if hits:
                suggestions = "\n".join(
                    f"- {h.symbol.qualname} ({h.symbol.kind}) - {h.symbol.summary}"
                    for h in hits
                )
                return "", f"No symbol named '{name}'. Closest by meaning:\n{suggestions}"
            return "", f"No symbol named '{name}' in {index.repo_name}."
        if len(matches) > 1:
            listed = "\n".join(
                f"- {m} ({index.code_map.symbols[m].kind}) - "
                f"{index.code_map.symbols[m].summary}"
                for m in matches[:10]
            )
            return "", (
                f"'{name}' is ambiguous - {len(matches)} matches. "
                f"Call this tool again with one of:\n{listed}"
            )
        return matches[0], ""

    def _describe(qualname: str) -> list[str]:
        """Header lines for a symbol: what it is, where it lives, what it says."""
        symbol = index.code_map.symbols[qualname]
        lines = [f"# {symbol.qualname}", f"kind: {symbol.kind}"]
        if symbol.location:
            lines.append(f"defined at: {symbol.location}")
        if symbol.signature:
            lines.append(f"signature: {symbol.signature}")
        if symbol.tags:
            lines.append(f"tags: {', '.join(symbol.tags)}")
        if symbol.extra:
            details = ", ".join(f"{k}={v}" for k, v in symbol.extra.items())
            lines.append(f"details: {details}")
        lines.append("")
        lines.append(_clip(symbol.doc) or "(no doc comment - intent is not documented)")
        return lines

    @tool
    def architecture_overview() -> str:
        """Get the architecture briefing for this codebase: components, wiring, entry points.

        Use this first when the question is broad ("what does this project do", "how is
        it structured", "where do I start"), or to re-orient after a long conversation.
        Covers the top-level layout, how the frameworks are wired together, the most
        depended-on modules, and where documentation is missing.
        """
        header = (
            f"Index backend: {index.backend}. "
            f"Doc comments are the source of every explanation below.\n\n"
        )
        return header + (index.digest or "No architecture digest available.")

    @tool
    def search_code(query: str, kind: str = "", limit: int = 8) -> str:
        """Find the parts of the codebase that deal with a topic, by meaning.

        Searches doc comments, names and signatures - not source bodies. Ask in the
        user's own words ("where are user uploads validated", "how are processes
        registered"), not with an exact identifier; use explain_symbol when you already
        know the name.

        Args:
            query: What you are looking for, in natural language.
            kind: Optional filter. One of module, class, function, method, agent_node,
                ogc_process, http_route. Empty means all kinds.
            limit: Maximum results, default 8.

        Returns:
            Ranked matches with kind, location and summary.
        """
        kinds = (kind,) if kind else None
        hits = index.search(query, k=max(1, min(limit, 25)), kinds=kinds)
        if not hits:
            # The backend is named even when nothing matched: an empty result from a
            # degraded lexical fallback means something different to the model than an
            # empty result from the vector index, and this is where it can tell.
            return (
                f"Nothing matched '{query}'"
                + (f" with kind '{kind}'" if kind else "")
                + f" (backend: {index.backend})."
                + " Try broader wording, or architecture_overview for the layout."
            )

        lines = [f"{len(hits)} matches for '{query}' (backend: {index.backend}):", ""]
        for hit in hits:
            symbol = hit.symbol
            lines.append(f"- {symbol.qualname} [{symbol.kind}] {symbol.location}")
            lines.append(f"  {symbol.summary}")
        lines.append("")
        lines.append("Call explain_symbol on any of these to see what it connects to.")
        return "\n".join(lines)

    @tool
    def explain_symbol(name: str) -> str:
        """Explain one symbol: its doc comment, and everything it is wired to.

        This is the tool that answers "what is this and how does it fit in". It returns
        the doc comment plus the neighbourhood from the code graph - callers, callees,
        contained members, base classes, and framework-level relationships such as which
        agent node runs next or which config entry registers it.

        Args:
            name: Qualified name, or just the identifier (e.g. `retriever_node`).

        Returns:
            The symbol's documentation and its connections.
        """
        qualname, error = _resolve_one(name)
        if error:
            return error

        lines = _describe(qualname)
        symbol = index.code_map.symbols[qualname]

        members = index.code_map.children(qualname)
        if members:
            lines.append("")
            lines.append(f"## Defines ({len(members)})")
            for member in members[:MAX_NEIGHBOURS_PER_KIND * 2]:
                lines.append(f"- {member.name} [{member.kind}] - {member.summary}")
            if len(members) > MAX_NEIGHBOURS_PER_KIND * 2:
                lines.append(f"- ... {len(members) - MAX_NEIGHBOURS_PER_KIND * 2} more")

        hood = index.code_map.neighborhood(qualname)
        lines.extend(_render_relations("## Outgoing", hood["outgoing"], _EDGE_PHRASING))
        lines.extend(_render_relations("## Incoming", hood["incoming"], _INBOUND_PHRASING))

        if symbol.kind != "module":
            owner = index.code_map.owning_module(qualname)
            if owner and owner != qualname:
                lines.append("")
                lines.append(f"Lives in module {owner}.")
        return "\n".join(lines)

    def _render_relations(heading: str, groups: dict, phrasing: dict) -> list[str]:
        """Format one direction of a neighbourhood, skipping `contains` (shown above)."""
        lines: list[str] = []
        for edge_kind, entries in sorted(groups.items()):
            if edge_kind == "contains":
                continue
            if not lines:
                lines.extend(["", heading])
            label = phrasing.get(edge_kind, edge_kind)
            lines.append(f"{label}:")
            merged = _merge_by_target(entries)
            for entry in merged[:MAX_NEIGHBOURS_PER_KIND]:
                detail = f" ({'; '.join(entry['details'])})" if entry["details"] else ""
                location = f" {entry['location']}" if entry["location"] else ""
                lines.append(
                    f"- {entry['qualname']}{detail}{location} - {entry['summary']}"
                )
            if len(merged) > MAX_NEIGHBOURS_PER_KIND:
                lines.append(f"- ... {len(merged) - MAX_NEIGHBOURS_PER_KIND} more")
        return lines

    def _merge_by_target(entries: list[dict]) -> list[dict]:
        """Collapse repeated edges to the same symbol into one line.

        A function called from three places yields three `calls` edges differing only in
        call site. Listed separately they read as three different relationships and eat
        the per-kind display budget, so the call sites are folded into one entry.
        """
        merged: dict[str, dict] = {}
        for entry in entries:
            target = merged.setdefault(
                entry["qualname"],
                {
                    "qualname": entry["qualname"],
                    "summary": entry["summary"],
                    "location": entry["location"],
                    "details": [],
                },
            )
            detail = entry.get("detail", "")
            if detail and detail not in target["details"]:
                target["details"].append(detail)
        return list(merged.values())

    @tool
    def trace_flow(start: str, end: str) -> str:
        """Trace how control gets from one symbol to another, step by step.

        Use this for "what happens when..." questions that span several modules - an
        HTTP request reaching the database, a user message reaching a particular agent
        node. Follows calls, framework control flow, and registration links; deliberately
        ignores imports and containment, which connect almost everything to everything.

        Args:
            start: Where the flow begins (e.g. an entry point or route handler).
            end: Where it should arrive.

        Returns:
            The chain of steps, or an explanation of why none was found.
        """
        src, error = _resolve_one(start)
        if error:
            return error
        dst, error = _resolve_one(end)
        if error:
            return error
        if src == dst:
            return f"{src} is both ends of the trace."

        path = index.code_map.shortest_path(src, dst)
        if not path:
            reverse = index.code_map.shortest_path(dst, src)
            if reverse:
                return (
                    f"No path from {src} to {dst}, but control does flow the other way "
                    f"({dst} -> {src}). Re-run trace_flow with the arguments swapped."
                )
            return (
                f"No traced path from {src} to {dst}. They may be connected only "
                "through dynamic dispatch, configuration, or a call this indexer could "
                "not resolve unambiguously - explain_symbol on each end will show what "
                "each one is actually wired to."
            )

        lines = [f"{len(path)} steps from {src} to {dst}:", ""]
        for step, edge in enumerate(path, start=1):
            target = index.code_map.symbols.get(edge.dst)
            verb = _EDGE_PHRASING.get(edge.kind, edge.kind)
            detail = f" [{edge.detail}]" if edge.detail else ""
            lines.append(f"{step}. {edge.src}\n   {verb}{detail} -> {edge.dst}")
            if target:
                location = f" ({target.location})" if target.location else ""
                lines.append(f"   {target.summary}{location}")
        return "\n".join(lines)

    @tool
    def list_module(name: str) -> str:
        """List what a module or package contains, and what it depends on.

        Use when the user asks "what is in this file" or you need the members of a module
        you have already located.

        Args:
            name: Module qualname or file-ish name (e.g. `workflow` or `llm.workflow`).

        Returns:
            The module's doc comment, its members, and its import relationships.
        """
        matches = [
            q for q in index.code_map.resolve(name)
            if index.code_map.symbols[q].kind == "module"
        ]
        if not matches:
            other = index.code_map.resolve(name)
            if other:
                return (
                    f"'{name}' is not a module. Matching symbols: "
                    + ", ".join(other[:8])
                    + ". Use explain_symbol for those."
                )
            return f"No module matched '{name}' in {index.repo_name}."
        if len(matches) > 1:
            listed = "\n".join(f"- {m}" for m in matches[:10])
            return f"'{name}' matches several modules:\n{listed}"

        qualname = matches[0]
        lines = _describe(qualname)

        members = index.code_map.children(qualname)
        lines.append("")
        lines.append(f"## Members ({len(members)})")
        for member in members:
            signature = f" {member.signature}" if member.signature else ""
            lines.append(f"- [{member.kind}] {member.name}{signature}")
            lines.append(f"  {member.summary}")
            for nested in index.code_map.children(member.qualname):
                lines.append(f"    - {nested.name} - {nested.summary}")

        imports = index.code_map.out_edges(qualname, ("imports",))
        if imports:
            lines.append("")
            lines.append("## Imports from this repo")
            lines.extend(f"- {e.dst}" for e in sorted(imports, key=lambda e: e.dst))

        importers = index.code_map.in_edges(qualname, ("imports",))
        if importers:
            lines.append("")
            lines.append(f"## Imported by ({len(importers)})")
            lines.extend(
                f"- {e.src}" for e in sorted(importers, key=lambda e: e.src)[:15]
            )
        return "\n".join(lines)

    return [architecture_overview, search_code, explain_symbol, trace_flow, list_module]
