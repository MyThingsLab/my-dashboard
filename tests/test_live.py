import json
import time
from pathlib import Path

from conftest import fake_gh, issue
from mydashboard.live import DashboardModel, Live, _load_workflow_steps, build_model
from mydashboard.shelves import Shelving


def test_load_workflow_steps_reads_the_sibling_repos_data_file(tmp_path: Path) -> None:
    workspace = tmp_path
    workflows = workspace / "my-pipeline" / "src" / "mypipeline" / "workflows.json"
    workflows.parent.mkdir(parents=True)
    workflows.write_text(json.dumps([{"id": "a"}]), encoding="utf-8")
    assert _load_workflow_steps(workspace, None) == [{"id": "a"}]


def test_load_workflow_steps_is_absent_not_fabricated_without_a_workspace() -> None:
    assert _load_workflow_steps(None, None) == []


def test_load_workflow_steps_prefers_an_explicit_override(tmp_path: Path) -> None:
    override = tmp_path / "custom.json"
    override.write_text(json.dumps([{"id": "b"}]), encoding="utf-8")
    assert _load_workflow_steps(None, override) == [{"id": "b"}]


def test_build_model_wires_gather_status_and_the_dependency_graph() -> None:
    runner = fake_gh(
        repos=["my-fleet"],
        issues={
            "MyThingsLab/my-fleet": [
                {
                    **issue(1, "lane:core"),
                    "title": "t1",
                    "body": "Blocked by my-fleet#2.",
                    "state": "OPEN",
                },
                {**issue(2), "title": "t2", "body": "", "state": "OPEN"},
            ]
        },
    )
    shelving = Shelving(shelves=())
    model = build_model(org="MyThingsLab", runner=runner, shelving=shelving)
    assert isinstance(model, DashboardModel)
    assert model.unshelved[0].name == "my-fleet"
    assert {n.id for n in model.graph.nodes} == {"my-fleet#1", "my-fleet#2"}


def _wait_for(predicate, *, timeout: float = 2.0, interval: float = 0.005) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("condition never became true")


def test_live_start_does_not_block_on_a_slow_first_build() -> None:
    # start() must return before the first (potentially slow, several `gh`
    # calls) build finishes -- otherwise the caller can't bind its HTTP
    # socket until a full-org sweep completes, and App.page()'s "still
    # building" message becomes unreachable dead code.
    def slow_builder() -> str:
        time.sleep(0.2)
        return "model-1"

    live = Live(slow_builder, refresh_seconds=3600)
    started = time.time()
    live.start()
    assert time.time() - started < 0.1  # returned long before the 0.2s build finished
    _wait_for(lambda: live.model == "model-1")
    live.stop()


def test_live_refresh_replaces_the_model_without_blocking_readers() -> None:
    live = Live(lambda: "first", refresh_seconds=3600)
    live.start()
    _wait_for(lambda: live.model == "first")

    live._builder = lambda: "second"
    live.refresh()
    assert live.model == "second"
    live.stop()


def test_a_failed_background_refresh_keeps_serving_the_last_good_model() -> None:
    state = {"n": 0}

    def builder() -> str:
        state["n"] += 1
        if state["n"] == 1:
            return "good"
        raise RuntimeError("gh: rate limited")

    live = Live(builder, refresh_seconds=0.01)
    live.start()
    _wait_for(lambda: live.model == "good")
    # One more refresh tick will raise inside the loop; the model must not change.
    time.sleep(0.05)
    assert live.model == "good"
    live.stop()
