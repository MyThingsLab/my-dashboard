from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from mythings.deps import DependencyGraph
from mythings.goals import GoalView


@dataclass(frozen=True)
class GraphNode:
    id: str  # "repo#N" for an issue, "workflow:<id>" for a workflow step
    kind: str  # "issue" | "workflow"
    label: str
    url: str = ""
    repo: str = ""
    state: str = "workflow"  # "blocked" | "ready" | "closed" | "workflow"
    goal: str | None = None
    prio: str | None = None
    lane: str | None = None
    # How deep down the chain this node sits: layer 0 waits on nothing, and a
    # higher layer waits on something in the layer below. The client turns
    # this into an x column -- see _layers for why the split is drawn there.
    layer: int = 0
    cyclic: bool = False


@dataclass(frozen=True)
class GraphEdge:
    src: str
    dst: str
    kind: str  # "blocked_by" | "depends_on" | "workflow"
    # The clause exactly as the issue body wrote it, so the detail panel can
    # quote the author rather than paraphrase a parse result -- which matters
    # most in the case where the parse is the thing under suspicion.
    text: str = ""


@dataclass(frozen=True)
class GraphModel:
    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()
    cycles: tuple[tuple[str, ...], ...] = ()

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = defaultdict(int)
        for node in self.nodes:
            out[node.state] += 1
        return dict(out)


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
                GraphEdge(
                    src=f"workflow:{step['id']}",
                    dst=f"workflow:{pred}",
                    kind="workflow",
                    text=f"runs after {pred}",
                )
            )
    return tuple(edges)


def _workflow_nodes(steps: Sequence[dict]) -> tuple[GraphNode, ...]:
    out = []
    for step in steps:
        action = step.get("action") or {}
        label = action.get("stage") or step["id"]
        out.append(
            GraphNode(
                id=f"workflow:{step['id']}",
                kind="workflow",
                label=label,
                repo=action.get("tool") or "",
                state="workflow",
            )
        )
    return tuple(out)


def _layers(node_ids: set[str], edges: Sequence[GraphEdge]) -> dict[str, int]:
    # Only the graph-theory half of the layout lives here, where it is
    # testable; the client turns a layer into pixels. That split is what lets
    # the graph page re-pack its columns when a filter hides two thirds of
    # the nodes, without either side holding a second copy of the traversal.
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
    keep = connected | set(goal_of)
    cyclic = {slug for cycle in dep_graph.cycles for slug in cycle}

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
            prio=issue.facets.prio,
            lane=issue.facets.lane,
            cyclic=slug in cyclic,
        )
        for slug, issue in dep_graph.nodes.items()
        if slug in keep
    )
    issue_edges = tuple(
        GraphEdge(src=e.src, dst=e.dst, kind=e.kind, text=e.text)
        for e in dep_graph.edges
        if e.src in keep and e.dst in keep
    )

    nodes = issue_nodes + _workflow_nodes(workflow_steps)
    edges = issue_edges + _workflow_edges(workflow_steps)
    layer_of = _layers({n.id for n in nodes}, edges)

    placed = tuple(
        sorted(
            (
                GraphNode(
                    id=n.id,
                    kind=n.kind,
                    label=n.label,
                    url=n.url,
                    repo=n.repo,
                    state=n.state,
                    goal=n.goal,
                    prio=n.prio,
                    lane=n.lane,
                    layer=layer_of.get(n.id, 0),
                    cyclic=n.cyclic,
                )
                for n in nodes
            ),
            # Same-goal then same-repo neighbours land adjacent in a column,
            # which reads better on this graph than a crossing-minimising
            # order: the question asked of it is "what is this goal waiting
            # on", not "how few lines can cross".
            key=lambda n: (n.layer, n.goal or "~", n.repo, n.id),
        )
    )
    return GraphModel(nodes=placed, edges=edges, cycles=dep_graph.cycles)


def as_dict(model: GraphModel) -> dict:
    return {
        "nodes": [
            {
                "id": n.id,
                "kind": n.kind,
                "label": n.label,
                "url": n.url,
                "repo": n.repo,
                "state": n.state,
                "goal": n.goal,
                "prio": n.prio,
                "lane": n.lane,
                "layer": n.layer,
                "cyclic": n.cyclic,
            }
            for n in model.nodes
        ],
        "edges": [
            {"src": e.src, "dst": e.dst, "kind": e.kind, "text": e.text} for e in model.edges
        ],
        "cycles": [list(c) for c in model.cycles],
    }


def render_json(model: GraphModel) -> bytes:
    return json.dumps(as_dict(model), indent=2).encode("utf-8")
