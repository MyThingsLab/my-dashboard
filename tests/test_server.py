import json
from pathlib import Path

from mythings.github import CIStatus
from mythings.goals import GoalPart, GoalView, IssueRef

from mydashboard.ask import AskStore
from mydashboard.fleet import Milestone, RepoStatus
from mydashboard.graph import GraphModel, GraphNode
from mydashboard.live import DashboardModel
from mydashboard.server import App


class _StubLive:
    def __init__(self, model: DashboardModel | None) -> None:
        self.model = model


def _status(name: str, *, ci: CIStatus = CIStatus.SUCCESS, **kw) -> RepoStatus:
    return RepoStatus(
        name=name,
        slug=f"MyThingsLab/{name}",
        purpose=None,
        ci=ci,
        open_issues=2,
        open_prs=1,
        last_dev_ledger=None,
        last_ledger=None,
        **kw,
    )


def _model(**kw) -> DashboardModel:
    base = {
        "shelved": {"dev-harness": [_status("my-fleet")]},
        "unshelved": [_status("my-idea")],
        "graph": GraphModel(),
        "generated_at": "2026-09-17T00:00Z",
        "complete": True,
    }
    return DashboardModel(**{**base, **kw})


def _app(model: DashboardModel | None, tmp_path: Path) -> App:
    return App(_StubLive(model), AskStore(tmp_path / "asks"))


def test_every_page_before_the_first_snapshot_says_it_is_building(tmp_path: Path) -> None:
    app = _app(None, tmp_path)
    for path in ("/", "/goal", "/queue", "/graph", "/goals", "/repos", "/asks"):
        assert b"Building the first snapshot" in app.page(path)


def test_the_repos_page_lists_repos_from_every_shelf(tmp_path: Path) -> None:
    page = _app(_model(), tmp_path).page("/repos").decode("utf-8")
    assert "my-fleet" in page
    assert "my-idea" in page
    assert 'id="repo-table"' in page


def test_a_pending_ask_renders_decide_buttons_on_the_overview(tmp_path: Path) -> None:
    asks = AskStore(tmp_path / "asks")
    ask = asks.create(action_kind="pr-merge", payload={"pr": 5}, timeout=30)
    app = App(_StubLive(_model()), asks)
    page = app.page("/").decode("utf-8")
    assert "pr-merge" in page
    assert f"/asks/{ask.id}/decide?decision=allow" in page
    assert f"/asks/{ask.id}/decide?decision=deny" in page
    # Deciding from the overview must come back to the overview.
    assert "from=%2F" in page


def test_the_nav_flags_a_pending_ask_and_stays_quiet_otherwise(tmp_path: Path) -> None:
    asks = AskStore(tmp_path / "asks")
    quiet = App(_StubLive(_model()), asks).page("/").decode("utf-8")
    assert 'class="count alert"' not in quiet
    asks.create(action_kind="pr-merge", payload={}, timeout=30)
    loud = App(_StubLive(_model()), asks).page("/").decode("utf-8")
    assert 'class="count alert"' in loud


def test_an_incomplete_snapshot_says_so_instead_of_showing_an_empty_repo_table(
    tmp_path: Path,
) -> None:
    # The graph stage has landed, the per-repo sweep has not. An empty table
    # here would read as "the org has no repos".
    partial = DashboardModel(
        graph=GraphModel(nodes=(GraphNode(id="r#1", kind="issue", label="t"),)),
        generated_at="2026-09-17T00:00Z",
        complete=False,
    )
    page = _app(partial, tmp_path).page("/repos").decode("utf-8")
    assert "Still sweeping the org" in page
    assert "loading repo status" in page


def test_a_red_main_is_surfaced_on_the_overview(tmp_path: Path) -> None:
    model = _model(shelved={"dev-harness": [_status("my-fleet", ci=CIStatus.FAILURE)]})
    page = _app(model, tmp_path).page("/").decode("utf-8")
    assert "Red on main" in page


def test_the_goals_page_shows_progress_and_a_verdict(tmp_path: Path) -> None:
    closed = IssueRef(
        repo="r", number=1, title="done", state="CLOSED", closed_at="2026-09-16T00:00:00Z"
    )
    open_ready = IssueRef(repo="r", number=2, title="todo", labels=("state:ready",))
    view = GoalView(
        goal_id="goal/cad-foundation",
        done_when=("the gate refuses a skipped check",),
        parts=(GoalPart(repo="r", open_issues=1, closed_issues=1, url="https://x/m"),),
        issues=(closed, open_ready),
    )
    page = _app(_model(goals=(view,)), tmp_path).page("/goals").decode("utf-8")
    assert "cad-foundation" in page
    assert "1/2 closed" in page
    assert "the gate refuses a skipped check" in page


