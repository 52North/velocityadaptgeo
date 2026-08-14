"""Recover OGC API - Processes registrations from a pygeoapi YAML configuration.

The link between a process the outside world can call and the class implementing it
exists only in `pygeoapi-config.yml`, as the string `processes.buffer.BufferProcessor`.
Miss it and the guide sees seventeen unrelated classes that nothing imports; catch it
and it can answer "which processes exist, and where is each one implemented".

The declared inputs and outputs are folded into the symbol as well, since for a
workflow-building system the port names *are* the contract between processes.
"""

from pathlib import Path
from typing import Any

from ..model import Edge, Symbol
from . import DetectContext, DetectResult

try:
    import yaml
except ImportError:  # pragma: no cover - detector degrades to a no-op without PyYAML
    yaml = None


class _LenientLoader(getattr(yaml, "SafeLoader", object)):
    """SafeLoader that tolerates unknown tags instead of refusing the whole file."""


if yaml is not None:
    _LenientLoader.add_multi_constructor(
        "", lambda loader, suffix, node: None  # noqa: ARG005 - unknown tags become None
    )


class PygeoapiDetector:
    """Maps `type: process` resources in a pygeoapi config to their processor classes."""

    name = "pygeoapi"

    def detect(self, ctx: DetectContext) -> DetectResult:
        """Scan YAML configs for process registrations. See `Detector.detect`."""
        result = DetectResult()
        if yaml is None:
            return result

        for path, repo_relative, _ in ctx.files:
            if path.suffix not in (".yml", ".yaml"):
                continue
            config = self._load(path)
            resources = (config or {}).get("resources")
            if not isinstance(resources, dict):
                continue
            self._detect_config(ctx, repo_relative, resources, result)
        return result

    def _load(self, path: Path) -> dict | None:
        """Parse a YAML file, returning None on anything unparseable."""
        try:
            loaded = yaml.load(path.read_text(encoding="utf-8", errors="replace"), _LenientLoader)
        except Exception:
            return None
        return loaded if isinstance(loaded, dict) else None

    def _detect_config(
        self,
        ctx: DetectContext,
        repo_relative: str,
        resources: dict,
        result: DetectResult,
    ) -> None:
        """Turn every process resource in one config into a symbol plus edges."""
        registered: list[tuple[str, str]] = []

        for process_id, resource in resources.items():
            if not isinstance(resource, dict) or resource.get("type") != "process":
                continue
            processor = (resource.get("processor") or {}).get("name", "")
            impl = ctx.resolve_suffix(processor, kinds=("class",))
            qualname = f"process:{process_id}"

            result.symbols.append(self._process_symbol(
                ctx, qualname, process_id, resource, processor, impl, repo_relative,
            ))
            result.edges.append(Edge(
                src=self._config_qualname(repo_relative), dst=qualname, kind="registers",
                detail=f"pygeoapi resource '{process_id}'",
            ))
            if impl:
                result.edges.append(Edge(
                    src=qualname, dst=impl, kind="implements",
                    detail=f"processor {processor}",
                ))
            registered.append((process_id, impl or processor or "(unresolved)"))

        if not registered:
            return

        result.symbols.append(self._config_symbol(repo_relative, registered))

        lines = [
            f"{len(registered)} OGC API - Processes registered in {repo_relative} "
            "(these are the callable capabilities of this system):"
        ]
        lines += [f"  {pid} -> {impl}" for pid, impl in sorted(registered)]
        result.notes.append("\n".join(lines))

    def _config_qualname(self, repo_relative: str) -> str:
        """Qualname of the symbol standing for a config file.

        Same `prefix:name` scheme as `process:buffer` and `http:GET /search`, so a
        framework construct is recognisable as one at a glance.
        """
        return f"config:{repo_relative}"

    def _config_symbol(self, repo_relative: str, registered: list[tuple[str, str]]) -> Symbol:
        """Build the symbol a config file's `registers` edges point out of.

        The registration is a real link in the chain from an HTTP process call to the
        class that answers it, so its source has to be a symbol the map holds. Emitting a
        bare file path instead leaves an edge out of a key nothing indexes: the
        registration renders as "(not indexed)", and `shortest_path` cannot start there at
        all, which is precisely the hop needed to explain how a process call arrives.

        Args:
            repo_relative: Path of the configuration file.
            registered: (process id, implementation) pairs found in it.

        Returns:
            A searchable symbol for the configuration file.
        """
        process_ids = ", ".join(sorted(pid for pid, _ in registered))
        return Symbol(
            qualname=self._config_qualname(repo_relative),
            kind="config_file",
            name=Path(repo_relative).name,
            file=repo_relative,
            lineno=1,
            doc=(
                f"pygeoapi configuration. Registers {len(registered)} OGC API - Processes, "
                "which is the only place each process id is bound to the class that "
                f"implements it: {process_ids}."
            ),
            signature=f"pygeoapi config '{repo_relative}'",
            tags=["pygeoapi", "config", "registry"],
            extra={"processes": sorted(pid for pid, _ in registered)},
        )

    def _process_symbol(
        self,
        ctx: DetectContext,
        qualname: str,
        process_id: str,
        resource: dict,
        processor: str,
        impl: str,
        config_file: str,
    ) -> Symbol:
        """Build a searchable symbol for one registered process.

        Documentation is taken from the config's own title/description - the public
        contract - and only falls back to the implementing class's docstring, which
        tends to describe mechanics rather than purpose.
        """
        title = resource.get("title") or ""
        description = resource.get("description") or ""
        if isinstance(title, dict):
            title = next(iter(title.values()), "")
        if isinstance(description, dict):
            description = next(iter(description.values()), "")

        doc_parts = [p for p in (title, description) if p]
        if not doc_parts and impl and (impl_symbol := ctx.code_map.symbols.get(impl)):
            doc_parts.append(impl_symbol.doc)

        inputs = self._port_names(resource.get("inputs"))
        outputs = self._port_names(resource.get("outputs"))
        doc = "\n".join(doc_parts)
        if inputs or outputs:
            doc += f"\n\nInputs: {', '.join(inputs) or '(none declared)'}"
            doc += f"\nOutputs: {', '.join(outputs) or '(none declared)'}"

        impl_symbol = ctx.code_map.symbols.get(impl) if impl else None
        return Symbol(
            qualname=qualname,
            kind="ogc_process",
            name=process_id,
            file=impl_symbol.file if impl_symbol else config_file,
            lineno=impl_symbol.lineno if impl_symbol else 1,
            doc=doc.strip(),
            signature=f"OGC process '{process_id}'({', '.join(inputs)}) -> {', '.join(outputs)}",
            tags=["ogc-process", "pygeoapi"],
            extra={
                "processor": processor,
                "implementation": impl,
                "inputs": inputs,
                "outputs": outputs,
                "config_file": config_file,
            },
        )

    def _port_names(self, ports: Any) -> list[str]:
        """Declared input or output names, tolerating both dict and list shapes."""
        if isinstance(ports, dict):
            return list(ports.keys())
        if isinstance(ports, list):
            return [p.get("id", "") for p in ports if isinstance(p, dict)]
        return []
