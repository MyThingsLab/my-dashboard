from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path

from mythings.github import CIStatus, Runner, _gh
from mythings.ledger import Ledger, LedgerEntry

ORG = "MyThingsLab"


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


def open_counts(slug: str, *, runner: Runner = _gh) -> tuple[int, int]:
    common = ["--repo", slug, "--state", "open", "--limit", "100", "--json", "number"]
    issues = json.loads(runner(["issue", "list", *common]))
    prs = json.loads(runner(["pr", "list", *common]))
    return len(issues), len(prs)


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


def _dev_ledger_tail_remote(slug: str, *, runner: Runner = _gh) -> str | None:
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
    return _format_entry(LedgerEntry.from_json(lines[-1]))


def _dev_ledger_tail_local(repo_dir: Path) -> str | None:
    dev_ledger = repo_dir / "dev-ledger"
    if not dev_ledger.is_dir():
        return None
    files = sorted(dev_ledger.glob("*.jsonl"))
    if not files:
        return None
    lines = [line for line in files[-1].read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return None
    return _format_entry(LedgerEntry.from_json(lines[-1]))


def _runtime_ledger_tail_local(repo_dir: Path) -> str | None:
    path = repo_dir / ".mythings" / "ledger.jsonl"
    if not path.exists():
        return None
    entries = list(Ledger(path))
    if not entries:
        return None
    return _format_entry(entries[-1])


def gather_status(
    name: str,
    *,
    org: str = ORG,
    runner: Runner = _gh,
    workspace: Path | None = None,
) -> RepoStatus:
    slug = f"{org}/{name}"
    local = workspace / name if workspace is not None else None
    if local is not None and local.is_dir():
        claude_md_path = local / "CLAUDE.md"
        claude_md = claude_md_path.read_text(encoding="utf-8") if claude_md_path.exists() else ""
        purpose = purpose_from_claude_md(claude_md)
        last_dev_ledger = _dev_ledger_tail_local(local)
        last_ledger = _runtime_ledger_tail_local(local)
    else:
        remote_claude_md = _decode_b64(_file_or_none(slug, "CLAUDE.md", runner=runner))
        purpose = purpose_from_claude_md(remote_claude_md)
        last_dev_ledger = _dev_ledger_tail_remote(slug, runner=runner)
        last_ledger = None  # runtime Ledger is workspace-local, gitignored — unreachable remotely
    open_issues, open_prs = open_counts(slug, runner=runner)
    return RepoStatus(
        name=name,
        slug=slug,
        purpose=purpose,
        ci=ci_status(slug, runner=runner),
        open_issues=open_issues,
        open_prs=open_prs,
        last_dev_ledger=last_dev_ledger,
        last_ledger=last_ledger,
    )
