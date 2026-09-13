from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from mythings.github import CIStatus, Runner, _gh
from mythings.labels import parse as parse_labels
from mythings.ledger import Ledger, LedgerEntry

ORG = "MyThingsLab"

# The prio facet of the CAD label schema, in rank order (core ADR 0005).
PRIORITIES = ("P0", "P1", "P2", "P3")

# A goal is a milestone whose title carries this prefix: one cross-repo
# objective, opened as a same-titled milestone in every repo it touches.
GOAL_PREFIX = "goal/"

_LEDGER_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


@dataclass(frozen=True)
class Milestone:
    title: str
    repo: str
    url: str
    open_issues: int
    closed_issues: int
    due_on: str | None = None

    @property
    def is_goal(self) -> bool:
        return self.title.startswith(GOAL_PREFIX)

    @property
    def total(self) -> int:
        return self.open_issues + self.closed_issues


@dataclass(frozen=True)
class RepoStatus:
    name: str
    slug: str
    purpose: str | None
    ci: CIStatus
    open_issues: int
    open_prs: int
    last_dev_ledger: str | None
    last_ledger: str | None
    last_activity_days: int | None = None
    web_app: dict | None = None
    # Open issues split by prio: label. Keys are a subset of PRIORITIES;
    # issues carrying no recognized prio land in unprioritised instead.
    by_priority: dict[str, int] = field(default_factory=dict)
    unprioritised: int = 0
    milestones: tuple[Milestone, ...] = ()

    def priority(self, prio: str) -> int:
        return self.by_priority.get(prio, 0)


def default_manifest_path() -> Path:
    # tools_manifest.json is the fleet's canonical registry, shipped as
    # package data inside mythings. Read the data file, never the private
    # mythings._manifest module — core's __all__ is contracts-only and that
    # module is build tooling (same convention as myguide.catalog).
    return Path(str(files("mythings").joinpath("tools_manifest.json")))


def load_web_apps(manifest_path: Path | None = None) -> dict[str, dict]:
    path = manifest_path or default_manifest_path()
    entries = json.loads(path.read_text(encoding="utf-8"))
    return {e["repo"]: e["web_app"] for e in entries if e.get("web_app")}


def list_org_repos(org: str = ORG, *, runner: Runner = _gh) -> list[str]:
    raw = runner(["repo", "list", org, "--json", "name", "--limit", "200"])
    return [obj["name"] for obj in json.loads(raw)]


def _decode_b64(content: str | None) -> str:
    if not content:
        return ""
    return base64.b64decode(content.replace("\n", "")).decode("utf-8")


def _file_or_none(slug: str, path: str, *, runner: Runner) -> str | None:
    try:
        return runner(["api", f"repos/{slug}/contents/{path}", "--jq", ".content"])
    except Exception:  # noqa: BLE001 - degrade to "no file", not a hard failure
        return None


