from __future__ import annotations

import base64
import json
from pathlib import Path

from mythings.github import CIStatus

from conftest import FakeGh, issue, run_row
from mydashboard.fleet import gather_status, purpose_from_claude_md


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def test_purpose_from_claude_md_reads_the_seam() -> None:
    text = "# my-x\n\n## This tool\n\n- **Purpose:** does the thing\n- **Backlog label:** my-x\n"
    assert purpose_from_claude_md(text) == "does the thing"


def test_purpose_from_claude_md_missing_seam_returns_none() -> None:
    assert purpose_from_claude_md("# my-x\n\nno seams here\n") is None


def test_gather_status_remote_mode_reads_via_gh(tmp_path: Path) -> None:
    slug = "MyThingsLab/my-x"
    dev_ledger_entry = json.dumps(
        {"tool": "claude-code", "kind": "ship", "outcome": "success", "detail": "shipped",
         "data": {}, "ts": "2026-07-01T00:00:00Z"}
    )
    fake = FakeGh(
        issues={slug: [issue(1), issue(2)]},
        prs={slug: [issue(3)]},
        runs={slug: [run_row()]},
        contents={
            f"repos/{slug}/contents/CLAUDE.md": _b64("- **Purpose:** does the thing\n"),
            f"repos/{slug}/contents/dev-ledger": json.dumps([{"name": "2026-07-01.jsonl"}]),
            f"repos/{slug}/contents/dev-ledger/2026-07-01.jsonl": _b64(dev_ledger_entry + "\n"),
        },
    )

    status = gather_status("my-x", org="MyThingsLab", runner=fake)

    assert status.purpose == "does the thing"
    assert status.ci == CIStatus.SUCCESS
    assert status.open_issues == 2
    assert status.open_prs == 1
    assert status.last_dev_ledger == "ship: shipped (2026-07-01T00:00:00Z)"
    assert status.last_ledger is None  # runtime Ledger is unreachable remotely


def test_gather_status_local_mode_reads_the_checkout(tmp_path: Path) -> None:
    workspace = tmp_path
    repo_dir = workspace / "my-x"
    (repo_dir / "dev-ledger").mkdir(parents=True)
    (repo_dir / "CLAUDE.md").write_text("- **Purpose:** local purpose\n", encoding="utf-8")
    (repo_dir / "dev-ledger" / "2026-07-02.jsonl").write_text(
        json.dumps(
            {"tool": "claude-code", "kind": "build", "outcome": "success", "detail": "built",
             "data": {}, "ts": "2026-07-02T00:00:00Z"}
        )
        + "\n",
        encoding="utf-8",
    )
    (repo_dir / ".mythings").mkdir()
    (repo_dir / ".mythings" / "ledger.jsonl").write_text(
        json.dumps(
            {"tool": "myx", "kind": "run", "outcome": "success", "detail": "ran",
             "data": {}, "ts": "2026-07-03T00:00:00Z"}
        )
        + "\n",
        encoding="utf-8",
    )
    slug = "MyThingsLab/my-x"
    fake = FakeGh(issues={slug: []}, prs={slug: []}, runs={slug: [run_row()]})

    status = gather_status("my-x", org="MyThingsLab", runner=fake, workspace=workspace)

    assert status.purpose == "local purpose"
    assert status.last_dev_ledger == "build: built (2026-07-02T00:00:00Z)"
    assert status.last_ledger == "run: ran (2026-07-03T00:00:00Z)"
