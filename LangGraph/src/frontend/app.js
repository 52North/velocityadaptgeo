const form = document.getElementById("chat-form");
const testPrompts = document.getElementById("test-prompts");
const input = document.getElementById("prompt");
const graphCanvas = document.getElementById("graph");
const graphStatus = document.getElementById("graph-status");
const graphLegend = document.getElementById("graph-legend");
const runButton = document.getElementById("run-graph");

const threadId = crypto.randomUUID();

const SVG_NS = "http://www.w3.org/2000/svg";
const NODE_W = 186;
const NODE_H = 78;
const COL_GAP = 104;
const ROW_GAP = 30;
const BAND_GAP = 62;
const PAD = 22;
const PORT_GAP = 15;
const PORT_R = 3.5;
const PORT_LABEL_W = 78;
const HOP_R = 6;
const HIDDEN_CONFIG_KEYS = ["server_url", "timeout_seconds"];

let executionGraph = { nodes: [], edges: [] };
let lastValidation = null;
let nodeRuns = {};
let running = false;
let nodeH = NODE_H;
let nodePorts = new Map();

/**
 * Render assistant prose as markdown into `el`.
 *
 * `marked` is loaded from a CDN, so fall back to plain text if it is unavailable
 * (offline) - `.message` is `pre-wrap`, so line breaks survive either way. The parsed
 * output is scrubbed before insertion: it is model output that can echo whatever the
 * user typed, so scripts, embeds and event handlers must not reach the DOM.
 */
function renderMarkdown(el, text) {
    if (!window.marked) {
        el.textContent = text;
        return;
    }
    el.classList.add("markdown");
    el.innerHTML = window.marked.parse(text, { breaks: true, gfm: true });
    el.querySelectorAll("script, style, iframe, object, embed, form").forEach((n) => n.remove());
    el.querySelectorAll("*").forEach((n) => {
        [...n.attributes].forEach(({ name, value }) => {
            const isUrl = /^(href|src|xlink:href)$/i.test(name);
            if (/^on/i.test(name) || (isUrl && /^(javascript|data):/i.test(value.trim()))) {
                n.removeAttribute(name);
            }
        });
    });
}

function addMessage(role, text = "") {
    const div = document.createElement("div");
    div.classList.add("message", role);
    div.textContent = text;
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
    return div;
}

/**
 * Assign each node a column by longest path from a root, so an edge always points
 * rightwards. Nodes in a cycle or with no incoming edge start at column 0.
 */
function columnOf(nodes, edges) {
    const incoming = new Map(nodes.map((n) => [n.id, []]));
    edges.forEach((e) => {
        if (incoming.has(e.target) && incoming.has(e.source)) {
            incoming.get(e.target).push(e.source);
        }
    });

    const column = new Map();
    const depth = (id, seen) => {
        if (column.has(id)) return column.get(id);
        if (seen.has(id)) return 0;
        seen.add(id);
        const parents = incoming.get(id) || [];
        const value = parents.length
            ? Math.max(...parents.map((p) => depth(p, seen) + 1))
            : 0;
        column.set(id, value);
        return value;
    };

    nodes.forEach((n) => depth(n.id, new Set()));
    return column;
}

/**
 * Collect, per node, the port names that actually carry an edge, so every parameter gets
 * its own anchor on the node border instead of all arrows meeting at one midpoint.
 * Ports keep the order the catalog declares them in, so a node's parameters always stack
 * in the same order as the process signature.
 */
function portsOf(nodes, edges) {
    const map = new Map(nodes.map((n) => [n.id, { in: [], out: [] }]));
    const add = (id, side, name) => {
        const list = map.get(id) && map.get(id)[side];
        if (list && !list.includes(name)) list.push(name);
    };
    edges.forEach((e) => {
        add(e.source, "out", e.source_output || "default");
        add(e.target, "in", e.target_input || "default");
    });
    const byDeclared = (declared) => (a, b) =>
        (declared.indexOf(a) + 1 || 99) - (declared.indexOf(b) + 1 || 99);
    nodes.forEach((n) => {
        const p = map.get(n.id);
        p.in.sort(byDeclared(n.inputs || []));
        p.out.sort(byDeclared(n.outputs || []));
    });
    return map;
}