def purpose_from_claude_md(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip().lstrip("-").strip()
        if stripped.startswith("**Purpose:**"):
            purpose = stripped.removeprefix("**Purpose:**").strip()
            return purpose or None
    return None


def open_work(slug: str, *, runner: Runner = _gh) -> tuple[list[dict], int]:
    # Issues come back with their labels so the prio: split costs no extra
    # call; PRs are still only counted. The limit is well clear of the
    # biggest backlog in the org — a repo that hit it would under-report its
    # priority split with no sign on the page that it had.
    common = ["--repo", slug, "--state", "open", "--limit", "1000", "--json"]
    issues = json.loads(runner(["issue", "list", *common, "number,labels"]))
    prs = json.loads(runner(["pr", "list", *common, "number"]))
    return issues, len(prs)


def split_by_priority(issues: list[dict]) -> tuple[dict[str, int], int]:
    # mythings.labels.parse is the one place the CAD vocabulary is spelled
    # out (core ADR 0005) — never re-split "prio:P0" by hand here.
    counts: dict[str, int] = {}
    unprioritised = 0
    for row in issues:
        names = [label["name"] for label in row.get("labels") or []]
        prio = parse_labels(names).prio
        if prio is None:
            unprioritised += 1
        else:
            counts[prio] = counts.get(prio, 0) + 1
    return counts, unprioritised


def open_milestones(slug: str, *, runner: Runner = _gh) -> tuple[Milestone, ...]:
    name = slug.split("/", 1)[-1]
    try:
        raw = runner(["api", f"repos/{slug}/milestones?state=open"])
    except Exception:  # noqa: BLE001 - no milestones (or repo unreachable): render as absent
        return ()
    return tuple(
        Milestone(
            title=row["title"],
            repo=name,
            url=row["html_url"],
            open_issues=row["open_issues"],
            closed_issues=row["closed_issues"],
            due_on=row.get("due_on"),
        )
        for row in json.loads(raw)
    )


def ci_status(slug: str, *, runner: Runner = _gh, branch: str = "main") -> CIStatus:
    argv = ["run", "list", "--repo", slug, "--branch", branch, "--limit", "1"]
    argv += ["--json", "status,conclusion"]
    rows = json.loads(runner(argv))
    if not rows:
        return CIStatus.NONE
    row = rows[0]
    if row.get("status") != "completed":
        return CIStatus.PENDING
    return CIStatus.SUCCESS if row.get("conclusion") == "success" else CIStatus.FAILURE


def _format_entry(entry: LedgerEntry) -> str:
    if entry.detail:
        return f"{entry.kind}: {entry.detail} ({entry.ts})"
    return f"{entry.kind} ({entry.ts})"


def _days_since(ts: str) -> int:
    when = datetime.strptime(ts, _LEDGER_TS_FORMAT).replace(tzinfo=UTC)
    return (datetime.now(UTC) - when).days


def _dev_ledger_tail_remote(slug: str, *, runner: Runner = _gh) -> LedgerEntry | None:
    try:
        raw = runner(["api", f"repos/{slug}/contents/dev-ledger", "--jq", "."])
    except Exception:  # noqa: BLE001 - no dev-ledger dir (or repo unreachable)
        return None
    files = sorted(obj["name"] for obj in json.loads(raw) if obj["name"].endswith(".jsonl"))
    if not files:
        return None
    content = _file_or_none(slug, f"dev-ledger/{files[-1]}", runner=runner)
    lines = [line for line in _decode_b64(content).splitlines() if line.strip()]
    if not lines:
        return None
    return LedgerEntry.from_json(lines[-1])


def _dev_ledger_tail_local(repo_dir: Path) -> LedgerEntry | None:
    dev_ledger = repo_dir / "dev-ledger"
    if not dev_ledger.is_dir():
        return None
    files = sorted(dev_ledger.glob("*.jsonl"))
    if not files:
        return None
    lines = [line for line in files[-1].read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return None
    return LedgerEntry.from_json(lines[-1])


def _runtime_ledger_tail_local(repo_dir: Path) -> LedgerEntry | None:
    path = repo_dir / ".mythings" / "ledger.jsonl"
    if not path.exists():
        return None
    entries = list(Ledger(path))
    if not entries:
        return None
    return entries[-1]


def gather_status(
    name: str,
    *,
    org: str = ORG,
    runner: Runner = _gh,
    workspace: Path | None = None,
    web_app: dict | None = None,
) -> RepoStatus:
    slug = f"{org}/{name}"
    local = workspace / name if workspace is not None else None
    if local is not None and local.is_dir():
        claude_md = ""
        for fname in ("AGENTS.md", "GEMINI.md", "CLAUDE.md"):
            path = local / fname
            if path.exists():
                claude_md = path.read_text(encoding="utf-8")
                break
        purpose = purpose_from_claude_md(claude_md)
        dev_entry = _dev_ledger_tail_local(local)
        runtime_entry = _runtime_ledger_tail_local(local)
    else:
        remote_claude_md = ""
        for fname in ("AGENTS.md", "GEMINI.md", "CLAUDE.md"):
            content = _file_or_none(slug, fname, runner=runner)
            if content:
                remote_claude_md = _decode_b64(content)
                break
        purpose = purpose_from_claude_md(remote_claude_md)
        dev_entry = _dev_ledger_tail_remote(slug, runner=runner)
        runtime_entry = None  # runtime Ledger is workspace-local, gitignored — unreachable remotely
    latest_entry = dev_entry or runtime_entry
    issues, open_prs = open_work(slug, runner=runner)
    by_priority, unprioritised = split_by_priority(issues)
    return RepoStatus(
        name=name,
        slug=slug,
        purpose=purpose,
        ci=ci_status(slug, runner=runner),
        open_issues=len(issues),
        open_prs=open_prs,
        by_priority=by_priority,
        unprioritised=unprioritised,
        milestones=open_milestones(slug, runner=runner),
        last_dev_ledger=_format_entry(dev_entry) if dev_entry else None,
        last_ledger=_format_entry(runtime_entry) if runtime_entry else None,
        last_activity_days=_days_since(latest_entry.ts) if latest_entry else None,
        web_app=web_app,
    )
