from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from mythings.deps import DependencyGraph
from mythings.deps import collect as collect_deps
from mythings.github import CIStatus, Runner, _gh
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

# One gather_status is ~5 serial `gh` calls, so a 55-repo org costs a few
# hundred round trips that are almost entirely latency. A pool turns minutes
# into tens of seconds. Capped at a constant rather than scaled to the repo
# count, to stay well clear of GitHub's secondary rate limits.
_MAX_WORKERS = 8


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
    graph: GraphModel = field(default_factory=GraphModel)
    goals: tuple[GoalView, ...] = ()
    shelved: dict[str, list[RepoStatus]] = field(default_factory=dict)
    unshelved: list[RepoStatus] = field(default_factory=list)
    generated_at: str = ""
    # False while the slow per-repo status sweep is still running, so a page
    # can say "still loading" rather than render an empty repo table that
    # looks indistinguishable from a fleet with no repos.
    complete: bool = False

    @property
    def repos(self) -> list[RepoStatus]:
        rows = [s for group in self.shelved.values() for s in group] + self.unshelved
        return sorted(rows, key=lambda r: r.name)

    def shelf_of(self, name: str) -> str:
        for label, group in self.shelved.items():
            if any(r.name == name for r in group):
                return label
        return "Unshelved"

    def red_repos(self) -> list[RepoStatus]:
        return [r for r in self.repos if r.ci == CIStatus.FAILURE]


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")


def _statuses(
    names: list[str], *, org: str, runner: Runner, workspace: Path | None
) -> dict[str, RepoStatus]:
    web_apps = load_web_apps()

    def one(name: str) -> RepoStatus:
        return gather_status(
            name, org=org, runner=runner, workspace=workspace, web_app=web_apps.get(name)
        )

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        return dict(zip(names, pool.map(one, names), strict=True))


def build_model(
    *,
    org: str = ORG,
    runner: Runner = _gh,
    workspace: Path | None = None,
    shelving: Shelving | None = None,
    workflows_path: Path | None = None,
) -> Iterator[DashboardModel]:
    # Yields twice on purpose. The graph needs one `gh` call per repo; the
    # repo cards need several, and waiting for them held the whole page
    # hostage to its slowest layer. Publishing the graph first makes it
    # usable in seconds while the repo table fills in behind it.
    names = list_org_repos(org, runner=runner)
    slugs = [f"{org}/{name}" for name in names]

    dep_graph: DependencyGraph = collect_deps(slugs, runner=runner)
    goal_views: tuple[GoalView, ...] = collect_goals(slugs, runner=runner)
    graph = build_graph(dep_graph, goal_views, _load_workflow_steps(workspace, workflows_path))
    yield DashboardModel(graph=graph, goals=goal_views, generated_at=_now())

    statuses = _statuses(names, org=org, runner=runner, workspace=workspace)
    shelving = shelving or load_shelves()
    mapped, unshelved_names = shelving.classify(names)
    yield DashboardModel(
        graph=graph,
        goals=goal_views,
        shelved={label: [statuses[n] for n in group] for label, group in mapped.items()},
        unshelved=[statuses[n] for n in sorted(unshelved_names)],
        generated_at=_now(),
        complete=True,
    )


class Live:
    # Holds the latest built DashboardModel behind a lock and refreshes it on
    # a background thread. The builder yields progressively more complete
    # models (see build_model) and each is published as it arrives, so a
    # request always reads the most complete snapshot built so far instead of
    # blocking on a fresh `gh` sweep -- which, unlike my-office's
    # per-request re-read of a local ledger file, would be minutes of GitHub
    # API calls.
    def __init__(self, builder, *, refresh_seconds: float = 300.0) -> None:
        self._builder = builder
        self._refresh_seconds = refresh_seconds
        self._lock = threading.Lock()
        self._model: DashboardModel | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def refresh(self) -> DashboardModel | None:
        for model in self._builder():
            with self._lock:
                self._model = model
        return self.model

    @property
    def model(self) -> DashboardModel | None:
        with self._lock:
            return self._model

    def start(self) -> None:
        # The first build is also on the thread, not blocking this call --
        # a full-org sweep is several `gh` calls per repo, and the caller is
        # about to bind an HTTP socket. Blocking here would mean the socket
        # isn't listening yet, so a request during that window gets
        # connection-refused instead of the page's "still building" state.
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
