import json

from mythings.deps import DepEdge, DependencyGraph
from mythings.goals import GoalPart, GoalView, IssueRef

from mydashboard.graph import GraphEdge, as_dict, build_graph, render_json


def _issue(repo: str, number: int, *, state: str = "OPEN", title: str = "t", **kw) -> IssueRef:
    return IssueRef(
        repo=repo, number=number, title=title, state=state, url=f"https://x/{number}", **kw
    )


def test_isolated_issues_with_no_edge_and_no_goal_are_dropped() -> None:
    a = _issue("r", 1)
    b = _issue("r", 2)
    graph = DependencyGraph(nodes={a.slug: a, b.slug: b})
    model = build_graph(graph)
    assert model.nodes == ()


def test_an_edge_keeps_both_endpoints() -> None:
    a = _issue("r", 1)
    b = _issue("r", 2)
    edge = DepEdge(src="r#1", dst="r#2", kind="blocked_by", text="r#2")
    model = build_graph(DependencyGraph(nodes={a.slug: a, b.slug: b}, edges=(edge,)))
    assert {n.id for n in model.nodes} == {"r#1", "r#2"}
    assert model.edges == (GraphEdge(src="r#1", dst="r#2", kind="blocked_by", text="r#2"),)


def test_a_goal_member_is_kept_even_with_no_edge() -> None:
    a = _issue("r", 1)
    graph = DependencyGraph(nodes={a.slug: a})
    view = GoalView(goal_id="goal/x", parts=(GoalPart(repo="r"),), issues=(a,))
    model = build_graph(graph, goal_views=(view,))
    assert model.nodes[0].id == "r#1"
    assert model.nodes[0].goal == "x"


def test_node_state_reflects_open_blocked_and_closed() -> None:
    a = _issue("r", 1)  # open, blocked by r#2 (open)
    b = _issue("r", 2)  # open, blocks r#1
    c = _issue("r", 3, state="CLOSED")  # closed, part of a goal so it's kept
    edge = DepEdge(src="r#1", dst="r#2", kind="blocked_by", text="r#2")
    graph = DependencyGraph(nodes={a.slug: a, b.slug: b, c.slug: c}, edges=(edge,))
    view = GoalView(goal_id="goal/x", parts=(), issues=(c,))
    model = build_graph(graph, goal_views=(view,))
    by_id = {n.id: n for n in model.nodes}
    assert by_id["r#1"].state == "blocked"
    assert by_id["r#2"].state == "ready"
    assert by_id["r#3"].state == "closed"
    assert model.counts() == {"blocked": 1, "ready": 1, "closed": 1}


def test_a_node_carries_its_prio_and_lane_facets() -> None:
    a = _issue("r", 1, labels=("prio:P0", "lane:core"))
    b = _issue("r", 2)
    edge = DepEdge(src="r#1", dst="r#2", kind="blocked_by", text="r#2")
    model = build_graph(DependencyGraph(nodes={a.slug: a, b.slug: b}, edges=(edge,)))
    node = next(n for n in model.nodes if n.id == "r#1")
    assert (node.prio, node.lane) == ("P0", "core")


def test_depth_counts_the_chain_not_the_node_count() -> None:
    # r#1 -> r#2 -> r#3, so depth is 2/1/0. The x axis is depth, which is
    # bounded by the longest chain; the previous layout put node *order* on x
    # and grew sideways without bound as the fleet grew.
    issues = {f"r#{n}": _issue("r", n) for n in (1, 2, 3)}
    edges = (
        DepEdge(src="r#1", dst="r#2", kind="blocked_by", text="r#2"),
        DepEdge(src="r#2", dst="r#3", kind="blocked_by", text="r#3"),
    )
    model = build_graph(DependencyGraph(nodes=issues, edges=edges))
    assert {n.id: n.layer for n in model.nodes} == {"r#1": 2, "r#2": 1, "r#3": 0}


