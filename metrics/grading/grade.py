"""Grade executed workflow graphs against the CoolSpots reference.

    uv run python grade.py <run_dir> [--variant V] [--target within|beyond]
    uv run python grade.py --sensitivity

Reads what `python -m src.batch <run_dir> --execute` (LangGraph) wrote: `executed[.<variant>].jsonl`
and `executions/`. Every distinct graph is compared with `outputs/reference.gpkg`, inside the
reference city boundary and in its UTM zone:

    target_iou      IoU of the graph's answer with the reference answer. `within` (green-300m prompt):
                    the graph's coverage (`multi-ring-buffer` coverage, else the widest `buffer`), or
                    its `geometry-difference` result when it has one, since that is then its final
                    answer (the city minus the rings: the inverse); `beyond` (CoolSpots prompt): the
                    `geometry-difference` result. None when the graph has no such output.
    coverage_iou    IoU of the coverage with the reference `within`, for both targets.
    band_agreement  On a grid, the share of points whose distance band in the graph overlaps the one in
                    the reference (inside a green space, a ring, or beyond the limit), among the points
                    that are not beyond the limit on both sides. 50 m steps against 75 m steps disagree
                    only where the bands really differ. None without rings.
    outer_m         The largest ring or buffer distance.
    city_iou        The graph's own city boundary against the reference's.
    correct         target_iou and band_agreement at least `THRESHOLDS`, and outer_m the reference limit.
                    Lenient: every reading the agents chose between 1000 and 10000 m² minimum area, any
                    ring steps and either tag set (also combined) passes (`--sensitivity`, 2026-10-19); 50000 m², rings
                    without a coverage, or subtracting the rings instead of the coverage do not.

The target comes from the run's seed id (`TARGETS`), or `--target`. Writes `grades[.<variant>].jsonl`
in the run folder (one line per result) and prints the distribution per category.

`--sensitivity` builds the reference again with the other parameters the agents choose (minimum area,
ring steps, OSM tags) and prints the same measures against the default reference: how far apart
reasonable readings of the prompt lie, which is what the ballpark thresholds are set from.
"""

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely
from shapely.geometry import shape

import cool_spots

REFERENCE = Path(__file__).parent / "outputs" / "reference.gpkg"
TARGETS = {"muenster_green_300m": "within", "muenster_coolspots_300m": "beyond"}
GRID_M = 25
# Lenient ballpark: just below the furthest plausible reading in the sensitivity run (10000 m² without
# natural=wood: 0.911 / 0.582 / 0.805), less the ~0.01 the process chain scores below the reference.
THRESHOLDS = {"within": 0.90, "beyond": 0.55, "bands": 0.78}
GREEN = (-1.0, 0.0)  # band of a point inside a green space: agrees only with the same


def _suffix(variant: str) -> str:
    return "" if variant == "pgvector" else f".{variant}"


def _read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_reference(path: Path = REFERENCE) -> dict:
    return from_layers(
        {
            name: gpd.read_file(path, layer=name)
            for name in ("city", "rings", "within", "beyond")
        }
    )


def from_layers(layers: dict) -> dict:
    """A `cool_spots.reference` result in the form the measures take."""
    rings = layers["rings"]
    return {
        "crs": layers["city"].crs,
        "city": layers["city"].union_all(),
        "coverage": layers["within"].union_all(),
        "difference": layers["beyond"].union_all(),
        "rings": list(
            zip(rings["inner_m"], rings["outer_m"], rings.geometry, strict=True)
        ),
        "outer_m": float(rings["outer_m"].max()),
    }


def _utm(geojson, crs) -> shapely.Geometry | None:
    """Any GeoJSON value (geometry, Feature, FeatureCollection) as one geometry in `crs`."""
    if not isinstance(geojson, dict) or "type" not in geojson:
        return None
    if geojson["type"] == "FeatureCollection":
        geoms = [
            shape(f["geometry"])
            for f in geojson.get("features", [])
            if f.get("geometry")
        ]
    elif geojson["type"] == "Feature":
        geoms = [shape(geojson["geometry"])] if geojson.get("geometry") else []
    else:
        geoms = [shape(geojson)]
    if not geoms:
        return shapely.Polygon()
    return gpd.GeoSeries(geoms, crs="EPSG:4326").to_crs(crs).union_all()


