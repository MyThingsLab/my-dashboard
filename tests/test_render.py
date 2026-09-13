from __future__ import annotations

from datetime import UTC, datetime, timedelta

from mythings.github import CIStatus

from mydashboard.fleet import Milestone, RepoStatus
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
    last_activity_days=5,
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
        last_activity_days=_STATUS.last_activity_days,
        web_app=_STATUS.web_app,
        by_priority=_STATUS.by_priority,
        unprioritised=_STATUS.unprioritised,
        milestones=_STATUS.milestones,
    )
    fields.update(overrides)
    return RepoStatus(**fields)


def _goal(
    title: str = "goal/cad-foundation",
    *,
    repo: str = "my-x",
    open_issues: int = 3,
    closed_issues: int = 1,
    due_on: str | None = None,
) -> Milestone:
    return Milestone(
        title=title,
        repo=repo,
        url=f"https://github.com/MyThingsLab/{repo}/milestone/1",
        open_issues=open_issues,
        closed_issues=closed_issues,
        due_on=due_on,
    )


def _in_days(days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")


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
    quiet = _status(last_dev_ledger=None, last_ledger=None, last_activity_days=None)
    page = render_org_page({"Development harness": [quiet]}, [])
    assert "State of the fleet:" not in page
    assert '<div class="last">' not in page  # unknown activity is absent, not guessed
    assert "stale" not in page  # unknown staleness is absent, not guessed


def test_render_org_page_flags_stale_repos_with_escalating_tone() -> None:
    stale = _status(name="my-stale", slug="MyThingsLab/my-stale", last_activity_days=45)
    very_stale = _status(name="my-fossil", slug="MyThingsLab/my-fossil", last_activity_days=120)
    page = render_org_page({"Development harness": [stale, very_stale]}, [])
    assert '<span class="pill warn">stale 45d</span>' in page
    assert '<span class="pill crit">stale 120d</span>' in page


def test_render_org_page_sorts_failing_ci_and_stale_repos_first() -> None:
    healthy = _status(name="my-healthy", ci=CIStatus.SUCCESS, last_activity_days=1)
    stale = _status(name="my-stale", ci=CIStatus.SUCCESS, last_activity_days=60)
    failing = _status(name="my-failing", ci=CIStatus.FAILURE, last_activity_days=1)
    page = render_org_page({"Development harness": [healthy, stale, failing]}, [])
    assert page.index("my-failing") < page.index("my-stale") < page.index("my-healthy")


def test_render_org_page_includes_generated_timestamp_when_given() -> None:
    page = render_org_page({"Development harness": [_STATUS]}, [], generated_at="2026-07-10T14:32Z")
    assert '<p class="generated">Generated 2026-07-10T14:32Z</p>' in page


def test_render_org_page_omits_generated_timestamp_when_absent() -> None:
    page = render_org_page({"Development harness": [_STATUS]}, [])
    assert '<p class="generated">' not in page


def test_render_org_page_escapes_html_in_status_fields() -> None:
    sneaky = _status(purpose='<script>alert("x")</script>')
    page = render_org_page({"Development harness": [sneaky]}, [])
    assert "<script>" not in page
    assert "&lt;script&gt;" in page


def test_render_org_page_omits_explore_section_without_any_web_app() -> None:
    page = render_org_page({"Development harness": [_STATUS]}, [])
    assert "<h2>Explore</h2>" not in page


def test_render_org_page_explore_shows_local_run_command() -> None:
    server = _status(
        name="my-server",
        web_app={"run": "myserver serve", "port": 8787, "hosted_url": None},
    )
    page = render_org_page({"Development harness": [_STATUS, server]}, [])
    assert "<h2>Explore</h2>" in page
    assert "1 tool with a web app" in page
    assert "myserver serve — localhost:8787" in page
    assert "my-x" not in page.split("<h2>Explore</h2>")[1].split("</section>")[0]


def test_render_org_page_explore_links_a_hosted_url() -> None:
    server = _status(
        name="my-server",
        web_app={"run": "myserver serve", "port": 8787, "hosted_url": "https://tools.example/x"},
    )
    page = render_org_page({"Development harness": [server]}, [])
    assert '<a href="https://tools.example/x">my-server</a>' in page


def test_render_org_table_is_the_markdown_engine_prompt() -> None:
    table = render_org_table({"Development harness": [_STATUS], "Services": []})
    assert "## Development harness" in table
    assert "| Tool | Purpose | CI | Issues | P0 | P1 | Goals | PRs | Last activity |" in table
    assert "## Services" not in table


def test_render_org_table_carries_priority_and_goals_to_the_engine() -> None:
    urgent = _status(by_priority={"P0": 2, "P2": 1}, milestones=(_goal(),))
    table = render_org_table({"Development harness": [urgent]})
    # The banner can only mention what the deterministic table shows.
    assert "| ✅ | 2 | 2 | 0 | goal/cad-foundation | 1 |" in table


def test_render_repo_card_reports_the_status_fields() -> None:
    card = render_repo_card(_STATUS)
    assert "does the thing" in card
    assert "Open issues: 2" in card
    assert "Open PRs: 1" in card
    assert "ship: shipped" in card


def test_render_repo_card_splits_priority_and_lists_milestones() -> None:
    card = render_repo_card(
        _status(
            open_issues=5,
            by_priority={"P0": 1, "P1": 2},
            unprioritised=2,
            milestones=(_goal(due_on="2026-09-18T00:00:00Z"), _goal("v2", open_issues=1)),
        )
    )
    assert "By priority: P0 1 · P1 2 · P2 0 · P3 0 · unprioritised 2" in card
    assert "Goal: goal/cad-foundation — 3 open, 1 closed, due 2026-09-18" in card
    assert "Milestone: v2 — 1 open, 1 closed" in card


# ---- backlog by priority ------------------------------------------------


def test_render_org_page_breaks_the_backlog_down_by_priority() -> None:
    a = _status(name="my-a", open_issues=4, by_priority={"P0": 2, "P1": 1}, unprioritised=1)
    b = _status(name="my-b", open_issues=3, by_priority={"P0": 1}, unprioritised=2)
    page = render_org_page({"Development harness": [a, b]}, [])

    assert "<h2>Backlog by priority</h2>" in page
    assert "4/7 open issues carry a priority" in page
    # P0 totals across repos and names who holds them, worst first.
    assert (
        '<div class="k">P0</div><div class="v">3</div><div class="d">my-a 2 · my-b 1</div>' in page
    )
    assert '<div class="k">Unprioritised</div><div class="v">3</div>' in page


def test_render_org_page_priority_tiles_link_to_an_org_wide_search() -> None:
    page = render_org_page({"Development harness": [_status(by_priority={"P0": 1})]}, [])
    assert "org%3AMyThingsLab%20is%3Aissue%20is%3Aopen%20label%3A%22prio%3AP0%22" in page


def test_render_org_page_priority_tiles_honour_the_org() -> None:
    page = render_org_page({"Development harness": [_STATUS]}, [], org="OtherOrg")
    assert "org%3AOtherOrg" in page
    assert "org%3AMyThingsLab" not in page


def test_render_org_page_omits_the_backlog_section_with_no_open_issues() -> None:
    page = render_org_page({"Development harness": [_status(open_issues=0)]}, [])
    assert "<h2>Backlog by priority</h2>" not in page


def test_render_org_page_priority_tile_is_untoned_at_zero() -> None:
    page = render_org_page({"Development harness": [_status(unprioritised=2)]}, [])
    assert '<a class="tile crit"' not in page  # no P0s open — nothing to alarm about


def test_render_org_page_cards_pill_open_p0_and_p1() -> None:
    page = render_org_page(
        {"Development harness": [_status(by_priority={"P0": 2, "P1": 1, "P3": 5})]}, []
    )
    assert '<span class="pill crit">2×P0</span>' in page
    assert '<span class="pill warn">1×P1</span>' in page
    assert "P3" not in page.split('<div class="pills">')[1]  # inventory, not a pill


def test_render_org_page_sorts_p0_holders_ahead_within_a_shelf() -> None:
    quiet = _status(name="my-quiet", last_activity_days=1)
    urgent = _status(name="my-urgent", last_activity_days=1, by_priority={"P0": 1})
    failing = _status(name="my-failing", ci=CIStatus.FAILURE, last_activity_days=1)
    page = render_org_page({"Development harness": [quiet, urgent, failing]}, [])
    shelf = page.split("<h2>Development harness</h2>")[1]
    # A red main still outranks a P0 — it blocks the repo entirely.
    assert shelf.index("my-failing") < shelf.index("my-urgent") < shelf.index("my-quiet")


# ---- goals ---------------------------------------------------------------


def test_render_org_page_groups_one_goal_across_repos() -> None:
    a = _status(name="my-a", milestones=(_goal(repo="my-a", open_issues=3, closed_issues=1),))
    b = _status(name="my-b", milestones=(_goal(repo="my-b", open_issues=1, closed_issues=5),))
    page = render_org_page({"Development harness": [a, b]}, [])

    assert "<h2>Goals</h2>" in page
    assert "1 open goal" in page  # one goal, not one card per repo
    assert page.count('<div class="name">goal/cad-foundation</div>') == 1
    assert "6/10 closed<span class=\"unit\"> (60%)</span> · 4 open across 2 repos" in page
    assert '<div class="bar"><span style="width:60%"></span></div>' in page
    # Each repo keeps its own chip, linking to that repo's milestone.
    chip = '<a class="pill" href="https://github.com/MyThingsLab/{0}/milestone/1">{0} {1}</a>'
    assert chip.format("my-a", 3) in page
    assert chip.format("my-b", 1) in page


def test_render_org_page_flags_an_overdue_goal() -> None:
    late = _status(milestones=(_goal(due_on=_in_days(-3)),))
    page = render_org_page({"Development harness": [late]}, [])
    assert '<span class="due crit">overdue 3d' in page


def test_render_org_page_warns_on_a_goal_due_soon() -> None:
    soon = _status(milestones=(_goal(due_on=_in_days(2)),))
    page = render_org_page({"Development harness": [soon]}, [])
    assert '<span class="due warn">due in 2d' in page


def test_render_org_page_leaves_a_distant_goal_untoned() -> None:
    later = _status(milestones=(_goal(due_on=_in_days(60)),))
    page = render_org_page({"Development harness": [later]}, [])
    assert '<span class="due">due in 60d' in page


def test_render_org_page_orders_goals_by_soonest_due_date() -> None:
    status = _status(
        milestones=(
            _goal("goal/later", due_on=_in_days(30)),
            _goal("goal/sooner", due_on=_in_days(2)),
            _goal("goal/undated"),
        )
    )
    page = render_org_page({"Development harness": [status]}, [])
    assert page.index("goal/sooner") < page.index("goal/later") < page.index("goal/undated")


def test_render_org_page_lists_non_goal_milestones_separately() -> None:
    status = _status(milestones=(_goal(), _goal("v2.0", open_issues=4)))
    page = render_org_page({"Development harness": [status]}, [])
    goals = page.split("<h2>Goals</h2>")[1].split("</section>")[0]
    assert "1 open goal" in goals  # v2.0 is not counted as a goal
    assert "Other open milestones" in goals
    assert "my-x · v2.0</a> — 4 open" in goals


def test_render_org_page_omits_the_goals_section_without_any_milestone() -> None:
    page = render_org_page({"Development harness": [_STATUS]}, [])
    assert "<h2>Goals</h2>" not in page


def test_render_org_page_tiles_count_goals_and_top_priorities() -> None:
    a = _status(name="my-a", by_priority={"P0": 2, "P1": 1}, milestones=(_goal(repo="my-a"),))
    b = _status(name="my-b", by_priority={"P1": 3}, milestones=(_goal(repo="my-b", open_issues=2),))
    page = render_org_page({"Development harness": [a, b]}, [])
    tile = '<div class="k">{}</div><div class="v">{}</div><div class="d">{}</div>'
    assert tile.format("Open issues", 4, "2 P0 · 4 P1") in page
    assert tile.format("Open goals", 1, "5 issues still open") in page


def test_render_org_page_escapes_html_in_a_goal_title() -> None:
    sneaky = _status(milestones=(_goal("goal/<script>alert(1)</script>"),))
    page = render_org_page({"Development harness": [sneaky]}, [])
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
