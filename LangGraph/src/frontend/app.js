const form = document.getElementById("chat-form");
const testPrompts = document.getElementById("test-prompts");
const input = document.getElementById("prompt");
const sendButton = form.querySelector('button[type="submit"]');
const graphCanvas = document.getElementById("graph");
const graphStatus = document.getElementById("graph-status");
const graphLegend = document.getElementById("graph-legend");
const graphNotes = document.getElementById("graph-notes");
const runButton = document.getElementById("run-graph");
const deleteButton = document.getElementById("delete-mode");

const threadId = crypto.randomUUID();

const SVG_NS = "http://www.w3.org/2000/svg";
const NODE_W = 186;
const NODE_H = 78;
const COL_GAP_MIN = 104;  // floor for the space between columns; widened to fit input/output labels
const ROW_GAP = 30;
const BAND_GAP = 62;
const PAD = 22;
const IO_GAP = 15;
const IO_R = 3.5;
const CHAR_W = 6;  // advance width of one character in the 10px monospace input/output labels
const HOP_R = 6;
const HIDDEN_CONFIG_KEYS = ["server_url", "timeout_seconds"];

let executionGraph = { nodes: [], edges: [] };
let lastValidation = null;
let unmetCapabilities = [];
let nodeRuns = {};
let running = false;
let chatting = false;

/**
 * No hand edits or runs while a run or a chat turn is in progress: a turn rewrites the
 * thread's graph as it goes, so an edit made meanwhile could be lost or lose the turn's.
 */
function graphLocked() {
    return running || chatting;
}
let deleting = false;
let picked = null;
let nodeH = NODE_H;
let nodeIO = new Map();

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
    el.querySelectorAll("script, style, iframe, object, embed, form, meta, link, base, svg, math").forEach((n) =>
        n.remove()
    );
    el.querySelectorAll("*").forEach((n) => {
        [...n.attributes].forEach(({ name, value }) => {
            const isUrl = /^(href|src|xlink:href|action|formaction)$/i.test(name);
            if (/^on/i.test(name) || /^(style|srcdoc)$/i.test(name) || (isUrl && !isSafeUrl(value))) {
                n.removeAttribute(name);
            }
        });
    });
}

/**
 * Allowlist for link targets: http(s), mailto, and relative or fragment URLs.
 *
 * Browsers drop whitespace and control characters inside a scheme (`java&#x09;script:` runs),
 * so those are stripped before the scheme is read.
 */
function isSafeUrl(value) {
    const url = value.replace(/[\u0000- \u007f]/g, "");
    const scheme = url.match(/^([a-z][a-z0-9+.-]*):/i);
    return !scheme || /^(https?|mailto)$/i.test(scheme[1]);
}

const MANAGER_ACTIONS = { search: "Search", build: "Build", validate: "Validate", chat: "Chat", done: "Done" };

/** Pull one string field out of manager JSON that may still be mid-stream. */
function jsonField(text, key) {
    const m = text.match(new RegExp('"' + key + '"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)'));
    return m && m[1].replace(/\\(.)/g, (_, c) => (c === "n" ? "\n" : c));
}

function planRow(parent, cls, text) {
    const el = document.createElement("div");
    el.className = cls;
    el.textContent = text;
    parent.appendChild(el);
    return el;
}

/**
 * Render a manager decision as a plan card rather than the raw JSON it streams.
 *
 * The text arrives token by token, so a real parse only succeeds on the last chunk;
 * until then the fields that have already streamed in are picked out one at a time and
 * the card fills up as it goes. Everything is set as text, never markup: this is model
 * output that can echo whatever the user typed.
 */