def graph_layers(execution: dict, node_dir: Path, crs) -> dict:
    """The graph's city, rings, coverage and difference, from its cached node outputs."""
    configs = {n["id"]: n["config"] for n in execution["graph"]["nodes"]}

    def output(node_id: str) -> dict:
        key = execution["nodes"][node_id]["output"]
        return (
            json.loads((node_dir / f"{key}.json").read_text(encoding="utf-8"))
            if key
            else {}
        )

    layers = {
        "city": None,
        "rings": None,
        "coverage": None,
        "difference": None,
        "outer_m": None,
    }
    buffers = []
    for node_id, node in execution["nodes"].items():
        out = output(node_id)
        if not out:
            continue
        if node["type"] == "city-boundary":
            layers["city"] = _utm(out.get("boundary"), crs)
        elif node["type"] == "multi-ring-buffer":
            features = (out.get("rings") or {}).get("features", [])
            layers["rings"] = [
                (
                    float(f["properties"]["innerDistance"]),
                    float(f["properties"]["outerDistance"]),
                    _utm(f["geometry"], crs),
                )
                for f in features
            ]
            layers["coverage"] = _utm(out.get("coverage"), crs)
            layers["outer_m"] = float(out.get("maxDistance") or 0) or None
        elif node["type"] == "buffer":
            buffers.append(
                (
                    float(configs[node_id].get("distance") or 0),
                    _utm(out.get("result"), crs),
                )
            )
        elif node["type"] == "geometry-difference":
            layers["difference"] = _utm(out.get("result"), crs)
    if layers["coverage"] is None and buffers:
        layers["outer_m"], layers["coverage"] = max(buffers, key=lambda b: b[0])
    return layers


def iou(a, b, city) -> float | None:
    if a is None or b is None:
        return None
    a, b = a.intersection(city), b.intersection(city)
    union = a.union(b).area
    return round(a.intersection(b).area / union, 4) if union else 1.0


class Grid:
    """Points every `step` metres inside the city, to compare distance bands."""

    def __init__(self, city, step: float = GRID_M):
        minx, miny, maxx, maxy = city.bounds
        x, y = np.meshgrid(np.arange(minx, maxx, step), np.arange(miny, maxy, step))
        x, y = x.ravel(), y.ravel()
        shapely.prepare(city)
        inside = shapely.contains_xy(city, x, y)
        self.x, self.y = x[inside], y[inside]

    def bands(self, layers: dict) -> tuple[np.ndarray, np.ndarray]:
        """Per point the band [lo, hi): green space, a ring, or beyond the limit."""
        lo = np.full(self.x.shape, layers["outer_m"] or 0.0)
        hi = np.full(self.x.shape, np.inf)
        covered = self._inside(layers["coverage"])
        lo[covered], hi[covered] = GREEN
        for inner, outer, geom in layers["rings"]:
            hit = self._inside(geom)
            lo[hit], hi[hit] = inner, outer
        return lo, hi

    def _inside(self, geom) -> np.ndarray:
        if geom is None or geom.is_empty:
            return np.zeros(self.x.shape, bool)
        shapely.prepare(geom)
        # Edges count: a point exactly at a ring's inner distance belongs to that ring ([inner, outer),
        # rings applied inner to outer), not to the green space it would fall into otherwise.
        return shapely.intersects_xy(geom, self.x, self.y)

    def agreement(self, graph: dict, ref_bands: tuple) -> float | None:
        if not graph["rings"] or graph["coverage"] is None:
            return None
        lo, hi = self.bands(graph)
        ref_lo, ref_hi = ref_bands
        relevant = ~(np.isinf(hi) & np.isinf(ref_hi))
        agree = (lo < ref_hi) & (ref_lo < hi)
        return round(float(agree[relevant].mean()), 4) if relevant.any() else None


