from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mythings.github import CIStatus

from conftest import fake_gh, issue, milestone, run_row
from mydashboard.fleet import (
    gather_status,
    load_web_apps,
    open_milestones,
    open_work,
    purpose_from_claude_md,
    split_by_priority,
)


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


def test_gather_status_reads_agents_md(tmp_path: Path) -> None:
    workspace = tmp_path
    repo_dir = workspace / "my-y"
    (repo_dir / "dev-ledger").mkdir(parents=True)
    (repo_dir / "AGENTS.md").write_text("- **Purpose:** canonical purpose\n", encoding="utf-8")
    slug = "MyThingsLab/my-y"
    fake = fake_gh(issues={slug: []}, prs={slug: []}, runs={slug: [run_row()]})
    status = gather_status("my-y", org="MyThingsLab", runner=fake, workspace=workspace)
    assert status.purpose == "canonical purpose"


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


def test_gather_status_passes_web_app_through() -> None:
    slug = "MyThingsLab/my-x"
    fake = fake_gh(issues={slug: []}, prs={slug: []}, runs={slug: [run_row()]})
    web_app = {"run": "myx serve", "port": 9000, "hosted_url": None}

    status = gather_status("my-x", org="MyThingsLab", runner=fake, web_app=web_app)

    assert status.web_app == web_app


def test_gather_status_web_app_defaults_to_none() -> None:
    slug = "MyThingsLab/my-x"
    fake = fake_gh(issues={slug: []}, prs={slug: []}, runs={slug: [run_row()]})

    status = gather_status("my-x", org="MyThingsLab", runner=fake)

    assert status.web_app is None


def test_open_work_asks_for_labels_on_the_call_that_counts_issues() -> None:
    slug = "MyThingsLab/my-x"
    seen: list[list[str]] = []

    def recording(argv: list[str]) -> str:
        seen.append(argv)
        return json.dumps([issue(1, "prio:P0")] if argv[0] == "issue" else [issue(2)])

    issues, open_prs = open_work(slug, runner=recording)

    assert [row["number"] for row in issues] == [1]
    assert open_prs == 1
    # One call, not a second pass for labels.
    assert [argv for argv in seen if argv[0] == "issue"] == [
        ["issue", "list", "--repo", slug, "--state", "open", "--limit", "1000", "--json",
         "number,labels"]
    ]


def test_split_by_priority_uses_the_cad_label_schema() -> None:
    issues = [
        issue(1, "prio:P0", "lane:kernel"),
        issue(2, "prio:P1"),
        issue(3, "prio:P1", "my-x"),  # a backlog label alongside the facet
        issue(4, "my-x"),
        issue(5),
    ]
    counts, unprioritised = split_by_priority(issues)
    assert counts == {"P0": 1, "P1": 2}
    assert unprioritised == 2


def test_split_by_priority_treats_an_unknown_prio_value_as_unprioritised() -> None:
    # parse() passes an unrecognized value through as unknown rather than
    # inventing a fifth priority — it must not count as prioritised either.
    counts, unprioritised = split_by_priority([issue(1, "prio:P9")])
    assert counts == {}
    assert unprioritised == 1


def test_open_milestones_reads_counts_and_due_date() -> None:
    slug = "MyThingsLab/my-x"
    fake = fake_gh(
        milestones={
            slug: [
                milestone(
                    "goal/cad-foundation",
                    open_issues=5,
                    closed_issues=3,
                    due_on="2026-09-18T00:00:00Z",
                ),
                milestone("v2", open_issues=1),
            ]
        }
    )

    goal, plain = open_milestones(slug, runner=fake)

    assert (goal.title, goal.repo, goal.is_goal, goal.total) == (
        "goal/cad-foundation",
        "my-x",
        True,
        8,
    )
    assert goal.due_on == "2026-09-18T00:00:00Z"
    assert (plain.title, plain.is_goal, plain.due_on) == ("v2", False, None)


def test_open_milestones_degrades_to_empty_when_unreachable() -> None:
    def boom(argv: list[str]) -> str:
        raise RuntimeError("gh api failed (404)")

    # Never guessed, never a hard failure: an unreachable repo has no goals.
    assert open_milestones("MyThingsLab/my-x", runner=boom) == ()


def test_gather_status_carries_priority_and_milestones() -> None:
    slug = "MyThingsLab/my-x"
    fake = fake_gh(
        issues={slug: [issue(1, "prio:P0"), issue(2, "prio:P0"), issue(3)]},
        prs={slug: []},
        runs={slug: [run_row()]},
        milestones={slug: [milestone("goal/cad-foundation", open_issues=2, closed_issues=1)]},
    )

    status = gather_status("my-x", org="MyThingsLab", runner=fake)

    assert status.open_issues == 3
    assert status.by_priority == {"P0": 2}
    assert status.priority("P0") == 2
    assert status.priority("P1") == 0
    assert status.unprioritised == 1
    assert [m.title for m in status.milestones] == ["goal/cad-foundation"]


def test_load_web_apps_keeps_only_repos_with_one(tmp_path: Path) -> None:
    manifest = tmp_path / "tools_manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {"repo": "my-server", "web_app": {"run": "myserver serve", "port": 8787}},
                {"repo": "my-todo"},
                {"repo": "my-guard", "web_app": None},
            ]
        ),
        encoding="utf-8",
    )

    web_apps = load_web_apps(manifest)

    assert web_apps == {"my-server": {"run": "myserver serve", "port": 8787}}
