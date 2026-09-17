import json

from mythings.deps import DepEdge, DependencyGraph
from mythings.goals import GoalPart, GoalView, IssueRef

from mydashboard.graph import GraphEdge, build_graph, render_json, render_svg


def _issue(repo: str, number: int, *, state: str = "OPEN", title: str = "t") -> IssueRef:
    return IssueRef(repo=repo, number=number, title=title, state=state, url=f"https://x/{number}")


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
    assert model.edges == (edge,)


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


def test_cycle_nodes_are_layered_without_crashing() -> None:
    a = _issue("r", 1)
    b = _issue("r", 2)
    edges = (
        DepEdge(src="r#1", dst="r#2", kind="blocked_by", text="r#2"),
        DepEdge(src="r#2", dst="r#1", kind="blocked_by", text="r#1"),
    )
    graph = DependencyGraph(nodes={a.slug: a, b.slug: b}, edges=edges, cycles=(("r#1", "r#2"),))
    model = build_graph(graph)
    assert {n.id for n in model.nodes} == {"r#1", "r#2"}
    assert model.cycles == (("r#1", "r#2"),)


def test_workflow_after_edges_become_graph_edges() -> None:
    steps = [
        {
            "id": "planner",
            "trigger": {"type": "always"},
            "action": {"type": "run-cli", "stage": "myplanner"},
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
        GraphEdge(src="workflow:dispatch", dst="workflow:planner", kind="workflow"),
    )


def test_legacy_event_triggered_steps_produce_no_edges() -> None:
    steps = [
        {"id": "x", "on": {"tool": "t", "kind": "k", "outcome": "success"}, "then": {"repo": "r"}}
    ]
    model = build_graph(DependencyGraph(nodes={}), workflow_steps=steps)
    assert model.edges == ()
    assert {n.id for n in model.nodes} == {"workflow:x"}


def test_render_json_round_trips_node_and_edge_fields() -> None:
    a = _issue("r", 1, title="Some issue")
    b = _issue("r", 2)
    edge = DepEdge(src="r#1", dst="r#2", kind="blocked_by", text="r#2")
    model = build_graph(DependencyGraph(nodes={a.slug: a, b.slug: b}, edges=(edge,)))
    payload = json.loads(render_json(model))
    assert {n["id"] for n in payload["nodes"]} == {"r#1", "r#2"}
    assert payload["edges"] == [{"src": "r#1", "dst": "r#2", "kind": "blocked_by"}]


def test_render_svg_links_a_node_to_its_url() -> None:
    a = _issue("r", 1, title="Some issue")
    b = _issue("r", 2)
    edge = DepEdge(src="r#1", dst="r#2", kind="blocked_by", text="r#2")
    model = build_graph(DependencyGraph(nodes={a.slug: a, b.slug: b}, edges=(edge,)))
    svg = render_svg(model)
    assert '<a href="https://x/1"' in svg
    assert "<svg" in svg


def test_render_svg_on_an_empty_model_does_not_crash() -> None:
    svg = render_svg(build_graph(DependencyGraph(nodes={})))
    assert "No blocking edges" in svg