/** Y of one port anchor relative to the node top: anchors spread evenly down the border. */
function portY(nodeId, side, name) {
    const list = (nodePorts.get(nodeId) || {})[side] || [];
    if (!list.length) return nodeH / 2;
    return (nodeH * (Math.max(0, list.indexOf(name)) + 1)) / (list.length + 1);
}

/**
 * Width actually available for the diagram: the canvas content box, excluding its
 * padding and any vertical scrollbar, so the drawing can never force sideways scrolling.
 */
function canvasContentWidth() {
    const style = getComputedStyle(graphCanvas);
    const padding = parseFloat(style.paddingLeft || 0) + parseFloat(style.paddingRight || 0);
    return Math.max(0, (graphCanvas.clientWidth || 0) - padding);
}

function svgEl(name, attrs = {}) {
    const el = document.createElementNS(SVG_NS, name);
    Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, String(v)));
    return el;
}

function truncate(text, max) {
    const value = String(text ?? "");
    return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

/**
 * Summarise the static inputs of a node, hiding transport details that are the same
 * for every node and say nothing about what the step does.
 */
function configSummary(node) {
    const entries = Object.entries(node.config || {})
        .filter(([k]) => !HIDDEN_CONFIG_KEYS.includes(k))
        .map(([k, v]) => {
            if (Array.isArray(v)) return `${k}=[${v.join(",")}]`;
            return `${k}=${v !== null && typeof v === "object" ? "{…}" : v}`;
        });
    if (entries.length) return entries.join(", ");
    return (node.inputs || []).length ? `inputs: ${node.inputs.join(", ")}` : "no static inputs";
}

function drawNode(svg, node, x, y) {
    const run = nodeRuns[node.id];
    const state = run ? run.state : "idle";
    const group = svgEl("g", {
        class: `gnode gnode-${state}`, transform: `translate(${x}, ${y})`,
    });
    group.appendChild(svgEl("rect", {
        width: NODE_W, height: nodeH, rx: 10, class: "gnode-box",
    }));
    group.appendChild(svgEl("rect", {
        width: 4, height: nodeH, rx: 2, class: "gnode-accent",
    }));

    if (run) {
        const badge = svgEl("text", { x: NODE_W - 12, y: 27, class: "gnode-run", "text-anchor": "end" });
        badge.textContent = run.label;
        group.appendChild(badge);
    }

    const title = svgEl("text", { x: 16, y: 27, class: "gnode-title" });
    title.textContent = truncate(node.type, 24);
    group.appendChild(title);

    const id = svgEl("text", { x: 16, y: 46, class: "gnode-id" });
    id.textContent = truncate(node.id, 28);
    group.appendChild(id);

    const cfg = svgEl("text", { x: 16, y: 64, class: "gnode-config" });
    cfg.textContent = truncate(configSummary(node), 28);
    group.appendChild(cfg);

    const ports = nodePorts.get(node.id) || { in: [], out: [] };
    [["in", 0, "end", -7, 13], ["out", NODE_W, "start", 7, -7]].forEach(
        ([side, cx, anchor, dx, dy]) => {
            ports[side].forEach((name) => {
                const cy = portY(node.id, side, name);
                group.appendChild(svgEl("circle", { cx, cy, r: PORT_R, class: "gport" }));
                const label = svgEl("text", {
                    x: cx + dx, y: cy + dy, class: "gport-label", "text-anchor": anchor,
                });
                label.textContent = truncate(name, 12);
                group.appendChild(label);
            });
        },
    );

    const full = svgEl("title");
    full.textContent = `${node.id}\nprocess: ${node.type}\nserver: ${(node.config || {}).server_url || "?"}\n${configSummary(node)}`;
    group.appendChild(full);

    svg.appendChild(group);
}

/** The two endpoints of an edge, each on its own port anchor. */
function edgeEnds(edge, from, to) {
    return {
        x1: from.x + NODE_W,
        y1: from.y + portY(edge.source, "out", edge.source_output || "default"),
        x2: to.x,
        y2: to.y + portY(edge.target, "in", edge.target_input || "default"),
    };
}

/**
 * Flatten one edge into a polyline: the single geometry used for crossing detection and
 * for drawing. Same-band edges are a sampled left-to-right curve; an edge whose target
 * wrapped onto a later band is routed orthogonally out to the right, down through
 * `laneY` in the gap between bands, then back left into the target.
 */
function edgeRoute(edge, from, to, laneY) {
    const { x1, y1, x2, y2 } = edgeEnds(edge, from, to);
    if (laneY === null) {
        const b = Math.max(28, (x2 - x1) / 2);
        return Array.from({ length: 19 }, (_, i) => {
            const t = i / 18, u = 1 - t;
            return {
                x: u ** 3 * x1 + 3 * u * u * t * (x1 + b) + 3 * u * t * t * (x2 - b) + t ** 3 * x2,
                y: u ** 3 * y1 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t ** 3 * y2,
            };
        });
    }
    const stub = 20;
    return [
        { x: x1, y: y1 }, { x: x1 + stub, y: y1 }, { x: x1 + stub, y: laneY },
        { x: x2 - stub, y: laneY }, { x: x2 - stub, y: y2 }, { x: x2, y: y2 },
    ];
}

/**
 * Where two segments genuinely cross, as a distance along the first one. Shared
 * endpoints and collinear overlaps return null: only a real X is worth hopping over,
 * and two edges leaving the same output port are one line splitting, not a crossing.
 */
function segCross(a, b, c, d) {
    const rx = b.x - a.x, ry = b.y - a.y, sx = d.x - c.x, sy = d.y - c.y;
    const den = rx * sy - ry * sx;
    if (Math.abs(den) < 1e-9) return null;
    const t = ((c.x - a.x) * sy - (c.y - a.y) * sx) / den;
    const u = ((c.x - a.x) * ry - (c.y - a.y) * rx) / den;
    if (t <= 0.001 || t >= 0.999 || u <= 0.001 || u >= 0.999) return null;
    return t * Math.hypot(rx, ry);
}

/** Cumulative distance along a polyline, one entry per point. */
function lengths(pts) {
    return pts.reduce(
        (acc, p, i) => (i ? [...acc, acc[i - 1] + Math.hypot(p.x - pts[i - 1].x, p.y - pts[i - 1].y)] : acc),
        [0],
    );
}

/**
 * Distances along `pts` at which it crosses any of the routes in `others`, merged when
 * closer together than one hop and kept clear of both endpoints so a bump never lands
 * on a port anchor or under the arrowhead.
 */
function crossings(pts, others) {
    const cum = lengths(pts);
    const total = cum[cum.length - 1];
    const found = [];
    for (let i = 1; i < pts.length; i++) {
        for (const o of others) {
            for (let k = 1; k < o.length; k++) {
                const d = segCross(pts[i - 1], pts[i], o[k - 1], o[k]);
                if (d === null) continue;
                const s = cum[i - 1] + d;
                if (s > HOP_R + 4 && s < total - HOP_R - 4) found.push(s);
            }
        }
    }
    return found.sort((a, b) => a - b)
        .filter((s, i, all) => !i || s - all[i - 1] > HOP_R * 2);
}

/** Point at distance `s` along a polyline. */
function atLen(pts, cum, s) {
    const i = Math.max(1, cum.findIndex((c) => c >= s));
    const seg = cum[i] - cum[i - 1] || 1;
    const k = (s - cum[i - 1]) / seg;
    return {
        x: pts[i - 1].x + (pts[i].x - pts[i - 1].x) * k,
        y: pts[i - 1].y + (pts[i].y - pts[i - 1].y) * k,
    };
}

/**
 * Draw one route: a solid line that lifts off at each crossing, with the gap bridged by
 * a dashed semicircular hop. The bump plus the dashes make it unambiguous which of two
 * lines meeting at a point actually continues through it.
 */
function drawRoute(svg, pts, others) {
    const cum = lengths(pts);
    const r = (n) => Math.round(n * 10) / 10;
    let line = `M ${r(pts[0].x)} ${r(pts[0].y)}`, hops = "", i = 1;

    crossings(pts, others).forEach((s) => {
        const a = atLen(pts, cum, s - HOP_R), b = atLen(pts, cum, s + HOP_R);
        while (i < pts.length && cum[i] < s - HOP_R) line += ` L ${r(pts[i].x)} ${r(pts[i].y)}`, i++;
        line += ` L ${r(a.x)} ${r(a.y)} M ${r(b.x)} ${r(b.y)}`;
        hops += ` M ${r(a.x)} ${r(a.y)} A ${HOP_R} ${HOP_R} 0 0 1 ${r(b.x)} ${r(b.y)}`;
        while (i < pts.length && cum[i] < s + HOP_R) i++;
    });
    for (; i < pts.length; i++) line += ` L ${r(pts[i].x)} ${r(pts[i].y)}`;

    svg.appendChild(svgEl("path", { d: line, class: "gedge", "marker-end": "url(#arrow)" }));
    if (hops) svg.appendChild(svgEl("path", { d: hops.trim(), class: "gedge gedge-hop" }));
}

/**
 * Render the OGC execution graph: one box per process node, one arrow per wired port.
 * Called on every graph update so the DAG grows as the workflow is assembled.
 */
function renderGraph() {
    const nodes = executionGraph.nodes || [];
    const edges = executionGraph.edges || [];

    graphStatus.textContent = nodes.length
        ? `${nodes.length} node${nodes.length === 1 ? "" : "s"}, ${edges.length} edge${edges.length === 1 ? "" : "s"}` +
          (lastValidation ? (lastValidation.valid ? " · valid" : " · invalid") : "")
        : "empty";
    graphStatus.className = "graph-status" +
        (nodes.length && lastValidation ? (lastValidation.valid ? " ok" : " bad") : "");

    graphLegend.hidden = !nodes.length;
    runButton.disabled = running || !nodes.length;
    runButton.textContent = running ? "Running…" : "Run";

    graphCanvas.innerHTML = "";

    if (!nodes.length) {
        const empty = document.createElement("div");
        empty.className = "graph-empty";
        empty.textContent = "No execution graph yet. Describe a geospatial task and the matching OGC processes will be wired up here.";
        graphCanvas.appendChild(empty);
        return;
    }

    nodePorts = portsOf(nodes, edges);
    const maxPorts = Math.max(0, ...[...nodePorts.values()].map(
        (p) => Math.max(p.in.length, p.out.length)
    ));
    nodeH = Math.max(NODE_H, (maxPorts + 1) * PORT_GAP);

    const column = columnOf(nodes, edges);
    const available = Math.max(canvasContentWidth(), NODE_W + PAD * 2);
    const perBand = Math.max(1, Math.floor(
        (available - PAD * 2 - PORT_LABEL_W + COL_GAP) / (NODE_W + COL_GAP)
    ));

    const rowCursor = new Map();
    const bandRows = new Map();
    const placed = new Map();

    nodes.forEach((node) => {
        const col = column.get(node.id) || 0;
        const row = rowCursor.get(col) || 0;
        rowCursor.set(col, row + 1);
        const band = Math.floor(col / perBand);
        bandRows.set(band, Math.max(bandRows.get(band) || 0, row + 1));
        placed.set(node.id, { col, band, row, colInBand: col % perBand });
    });

    const bands = [...bandRows.keys()].sort((a, b) => a - b);
    const bandTop = new Map();
    let cursorY = PAD;
    bands.forEach((band) => {
        bandTop.set(band, cursorY);
        cursorY += bandRows.get(band) * (nodeH + ROW_GAP) - ROW_GAP + BAND_GAP;
    });

    // Port labels sit outside the box, so the outermost columns need a gutter to
    // print into - reserved only when a node there actually has labelled ports.
    const usedCols = Math.min(perBand, Math.max(...column.values()) + 1);
    const gutter = (test) => PAD + ([...placed.entries()].some(
        ([id, slot]) => test(slot, nodePorts.get(id) || { in: [], out: [] })
    ) ? PORT_LABEL_W : 0);
    const leftPad = gutter((slot, p) => slot.colInBand === 0 && p.in.length);
    const rightPad = gutter((slot, p) => slot.colInBand === usedCols - 1 && p.out.length);

    placed.forEach((slot) => {
        slot.x = leftPad + slot.colInBand * (NODE_W + COL_GAP);
        slot.y = bandTop.get(slot.band) + slot.row * (nodeH + ROW_GAP);
    });

    const width = Math.max(leftPad + rightPad + usedCols * (NODE_W + COL_GAP) - COL_GAP, available);
    const height = cursorY - BAND_GAP + PAD;

    const svg = svgEl("svg", {
        width, height, viewBox: `0 0 ${width} ${height}`, class: "graph-svg",
    });

    const marker = svgEl("marker", {
        id: "arrow", viewBox: "0 0 10 10", refX: 9, refY: 5,
        markerWidth: 6, markerHeight: 6, orient: "auto-start-reverse",
    });
    marker.appendChild(svgEl("path", { d: "M 0 0 L 10 5 L 0 10 z", class: "garrow" }));
    const defs = svgEl("defs");
    defs.appendChild(marker);
    svg.appendChild(defs);

    // Route every edge first: hops are only computable once all the geometry is known.
    const laneUsage = new Map();
    const routes = edges.flatMap((edge) => {
        const from = placed.get(edge.source);
        const to = placed.get(edge.target);
        if (!from || !to) return [];
        let laneY = null;
        if (to.band !== from.band || to.x <= from.x) {
            const laneBand = Math.max(from.band, to.band);
            const taken = laneUsage.get(laneBand) || 0;
            laneUsage.set(laneBand, taken + 1);
            laneY = bandTop.get(laneBand) - BAND_GAP / 2 - taken * 15;
        }
        return [edgeRoute(edge, from, to, laneY)];
    });
    // Each route hops over the ones drawn before it, so exactly one of any two crossing
    // lines carries the bump.
    routes.forEach((pts, i) => drawRoute(svg, pts, routes.slice(0, i)));

    nodes.forEach((node) => {
        const at = placed.get(node.id);
        drawNode(svg, node, at.x, at.y);
    });

    graphCanvas.appendChild(svg);

    if (lastValidation && !lastValidation.valid && (lastValidation.errors || []).length) {
        const errors = document.createElement("ul");
        errors.className = "graph-errors";
        lastValidation.errors.forEach((err) => {
            const li = document.createElement("li");
            li.textContent = err;
            errors.appendChild(li);
        });
        graphCanvas.appendChild(errors);
    }
}

/**
 * Forget the layers of a previous run, so the results window never mixes the outputs of
 * two runs or of a graph that has since been rebuilt.
 */
function resetResultLayers() {
    if (leafletMap) {
        layerCache.forEach((layer) => leafletMap.removeLayer(layer));
    }
    layerCache.clear();
    mapLayers = [];
    resultsButton.disabled = true;
    if (resultsWindow && !resultsWindow.hidden) renderLayerList();
}

/**
 * Append one line to the execution log shown beneath the graph.
 * Output payloads arrive pre-summarised from the server, never as raw geometry. The log
 * lives outside the graph canvas, which `renderGraph` rebuilds on every progress event.
 */
function logRun(kind, text, detail) {
    const log = document.getElementById("run-log");
    log.hidden = false;
    const row = document.createElement("div");
    row.className = `run-row run-${kind}`;
    row.textContent = text;
    if (detail) {
        const pre = document.createElement("pre");
        pre.textContent = detail;
        row.appendChild(pre);
    }
    log.appendChild(row);
    log.scrollTop = log.scrollHeight;
}

/**
 * Execute the graph the assistant built for this thread, streaming per-node progress.
 * Node states are mirrored onto the diagram so the run is visible where the graph is.
 */
function runGraph() {
    if (running || !(executionGraph.nodes || []).length) return;

    running = true;
    nodeRuns = {};
    resetResultLayers();
    const log = document.getElementById("run-log");
    log.innerHTML = "";
    log.hidden = true;
    renderGraph();

    const started = Date.now();
    const source = new EventSource(`/api/execute?thread_id=${encodeURIComponent(threadId)}`);

    const finish = () => {
        source.close();
        running = false;
        renderGraph();
    };

    source.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.event === "graph-start") {
            logRun("info", `Running ${data.order.length} node(s)…`);
        } else if (data.event === "node-start") {
            nodeRuns[data.node] = { state: "running", label: "…" };
            logRun("start", `▶ ${data.process}`,
                Object.entries(data.inputs || {}).map(([k, v]) => `${k} = ${v}`).join("\n"));
            renderGraph();
        } else if (data.event === "node-done") {
            nodeRuns[data.node] = { state: "done", label: `${(data.ms / 1000).toFixed(1)}s` };
            logRun("done", `✓ ${data.process} — ${(data.ms / 1000).toFixed(1)}s`,
                Object.entries(data.outputs || {}).map(([k, v]) => `${k} = ${v}`).join("\n"));
            registerLayers(data.node, data.process, data.geo);
            renderGraph();
        } else if (data.event === "node-error") {
            nodeRuns[data.node] = { state: "failed", label: "failed" };
            logRun("error", `✗ ${data.process}`, data.error);
            renderGraph();
        } else if (data.event === "node-skipped") {
            nodeRuns[data.node] = { state: "skipped", label: "skipped" };
            logRun("skip", `– ${data.process} skipped`, data.reason);
            renderGraph();
        } else if (data.event === "graph-done") {
            const secs = ((Date.now() - started) / 1000).toFixed(1);
            logRun(data.ok ? "done" : "error",
                `${data.ok ? "Finished" : "Finished with errors"} — ${data.ran} ran, ${data.failed} failed, ${secs}s total`);
            finish();
        } else if (data.event === "graph-error") {
            logRun("error", "Cannot execute graph", data.error);
            finish();
        }
    };

    source.onerror = () => {
        if (running) logRun("error", "Connection to the execution stream was lost.");
        finish();
    };
}