def test_cycle_members_are_flagged_and_layered_without_crashing() -> None:
    a = _issue("r", 1)
    b = _issue("r", 2)
    edges = (
        DepEdge(src="r#1", dst="r#2", kind="blocked_by", text="r#2"),
        DepEdge(src="r#2", dst="r#1", kind="blocked_by", text="r#1"),
    )
    graph = DependencyGraph(nodes={a.slug: a, b.slug: b}, edges=edges, cycles=(("r#1", "r#2"),))
    model = build_graph(graph)
    assert {n.id for n in model.nodes} == {"r#1", "r#2"}
    assert all(n.cyclic for n in model.nodes)
    assert model.cycles == (("r#1", "r#2"),)


def test_a_node_outside_a_cycle_is_not_flagged() -> None:
    a = _issue("r", 1)
    b = _issue("r", 2)
    edge = DepEdge(src="r#1", dst="r#2", kind="blocked_by", text="r#2")
    model = build_graph(DependencyGraph(nodes={a.slug: a, b.slug: b}, edges=(edge,)))
    assert not any(n.cyclic for n in model.nodes)


def test_workflow_after_edges_become_graph_edges() -> None:
    steps = [
        {
            "id": "planner",
            "trigger": {"type": "always"},
            "action": {"type": "run-cli", "stage": "myplanner", "tool": "my-planner"},
        },
        {
            "id": "dispatch",
            "trigger": {"type": "after", "nodes": ["planner"]},
            "action": {"type": "run-cli", "stage": "fleet-dispatch"},
        },
    ]
    model = build_graph(DependencyGraph(nodes={}), workflow_steps=steps)
    ids = {n.id for n in model.nodes}
    assert ids == {"workflow:planner", "workflow:dispatch"}
    assert model.edges == (
        GraphEdge(
            src="workflow:dispatch",
            dst="workflow:planner",
            kind="workflow",
            text="runs after planner",
        ),
    )
    planner = next(n for n in model.nodes if n.id == "workflow:planner")
    assert planner.repo == "my-planner"


def test_legacy_event_triggered_steps_produce_no_edges() -> None:
    steps = [
        {"id": "x", "on": {"tool": "t", "kind": "k", "outcome": "success"}, "then": {"repo": "r"}}
    ]
    model = build_graph(DependencyGraph(nodes={}), workflow_steps=steps)
    assert model.edges == ()
    assert {n.id for n in model.nodes} == {"workflow:x"}


def test_as_dict_sends_no_coordinates_only_the_depth() -> None:
    # The client computes positions from the depth so a filter can re-pack the
    # columns. Shipping x/y would freeze the layout at full-graph size.
    a = _issue("r", 1, title="Some issue")
    b = _issue("r", 2)
    edge = DepEdge(src="r#1", dst="r#2", kind="blocked_by", text="blocked by r#2")
    model = build_graph(DependencyGraph(nodes={a.slug: a, b.slug: b}, edges=(edge,)))
    payload = as_dict(model)
    node = payload["nodes"][0]
    assert "x" not in node and "y" not in node
    assert "layer" in node
    assert payload["edges"] == [
        {"src": "r#1", "dst": "r#2", "kind": "blocked_by", "text": "blocked by r#2"}
    ]


def test_render_json_carries_the_verbatim_blocker_clause() -> None:
    a = _issue("r", 1)
    b = _issue("r", 2)
    edge = DepEdge(src="r#1", dst="r#2", kind="depends_on", text="depends on r#2 for the seam")
    model = build_graph(DependencyGraph(nodes={a.slug: a, b.slug: b}, edges=(edge,)))
    payload = json.loads(render_json(model))
    assert payload["edges"][0]["text"] == "depends on r#2 for the seam"


def test_an_empty_model_renders_an_empty_payload() -> None:
    payload = json.loads(render_json(build_graph(DependencyGraph(nodes={}))))
    assert payload == {"nodes": [], "edges": [], "cycles": []}
