from __future__ import annotations

import html
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from mythings.deps import DependencyGraph
from mythings.goals import GoalView

# Node vertical/horizontal spacing for the deterministic layered layout --
# same "server computes geometry, client just draws" split my-office's
# build_scene() uses for desks.
_ROW_HEIGHT = 90
_COL_WIDTH = 220
_MARGIN = 40
_RADIUS = 10

_STATE_COLOR = {
    "blocked": "#c0392b",
    "ready": "#2e7d32",
    "closed": "#9e9e9e",
    "workflow": "#2962ff",
}


@dataclass(frozen=True)
class GraphNode:
    id: str  # "repo#N" for an issue, "workflow:<id>" for a workflow step
    kind: str  # "issue" | "workflow"
    label: str
    url: str = ""
    repo: str = ""
    state: str = "workflow"  # "blocked" | "ready" | "closed" | "workflow"
    goal: str | None = None
    layer: int = 0
    order: int = 0

    @property
    def x(self) -> int:
        return _MARGIN + self.order * _COL_WIDTH

    @property
    def y(self) -> int:
        return _MARGIN + self.layer * _ROW_HEIGHT


@dataclass(frozen=True)
class GraphEdge:
    src: str
    dst: str
    kind: str  # "blocked_by" | "depends_on" | "workflow"


@dataclass(frozen=True)
class GraphModel:
    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()
    cycles: tuple[tuple[str, ...], ...] = ()


def _workflow_edges(steps: Sequence[dict]) -> tuple[GraphEdge, ...]:
    # Only the explicit "after" DAG entries -- the ledger-event-triggered
    # handoffs (legacy `on`/`then` shape) fan out conditionally on runtime
    # data, not a fixed dependency, so they don't belong in a static graph.
    edges = []
    for step in steps:
        trigger = step.get("trigger") or {}
        if trigger.get("type") != "after":
            continue
        for pred in trigger.get("nodes") or ():
            edges.append(
                GraphEdge(src=f"workflow:{step['id']}", dst=f"workflow:{pred}", kind="workflow")
            )
    return tuple(edges)


def _workflow_nodes(steps: Sequence[dict]) -> tuple[GraphNode, ...]:
    out = []
    for step in steps:
        action = step.get("action") or {}
        label = action.get("stage") or step["id"]
        out.append(
            GraphNode(id=f"workflow:{step['id']}", kind="workflow", label=label, state="workflow")
        )
    return tuple(out)


def _layers(node_ids: set[str], edges: Sequence[GraphEdge]) -> dict[str, int]:
    out: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge.dst in node_ids:
            out[edge.src].append(edge.dst)

    memo: dict[str, int] = {}
    in_progress: set[str] = set()

    def layer(node: str) -> int:
        if node in memo:
            return memo[node]
        if node in in_progress:
            return 0  # a cycle edge -- already flagged separately, never used to place layout
        in_progress.add(node)
        result = 1 + max((layer(dst) for dst in out.get(node, ())), default=-1)
        in_progress.discard(node)
        memo[node] = result
        return result

    return {node: layer(node) for node in node_ids}