runButton.addEventListener("click", runGraph);

const LAYER_COLORS = ["#22c55e", "#38bdf8", "#f472b6", "#a78bfa", "#f87171", "#facc15"];
const DISTANCE_RAMP = ["#bbf7d0", "#86efac", "#4ade80", "#22c55e", "#15803d"];

const resultsWindow = document.getElementById("results-window");
const resultsLayers = document.getElementById("results-layers");
const resultsButton = document.getElementById("show-results");

let mapLayers = [];
let leafletMap = null;
let baseLayer = null;
const layerCache = new Map();

/**
 * Register the drawable outputs a finished node reported, so they can be offered as
 * map layers. Non-GeoJSON outputs (counts, areas, CRS codes) are simply absent here.
 */
function registerLayers(nodeId, process, geo) {
    Object.entries(geo || {}).forEach(([port, info]) => {
        mapLayers.push({
            key: `${nodeId}.${port}`, node: nodeId, process, port,
            kind: info.kind, count: info.features, index: mapLayers.length,
        });
    });
    resultsButton.disabled = mapLayers.length === 0;
}

/** Style one feature, shading multi-ring bands by distance when they carry one. */
function styleFor(entry, distances) {
    const color = LAYER_COLORS[entry.index % LAYER_COLORS.length];
    return (feature) => {
        const distance = feature.properties && feature.properties.outerDistance;
        if (distances.length > 1 && typeof distance === "number") {
            const rank = distances.indexOf(distance);
            return {
                color: DISTANCE_RAMP[Math.min(rank, DISTANCE_RAMP.length - 1)],
                weight: 1, opacity: 0.9, fillOpacity: 0.5,
            };
        }
        return { color, weight: 1.5, opacity: 0.95, fillOpacity: 0.2 };
    };
}

