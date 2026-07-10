from __future__ import annotations

import base64
import subprocess
from pathlib import Path

from mythings.engine import NoopEngine
from mythings.ledger import Ledger

from conftest import FakeGh, make_site_repo, run_row
from mydashboard.dashboard import Dashboard

_SHELVES = """
[shelves.harness]
label = "Development harness"
repos = ["my-a", "my-b"]
"""


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _show(repo: Path, ref: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), "show", ref], capture_output=True, text=True, check=True
    )
    return proc.stdout


def _fake_fleet(names: list[str]) -> FakeGh:
    issues = {f"MyThingsLab/{n}": [] for n in names}
    prs = {f"MyThingsLab/{n}": [] for n in names}
    runs = {f"MyThingsLab/{n}": [run_row()] for n in names}
    contents = {}
    for n in names:
        contents[f"repos/MyThingsLab/{n}/contents/CLAUDE.md"] = _b64(
            f"- **Purpose:** purpose of {n}\n"
        )
    return FakeGh(repos=names, issues=issues, prs=prs, runs=runs, contents=contents)


def test_render_happy_path_opens_pr(tmp_path: Path) -> None:
    site = make_site_repo(tmp_path)
    shelves = tmp_path / "shelves.toml"
    shelves.write_text(_SHELVES, encoding="utf-8")
    fake = _fake_fleet(["my-a", "my-b", "my-mystery"])
    dashboard = Dashboard(
        repo_root=site,
        repo="MyThingsLab/mythingslab.github.io",
        ledger=Ledger(tmp_path / "led.jsonl"),
        shelves_path=shelves,
        runner=fake,
    )

    result = dashboard.render()

    assert result.outcome == "success"
    assert result.pr == 9
    subprocess.run(["git", "-C", str(site), "fetch", "-q", "origin"], check=True)
    page = _show(site, "origin/my-dashboard/render:dashboard/index.html")
    assert "<h2>Development harness</h2>" in page
    assert "my-a" in page and "my-b" in page
    assert "<h2>Unshelved</h2>" in page and "my-mystery" in page
    assert '<p class="generated">Generated ' in page

    recorded = list(Ledger(tmp_path / "led.jsonl"))
    assert recorded[-1].tool == "mydashboard" and recorded[-1].kind == "dashboard_render"
    assert recorded[-1].outcome == "success"


def test_render_skipped_when_page_unchanged(tmp_path: Path) -> None:
    site = make_site_repo(tmp_path)
    shelves = tmp_path / "shelves.toml"
    shelves.write_text(_SHELVES, encoding="utf-8")
    fake = _fake_fleet(["my-a", "my-b"])
    ledger = Ledger(tmp_path / "led.jsonl")

    first = Dashboard(
        repo_root=site,
        repo="MyThingsLab/mythingslab.github.io",
        ledger=ledger,
        shelves_path=shelves,
        runner=fake,
    ).render()
    assert first.outcome == "success"

    subprocess.run(["git", "-C", str(site), "fetch", "-q", "origin"], check=True)
    subprocess.run(
        ["git", "-C", str(site), "checkout", "main"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(site), "merge", "--ff-only", "origin/my-dashboard/render"],
        check=True,
        capture_output=True,
    )

    second = Dashboard(
        repo_root=site,
        repo="MyThingsLab/mythingslab.github.io",
        ledger=ledger,
        shelves_path=shelves,
        runner=fake,
    ).render()

    assert second.outcome == "skipped"
    assert second.pr is None


def test_render_removes_the_legacy_markdown_page(tmp_path: Path) -> None:
    site = make_site_repo(tmp_path)
    legacy = site / "dashboard" / "index.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# old markdown dashboard\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(site), "add", "dashboard/index.md"], check=True)
    subprocess.run(
        ["git", "-C", str(site), "commit", "-q", "-m", "seed legacy page"], check=True
    )
    subprocess.run(["git", "-C", str(site), "push", "-q", "origin", "main"], check=True)
    shelves = tmp_path / "shelves.toml"
    shelves.write_text(_SHELVES, encoding="utf-8")
    fake = _fake_fleet(["my-a", "my-b"])
    dashboard = Dashboard(
        repo_root=site,
        repo="MyThingsLab/mythingslab.github.io",
        ledger=Ledger(tmp_path / "led.jsonl"),
        shelves_path=shelves,
        runner=fake,
    )

    result = dashboard.render()

    assert result.outcome == "success"
    subprocess.run(["git", "-C", str(site), "fetch", "-q", "origin"], check=True)
    listing = _show(site, "origin/my-dashboard/render:dashboard")
    assert "index.html" in listing
    assert "index.md" not in listing


def test_render_summarize_with_noop_omits_banner(tmp_path: Path) -> None:
    site = make_site_repo(tmp_path)
    shelves = tmp_path / "shelves.toml"
    shelves.write_text(_SHELVES, encoding="utf-8")
    fake = _fake_fleet(["my-a", "my-b"])
    dashboard = Dashboard(
        repo_root=site,
        repo="MyThingsLab/mythingslab.github.io",
        ledger=Ledger(tmp_path / "led.jsonl"),
        shelves_path=shelves,
        runner=fake,
        engine=NoopEngine(),
    )

    result = dashboard.render(summarize=True)

    subprocess.run(["git", "-C", str(site), "fetch", "-q", "origin"], check=True)
    page = _show(site, "origin/my-dashboard/render:dashboard/index.html")
    assert result.outcome == "success"
    assert "State of the fleet:" not in page  # NoopEngine's empty reply -> banner omitted


def test_status_reads_local_checkout_and_records_ledger(tmp_path: Path) -> None:
    repo_dir = tmp_path / "my-a"
    repo_dir.mkdir()
    (repo_dir / "CLAUDE.md").write_text("- **Purpose:** purpose of my-a\n", encoding="utf-8")
    fake = _fake_fleet(["my-a"])
    ledger = Ledger(tmp_path / "led.jsonl")
    dashboard = Dashboard(ledger=ledger, org="MyThingsLab", workspace=tmp_path, runner=fake)

    result = dashboard.status("my-a")

    assert result.outcome == "success"
    assert "purpose of my-a" in result.card
    recorded = list(ledger)
    assert recorded[-1].kind == "status" and recorded[-1].outcome == "success"