def build_graph(
    dep_graph: DependencyGraph,
    goal_views: Sequence[GoalView] = (),
    workflow_steps: Sequence[dict] = (),
) -> GraphModel:
    goal_of: dict[str, str] = {}
    for view in goal_views:
        for issue in view.issues:
            goal_of[issue.slug] = view.slug

    # An isolated issue with no edge and no goal is noise on a graph whose
    # point is "blocking one another" -- it already has a card on the
    # existing status page. Keep the graph to nodes that actually connect.
    connected = {e.src for e in dep_graph.edges} | {
        e.dst for e in dep_graph.edges if e.dst in dep_graph.nodes
    }
    in_a_goal = set(goal_of)
    keep = connected | in_a_goal

    issue_nodes = tuple(
        GraphNode(
            id=slug,
            kind="issue",
            label=issue.title,
            url=issue.url,
            repo=issue.repo,
            state=(
                "closed"
                if not issue.is_open
                else ("blocked" if slug in dep_graph.blocked else "ready")
            ),
            goal=goal_of.get(slug),
        )
        for slug, issue in dep_graph.nodes.items()
        if slug in keep
    )
    issue_edges = tuple(e for e in dep_graph.edges if e.src in keep and e.dst in keep)

    workflow_nodes = _workflow_nodes(workflow_steps)
    workflow_edges = _workflow_edges(workflow_steps)

    nodes_by_id = {n.id: n for n in issue_nodes + workflow_nodes}
    edges = issue_edges + workflow_edges
    layer_of = _layers(set(nodes_by_id), edges)

    by_layer: dict[int, list[str]] = defaultdict(list)
    for node_id in nodes_by_id:
        by_layer[layer_of.get(node_id, 0)].append(node_id)

    placed: list[GraphNode] = []
    for layer_no in sorted(by_layer):
        for order, node_id in enumerate(sorted(by_layer[layer_no])):
            base = nodes_by_id[node_id]
            placed.append(
                GraphNode(
                    id=base.id,
                    kind=base.kind,
                    label=base.label,
                    url=base.url,
                    repo=base.repo,
                    state=base.state,
                    goal=base.goal,
                    layer=layer_no,
                    order=order,
                )
            )

    return GraphModel(nodes=tuple(placed), edges=edges, cycles=dep_graph.cycles)


def render_json(model: GraphModel) -> bytes:
    payload = {
        "nodes": [
            {
                "id": n.id,
                "kind": n.kind,
                "label": n.label,
                "url": n.url,
                "repo": n.repo,
                "state": n.state,
                "goal": n.goal,
                "x": n.x,
                "y": n.y,
            }
            for n in model.nodes
        ],
        "edges": [{"src": e.src, "dst": e.dst, "kind": e.kind} for e in model.edges],
        "cycles": [list(c) for c in model.cycles],
    }
    return json.dumps(payload, indent=2).encode("utf-8")


def render_svg(model: GraphModel) -> str:
    if not model.nodes:
        return "<p><em>No blocking edges or goal-linked issues found.</em></p>"

    by_id = {n.id: n for n in model.nodes}
    width = max((n.x for n in model.nodes), default=0) + _COL_WIDTH
    height = max((n.y for n in model.nodes), default=0) + _ROW_HEIGHT

    lines = []
    for edge in model.edges:
        src, dst = by_id.get(edge.src), by_id.get(edge.dst)
        if src is None or dst is None:
            continue
        lines.append(
            f'<line x1="{src.x}" y1="{src.y}" x2="{dst.x}" y2="{dst.y}" '
            f'stroke="#999" stroke-width="1.5" marker-end="url(#arrow)" />'
        )

    cyclic = {slug for cycle in model.cycles for slug in cycle}
    shapes = []
    for n in model.nodes:
        color = _STATE_COLOR[n.state]
        ring = ' stroke="#000" stroke-width="3"' if n.id in cyclic else ""
        label = html.escape(n.label[:40] + ("…" if len(n.label) > 40 else ""))
        circle = f'<circle cx="{n.x}" cy="{n.y}" r="{_RADIUS}" fill="{color}"{ring} />'
        text = f'<text x="{n.x + _RADIUS + 6}" y="{n.y + 4}" font-size="12">{label}</text>'
        node_svg = f"{circle}\n{text}"
        if n.url:
            shapes.append(f'<a href="{html.escape(n.url)}" target="_blank">{node_svg}</a>')
        else:
            shapes.append(f"<g>{node_svg}</g>")

    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        'xmlns="http://www.w3.org/2000/svg">\n'
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="8" refY="3" '
        'orient="auto"><path d="M0,0 L8,3 L0,6 z" fill="#999" /></marker></defs>\n'
        + "\n".join(lines)
        + "\n"
        + "\n".join(shapes)
        + "\n</svg>"
    )
