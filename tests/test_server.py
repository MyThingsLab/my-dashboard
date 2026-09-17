import json
from pathlib import Path

from mythings.github import CIStatus

from mydashboard.ask import AskStore
from mydashboard.fleet import RepoStatus
from mydashboard.graph import GraphModel
from mydashboard.live import DashboardModel
from mydashboard.server import App


class _StubLive:
    def __init__(self, model: DashboardModel | None) -> None:
        self.model = model


def _status(name: str) -> RepoStatus:
    return RepoStatus(
        name=name,
        slug=f"MyThingsLab/{name}",
        purpose=None,
        ci=CIStatus.SUCCESS,
        open_issues=2,
        open_prs=1,
        last_dev_ledger=None,
        last_ledger=None,
    )


def test_page_before_the_first_snapshot_does_not_crash(tmp_path: Path) -> None:
    app = App(_StubLive(None), AskStore(tmp_path / "asks"))
    assert b"reload in a moment" in app.page()


def test_page_lists_repos_and_pending_asks(tmp_path: Path) -> None:
    model = DashboardModel(
        shelved={"dev-harness": [_status("my-fleet")]},
        unshelved=[_status("my-idea")],
        graph=GraphModel(),
        generated_at="2026-09-17T00:00Z",
    )
    asks = AskStore(tmp_path / "asks")
    ask = asks.create(action_kind="pr-merge", payload={"pr": 5}, timeout=30)
    app = App(_StubLive(model), asks)
    page = app.page().decode("utf-8")
    assert "my-fleet" in page
    assert "my-idea" in page
    assert "pr-merge" in page
    assert f'/asks/{ask.id}/decide?decision=allow' in page
    assert f'/asks/{ask.id}/decide?decision=deny' in page


def test_graph_json_before_the_first_snapshot_is_an_empty_graph(tmp_path: Path) -> None:
    app = App(_StubLive(None), AskStore(tmp_path / "asks"))
    payload = json.loads(app.graph_json())
    assert payload == {"nodes": [], "edges": []}


def test_dashboard_json_reports_repo_rows(tmp_path: Path) -> None:
    model = DashboardModel(
        shelved={"dev-harness": [_status("my-fleet")]},
        unshelved=[],
        graph=GraphModel(),
        generated_at="2026-09-17T00:00Z",
    )
    app = App(_StubLive(model), AskStore(tmp_path / "asks"))
    payload = json.loads(app.dashboard_json())
    assert payload["repos"] == [
        {
            "name": "my-fleet",
            "slug": "MyThingsLab/my-fleet",
            "ci": "success",
            "open_issues": 2,
            "open_prs": 1,
            "last_activity_days": None,
        }
    ]
