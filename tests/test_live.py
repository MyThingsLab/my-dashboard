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


def _runner():
    return fake_gh(
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


def test_build_model_publishes_the_graph_before_the_repo_sweep() -> None:
    # The two stages exist so the graph is usable while the (much slower)
    # per-repo status sweep is still running. Asserting the order is what
    # stops a refactor from collapsing them back into one slow yield.
    stages = list(build_model(org="MyThingsLab", runner=_runner(), shelving=Shelving(shelves=())))
    assert len(stages) == 2

    first, second = stages
    assert {n.id for n in first.graph.nodes} == {"my-fleet#1", "my-fleet#2"}
    assert first.repos == []
    assert first.complete is False

    assert isinstance(second, DashboardModel)
    assert [r.name for r in second.repos] == ["my-fleet"]
    assert second.complete is True
    assert second.graph.nodes == first.graph.nodes


def test_an_unshelved_repo_reports_a_shelf_rather_than_vanishing() -> None:
    final = list(build_model(org="MyThingsLab", runner=_runner(), shelving=Shelving(shelves=())))[
        -1
    ]
    assert final.shelf_of("my-fleet") == "Unshelved"


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
    # socket until a full-org sweep completes, and the page's "still
    # building" message becomes unreachable dead code.
    def slow_builder():
        time.sleep(0.2)
        yield "model-1"

    live = Live(slow_builder, refresh_seconds=3600)
    started = time.time()
    live.start()
    assert time.time() - started < 0.1  # returned long before the 0.2s build finished
    _wait_for(lambda: live.model == "model-1")
    live.stop()


def test_each_stage_is_published_as_it_arrives() -> None:
    gate = {"release": False}

    def staged():
        yield "stage-1"
        while not gate["release"]:
            time.sleep(0.005)
        yield "stage-2"

    live = Live(staged, refresh_seconds=3600)
    live.start()
    _wait_for(lambda: live.model == "stage-1")
    assert live.model == "stage-1"  # second stage still blocked, first already readable
    gate["release"] = True
    _wait_for(lambda: live.model == "stage-2")
    live.stop()


def test_live_refresh_replaces_the_model_without_blocking_readers() -> None:
    live = Live(lambda: iter(["first"]), refresh_seconds=3600)
    live.start()
    _wait_for(lambda: live.model == "first")

    live._builder = lambda: iter(["second"])
    live.refresh()
    assert live.model == "second"
    live.stop()


def test_a_failed_background_refresh_keeps_serving_the_last_good_model() -> None:
    state = {"n": 0}

    def builder():
        state["n"] += 1
        if state["n"] == 1:
            yield "good"
            return
        raise RuntimeError("gh: rate limited")

    live = Live(builder, refresh_seconds=0.01)
    live.start()
    _wait_for(lambda: live.model == "good")
    # Later refresh ticks raise inside the loop; the model must not change.
    time.sleep(0.05)
    assert live.model == "good"
    live.stop()


def test_a_stage_that_raises_midway_keeps_the_stage_it_already_published() -> None:
    # The graph stage landing and the repo sweep then failing must leave the
    # graph readable, not roll the whole snapshot back to None.
    def half_broken():
        yield "graph-only"
        raise RuntimeError("gh: rate limited during the repo sweep")

    live = Live(half_broken, refresh_seconds=3600)
    live.start()
    _wait_for(lambda: live.model == "graph-only")
    time.sleep(0.05)
    assert live.model == "graph-only"
    live.stop()
