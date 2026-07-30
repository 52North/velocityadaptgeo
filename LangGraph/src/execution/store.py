"""In-memory store for the most recent execution results of each thread.

Execution outputs are far too large to push through the event stream - a single OSM step
returns megabytes of geometry - so the run keeps them here and the frontend fetches only
the layer it wants to draw. The store is deliberately bounded and process-local: results
are a view of the last run, not a record of it, and are expected to disappear on restart.
"""

from collections import OrderedDict

MAX_THREADS = 8

_runs: OrderedDict[str, dict[str, dict]] = OrderedDict()


def start_run(thread_id: str) -> None:
    """Drop any results kept for a thread, so a new run never shows stale layers."""
    _runs.pop(thread_id, None)
    _runs[thread_id] = {}
    while len(_runs) > MAX_THREADS:
        _runs.popitem(last=False)


def save_node_result(thread_id: str, node_id: str, outputs: dict) -> None:
    """Record one node's full output map."""
    _runs.setdefault(thread_id, {})[node_id] = outputs


def get_node_output(thread_id: str, node_id: str, output: str):
    """Return one named output of one node, or None when it was never produced."""
    return (_runs.get(thread_id) or {}).get(node_id, {}).get(output)


def run_nodes(thread_id: str) -> list[str]:
    """List the nodes that produced results in a thread's last run."""
    return list((_runs.get(thread_id) or {}).keys())