def test_a_goal_with_no_done_when_says_there_is_nothing_to_verify_against(tmp_path: Path) -> None:
    view = GoalView(goal_id="goal/x", issues=(IssueRef(repo="r", number=1, title="t"),))
    page = _app(_model(goals=(view,)), tmp_path).page("/goals").decode("utf-8")
    assert "no done_when" in page


def test_graph_json_before_the_first_snapshot_is_an_empty_graph(tmp_path: Path) -> None:
    payload = json.loads(_app(None, tmp_path).graph_json())
    assert payload == {"nodes": [], "edges": [], "cycles": []}


def test_repos_json_reports_rows_with_their_shelf(tmp_path: Path) -> None:
    model = _model(unshelved=[])
    payload = json.loads(_app(model, tmp_path).repos_json())
    assert payload["complete"] is True
    assert payload["repos"] == [
        {
            "name": "my-fleet",
            "slug": "MyThingsLab/my-fleet",
            "ci": "success",
            "open_issues": 2,
            "open_prs": 1,
            "by_priority": {},
            "last_activity_days": None,
            "shelf": "dev-harness",
        }
    ]


def test_asks_json_lists_only_pending_asks(tmp_path: Path) -> None:
    asks = AskStore(tmp_path / "asks")
    kept = asks.create(action_kind="pr-merge", payload={"pr": 1}, timeout=30)
    decided = asks.create(action_kind="pr-merge", payload={"pr": 2}, timeout=30)
    asks.decide(decided.id, "allow")
    payload = json.loads(App(_StubLive(_model()), asks).asks_json())
    assert [a["id"] for a in payload] == [kept.id]


def test_static_serves_only_the_allowlisted_assets(tmp_path: Path) -> None:
    app = _app(_model(), tmp_path)
    body, content_type = app.static("graph.js")
    assert b"api/graph" in body
    assert "javascript" in content_type
    # Anything else, including a traversal attempt, is simply not found.
    assert app.static("../server.py") is None
    assert app.static("shelves.toml") is None


def test_a_repo_missing_from_the_shelves_map_still_reports_a_shelf(tmp_path: Path) -> None:
    model = _model(shelved={}, unshelved=[_status("my-idea")])
    payload = json.loads(_app(model, tmp_path).repos_json())
    assert payload["repos"][0]["shelf"] == "Unshelved"


def test_a_repo_goal_milestone_shows_in_its_row(tmp_path: Path) -> None:
    milestone = Milestone(
        title="goal/cad-foundation",
        repo="my-fleet",
        url="https://x/m",
        open_issues=1,
        closed_issues=0,
    )
    model = _model(shelved={"dev-harness": [_status("my-fleet", milestones=(milestone,))]})
    page = _app(model, tmp_path).page("/repos").decode("utf-8")
    assert "goal/cad-foundation" in page


def test_the_goal_focus_page_renders_single_goal_and_checklist(tmp_path: Path) -> None:
    closed = IssueRef(
        repo="my-fleet",
        number=1,
        title="done",
        state="CLOSED",
        closed_at="2026-09-16T00:00:00Z",
    )
    open_ready = IssueRef(repo="my-fleet", number=2, title="todo", labels=("state:ready",))
    view = GoalView(
        goal_id="goal/cad-foundation",
        done_when=("the gate refuses a skipped check",),
        parts=(GoalPart(repo="my-fleet", open_issues=1, closed_issues=1, url="https://x/m"),),
        issues=(closed, open_ready),
    )
    page = _app(_model(goals=(view,)), tmp_path).page("/goal").decode("utf-8")
    assert "ACTIVE GOAL FOCUS" in page
    assert "cad-foundation" in page
    assert "the gate refuses a skipped check" in page
    assert "my-fleet (1/2)" in page


def test_the_queue_page_renders_5_stages(tmp_path: Path) -> None:
    node = GraphNode(id="core#105", kind="issue", label="AST parse", state="ready")
    model = _model(graph=GraphModel(nodes=(node,)))
    page = _app(model, tmp_path).page("/queue").decode("utf-8")
    assert "Deterministic LLM Dispatch Pipeline" in page
    assert "1. Context Prep" in page
    assert "2. LLM Queue" in page
    assert "3. Inference" in page
    assert "4. Policy Gate" in page
    assert "5. Verify &amp; Draft" in page
    assert "core#105" in page


def test_queue_json_reports_pipeline_stages(tmp_path: Path) -> None:
    node = GraphNode(id="core#105", kind="issue", label="AST parse", state="ready")
    model = _model(graph=GraphModel(nodes=(node,)))
    payload = json.loads(_app(model, tmp_path).queue_json())
    assert len(payload["stages"]) == 5
    assert payload["stages"][1]["stage"] == "llm_queue"
    assert "core#105" in payload["stages"][1]["tasks"]