function describeProperties(properties) {
    const rows = Object.entries(properties || {})
        .filter(([, v]) => v !== null && typeof v !== "object")
        .map(([k, v]) => `<strong>${k}</strong>: ${v}`);
    return rows.length ? rows.join("<br>") : "no attributes";
}

/** Fit the map to everything currently switched on. */
function fitToVisible() {
    let bounds = null;
    mapLayers.forEach((entry) => {
        const layer = layerCache.get(entry.key);
        if (!layer || !leafletMap.hasLayer(layer)) return;
        bounds = bounds ? bounds.extend(layer.getBounds()) : layer.getBounds();
    });
    if (bounds && bounds.isValid()) leafletMap.fitBounds(bounds, { padding: [24, 24] });
}

async function toggleLayer(entry, on, noteEl) {
    if (!on) {
        const existing = layerCache.get(entry.key);
        if (existing) leafletMap.removeLayer(existing);
        fitToVisible();
        return;
    }

    if (!layerCache.has(entry.key)) {
        noteEl.textContent = "loading…";
        const url = `/api/result?thread_id=${encodeURIComponent(threadId)}` +
            `&node=${encodeURIComponent(entry.node)}&output=${encodeURIComponent(entry.port)}`;
        const response = await fetch(url);
        if (!response.ok) {
            noteEl.textContent = `failed (${response.status})`;
            return;
        }
        const collection = await response.json();
        const distances = [...new Set((collection.features || [])
            .map((f) => f.properties && f.properties.outerDistance)
            .filter((v) => typeof v === "number"))].sort((a, b) => a - b);

        const layer = L.geoJSON(collection, {
            style: styleFor(entry, distances),
            pointToLayer: (feature, latlng) => L.circleMarker(latlng, { radius: 5 }),
            onEachFeature: (feature, lyr) => lyr.bindPopup(describeProperties(feature.properties)),
        });
        layerCache.set(entry.key, layer);
        noteEl.textContent = collection.truncated
            ? `showing ${collection.features.length} of ${collection.total}`
            : `${collection.features.length} feature(s)`;
    }

    layerCache.get(entry.key).addTo(leafletMap);
    fitToVisible();
}

