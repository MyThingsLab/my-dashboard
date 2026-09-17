from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from mythings.deps import collect as collect_deps
from mythings.github import Runner, _gh
from mythings.goals import GoalView
from mythings.goals import collect as collect_goals

from mydashboard.fleet import ORG, RepoStatus, gather_status, list_org_repos, load_web_apps
from mydashboard.graph import GraphModel, build_graph
from mydashboard.shelves import Shelving, load_shelves

# my-pipeline declares its workflow DAG as this file, checked into that
# sibling repo. Read as data, never `import mypipeline` -- my-pipeline's own
# README states it never imports another tool's package either, and the
# fleet doesn't cross-import sibling tool packages.
_WORKFLOWS_REL_PATH = "my-pipeline/src/mypipeline/workflows.json"


def _load_workflow_steps(workspace: Path | None, override: Path | None) -> list[dict]:
    path = override or (workspace / _WORKFLOWS_REL_PATH if workspace else None)
    if path is None or not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


@dataclass(frozen=True)
class DashboardModel:
    shelved: dict[str, list[RepoStatus]]
    unshelved: list[RepoStatus]
    graph: GraphModel
    generated_at: str


def build_model(
    *,
    org: str = ORG,
    runner: Runner = _gh,
    workspace: Path | None = None,
    shelving: Shelving | None = None,
    workflows_path: Path | None = None,
) -> DashboardModel:
    names = list_org_repos(org, runner=runner)
    web_apps = load_web_apps()
    statuses = {
        name: gather_status(
            name, org=org, runner=runner, workspace=workspace, web_app=web_apps.get(name)
        )
        for name in names
    }
    shelving = shelving or load_shelves()
    mapped, unshelved_names = shelving.classify(names)
    shelved = {label: [statuses[n] for n in repo_names] for label, repo_names in mapped.items()}
    unshelved = [statuses[n] for n in sorted(unshelved_names)]

    slugs = [f"{org}/{name}" for name in names]
    dep_graph = collect_deps(slugs, runner=runner)
    goal_views: tuple[GoalView, ...] = collect_goals(slugs, runner=runner)
    workflow_steps = _load_workflow_steps(workspace, workflows_path)
    graph = build_graph(dep_graph, goal_views, workflow_steps)

    return DashboardModel(
        shelved=shelved,
        unshelved=unshelved,
        graph=graph,
        generated_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
    )


class Live:
    # Holds the latest built DashboardModel behind a lock and refreshes it on
    # a background thread. gather_status/collect_deps/collect_goals are each
    # several `gh` calls per repo -- unlike my-office's per-request re-read of
    # a local ledger file, recomputing this on every HTTP request would be
    # slow and could burn through the GitHub API rate limit, so a request
    # always reads the latest already-built snapshot instead.
    def __init__(self, builder, *, refresh_seconds: float = 300.0) -> None:
        self._builder = builder
        self._refresh_seconds = refresh_seconds
        self._lock = threading.Lock()
        self._model: DashboardModel | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def refresh(self) -> DashboardModel:
        model = self._builder()
        with self._lock:
            self._model = model
        return model

    @property
    def model(self) -> DashboardModel | None:
        with self._lock:
            return self._model

    def start(self) -> None:
        # The first build is also on the thread, not blocking this call --
        # a full-org sweep is several `gh` calls per repo, and the caller is
        # about to bind an HTTP socket. Blocking here would mean the socket
        # isn't listening yet, so a request during that window gets
        # connection-refused instead of App.page()'s "building the first
        # snapshot" message. The `model is None` case already exists for
        # exactly that window; use it, don't dodge it.
        def loop() -> None:
            while True:
                try:
                    self.refresh()
                except Exception:  # noqa: BLE001 - a failed refresh keeps serving the last-good model
                    pass
                if self._stop.wait(self._refresh_seconds):
                    return

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
