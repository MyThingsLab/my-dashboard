from __future__ import annotations

from mythings.github import CIStatus

from mydashboard.fleet import RepoStatus
from mydashboard.render import render_org_page, render_repo_card

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


def test_render_org_page_groups_by_shelf_and_lists_unshelved() -> None:
    page = render_org_page({"Development harness": [_STATUS], "Services": []}, ["my-mystery"])
    assert "## Development harness" in page
    assert "my-x" in page
    assert "## Services" not in page  # empty shelves are omitted
    assert "## Unshelved" in page and "- my-mystery" in page


def test_render_org_page_includes_banner_when_given() -> None:
    page = render_org_page({"Development harness": [_STATUS]}, [], banner="The fleet is healthy.")
    assert "The fleet is healthy." in page


def test_render_repo_card_reports_the_status_fields() -> None:
    card = render_repo_card(_STATUS)
    assert "does the thing" in card
    assert "Open issues: 2" in card
    assert "Open PRs: 1" in card
    assert "ship: shipped" in card
