"""Find the doors into the system: HTTP routes and runnable scripts.

"Where does a request actually enter?" is the first question a new colleague asks and
the one a docstring index answers worst, because a route handler's docstring describes
what it computes, never that it is reachable at `POST /chat`. The URL lives in a
decorator argument.
"""

import ast
from pathlib import Path

from ..model import Edge, Symbol
from . import DetectContext, DetectResult

ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "route"}

# Calls creating something routes are declared on whose prefix is spelled `prefix=`.
# Deliberately short: a framework whose prefix is spelled differently (Flask's
# `url_prefix`, set at registration) would otherwise resolve to "no prefix" and have its
# paths presented as absolute, which is exactly the failure being fixed here. Unknown
# routers fall through to the router-relative label instead.
ROUTER_FACTORIES = {"APIRouter", "FastAPI"}

# Appended wherever a path is known only relative to its router. Presenting a relative
# path as absolute is the worse failure: the reader cannot tell that it needs completing.
RELATIVE_LABEL = "(path is relative to its router)"


class EntrypointDetector:
    """Detects HTTP route handlers and `__main__` script entry points."""

    name = "entrypoints"

    def detect(self, ctx: DetectContext) -> DetectResult:
        """Scan Python files for routes and main guards. See `Detector.detect`."""
        result = DetectResult()
        routes: list[tuple[str, str, str, bool]] = []
        scripts: list[str] = []

        for path, repo_relative, _ in ctx.files:
            if path.suffix != ".py":
                continue
            tree = self._parse(path)
            if tree is None:
                continue
            module_qualname = self._module_of(ctx, repo_relative)
            routes.extend(self._routes(ctx, tree, module_qualname, result))
            if self._has_main_guard(tree):
                scripts.append(repo_relative)

        if routes:
            lines = ["HTTP entry points:"]
            lines += [
                f"  {method} {route} -> {handler}" + (f"  {RELATIVE_LABEL}" if relative else "")
                for method, route, handler, relative in sorted(routes, key=lambda r: r[1])
            ]
            result.notes.append("\n".join(lines))
        if scripts:
            result.notes.append(
                "Runnable as a script (has a __main__ guard): " + ", ".join(sorted(scripts))
            )
        return result

    def _parse(self, path: Path) -> ast.AST | None:
        """Parse a file, returning None when it cannot be read or parsed."""
        try:
            return ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            return None

    def _module_of(self, ctx: DetectContext, repo_relative: str) -> str:
        """Qualname of the module symbol recorded for a file."""
        for qualname, symbol in ctx.code_map.symbols.items():
            if symbol.kind == "module" and symbol.file == repo_relative:
                return qualname
        return ""

    def _routes(
        self,
        ctx: DetectContext,
        tree: ast.AST,
        module_qualname: str,
        result: DetectResult,
    ) -> list[tuple[str, str, str, bool]]:
        """Find decorated route handlers and tag their symbols with the URL.

        Returns:
            (HTTP method, path, handler qualname, path-is-router-relative) per route.
        """
        prefixes = self._router_prefixes(tree)
        found: list[tuple[str, str, str, bool]] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                route = self._route_of(decorator)
                if route is None:
                    continue
                router, method, path = route
                # A router declared elsewhere, or mounted under a computed prefix, leaves
                # the real URL unknowable from this file. Say so rather than guessing.
                relative = router not in prefixes
                url = path if relative else self._join(prefixes[router], path)
                handler = f"{module_qualname}.{node.name}" if module_qualname else node.name
                symbol = ctx.code_map.symbols.get(handler)
                if symbol is not None:
                    tags = {"http-route", "entrypoint"} | ({"router-relative"} if relative else set())
                    symbol.tags = sorted(set(symbol.tags) | tags)
                    symbol.extra["http"] = f"{method} {url}"
                    if relative:
                        symbol.extra["path_kind"] = "router-relative"
                    result.edges.append(Edge(
                        src=f"http:{method} {url}", dst=handler, kind="registers",
                        detail="HTTP route" + (f" {RELATIVE_LABEL}" if relative else ""),
                    ))
                    result.symbols.append(Symbol(
                        qualname=f"http:{method} {url}",
                        kind="http_route",
                        name=f"{method} {url}",
                        file=symbol.file,
                        lineno=symbol.lineno,
                        doc=f"HTTP {method} {url}, handled by {handler}."
                            + (f" Declared on the router `{router}`, whose mount prefix is "
                               f"not visible in {symbol.file}, so the full URL adds "
                               "whatever prefix it is mounted under." if relative else "")
                            + (f"\n\n{symbol.doc}" if symbol.doc else ""),
                        signature=f"{method} {url}" + (f" {RELATIVE_LABEL}" if relative else ""),
                        tags=sorted(tags),
                        extra={"handler": handler, "router": router,
                               "path_kind": "router-relative" if relative else "absolute"},
                    ))
                found.append((method, url, handler, relative))
        return found

    def _router_prefixes(self, tree: ast.AST) -> dict[str, str]:
        """Map each router or app variable in this file to the prefix its routes carry.

        A route path is written relative to its router: `APIRouter(prefix="/guide")` plus
        `@router.post("/ask")` serves `/guide/ask`. Reading the decorator alone yields
        `/ask`, which 404s - and it is quoted with a `file:line` citation, so it reads as
        verified. Only what this file states is trusted; a variable missing from the result
        is one whose prefix could not be determined, not one with no prefix.

        Args:
            tree: Parsed module.

        Returns:
            Variable name → prefix (possibly ""), for routers whose prefix is readable.
        """
        prefixes: dict[str, str] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            callee = node.value.func
            factory = callee.id if isinstance(callee, ast.Name) else getattr(callee, "attr", "")
            if factory not in ROUTER_FACTORIES:
                continue
            prefix = self._prefix_kwarg(node.value)
            if prefix is None:
                continue  # computed prefix: routes stay router-relative
            for target in node.targets:
                if isinstance(target, ast.Name):
                    prefixes[target.id] = prefix

        # `include_router(router, prefix="/x")` mounts a router under a second prefix,
        # above whatever the router declares for itself.
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not self._is_include_router(node.func):
                continue
            if not node.args or not isinstance(node.args[0], ast.Name):
                continue
            included = node.args[0].id
            mount = self._prefix_kwarg(node)
            if mount is None:
                prefixes.pop(included, None)
            elif mount:
                prefixes[included] = self._join(mount, prefixes.get(included, ""))
        return prefixes

    def _is_include_router(self, callee: ast.expr) -> bool:
        """Whether an expression is an `include_router` callee, bound or bare."""
        if isinstance(callee, ast.Attribute):
            return callee.attr == "include_router"
        return isinstance(callee, ast.Name) and callee.id == "include_router"

    def _prefix_kwarg(self, call: ast.Call) -> str | None:
        """Read a call's `prefix=` argument.

        Returns:
            The prefix string, "" when the call declares none, or None when it declares
            one this reader cannot evaluate - including `**kwargs`, which may hide one.
        """
        opaque = False
        for keyword in call.keywords:
            if keyword.arg == "prefix":
                value = keyword.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    return value.value
                return None
            if keyword.arg is None:
                opaque = True
        return None if opaque else ""

    def _join(self, prefix: str, path: str) -> str:
        """Concatenate a router prefix and a route path the way the frameworks do."""
        if not prefix:
            return path
        base = prefix.rstrip("/")
        tail = path.lstrip("/")
        if not path:
            return base
        return f"{base}/{tail}" if tail else f"{base}/"

    def _route_of(self, decorator: ast.expr) -> tuple[str, str, str] | None:
        """Extract (router variable, METHOD, path) from a routing decorator.

        Returns:
            The triple, or None when the decorator is not a route. The router variable is
            "" when the decorator is applied to something other than a plain name, which
            leaves the path router-relative.
        """
        if not isinstance(decorator, ast.Call):
            return None
        func = decorator.func
        if not isinstance(func, ast.Attribute) or func.attr not in ROUTE_METHODS:
            return None
        if not decorator.args:
            return None
        first = decorator.args[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            return None
        router = func.value.id if isinstance(func.value, ast.Name) else ""
        return router, func.attr.upper(), first.value

    def _has_main_guard(self, tree: ast.AST) -> bool:
        """Whether the module has an `if __name__ == "__main__":` block.

        The operator and the compared value both matter: `if __name__ != "__main__":` is a
        library-only guard, the opposite claim, and reporting the module as runnable would
        send a newcomer to run a file that deliberately refuses to be run.
        """
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            test = node.test
            if not isinstance(test, ast.Compare) or len(test.ops) != 1:
                continue
            if not isinstance(test.ops[0], ast.Eq):
                continue
            sides = [test.left, test.comparators[0]]
            names = {s.id for s in sides if isinstance(s, ast.Name)}
            values = {s.value for s in sides if isinstance(s, ast.Constant)}
            if "__name__" in names and "__main__" in values:
                return True
        return False