def measures(graph: dict, ref: dict, target: str, grid: Grid, ref_bands: tuple) -> dict:
    answer = {"within": "coverage", "beyond": "difference"}[target]
    final = graph["difference"] if graph["difference"] is not None else graph[answer]
    return {
        "target_iou": iou(final, ref[answer], ref["city"]),
        "coverage_iou": iou(graph["coverage"], ref["coverage"], ref["city"]),
        "band_agreement": grid.agreement(graph, ref_bands),
        "outer_m": graph["outer_m"],
        "city_iou": iou(graph["city"], ref["city"], ref["city"].union(graph["city"]))
        if graph["city"]
        else None,
    }


def correct(m: dict, target: str, limit: float) -> bool:
    return (
        (m["target_iou"] or 0) >= THRESHOLDS[target]
        and (m["band_agreement"] or 0) >= THRESHOLDS["bands"]
        and m["outer_m"] == limit
    )


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval, as in LangGraph/src/batch_summary.py."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z / (1 + z * z / n) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, centre - half), min(1.0, centre + half)


def grade(run_dir: Path, variant: str, target: str | None, grid_m: float) -> None:
    seed_id = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))["seed"][
        "id"
    ]
    target = target or TARGETS[seed_id]
    ref = load_reference()
    grid = Grid(ref["city"], grid_m)
    ref_bands = grid.bands(ref)
    executions = run_dir / "executions"

    lines = _read_jsonl(run_dir / f"executed{_suffix(variant)}.jsonl")
    by_sig = {}
    for sig in sorted({line["signature"] for line in lines}):
        execution = json.loads((executions / f"{sig}.json").read_text(encoding="utf-8"))
        failed = [
            f"{n['type']}: {n['error']}"
            for n in execution["nodes"].values()
            if n["error"]
        ]
        if not execution["nodes"] or failed:
            by_sig[sig] = {
                "executed": False,
                "errors": failed or [execution.get("error")],
            }
            continue
        graph = graph_layers(execution, executions / "nodes", ref["crs"])
        m = measures(graph, ref, target, grid, ref_bands)
        by_sig[sig] = {
            "executed": True,
            **m,
            "correct": correct(m, target, ref["outer_m"]),
        }

    with (run_dir / f"grades{_suffix(variant)}.jsonl").open("w", encoding="utf-8") as f:
        for line in lines:
            f.write(
                json.dumps(
                    {**line, "target": target, **by_sig[line["signature"]]},
                    ensure_ascii=False,
                )
                + "\n"
            )
    _print_summary(lines, by_sig, target, seed_id, variant)


def _fmt(values: list) -> str:
    values = [v for v in values if v is not None]
    if not values:
        return "-"
    return f"{statistics.median(values):.3f} [{min(values):.3f}-{max(values):.3f}]"


def _print_summary(
    lines: list[dict], by_sig: dict, target: str, seed_id: str, variant: str
) -> None:
    print(
        f"{seed_id} / {variant}: target {target}, {len(lines)} results, {len(by_sig)} distinct graphs\n"
    )
    groups = defaultdict(list)
    for line in lines:
        groups[line["category"]].append(line)
        groups["(all)"].append(line)
    print(
        f"{'category':<18}{'n':>4}{'run':>5}{'asked':>7}  {'correct [95% CI]':<22}"
        f"{'target_iou median [range]':<27}{'band_agreement':<27}"
    )
    for category, members in sorted(groups.items()):
        grades = [by_sig[m["signature"]] for m in members]
        ran = [g for g in grades if g["executed"]]
        k = sum(g.get("correct", False) for g in grades)
        lo, hi = wilson(k, len(members))
        score = f"{k}/{len(members)} {k / len(members):.0%} [{lo:.0%}-{hi:.0%}]"
        print(
            f"{category:<18}{len(members):>4}{len(ran):>5}{sum(bool(m['asked']) for m in members):>7}  "
            f"{score:<22}{_fmt([g['target_iou'] for g in ran]):<27}{_fmt([g['band_agreement'] for g in ran]):<27}"
        )
    print("\nper graph (most results first):")
    counts = defaultdict(int)
    for line in lines:
        counts[line["signature"]] += 1
    for sig, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        g = by_sig[sig]
        if g["executed"]:
            print(
                f"  {sig} {n:>4}x  {'ok   ' if g['correct'] else 'WRONG'}  target {g['target_iou']}  coverage {g['coverage_iou']}  "
                f"bands {g['band_agreement']}  outer {g['outer_m']}  city {g['city_iou']}"
            )
        else:
            print(
                f"  {sig} {n:>4}x  not executed: {'; '.join(map(str, g['errors']))[:200]}"
            )