function renderManagerPlan(el, raw) {
    const text = raw.replace(/```(json)?/gi, "").trim();
    let data = null;
    try { data = JSON.parse(text.slice(text.indexOf("{"))); } catch (e) { /* still streaming */ }

    const action = data?.next_action || jsonField(text, "next_action");
    const name = data?.step?.name || jsonField(text, "name");
    const reasoning = data?.reasoning || jsonField(text, "reasoning");
    const instruction = data ? data.step?.instruction : jsonField(text, "instruction");

    el.textContent = "";
    if (!action && !name && !reasoning) {
        planRow(el, "plan-wait", "planning…");
        return;
    }

    const head = planRow(el, "plan-head", "");
    if (action) planRow(head, `plan-action action-${action}`, MANAGER_ACTIONS[action] || action);
    if (name) planRow(head, "plan-name", name);

    if (typeof instruction === "string" && instruction) {
        planRow(el, "plan-instruction", instruction);
    } else if (instruction && typeof instruction === "object") {
        const box = planRow(el, "plan-op", "");
        if (instruction.op) planRow(box, "plan-op-name", instruction.op);
        Object.entries(instruction.args || {}).forEach(([key, value]) => {
            const row = planRow(box, "plan-arg", "");
            planRow(row, "plan-arg-key", key);
            planRow(row, "plan-arg-val", typeof value === "object" ? JSON.stringify(value) : String(value));
        });
    }
    if (reasoning) planRow(el, "plan-reason", reasoning);
}

/**
 * Render the retriever's catalog hits as ranked rows instead of the raw
 * `N. process_id | title | similarity=0.83` lines it emits. Anything that does not
 * match that shape (the "no matching processes" case) is kept as plain text.
 */
function renderCandidates(el, raw) {
    el.textContent = "";
    const head = planRow(el, "plan-head", "");
    planRow(head, "plan-action action-search", "Catalog");
    planRow(head, "plan-name", /^Top retrieved/.test(raw.trim()) ? "Top retrieved processes" : "No match");

    let rows = 0;
    raw.split("\n").forEach((line) => {
        const m = line.match(/^\s*(\d+)\.\s*(.*?)\s*\|\s*(.*?)\s*\|\s*similarity=(.*)$/);
        if (!m) return;
        rows += 1;
        const [, rank, pid, title, sim] = m;
        const score = Number(sim);
        const strength = !Number.isFinite(score) ? "" : score >= 0.7 ? " score-strong" : score <= 0.55 ? " score-weak" : "";

        const row = planRow(el, "candidate", "");
        planRow(row, "candidate-rank", rank);
        const body = planRow(row, "candidate-body", "");
        planRow(body, "candidate-id", pid);
        if (title) planRow(body, "candidate-title", title);

        const meter = planRow(row, `candidate-score${strength}`, "");
        planRow(meter, "candidate-score-value", Number.isFinite(score) ? score.toFixed(2) : sim);
        const fill = planRow(planRow(meter, "candidate-bar", ""), "candidate-bar-fill", "");
        fill.style.width = `${Math.round(Math.min(1, Math.max(0, score || 0)) * 100)}%`;
    });

    if (!rows) planRow(el, "plan-instruction", raw.trim());
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
 * Collect, per node, every input and output the process declares - not only the wired ones -
 * so an unconnected parameter shows up as an empty socket instead of being invisible. They keep
 * the order the catalog declares them in, so a node's parameters always stack in the same
 * order as the process signature. An input/output named only by an edge is appended rather than
 * dropped: a graph wired to an undeclared name should be visible, not silently centred.
 */
function ioOf(nodes, edges) {
    const map = new Map(nodes.map((n) => [n.id, {
        in: [...(n.inputs || [])], out: [...(n.outputs || [])], wired: new Set(),
        values: Object.fromEntries(Object.entries(n.config || {})
            .filter(([k]) => !HIDDEN_CONFIG_KEYS.includes(k))
            .map(([k, v]) => [k, formatValue(v)])),
    }]));
    // A value set on an input the catalog never declared is still a parameter of this node,
    // so it gets a socket like any other rather than disappearing with the box summary.
    map.forEach((p) => Object.keys(p.values).forEach((k) => {
        if (!p.in.includes(k)) p.in.push(k);
    }));
    edges.forEach((e) => [["out", e.source, e.source_output], ["in", e.target, e.target_input]]
        .forEach(([side, id, edgeName]) => {
            const p = map.get(id);
            if (!p) return;
            const name = edgeName || "default";
            if (!p[side].includes(name)) p[side].push(name);
            p.wired.add(`${side}:${name}`);
        }));
    return map;
}

/** Y of one input/output anchor relative to the node top: anchors spread evenly down the border. */
function ioY(nodeId, side, name) {
    const list = (nodeIO.get(nodeId) || {})[side] || [];
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

/** One static value, short enough to print beside its socket. */
function formatValue(v) {
    if (Array.isArray(v)) return `[${v.join(",")}]`;
    return v !== null && typeof v === "object" ? "{…}" : String(v);
}

/**
 * What one input/output prints beside its socket: its name, and its static value when it has one.
 *
 * The values used to be summarised inside the box in `config` order, which is not the
 * order the sockets stack in - so a node listed its parameters twice and the two lists
 * disagreed. Printing each value on the input it belongs to leaves one place to read it.
 * A wired input shows no value: an edge overrides `config` at run time, so the label
 * would be naming something that will not be used.
 */
function ioLabel(nodeId, side, name) {
    const io = nodeIO.get(nodeId);
    const value = side === "in" && io && !io.wired.has(`in:${name}`)
        ? io.values[name] : undefined;
    return value === undefined
        ? truncate(name, 14)
        : `${truncate(name, 14)}=${truncate(value, 12)}`;
}

function drawNode(svg, node, x, y) {
    const run = nodeRuns[node.id];
    const state = run ? run.state : "idle";
    const group = svgEl("g", {
        class: `gnode gnode-${state}`, transform: `translate(${x}, ${y})`,
        "data-node": node.id,
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

    const io = nodeIO.get(node.id) || { in: [], out: [], wired: new Set(), values: {} };
    [["in", 0, "end", -7, 13], ["out", NODE_W, "start", 7, -7]].forEach(
        ([side, cx, anchor, dx, dy]) => {
            io[side].forEach((name) => {
                // An unwired input/output is drawn hollow and its name dimmed, so the sockets still
                // free to be connected read as offers rather than as part of the pipeline.
                const kind = io.wired.has(`${side}:${name}`) ? "-wired" : "-open";
                const cy = ioY(node.id, side, name);
                // One group per input/output: the dot, an oversized transparent grab area so a
                // wire can be started without pixel-hunting, and the name. It carries the
                // input/output's identity and its absolute anchor, which is all the drag handlers
                // need to know about the drawing.
                const socket = svgEl("g", {
                    class: "gio-group", "data-node": node.id, "data-side": side,
                    "data-io": name, "data-ax": x + cx, "data-ay": y + cy,
                });
                socket.appendChild(svgEl("circle", { cx, cy, r: IO_R, class: `gio gio${kind}` }));
                socket.appendChild(svgEl("circle", { cx, cy, r: 8, class: "gio-hit" }));
                const label = svgEl("text", {
                    x: cx + dx, y: cy + dy,
                    class: `gio-label gio-label${kind}`, "text-anchor": anchor,
                });
                label.textContent = ioLabel(node.id, side, name);
                socket.appendChild(label);
                group.appendChild(socket);
            });
        },
    );

    // Input/output labels are truncated to fit beside their socket; the tooltip spells the
    // values out in full, in the same order the sockets stack.
    const full = svgEl("title");
    full.textContent = [
        node.id, `process: ${node.type}`,
        `server: ${(node.config || {}).server_url || "?"}`,
        ...io.in.filter((name) => io.values[name] !== undefined)
            .map((name) => `${name} = ${io.values[name]}`),
    ].join("\n");
    group.appendChild(full);

    svg.appendChild(group);
}

/** The two endpoints of an edge, each on its own input/output anchor. */
function edgeEnds(edge, from, to) {
    return {
        x1: from.x + NODE_W,
        y1: from.y + ioY(edge.source, "out", edge.source_output || "default"),
        x2: to.x,
        y2: to.y + ioY(edge.target, "in", edge.target_input || "default"),
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
 * and two edges leaving the same output are one line splitting, not a crossing.
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
 * on an input/output anchor or under the arrowhead.
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
function drawRoute(svg, pts, others, edge) {
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
    // A fat transparent copy on top: a 1.5px line is not something to ask anyone to aim
    // at, and the four fields are what `disconnect` needs to remove this edge and no other.
    svg.appendChild(svgEl("path", {
        d: line, class: "gedge-hit",
        "data-edge": JSON.stringify([
            edge.source, edge.source_output || "default",
            edge.target, edge.target_input || "default",
        ]),
    }));
}

/**
 * Render the OGC execution graph: one box per process node, one arrow per wired input.
 * Called on every graph update so the DAG grows as the workflow is assembled.
 */
/**
 * Note, beside the graph, every capability the user asked for that the catalog cannot
 * perform. These are gaps the graph itself cannot show - nothing was added for them -
 * so without this panel the only record is a sentence in the chat that scrolls away.
 */
function renderNotes() {
    graphNotes.innerHTML = "";
    graphNotes.hidden = !unmetCapabilities.length;
    if (graphNotes.hidden) return;

    const title = document.createElement("div");
    title.className = "graph-notes-title";
    title.textContent = `Not in the catalog — ${unmetCapabilities.length} capabilit${unmetCapabilities.length === 1 ? "y" : "ies"} not built`;
    graphNotes.appendChild(title);

    unmetCapabilities.forEach((note) => {
        const row = document.createElement("div");
        row.className = "graph-note";
        const what = document.createElement("b");
        what.textContent = note.capability || "(unnamed capability)";
        row.appendChild(what);
        if (note.closest_process) {
            const sim = typeof note.similarity === "number" ? `, similarity ${note.similarity.toFixed(2)}` : "";
            row.appendChild(document.createTextNode(` — closest match was ${note.closest_process}${sim}, which does not do it`));
        }
        graphNotes.appendChild(row);
    });
}

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
    renderNotes();
    runButton.disabled = graphLocked() || !nodes.length;
    runButton.textContent = running ? "Running…" : "Run";
    deleteButton.disabled = graphLocked() || !nodes.length;
    if (deleteButton.disabled && deleting) armDelete(false);

    clearPick();
    closeEditor();
    graphCanvas.innerHTML = "";

    if (!nodes.length) {
        const empty = document.createElement("div");
        empty.className = "graph-empty";
        empty.textContent = "No execution graph yet. Describe a geospatial task and the matching OGC processes will be wired up here.";
        graphCanvas.appendChild(empty);
        return;
    }

    nodeIO = ioOf(nodes, edges);
    const maxIO = Math.max(0, ...[...nodeIO.values()].map(
        (p) => Math.max(p.in.length, p.out.length)
    ));
    nodeH = Math.max(NODE_H, (maxIO + 1) * IO_GAP);

    // Labels print outside the box - inputs into the gap left of their column, outputs into
    // the gap right of it - so the gap is measured from the longest label actually drawn
    // rather than fixed. A graph with no static values keeps a tight layout; a long value
    // widens the columns instead of overprinting its neighbour.
    const widest = (side) => CHAR_W * Math.max(0, ...[...nodeIO].flatMap(
        ([id, p]) => p[side].map((name) => ioLabel(id, side, name).length)
    ));
    const inW = widest("in");
    const outW = widest("out");
    const colGap = Math.max(COL_GAP_MIN, inW + outW + IO_R * 4);

    const column = columnOf(nodes, edges);
    const available = Math.max(canvasContentWidth(), NODE_W + PAD * 2);
    const perBand = Math.max(1, Math.floor(
        (available - PAD * 2 - inW - outW + colGap) / (NODE_W + colGap)
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

    // The outermost columns have no neighbouring gap to print into, so they get a gutter -
    // reserved only when a node there actually has labelled inputs/outputs.
    const usedCols = Math.min(perBand, Math.max(...column.values()) + 1);
    const gutter = (w, test) => PAD + ([...placed.entries()].some(
        ([id, slot]) => test(slot, nodeIO.get(id) || { in: [], out: [] })
    ) ? w + IO_R * 2 : 0);
    const leftPad = gutter(inW, (slot, p) => slot.colInBand === 0 && p.in.length);
    const rightPad = gutter(outW, (slot, p) => slot.colInBand === usedCols - 1 && p.out.length);

    placed.forEach((slot) => {
        slot.x = leftPad + slot.colInBand * (NODE_W + colGap);
        slot.y = bandTop.get(slot.band) + slot.row * (nodeH + ROW_GAP);
    });

    const width = Math.max(leftPad + rightPad + usedCols * (NODE_W + colGap) - colGap, available);
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
        return [{ edge, pts: edgeRoute(edge, from, to, laneY) }];
    });
    // Each route hops over the ones drawn before it, so exactly one of any two crossing
    // lines carries the bump.
    routes.forEach((r, i) => drawRoute(svg, r.pts, routes.slice(0, i).map((o) => o.pts), r.edge));

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

/** Client coordinates in the SVG's own units, so a drawn line lands under the cursor. */
function svgPoint(svg, evt) {
    const pt = svg.createSVGPoint();
    pt.x = evt.clientX;
    pt.y = evt.clientY;
    return pt.matrixTransform(svg.getScreenCTM().inverse());
}

/**
 * Apply one hand edit through the same ops the assistant uses.
 *
 * The server owns the graph, so the browser never mutates its copy: it sends the op and
 * redraws whatever comes back. That way an edit the builder would refuse (a cycle, a
 * self-link) simply reports itself instead of leaving the panel showing a graph the
 * assistant does not have.
 */
async function graphOp(op, args) {
    try {
        const resp = await fetch("/api/graph/op", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ thread_id: threadId, op, args }),
        });
        const data = await resp.json();
        if (!resp.ok) {
            graphStatus.textContent = data.detail || "edit refused";
            graphStatus.className = "graph-status bad";
            return false;
        }
        executionGraph = data.graph;
        lastValidation = data.validation;
        renderGraph();
        return true;
    } catch (err) {
        graphStatus.textContent = `edit failed: ${err.message}`;
        graphStatus.className = "graph-status bad";
        return false;
    }
}

/**
 * Type a literal into an input no edge feeds.
 *
 * This is how a wrong value gets corrected without re-prompting the assistant. Only open
 * inputs are offered: an output is produced, not chosen, and a wired input already has
 * its value, so editing either would be a promise the executor does not keep. The answer
 * is read as JSON so numbers and lists stay typed, falling back to the raw string.
 */
/** Take down the value editor, if one is open. */
function closeEditor() {
    if (editor) editor.remove();
    editor = null;
}

function editInput(nodeId, side, input, wired) {
    if (side !== "in" || wired) return;
    closeEditor();
    const node = (executionGraph.nodes || []).find((n) => n.id === nodeId);
    const current = (node && node.config || {})[input];
    const socket = graphCanvas.querySelector(
        `.gio-group[data-node="${nodeId}"][data-side="in"][data-io="${input}"]`);
    if (!socket) return;
    const at = socket.getBoundingClientRect();

    // A form, so Enter commits for free.
    editor = document.createElement("form");
    editor.className = "input-editor";
    editor.style.left = `${at.left}px`;
    editor.style.top = `${at.bottom + 6}px`;
    const name = document.createElement("label");
    name.textContent = input;
    const field = document.createElement("input");
    Object.assign(field, { type: "text", autocomplete: "off", placeholder: "empty clears" });
    field.value = current === undefined ? "" : JSON.stringify(current);
    const hint = document.createElement("span");
    hint.textContent = "Enter applies · Esc cancels";
    editor.append(name, field, hint);

    editor.addEventListener("submit", (evt) => {
        evt.preventDefault();
        const raw = field.value.trim();
        let value = null;
        if (raw) {
            try { value = JSON.parse(raw); } catch { value = raw; }
        }
        closeEditor();
        graphOp("set_input", { node_id: nodeId, input, value });
    });
    field.addEventListener("blur", closeEditor);

    document.body.appendChild(editor);
    field.focus();
    field.select();
}

/**
 * Drag an output onto an input (or the other way round) to wire them together.
 *
 * A drag that ends where it started is a click, and means "edit this input's value" - the
 * two share a target because they are the same gesture on the same thing, and telling
 * them apart by distance costs less than a second affordance per socket. Direction is
 * normalised here rather than refused, so dragging an input onto an output works too.
 */
let draft = null;
let suppressClick = false;
let editor = null;

// Scrolling slides the drawing out from under a field pinned to one of its sockets.
graphCanvas.addEventListener("scroll", closeEditor);

graphCanvas.addEventListener("pointerdown", (evt) => {
    const socket = evt.target.closest(".gio-group");
    if (!socket || graphLocked() || deleting || picked || evt.button !== 0) return;
    const svg = graphCanvas.querySelector("svg");
    if (!svg) return;
    evt.preventDefault();
    const path = svgEl("path", { class: "gedge-draft" });
    svg.appendChild(path);
    draft = { svg, path, socket, moved: false, ax: +socket.dataset.ax, ay: +socket.dataset.ay };
    graphCanvas.classList.add("wiring");
});

window.addEventListener("pointermove", (evt) => {
    const live = draft || (picked && picked.kind === "edge" ? picked : null);
    if (!live) return;
    const at = svgPoint(live.svg, evt);
    if (draft && Math.hypot(at.x - live.ax, at.y - live.ay) > 14) draft.moved = true;
    live.path.setAttribute("d", `M ${live.ax} ${live.ay} L ${at.x} ${at.y}`);
});

window.addEventListener("pointerup", (evt) => {
    if (!draft) return;
    const { socket, moved } = draft;
    suppressClick = moved;
    draft.path.remove();
    graphCanvas.classList.remove("wiring");
    draft = null;

    const from = socket.dataset;
    if (!moved) return editInput(from.node, from.side, from.io,
                                 socket.querySelector(".gio-wired"));

    const target = document.elementFromPoint(evt.clientX, evt.clientY)?.closest(".gio-group");
    if (!target) return;
    const to = target.dataset;
    if (to.node === from.node || to.side === from.side) return;

    const [out, inp] = from.side === "out" ? [from, to] : [to, from];
    graphOp("connect", {
        source: out.node, source_output: out.io,
        target: inp.node, target_input: inp.io,
    });
});

/**
 * Arm or disarm removal.
 *
 * Deleting is deliberately two gestures: nothing on the canvas removes anything until
 * Delete is pressed, so a stray click can never cost a node. While armed the canvas says
 * so - red hover on whatever is about to go - and one removal disarms it again, which is
 * both the confirmation and the way out. Escape leaves without removing anything.
 */
function armDelete(on) {
    deleting = on && !graphLocked();
    graphCanvas.classList.toggle("deleting", deleting);
    deleteButton.classList.toggle("armed", deleting);
    deleteButton.textContent = deleting ? "Click to delete…" : "Delete";
}

deleteButton.addEventListener("click", () => armDelete(!deleting));
window.addEventListener("keydown", (evt) => {
    if (evt.key !== "Escape") return;
    if (editor) return closeEditor();
    if (deleting) armDelete(false);
    if (picked) {
        clearPick();
        renderGraph();
    }
});

/** Drop whatever is held: the canvas goes back to plain clicking. */
function clearPick() {
    if (picked && picked.path) picked.path.remove();
    picked = null;
    graphCanvas.classList.remove("picking", "wiring");
    graphCanvas.querySelectorAll(".picked").forEach((el) => el.classList.remove("picked"));
}

/**
 * Pick something up, then click where it belongs.
 *
 * Two edits are really the same gesture - re-pointing a connection and trading two nodes'
 * places - and both are corrections of an existing graph rather than additions to it, so
 * neither is reachable by dragging from a free input/output. Holding the thing between two clicks
 * is what makes them one mechanism: the first click says what moves, the second says
 * where, and Escape drops it. Nothing changes until the second click lands.
 */
function pickEdge(hit) {
    const [source, source_output] = JSON.parse(hit.dataset.edge);
    const svg = graphCanvas.querySelector("svg");
    const anchor = graphCanvas.querySelector(
        `.gio-group[data-node="${source}"][data-side="out"][data-io="${source_output}"]`);
    if (!svg || !anchor) return;

    const path = svgEl("path", { class: "gedge-draft" });
    svg.appendChild(path);
    picked = {
        kind: "edge", edge: JSON.parse(hit.dataset.edge), svg, path,
        ax: +anchor.dataset.ax, ay: +anchor.dataset.ay,
    };
    // Every open input lights up, exactly as it does mid-drag: the loose end is looking
    // for the same kind of home either way.
    graphCanvas.classList.add("picking", "wiring");
    graphStatus.textContent = `re-pointing ${source}.${source_output} — click an input`;
    graphStatus.className = "graph-status";
}

async function dropEdge(end) {
    const [source, source_output, target, target_input] = picked.edge;
    clearPick();
    if (end.node === target && end.io === target_input) return renderGraph();

    // Connect first, disconnect second: if the new wiring is refused - a cycle, say - the
    // original connection is still there, rather than lost to a half-finished move.
    if (await graphOp("connect", {
        source, source_output, target: end.node, target_input: end.io,
    })) {
        await graphOp("disconnect", { source, source_output, target, target_input });
    }
}

async function swapWith(nodeId) {
    const node_a = picked.id;
    clearPick();
    const before = (executionGraph.edges || []).length;
    if (!await graphOp("swap_nodes", { node_a, node_b: nodeId })) return;

    const lost = before - (executionGraph.edges || []).length;
    if (lost > 0) {
        graphStatus.textContent +=
            ` · ${lost} connection${lost === 1 ? "" : "s"} could not carry over`;
        graphStatus.className = "graph-status bad";
    }
}

graphCanvas.addEventListener("click", (evt) => {
    if (suppressClick) return void (suppressClick = false);
    if (graphLocked()) return;

    const hit = evt.target.closest("[data-edge]");
    const socket = evt.target.closest(".gio-group");
    const node = evt.target.closest(".gnode");

    if (deleting) {
        if (!hit && !node) return;
        armDelete(false);
        if (hit) {
            const [source, source_output, target, target_input] = JSON.parse(hit.dataset.edge);
            graphOp("disconnect", { source, source_output, target, target_input });
        } else {
            graphOp("remove_node", { node_id: node.dataset.node });
        }
        return;
    }

    if (picked) {
        if (picked.kind === "edge" && socket && socket.dataset.side === "in") return dropEdge(socket.dataset);
        if (picked.kind === "node" && node && node.dataset.node !== picked.id) return swapWith(node.dataset.node);
        clearPick();
        return renderGraph();
    }

    if (hit) return pickEdge(hit);
    // Only a wired node offers a swap: trading places with nothing to trade is a no-op,
    // and a click on an input/output is its own gesture, not the node's.
    if (!node || socket) return;
    const id = node.dataset.node;
    if (!(executionGraph.edges || []).some((e) => e.source === id || e.target === id)) return;

    picked = { kind: "node", id };
    node.classList.add("picked");
    graphCanvas.classList.add("picking");
    graphStatus.textContent = `swapping ${id} — click the node to trade places with`;
    graphStatus.className = "graph-status";
});

/**
 * Right-click a line to cut it.
 *
 * Losing a node costs the work that built it, so removing one stays behind the armed
 * Delete button; a connection is one drag to put back, and cheap enough to give the
 * gesture the browser already reserves for acting on the thing under the cursor.
 */
graphCanvas.addEventListener("contextmenu", (evt) => {
    const hit = evt.target.closest("[data-edge]");
    if (!hit || graphLocked()) return;
    evt.preventDefault();
    if (picked) clearPick();
    if (deleting) armDelete(false);
    const [source, source_output, target, target_input] = JSON.parse(hit.dataset.edge);
    graphOp("disconnect", { source, source_output, target, target_input });
});

/**
 * Forget the layers of a previous run, so the results window never mixes the outputs of
 * two runs or of a graph that has since been rebuilt.
 */
function resetResultLayers() {
    if (leafletMap) {
        layerCache.forEach((layer) => leafletMap.removeLayer(layer));
    }
    layerCache.clear();
    layerLoads.clear();
    resultsGeneration += 1;
    layersListed = false;
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
    if (graphLocked() || !(executionGraph.nodes || []).length) return;

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
// Fetches still loading, by layer key, so ticking a box twice never builds two layers.
const layerLoads = new Map();
// Bumped by every reset: a fetch that returns under an older number belongs to a previous run.
let resultsGeneration = 0;
// Whether this run's layers have been listed yet; the first listing shows the last layer.
let layersListed = false;

/**
 * Register the drawable outputs a finished node reported, so they can be offered as
 * map layers. Non-GeoJSON outputs (counts, areas, CRS codes) are simply absent here.
 */
function registerLayers(nodeId, process, geo) {
    Object.entries(geo || {}).forEach(([output, info]) => {
        mapLayers.push({
            key: `${nodeId}.${output}`, node: nodeId, process, output,
            kind: info.kind, count: info.features, index: mapLayers.length,
            on: false, note: `${info.kind}${info.features > 1 ? ` · ${info.features}` : ""}`, noteEl: null,
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

/** Popup content for one feature, as nodes: the properties come from OSM and other external data. */
function describeProperties(properties) {
    const rows = Object.entries(properties || {}).filter(([, v]) => v !== null && typeof v !== "object");
    const el = document.createElement("div");
    if (!rows.length) {
        el.textContent = "no attributes";
        return el;
    }
    rows.forEach(([k, v], i) => {
        if (i) el.append(document.createElement("br"));
        const key = document.createElement("strong");
        key.textContent = k;
        el.append(key, `: ${v}`);
    });
    return el;
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

/** Show `text` in the entry's row, and keep it for when the list is drawn again. */
function setNote(entry, text) {
    entry.note = text;
    if (entry.noteEl) entry.noteEl.textContent = text;
}

/** Fetch one output and build its map layer; throws when the server has none. */
async function fetchLayer(entry) {
    const url = `/api/result?thread_id=${encodeURIComponent(threadId)}` +
        `&node=${encodeURIComponent(entry.node)}&output=${encodeURIComponent(entry.output)}`;
    const response = await fetch(url);
    if (!response.ok) throw new Error(String(response.status));
    const collection = await response.json();
    const distances = [...new Set((collection.features || [])
        .map((f) => f.properties && f.properties.outerDistance)
        .filter((v) => typeof v === "number"))].sort((a, b) => a - b);

    const layer = L.geoJSON(collection, {
        style: styleFor(entry, distances),
        pointToLayer: (feature, latlng) => L.circleMarker(latlng, { radius: 5 }),
        onEachFeature: (feature, lyr) => lyr.bindPopup(describeProperties(feature.properties)),
    });
    const note = collection.truncated
        ? `showing ${collection.features.length} of ${collection.total}`
        : `${collection.features.length} feature(s)`;
    return { layer, note };
}

/**
 * Switch one layer on or off. `entry.on` is what its box shows, so the map is made to
 * follow it even when a fetch returns after the box changed or the results were reset.
 */
async function toggleLayer(entry, on) {
    entry.on = on;
    if (!on) {
        const existing = layerCache.get(entry.key);
        if (existing) leafletMap.removeLayer(existing);
        fitToVisible();
        return;
    }

    if (!layerCache.has(entry.key)) {
        const generation = resultsGeneration;
        setNote(entry, "loading…");
        if (!layerLoads.has(entry.key)) layerLoads.set(entry.key, fetchLayer(entry));
        let loaded;
        try {
            loaded = await layerLoads.get(entry.key);
        } catch (err) {
            if (generation !== resultsGeneration) return;
            layerLoads.delete(entry.key);  // ticking again retries
            setNote(entry, `failed (${err.message})`);
            return;
        }
        // Reset while loading: the layer belongs to a run whose results are gone.
        if (generation !== resultsGeneration) return;
        layerLoads.delete(entry.key);
        if (!layerCache.has(entry.key)) layerCache.set(entry.key, loaded.layer);
        setNote(entry, loaded.note);
        // Unticked while loading: kept for the next tick, not drawn.
        if (!entry.on) return;
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

    // Afterwards the boxes show what each entry holds, so a reopened list matches the map.
    if (!layersListed) {
        layersListed = true;
        mapLayers[mapLayers.length - 1].on = true;
    }

    mapLayers.forEach((entry) => {
        const row = document.createElement("label");
        row.className = "layer-row";

        const box = document.createElement("input");
        box.type = "checkbox";
        box.checked = entry.on;
        const note = document.createElement("span");
        note.className = "layer-note";
        entry.noteEl = note;
        note.textContent = entry.note;

        const swatch = document.createElement("span");
        swatch.className = "layer-swatch";
        swatch.style.background = LAYER_COLORS[entry.index % LAYER_COLORS.length];

        const title = document.createElement("span");
        title.className = "layer-title";
        title.textContent = `${entry.process}.${entry.output}`;

        box.addEventListener("change", () => toggleLayer(entry, box.checked));

        row.append(box, swatch, title, note);
        resultsLayers.appendChild(row);

        if (entry.on) toggleLayer(entry, true);
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

/**
 * Hold further sends while a turn streams. A second turn on the same thread would run
 * alongside the first: both write into one conversation and their tokens interleave here.
 * The input stays editable, so the next message can be typed while waiting. The graph is
 * locked too, see `graphLocked`.
 */
function setChatting(on) {
    chatting = on;
    sendButton.disabled = on;
    testPrompts.querySelectorAll("button").forEach((button) => {
        button.disabled = on;
    });
    renderGraph();  // the Run and Delete buttons follow the lock
}

form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (chatting) return;

    const prompt = input.value.trim();
    if (!prompt) return;

    addMessage("user", prompt);
    input.value = "";
    setChatting(true);

    let currentStep = null;
    let currentStepMessage = null;
    let currentStepText = "";

    const evtSource = new EventSource(
        `/api/stream?prompt=${encodeURIComponent(prompt)}&thread_id=${encodeURIComponent(threadId)}`
    );

    // The server ends every turn with a `done` event, so a stream that closes without one broke.
    let finished = false;
    const finish = () => {
        finished = true;
        evtSource.close();
        setChatting(false);
        if (currentStepMessage) {
            currentStepMessage.classList.remove("streaming");
            currentStepMessage.classList.add("final");
        }
    };
    const streamError = (text) => {
        addMessage("assistant", text).classList.add("stream-error");
    };

    evtSource.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.event === "done") return finish();
        if (data.event === "error") return streamError(`The assistant stopped with an error: ${data.error}`);

        if (data.event === "graph") {
            if (data.workflow_graph) {
                executionGraph = data.workflow_graph;
                nodeRuns = {};
                resetResultLayers();
            }
            if (data.last_validation) lastValidation = data.last_validation;
            if (data.unmet_capabilities) unmetCapabilities = data.unmet_capabilities;
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
                currentStepMessage.classList.add("manager-plan");
            }
            if (node === "retriever" && messageType !== "tool") {
                currentStepMessage.classList.add("candidate-list");
            }
        }

        if (content) {
            currentStepText += content;

            if (messageType === "tool") {
                currentStepMessage.style.fontStyle = "italic";
                currentStepMessage.style.color = "#666";

                try {
                    const parsedContent = JSON.parse(currentStepText);
                    // Built as nodes, not HTML: tool results carry external text (OSM names, echoed prompts).
                    const label = document.createElement("strong");
                    label.textContent = `Action (${node}):`;
                    const pre = document.createElement("pre");
                    pre.style.margin = "5px 0 0 0";
                    pre.style.fontSize = "0.9em";
                    pre.textContent = JSON.stringify(parsedContent, null, 2);
                    currentStepMessage.replaceChildren(label, pre);
                } catch (e) {
                    renderMarkdown(currentStepMessage, currentStepText);
                }
            } else if (node === "manager") {
                renderManagerPlan(currentStepMessage, currentStepText);
            } else if (node === "retriever") {
                renderCandidates(currentStepMessage, currentStepText);
            } else {
                renderMarkdown(currentStepMessage, currentStepText);
            }
        }

        chat.scrollTop = chat.scrollHeight;
    };


    // Closed here either way: left open, EventSource reconnects and the prompt runs again.
    evtSource.onerror = () => {
        if (!finished) streamError("Connection to the assistant was lost; the reply may be incomplete.");
        finish();
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
 * One button per canned prompt in `prompts.jsonl`, so a test run does not need the
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
            button.disabled = chatting;
            button.addEventListener("click", () => {
                input.value = prompt;
                form.requestSubmit();
            });
            testPrompts.appendChild(button);
        });
        testPrompts.hidden = !prompts.length;
    })
    .catch(() => {});
