from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mythings.github import CIStatus

from conftest import fake_gh, issue, run_row
from mydashboard.fleet import gather_status, purpose_from_claude_md


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def test_purpose_from_claude_md_reads_the_seam() -> None:
    text = "# my-x\n\n## This tool\n\n- **Purpose:** does the thing\n- **Backlog label:** my-x\n"
    assert purpose_from_claude_md(text) == "does the thing"


def test_purpose_from_claude_md_missing_seam_returns_none() -> None:
    assert purpose_from_claude_md("# my-x\n\nno seams here\n") is None


def _ts(days_ago: int) -> str:
    when = datetime.now(UTC) - timedelta(days=days_ago, minutes=1)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_gather_status_remote_mode_reads_via_gh(tmp_path: Path) -> None:
    slug = "MyThingsLab/my-x"
    dev_ledger_entry = json.dumps(
        {"tool": "claude-code", "kind": "ship", "outcome": "success", "detail": "shipped",
         "data": {}, "ts": _ts(5)}
    )
    fake = fake_gh(
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
    assert status.last_dev_ledger == f"ship: shipped ({_ts(5)})"
    assert status.last_ledger is None  # runtime Ledger is unreachable remotely
    assert status.last_activity_days == 5


def test_gather_status_local_mode_reads_the_checkout(tmp_path: Path) -> None:
    workspace = tmp_path
    repo_dir = workspace / "my-x"
    (repo_dir / "dev-ledger").mkdir(parents=True)
    (repo_dir / "CLAUDE.md").write_text("- **Purpose:** local purpose\n", encoding="utf-8")
    (repo_dir / "dev-ledger" / "2026-07-02.jsonl").write_text(
        json.dumps(
            {"tool": "claude-code", "kind": "build", "outcome": "success", "detail": "built",
             "data": {}, "ts": _ts(2)}
        )
        + "\n",
        encoding="utf-8",
    )
    (repo_dir / ".mythings").mkdir()
    (repo_dir / ".mythings" / "ledger.jsonl").write_text(
        json.dumps(
            {"tool": "myx", "kind": "run", "outcome": "success", "detail": "ran",
             "data": {}, "ts": _ts(1)}
        )
        + "\n",
        encoding="utf-8",
    )
    slug = "MyThingsLab/my-x"
    fake = fake_gh(issues={slug: []}, prs={slug: []}, runs={slug: [run_row()]})

    status = gather_status("my-x", org="MyThingsLab", runner=fake, workspace=workspace)

    assert status.purpose == "local purpose"
    assert status.last_dev_ledger == f"build: built ({_ts(2)})"
    assert status.last_ledger == f"run: ran ({_ts(1)})"
    # dev-ledger wins the priority race over the runtime ledger for staleness too.
    assert status.last_activity_days == 2


def test_gather_status_no_activity_data_leaves_days_unset() -> None:
    slug = "MyThingsLab/my-x"
    fake = fake_gh(issues={slug: []}, prs={slug: []}, runs={slug: [run_row()]})

    status = gather_status("my-x", org="MyThingsLab", runner=fake)

    assert status.last_dev_ledger is None
    assert status.last_activity_days is None