/** Build the layer switcher for the outputs of the last run. */
function renderLayerList() {
    resultsLayers.innerHTML = "";
    if (!mapLayers.length) {
        resultsLayers.innerHTML = '<p class="results-empty">Run the graph to produce results.</p>';
        return;
    }

    mapLayers.forEach((entry, i) => {
        const row = document.createElement("label");
        row.className = "layer-row";

        const box = document.createElement("input");
        box.type = "checkbox";
        const note = document.createElement("span");
        note.className = "layer-note";
        note.textContent = `${entry.kind}${entry.count > 1 ? ` · ${entry.count}` : ""}`;

        const swatch = document.createElement("span");
        swatch.className = "layer-swatch";
        swatch.style.background = LAYER_COLORS[entry.index % LAYER_COLORS.length];

        const title = document.createElement("span");
        title.className = "layer-title";
        title.textContent = `${entry.process}.${entry.port}`;

        box.addEventListener("change", () => toggleLayer(entry, box.checked, note));

        row.append(box, swatch, title, note);
        resultsLayers.appendChild(row);

        if (i === mapLayers.length - 1) {
            box.checked = true;
            toggleLayer(entry, true, note);
        }
    });
}

function openResults() {
    resultsWindow.hidden = false;
    if (!leafletMap) {
        leafletMap = L.map("results-map", { preferCanvas: true }).setView([51.96, 7.62], 11);
        baseLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
            attribution: "&copy; OpenStreetMap contributors", maxZoom: 19,
        }).addTo(leafletMap);
    }
    renderLayerList();
    leafletMap.invalidateSize();
}

