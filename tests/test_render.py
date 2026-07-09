from __future__ import annotations

from mythings.github import CIStatus

from mydashboard.fleet import RepoStatus
from mydashboard.render import render_org_page, render_org_table, render_repo_card

_STATUS = RepoStatus(
    name="my-x",
    slug="MyThingsLab/my-x",
    purpose="does the thing",
    ci=CIStatus.SUCCESS,
    open_issues=2,
    open_prs=1,
    last_dev_ledger="ship: shipped (2026-07-01T00:00:00Z)",
    last_ledger=None,
)


def _status(**overrides) -> RepoStatus:
    fields = dict(
        name=_STATUS.name,
        slug=_STATUS.slug,
        purpose=_STATUS.purpose,
        ci=_STATUS.ci,
        open_issues=_STATUS.open_issues,
        open_prs=_STATUS.open_prs,
        last_dev_ledger=_STATUS.last_dev_ledger,
        last_ledger=_STATUS.last_ledger,
    )
    fields.update(overrides)
    return RepoStatus(**fields)


def test_render_org_page_groups_by_shelf_and_cards_unshelved() -> None:
    mystery = _status(name="my-mystery", slug="MyThingsLab/my-mystery", ci=CIStatus.NONE)
    page = render_org_page({"Development harness": [_STATUS], "Services": []}, [mystery])
    assert "<h2>Development harness</h2>" in page
    assert "my-x" in page
    assert "<h2>Services</h2>" not in page  # empty shelves are omitted
    assert "<h2>Unshelved</h2>" in page and "my-mystery" in page
    assert "not in shelves.toml" in page  # unshelved cards carry the drift pill


def test_render_org_page_tiles_summarize_the_fleet() -> None:
    failing = _status(name="my-y", slug="MyThingsLab/my-y", ci=CIStatus.FAILURE, open_prs=0)
    page = render_org_page({"Development harness": [_STATUS, failing]}, [])
    assert "2 tools, one loop" in page
    assert '<div class="v">1<span class="unit">/2</span></div>' in page  # CI green count
    assert "1 failing" in page


def test_render_org_page_includes_banner_and_taglines_when_given() -> None:
    page = render_org_page(
        {"Development harness": [_STATUS]},
        [],
        banner="The fleet is healthy.",
        taglines={"Development harness": "runs the autonomous cycle"},
    )
    assert "The fleet is healthy." in page
    assert "State of the fleet:" in page
    assert '<span class="what">runs the autonomous cycle</span>' in page


def test_render_org_page_omits_banner_and_activity_when_absent() -> None:
    quiet = _status(last_dev_ledger=None, last_ledger=None)
    page = render_org_page({"Development harness": [quiet]}, [])
    assert "State of the fleet:" not in page
    assert '<div class="last">' not in page  # unknown activity is absent, not guessed


def test_render_org_page_escapes_html_in_status_fields() -> None:
    sneaky = _status(purpose='<script>alert("x")</script>')
    page = render_org_page({"Development harness": [sneaky]}, [])
    assert "<script>" not in page
    assert "&lt;script&gt;" in page


def test_render_org_table_is_the_markdown_engine_prompt() -> None:
    table = render_org_table({"Development harness": [_STATUS], "Services": []})
    assert "## Development harness" in table
    assert "| Tool | Purpose | CI | Issues | PRs | Last activity |" in table
    assert "## Services" not in table


def test_render_repo_card_reports_the_status_fields() -> None:
    card = render_repo_card(_STATUS)
    assert "does the thing" in card
    assert "Open issues: 2" in card
    assert "Open PRs: 1" in card
    assert "ship: shipped" in card
