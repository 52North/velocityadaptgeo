const form = document.getElementById("chat-form");
const input = document.getElementById("prompt");
const graphCanvas = document.getElementById("graph");
const graphStatus = document.getElementById("graph-status");
const runButton = document.getElementById("run-graph");

const threadId = crypto.randomUUID();

const SVG_NS = "http://www.w3.org/2000/svg";
const NODE_W = 200;
const NODE_H = 78;
const COL_GAP = 124;
const ROW_GAP = 30;
const PAD = 26;
const HIDDEN_CONFIG_KEYS = ["server_url", "timeout_seconds"];

let executionGraph = { nodes: [], edges: [] };
let lastValidation = null;
let nodeRuns = {};
let running = false;

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
        .map(([k, v]) => `${k}=${typeof v === "object" ? "{…}" : v}`);
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
        width: NODE_W, height: NODE_H, rx: 10, class: "gnode-box",
    }));
    group.appendChild(svgEl("rect", {
        width: 4, height: NODE_H, rx: 2, class: "gnode-accent",
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

    const full = svgEl("title");
    full.textContent = `${node.id}\nprocess: ${node.type}\nserver: ${(node.config || {}).server_url || "?"}\n${configSummary(node)}`;
    group.appendChild(full);

    svg.appendChild(group);
}

/**
 * Label an edge by its ports, kept short enough to sit inside the column gap without
 * being overlapped by the node boxes. Matching port names collapse to a single word.
 */
function portLabel(edge) {
    const out = edge.source_output || "default";
    const into = edge.target_input || "default";
    return out === into ? out : `${out}→${into}`;
}

function drawEdge(svg, edge, from, to) {
    const x1 = from.x + NODE_W;
    const y1 = from.y + NODE_H / 2;
    const x2 = to.x;
    const y2 = to.y + NODE_H / 2;
    const bend = Math.max(28, (x2 - x1) / 2);

    svg.appendChild(svgEl("path", {
        d: `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`,
        class: "gedge",
        "marker-end": "url(#arrow)",
    }));

    const label = svgEl("text", {
        x: (x1 + x2) / 2,
        y: (y1 + y2) / 2 - 8,
        class: "gedge-label",
        "text-anchor": "middle",
    });
    label.textContent = truncate(portLabel(edge), 18);
    svg.appendChild(label);
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

    const column = columnOf(nodes, edges);
    const rowCursor = new Map();
    const placed = new Map();

    nodes.forEach((node) => {
        const col = column.get(node.id) || 0;
        const row = rowCursor.get(col) || 0;
        rowCursor.set(col, row + 1);
        placed.set(node.id, {
            x: PAD + col * (NODE_W + COL_GAP),
            y: PAD + row * (NODE_H + ROW_GAP),
        });
    });

    const width = PAD * 2 + (Math.max(...column.values()) + 1) * (NODE_W + COL_GAP) - COL_GAP;
    const height = PAD * 2 + Math.max(...rowCursor.values()) * (NODE_H + ROW_GAP) - ROW_GAP;

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

    edges.forEach((edge) => {
        const from = placed.get(edge.source);
        const to = placed.get(edge.target);
        if (from && to) drawEdge(svg, edge, from, to);
    });

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
                    targetContainer.innerHTML = currentStepText.replace(/\n/g, '<br>');
                }
            } else if (node === "manager") {
                targetContainer.textContent = currentStepText.replace(/```(json)?/gi, '').trim();
            } else {
                targetContainer.innerHTML = currentStepText.replace(/\n/g, '<br>');
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

renderGraph();