resultsButton.addEventListener("click", openResults);
document.getElementById("close-results").addEventListener("click", () => {
    resultsWindow.hidden = true;
});

form.addEventListener("submit", (e) => {
    e.preventDefault();

    const prompt = input.value.trim();
    if (!prompt) return;

    addMessage("user", prompt);
    input.value = "";

    let currentStep = null;
    let currentStepMessage = null;
    let currentStepText = "";

    const evtSource = new EventSource(
        `/api/stream?prompt=${encodeURIComponent(prompt)}&thread_id=${encodeURIComponent(threadId)}`
    );

    evtSource.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.event === "graph") {
            if (data.workflow_graph) {
                executionGraph = data.workflow_graph;
                nodeRuns = {};
                resetResultLayers();
            }
            if (data.last_validation) lastValidation = data.last_validation;
            renderGraph();
            return;
        }

        const messageType = data.type;
        const step = data.metadata?.langgraph_step;
        const node = data.metadata?.langgraph_node;
        const content = data.content;

        if (!step) return;

        if (step !== currentStep) {
            currentStep = step;
            currentStepMessage = null;
            currentStepText = "";
        }

        if (!currentStepMessage) {
            currentStepMessage = addMessage("assistant", "");
            currentStepMessage.classList.add(`type-${messageType}`);

            if (node) {
                currentStepMessage.classList.add(`node-${node}`);
            }
            if (node === "manager") {
                currentStepMessage.innerHTML = `
                            <details class="manager-details">
                                <summary>Manager Activity</summary>
                                <pre class="content"></pre>
                            </details>
                        `;
            }
        }

        if (content) {
            currentStepText += content;

            const targetContainer = node === "manager"
                ? currentStepMessage.querySelector('.content')
                : currentStepMessage;

            if (messageType === "tool") {
                currentStepMessage.style.fontStyle = "italic";
                currentStepMessage.style.color = "#666";

                try {
                    const parsedContent = JSON.parse(currentStepText);
                    targetContainer.innerHTML = `<strong>Action (${node}):</strong><br/>
                        <pre style="margin: 5px 0 0 0; font-size: 0.9em;">${JSON.stringify(parsedContent, null, 2)}</pre>`;
                } catch (e) {
                    renderMarkdown(targetContainer, currentStepText);
                }
            } else if (node === "manager") {
                targetContainer.textContent = currentStepText.replace(/```(json)?/gi, '').trim();
            } else {
                renderMarkdown(targetContainer, currentStepText);
            }
        }

        chat.scrollTop = chat.scrollHeight;
    };


    evtSource.onerror = () => {
        evtSource.close();
        if (currentStepMessage) {
            currentStepMessage.classList.remove("streaming");
            currentStepMessage.classList.add("final");
        }
    };
});

let lastCanvasWidth = 0;
new ResizeObserver(() => {
    const width = graphCanvas.clientWidth;
    if (Math.abs(width - lastCanvasWidth) < 8) return;
    lastCanvasWidth = width;
    renderGraph();
}).observe(graphCanvas);

renderGraph();

/**
 * One button per canned prompt in `prompts-summar.md`, so a test run does not need the
 * prompt pasted in by hand. Clicking fills the input and submits the real form, so the
 * send path is exactly the one a typed message takes.
 */
fetch("/api/test-prompts")
    .then((r) => r.json())
    .then((prompts) => {
        prompts.forEach(({ label, prompt }) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "test-prompt";
            button.textContent = label;
            button.title = prompt;
            button.addEventListener("click", () => {
                input.value = prompt;
                form.requestSubmit();
            });
            testPrompts.appendChild(button);
        });
        testPrompts.hidden = !prompts.length;
    })
    .catch(() => {});