SENSITIVITY = [
    ("min_area 0", {"min_area": 0}),
    ("min_area 1000", {"min_area": 1000}),
    ("min_area 5000", {"min_area": 5000}),
    ("min_area 10000", {"min_area": 10000}),
    ("min_area 50000", {"min_area": 50000}),
    ("rings 50 m steps", {"intervals": [0, 50, 100, 150, 200, 250, 300]}),
    ("rings 100 m steps", {"intervals": [0, 100, 200, 300]}),
    ("tags without natural=wood", {"tags": {"landuse": "forest", "leisure": "park"}}),
    (
        "min_area 5000, without wood",
        {"min_area": 5000, "tags": {"landuse": "forest", "leisure": "park"}},
    ),
    (
        "min_area 10000, without wood",
        {"min_area": 10000, "tags": {"landuse": "forest", "leisure": "park"}},
    ),
    (
        "min_area 10000, 50 m steps",
        {"min_area": 10000, "intervals": [0, 50, 100, 150, 200, 250, 300]},
    ),
]


def sensitivity(grid_m: float) -> None:
    base = load_reference()
    grid = Grid(base["city"], grid_m)
    base_bands = grid.bands(base)
    downloads = {}
    print(f"{'variant':<30}{'within_iou':>11}{'beyond_iou':>11}{'bands':>8}")
    for name, params in SENSITIVITY:
        tags = params.get("tags", cool_spots.TAGS)
        key = json.dumps(tags, sort_keys=True)
        if key not in downloads:
            try:
                downloads[key] = cool_spots.fetch(cool_spots.CITY_NAME, tags)
            except Exception as err:  # noqa: BLE001 - Overpass at capacity: report, try the rest
                downloads[key] = None
                print(
                    f"{name:<30}download failed: {str(err).splitlines()[0][:80]}",
                    flush=True,
                )
        if downloads[key] is None:
            continue
        city, spots = downloads[key]
        layers = from_layers(
            cool_spots.reference(
                city,
                spots,
                params.get("min_area", cool_spots.MIN_AREA),
                params.get("intervals", cool_spots.INTERVALS),
            )
        )
        within = iou(layers["coverage"], base["coverage"], base["city"])
        beyond = iou(layers["difference"], base["difference"], base["city"])
        print(
            f"{name:<30}{within:>11.4f}{beyond:>11.4f}{grid.agreement(layers, base_bands):>8.4f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_dir", type=Path, nargs="?")
    parser.add_argument("--variant", default="pgvector")
    parser.add_argument(
        "--target", choices=("within", "beyond"), help="default: from the run's seed id"
    )
    parser.add_argument(
        "--grid",
        type=float,
        default=GRID_M,
        help="grid step in m (default %(default)s)",
    )
    parser.add_argument(
        "--sensitivity", action="store_true", help="compare reference variants and exit"
    )
    args = parser.parse_args()
    if args.sensitivity:
        sensitivity(args.grid)
    elif args.run_dir:
        grade(args.run_dir, args.variant, args.target, args.grid)
    else:
        parser.error("give a run_dir or --sensitivity")


if __name__ == "__main__":
    main()
