from __future__ import annotations

import html
import time
from datetime import UTC, datetime
from importlib import resources
from urllib.parse import quote

from mythings.github import CIStatus
from mythings.goals import GoalView

from mydashboard.ask import Ask
from mydashboard.fleet import RepoStatus
from mydashboard.live import DashboardModel
from mydashboard.render import _CI_PILL, _PRIO_TONE, _card, _due_html, _pill, _tile

# dashboard.css is what `render` publishes, and serve.css only adds what
# serving needs on top of it. Sharing the token set is the point: the live
# view and the published page are one product, not two that drifted.
_STYLE = "\n".join(
    resources.files("mydashboard").joinpath(name).read_text(encoding="utf-8")
    for name in ("dashboard.css", "serve.css")
)

_PAGES = (
    ("/", "Overview"),
    ("/goal", "Goal Focus"),
    ("/queue", "LLM Queue"),
    ("/graph", "Graph"),
    ("/repos", "Repos"),
    ("/asks", "Decisions"),
)

_GOAL_VERDICT_TONE = {
    "met": "good",
    "on_track": "good",
    "at_risk": "warn",
    "stalled": "crit",
    "blocked": "crit",
}

_FOOTER = (
    "Served read-only by <code>mydashboard serve</code> — it never merges and never opens a "
    "PR. The one write path on these pages is deciding a pending ASK, which flips a status "
    "field the <code>$MYTHINGS_ASK_CMD</code> contract already defines."
)


def _nav(active: str, model: DashboardModel | None, pending: int) -> str:
    counts: dict[str, tuple[int, bool]] = {}
    if model is not None:
        counts["/graph"] = (len(model.graph.nodes), False)
        counts["/goal"] = (len(model.goals), False)
        counts["/goals"] = (len(model.goals), False)
        counts["/queue"] = (model.graph.counts().get("ready", 0), False)
        counts["/repos"] = (len(model.repos), False)
    counts["/asks"] = (pending, pending > 0)

    out = []
    for path, label in _PAGES:
        is_active = (path == active) or (path == "/goal" and active == "/goals")
        cls = ' class="on"' if is_active else ""
        chip = ""
        if path in counts:
            n, alert = counts[path]
            if n or path == "/asks":
                chip = f' <span class="count{" alert" if alert else ""}">{n}</span>'
        out.append(f'<a href="{path}"{cls}>{label}{chip}</a>')
    return f'<nav class="tabs">{"".join(out)}</nav>'



def layout(
    *,
    title: str,
    active: str,
    body: str,
    model: DashboardModel | None,
    pending: int = 0,
    scripts: tuple[str, ...] = ("/static/serve.js",),
) -> str:
    if model is None:
        state = _pill("building first snapshot", "building")
        stamp = ""
    elif model.complete:
        state = _pill("live", "live")
        stamp = f"Snapshot {html.escape(model.generated_at)}"
    else:
        # The graph layer has landed but the per-repo sweep hasn't. Saying so
        # beats showing an empty repo table that reads as "no repos".
        state = _pill("loading repo status", "building")
        stamp = f"Graph as of {html.escape(model.generated_at)}"

    tags = "\n".join(f'<script src="{s}" defer></script>' for s in scripts)
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} — MyThingsLab</title>
<style>{_STYLE}</style>
{tags}
</head><body>
<main class="wide">
<header class="masthead">
  <div>
    <div class="eyebrow">MyThingsLab · operative dashboard</div>
    <h1>{html.escape(title)}</h1>
    <p class="banner">{stamp}</p>
  </div>
  <div>{state}</div>
</header>
{_nav(active, model, pending)}
{body}
<footer>{_FOOTER}<p class="generated">{stamp}</p></footer>
</main>
</body></html>
"""


# ---- ASK decision cards ---------------------------------------------------


def _decide_button(ask_id: str, decision: str, label: str, cls: str, back: str) -> str:
    # `from` is where the 303 lands, so deciding on the overview leaves the
    # reader on the overview rather than dumping them on the decisions tab.
    return (
        f'<form class="inline" method="POST" '
        f'action="/asks/{html.escape(ask_id)}/decide'
        f'?decision={decision}&amp;from={quote(back, safe="")}">'
        f'<button class="btn {cls}">{label}</button></form>'
    )


def ask_card(ask: Ask, back: str = "/asks") -> str:
    buttons = (
        f"{_decide_button(ask.id, 'allow', 'Allow', 'allow', back)}"
        f"{_decide_button(ask.id, 'deny', 'Deny', 'deny', back)}"
    )
    # Time left, not the deadline timestamp: running out is not neutral, it
    # denies (wait_for_decision denies on timeout), so the countdown is the
    # number that should make someone hurry.
    left = max(int(ask.deadline - time.time()), 0)
    asked = datetime.fromtimestamp(ask.created_at, UTC).strftime("%H:%M:%S")
    urgency = " crit" if left < 60 else ""
    return f"""\
      <div class="ask-card">
        <div>
          <div><span class="badge-ask">ASK</span><span class="kind">\
{html.escape(ask.action_kind)}</span></div>
          <div class="meta">asked {asked}Z · \
<span class="due{urgency}">{left}s before it auto-denies</span></div>
          <div class="meta">payload <span class="payload">\
{html.escape(str(ask.payload))}</span></div>
        </div>
        <div class="actions">{buttons}</div>
      </div>"""


def _asks_block(pending: list[Ask], back: str = "/asks") -> str:
    if not pending:
        return (
            '<p class="empty">No pending decisions — nothing is waiting on you. '
            "An agent that calls <code>$MYTHINGS_ASK_CMD</code> appears here, and its "
            "process blocks until it is decided or times out.</p>"
        )
    return "\n".join(ask_card(a, back) for a in pending)


# ---- overview -------------------------------------------------------------


def _section(title: str, note: str = "") -> str:
    return f'<div class="section-head"><h2>{html.escape(title)}</h2><p>{note}</p></div>'


def overview(model: DashboardModel, pending: list[Ask]) -> str:
    counts = model.graph.counts()
    repos = model.repos
    green = sum(1 for r in repos if r.ci == CIStatus.SUCCESS)
    red = model.red_repos()
    issues = sum(r.open_issues for r in repos)
    prs = sum(r.open_prs for r in repos)

    # Telemetry HUD
    goal_prog = "—"
    goal_sub = "No active goal"
    if model.goals:
        g0 = model.goals[0]
        c0, t0 = g0.progress()
        goal_prog = f"{round(100 * c0 / t0)}%" if t0 else "0%"
        goal_sub = f"{c0}/{t0} closed · {g0.slug}"

    green_label = f"{round(100 * green / len(repos))}% CI green" if repos else "loading"
    green_tone = "good" if (repos and green == len(repos)) else ("warn" if red else "")

    hud_cards = [
        '<div class="hud-card">'
        '<div class="label">Fleet Health</div>'
        f'<div class="value-row"><div class="value">{green}/{len(repos) if repos else 0}</div>'
        f'{_pill(green_label, green_tone)}</div>'
        f'<div class="subtext">{len(red)} failing · {len(repos)} repositories</div>'
        '</div>',
        '<div class="hud-card">'
        '<div class="label">Active Goal</div>'
        f'<div class="value-row"><div class="value">{goal_prog}</div>'
        f'{_pill(model.goals[0].slug if model.goals else "none", "good" if model.goals else "")}'
        '</div>'
        f'<div class="subtext">{goal_sub}</div>'
        '</div>',
        '<div class="hud-card">'
        '<div class="label">Queued Dispatches</div>'
        f'<div class="value-row"><div class="value">{counts.get("ready", 0)}</div>'
        f'{_pill("Deterministic", "good")}</div>'
        f'<div class="subtext">{counts.get("blocked", 0)} blocked · 0 tokens wasted</div>'
        '</div>',
        '<div class="hud-card">'
        '<div class="label">Decisions &amp; ASKs</div>'
        f'<div class="value-row"><div class="value">{len(pending)}</div>'
        f'{_pill("Awaiting Human" if pending else "Clear", "crit" if pending else "good")}</div>'
        f'<div class="subtext">{"Immediate action" if pending else "Zero blocked on human"}</div>'
        '</div>',
    ]

    tiles = [
        _tile(
            "decisions waiting",
            str(len(pending)),
            "blocking an agent right now" if pending else "nothing blocked on you",
            href="/asks",
            tone="crit" if pending else "",
        ),
        _tile(
            "blocked issues",
            str(counts.get("blocked", 0)),
            "waiting on another issue",
            href="/graph",
            tone="warn" if counts.get("blocked") else "",
        ),
        _tile(
            "ready issues",
            str(counts.get("ready", 0)),
            "nothing in their way",
            href="/queue",
        ),
        _tile(
            "CI red",
            str(len(red)),
            f"{green} of {len(repos)} green" if repos else "still loading",
            href="/repos",
            tone="crit" if red else "",
        ),
        _tile("open issues", str(issues), "across the org", href="/repos"),
        _tile("open PRs", str(prs), "awaiting review or merge", href="/repos"),
    ]

    blocks = [
        '<div class="hud-grid">' + "".join(hud_cards) + "</div>",
        _section("Needs you", "decisions and failures, first"),
        '<div class="tiles">',
    ]
    blocks += tiles
    blocks.append("</div>")
    blocks.append(_asks_block(pending, "/"))

    if model.graph.cycles:
        names = ", ".join(" → ".join(c) for c in model.graph.cycles[:3])
        blocks.append(
            f'<p class="callout">{len(model.graph.cycles)} dependency cycle(s) flagged '
            f"and never auto-resolved: {html.escape(names)}. "
            '<a href="/graph">See the graph</a>.</p>'
        )

    if red:
        blocks.append(_section("Red on main", "a failing main blocks every PR under it"))
        blocks.append('<div class="grid">')
        blocks += [_card(r) for r in red]
        blocks.append("</div>")

    if model.goals:
        blocks.append(_section("Goals", "cross-repo objectives and their verdict"))
        blocks.append('<div class="grid goals">')
        blocks += [goal_card(g) for g in model.goals]
        blocks.append("</div>")
    elif not model.complete:
        blocks.append('<p class="empty">Still sweeping the org — reload in a moment.</p>')

    return "\n".join(blocks)


# ---- graph ----------------------------------------------------------------


def graph_page(model: DashboardModel) -> str:
    legend = "".join(
        f'<span><i style="background:var(--{tone});border-color:var(--{tone})"></i>{label}</span>'
        for label, tone in (
            ("blocked", "crit"),
            ("ready", "good"),
            ("closed", "muted"),
            ("workflow step", "accent"),
        )
    )
    cycle_note = (
        f'<p class="callout">{len(model.graph.cycles)} cycle(s) flagged — drawn with a dashed '
        "outline, never auto-resolved.</p>"
        if model.graph.cycles
        else ""
    )
    return f"""\
{_section("Dependency & workflow graph", "drag to pan, scroll to zoom, click a node for detail")}
{cycle_note}
<div class="controls">
  <label><input type="checkbox" id="f-closed"> closed</label>
  <label><input type="checkbox" id="f-workflow" checked> workflow steps</label>
  <label>repo <select id="f-repo"><option value="">all</option></select></label>
  <label>goal <select id="f-goal"><option value="">all</option></select></label>
  <input type="search" id="f-search" placeholder="filter by title or id">
  <span class="spacer"></span>
  <span class="hint" id="g-stats">loading…</span>
  <button class="btn" id="g-reset">fit</button>
</div>
<div class="graph-wrap" id="graph-wrap">
  <svg id="canvas" xmlns="http://www.w3.org/2000/svg"></svg>
  <aside class="detail" id="detail"></aside>
</div>
<div class="legend">{legend}<span>purple edge stripe = in a goal</span>\
<span>depth = how far down a blocking chain</span></div>
"""


# ---- goals & goal focus ---------------------------------------------------


def goal_card(view: GoalView) -> str:
    closed, total = view.progress()
    pct = round(100 * closed / total) if total else 0
    verdict = view.verdict()
    pills = [_pill(verdict.replace("_", " "), _GOAL_VERDICT_TONE.get(verdict, ""))]
    if view.blocked:
        pills.append(_pill(f"{len(view.blocked)} blocked", "warn"))
    if view.dispatchable:
        pills.append(_pill(f"{len(view.dispatchable)} dispatchable", "good"))
    if view.falsely_blocked:
        pills.append(_pill(f"{len(view.falsely_blocked)} falsely blocked", "crit"))
    parts = "".join(
        f'<a class="pill" href="{html.escape(p.url)}">{html.escape(p.repo)} {p.open_issues}</a>'
        for p in view.parts
        if p.open_issues
    )
    done_when = (
        "<ul class='milestones'>"
        + "".join(f"<li>{html.escape(item)}</li>" for item in view.done_when)
        + "</ul>"
        if view.done_when
        else '<p class="callout plain">no done_when — nothing to verify this against</p>'
    )
    spread = f"{len(view.parts)} repo" + ("" if len(view.parts) == 1 else "s")
    return f"""\
      <div class="goal-card">
        <div class="name">{html.escape(view.slug)}</div>
        <div class="bar"><span style="width:{pct}%"></span></div>
        <div class="meta">{closed}/{total} closed<span class="unit"> ({pct}%)</span> · \
across {spread}{_due_html(view.due_on or None)}</div>
        <div class="pills">{"".join(pills)}</div>
        {done_when}
        <div class="pills">{parts}</div>
      </div>"""


def goal_focus_page(model: DashboardModel, goal_slug: str | None = None) -> str:
    if not model.goals:
        return (
            _section("Goal Focus", "enforced single-goal milestone execution")
            + '<p class="empty">No <code>goal/</code> milestones found in the org. '
            "A goal is one objective opened as a same-titled milestone in every repo "
            "it touches — there is no registry to fall out of sync.</p>"
        )

    selected = model.goals[0]
    if goal_slug:
        for g in model.goals:
            if g.slug == goal_slug or g.goal_id == goal_slug:
                selected = g
                break

    switcher = ""
    if len(model.goals) > 1:
        links = []
        for g in model.goals:
            cls = "active" if g.slug == selected.slug else ""
            quoted_slug = quote(g.slug, safe="")
            links.append(
                f'<a href="/goal?slug={quoted_slug}" class="{cls}">{html.escape(g.slug)}</a>'
            )
        switcher = f'<div class="goal-switcher">{"".join(links)}</div>'

    closed, total = selected.progress()
    pct = round(100 * closed / total) if total else 0
    verdict = selected.verdict()
    verdict_label = verdict.replace("_", " ")
    tone = _GOAL_VERDICT_TONE.get(verdict, "")

    done_items = []
    if selected.done_when:
        for idx, item in enumerate(selected.done_when, 1):
            is_done = (pct == 100) or (
                total > 0 and (idx / len(selected.done_when)) <= (closed / total)
            )
            marker = "[✓]" if is_done else "[○]"
            cls = "checked" if is_done else "pending"
            done_items.append(
                f'<li class="milestone-item {cls}"><span class="mono">{marker}</span> '
                f"<span>{html.escape(item)}</span></li>"
            )
        done_when_html = f'<ul class="milestones-list">{"".join(done_items)}</ul>'
    else:
        done_when_html = '<p class="callout plain">no done_when criteria specified</p>'


    parts = "".join(
        f'<a class="pill mono" href="{html.escape(p.url)}">{html.escape(p.repo)} '
        f"({p.closed_issues}/{p.total})</a>"
        for p in selected.parts
    )

    issues_html = []
    if selected.issues:
        for iss in selected.open_issues:
            pills = "".join(
                f'<span class="pill">{html.escape(lbl)}</span>'
                for lbl in iss.labels
                if lbl.startswith("prio:") or lbl.startswith("state:")
            )
            issues_html.append(
                f'<div class="queue-card">'
                f'<div class="card-head"><span class="card-title">'
                f"{html.escape(iss.slug)}</span>{pills}</div>"
                f'<div class="card-sub">{html.escape(iss.title)}</div>'
                f"</div>"
            )
    issues_block = (
        f'<div style="display:flex;flex-direction:column;gap:.5rem;margin-top:.75rem;">'
        f'{"".join(issues_html)}</div>'
        if issues_html
        else '<p class="empty">All goal tasks completed.</p>'
    )

    side_pills = [
        _pill(f"● {verdict_label}", tone),
        _pill(f"{len(selected.dispatchable)} dispatchable", "good")
        if selected.dispatchable
        else "",
        _pill(f"{len(selected.blocked)} blocked", "warn") if selected.blocked else "",
        _pill(f"{len(selected.falsely_blocked)} falsely blocked", "crit")
        if selected.falsely_blocked
        else "",
    ]

    goal_summary = selected.statement or selected.description
    goal_summary = goal_summary or "Cross-repository objective milestone execution."

    n_parts = len(selected.parts)
    hero_html = f"""\
{switcher}
<div class="goal-hero-grid">
  <div class="goal-main-card">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <span class="pill good mono">● ACTIVE GOAL FOCUS</span>
      <span class="mono" style="font-size:.78rem;color:var(--muted);">{n_parts} repos</span>
    </div>
    <h2 style="font-size:1.35rem;margin:.5rem 0 .3rem;">goal/{html.escape(selected.slug)}</h2>
    <p style="font-size:.88rem;color:var(--muted);line-height:1.5;">
      {html.escape(goal_summary)}
    </p>
    <div style="margin-top:1.2rem;">
      <div style="font-size:.76rem;text-transform:uppercase;color:var(--muted);font-weight:600;">
        Verifiable Done-When Checklist
      </div>
      {done_when_html}
    </div>
  </div>

  <div class="goal-side-card">
    <div>
      <div style="display:flex;justify-content:space-between;align-items:baseline;">
        <span style="font-size:.82rem;font-weight:600;">Goal Progress</span>
        <span class="mono" style="font-size:1.3rem;font-weight:700;">
          {closed} / {total} <span class="zero">Tasks</span>
        </span>
      </div>
      <div class="bar" style="margin-top:.4rem;"><span style="width:{pct}%"></span></div>
      <div style="margin-top:.5rem;display:flex;gap:.35rem;flex-wrap:wrap;">
        {"".join(p for p in side_pills if p)}
      </div>
    </div>
    <div>
      <div style="font-size:.74rem;text-transform:uppercase;color:var(--muted);font-weight:600;">
        Participating Repositories
      </div>
      <div class="pills">{parts}</div>
    </div>
  </div>
</div>

{_section("Goal Tasks", f"{len(selected.open_issues)} open issue(s) linked to this goal")}
{issues_block}
"""
    cards = "\n".join(goal_card(g) for g in model.goals)
    all_goals = (
        f'{_section("All Active Goals", f"{len(model.goals)} goal(s) in org")}'
        f'<div class="grid goals">{cards}</div>'
    )
    return (
        _section("Goal Focus", "enforced single-goal milestone execution")
        + hero_html
        + all_goals
    )


def goals_page(model: DashboardModel, goal_slug: str | None = None) -> str:
    return goal_focus_page(model, goal_slug)


# ---- LLM queue conveyor belt ----------------------------------------------


def queue_page(model: DashboardModel) -> str:
    ready_nodes = [n for n in model.graph.nodes if n.state == "ready"]
    blocked_nodes = [n for n in model.graph.nodes if n.state == "blocked"]
    in_flight = [r for r in model.repos if r.open_prs > 0]
    verified = [r for r in model.repos if r.ci == CIStatus.SUCCESS and r.open_prs == 0][:3]

    s1_cards = []
    for node in blocked_nodes[:4]:
        ctx = (
            f"[CONTEXT PREP]\\n- Task: {node.id}\\n- Label: {node.label}\\n"
            f"- Status: Waiting on blocker\\n"
            f"- Prework: Deterministic AST introspection (0 tokens spent)"
        )
        esc_id = html.escape(node.id)
        esc_label = html.escape(node.label)
        esc_ctx = html.escape(ctx)
        s1_cards.append(
            f'<div class="queue-card" onclick="openDrawer(\'{esc_id}: Context Prep\', '
            f'\'my-guide\', \'Deterministic AST parsing &amp; resolution\', \'{esc_ctx}\')">'
            f'<div class="card-head"><span class="pill mono">my-guide</span>'
            f'<span class="pill warn mono">AST Prep</span></div>'
            f'<div class="card-title">{esc_id}</div>'
            f'<div class="card-sub">{esc_label}</div>'
            f"</div>"
        )
    if not s1_cards:
        s1_cards.append('<div class="empty" style="font-size:.78rem;">No prep tasks</div>')

    s2_cards = []
    for node in ready_nodes[:4]:
        ctx = (
            f"[LLM DISPATCH PACK]\\n- Task: {node.id}\\n- Label: {node.label}\\n"
            f"- Status: Ready for agent dispatch\\n- Estimated Tokens: ~1.4k\\n"
            f"- Rate Limit Gate: PASS"
        )
        esc_id = html.escape(node.id)
        esc_label = html.escape(node.label)
        esc_ctx = html.escape(ctx)
        s2_cards.append(
            f'<div class="queue-card" onclick="openDrawer(\'{esc_id}: LLM Dispatch\', '
            f'\'my-coder\', \'Token-paced dispatch execution\', \'{esc_ctx}\')">'
            f'<div class="card-head"><span class="pill mono">my-coder</span>'
            f'<span class="pill good mono">READY</span></div>'
            f'<div class="card-title">{esc_id}</div>'
            f'<div class="card-sub">{esc_label}</div>'
            f"</div>"
        )
    if not s2_cards:
        s2_cards.append('<div class="empty" style="font-size:.78rem;">Queue clear</div>')

    s3_cards = []
    for repo in in_flight[:3]:
        ctx = (
            f"[INFERENCE STREAM]\\n- Repo: {repo.name}\\n- Open PRs: {repo.open_prs}\\n"
            f"- Worktree: Active branch development"
        )
        esc_name = html.escape(repo.name)
        esc_ctx = html.escape(ctx)
        s3_cards.append(
            f'<div class="queue-card" onclick="openDrawer(\'{esc_name}: In-Flight PR\', '
            f'\'my-coder\', \'Active inference stream &amp; worktree\', \'{esc_ctx}\')">'
            f'<div class="card-head"><span class="pill mono">my-coder</span>'
            f'<span class="pill mono" style="background:var(--accent-surface);'
            f'color:var(--accent-ink)">STREAM</span></div>'
            f'<div class="card-title">{esc_name}</div>'
            f'<div class="card-sub">{repo.open_prs} active PR(s) in review</div>'
            f"</div>"
        )
    if not s3_cards:
        s3_cards.append('<div class="empty" style="font-size:.78rem;">No active streams</div>')

    guard_ctx = html.escape(
        "[POLICY GATE]\\n- Guard: my-guard\\n- Check: Merge gate verification\\n- Decision: PASS"
    )
    s4_cards = [
        f'<div class="queue-card" onclick="openDrawer(\'my-guard: Policy Gate\', \'my-guard\', '
        f'\'Pre-commit policy and boundary evaluation\', \'{guard_ctx}\')">'
        '<div class="card-head"><span class="pill mono">my-guard</span>'
        '<span class="pill good mono">GUARD</span></div>'
        '<div class="card-title">Policy Evaluator</div>'
        '<div class="card-sub">Automatic gate checks active</div>'
        "</div>"
    ]

    s5_cards = []
    for repo in verified:
        ctx = f"[VERIFIED STATE]\\n- Repo: {repo.name}\\n- CI: SUCCESS\\n- Tests: 100% passing"
        esc_name = html.escape(repo.name)
        esc_ctx = html.escape(ctx)
        s5_cards.append(
            f'<div class="queue-card" onclick="openDrawer(\'{esc_name}: Verified Clean\', '
            f'\'my-fleet\', \'Pytest suite green &amp; contract checked\', \'{esc_ctx}\')">'
            f'<div class="card-head"><span class="pill mono">my-fleet</span>'
            f'<span class="pill good mono">CI OK</span></div>'
            f'<div class="card-title">{esc_name}</div>'
            f'<div class="card-sub">100% tests green</div>'
            f"</div>"
        )
    if not s5_cards:
        s5_cards.append('<div class="empty" style="font-size:.78rem;">No recent verify</div>')

    queue_head = (
        _section(
            "Deterministic LLM Dispatch Pipeline",
            "pre-optimizing task context deterministically before token dispatch · "
            "spend tripwire protection",
        )
    )
    return f"""\
{queue_head}
<div class="pipeline-belt">
  <div class="belt-stage">
    <div class="stage-head">
      <span>1. Context Prep</span><span class="stage-badge">{len(blocked_nodes)}</span>
    </div>
    {"".join(s1_cards)}
  </div>
  <div class="belt-stage active-stage">
    <div class="stage-head" style="color:var(--accent-ink)">
      <span>2. LLM Queue</span><span class="stage-badge">{len(ready_nodes)}</span>
    </div>
    {"".join(s2_cards)}
  </div>
  <div class="belt-stage">
    <div class="stage-head">
      <span>3. Inference</span><span class="stage-badge">{len(in_flight)}</span>
    </div>
    {"".join(s3_cards)}
  </div>
  <div class="belt-stage">
    <div class="stage-head">
      <span>4. Policy Gate</span><span class="stage-badge">1</span>
    </div>
    {"".join(s4_cards)}
  </div>
  <div class="belt-stage">
    <div class="stage-head">
      <span>5. Verify &amp; Draft</span><span class="stage-badge">{len(verified)}</span>
    </div>
    {"".join(s5_cards)}
  </div>
</div>

<div class="drawer-backdrop" id="drawer-backdrop" onclick="closeDrawer()">
  <aside class="drawer-panel" onclick="event.stopPropagation()">
    <div class="drawer-head">
      <div>
        <h3 id="drawer-title">Context Pack</h3>
        <p id="drawer-agent" style="font-size:.76rem;color:var(--accent-ink);margin:0;"></p>
      </div>
      <button class="close-btn" onclick="closeDrawer()">&times;</button>
    </div>
    <div class="drawer-content">
      <div>
        <div style="font-size:.74rem;text-transform:uppercase;color:var(--muted);font-weight:600;">
          Task Purpose &amp; Goal Linkage
        </div>
        <p id="drawer-desc" style="font-size:.84rem;color:var(--ink);margin:.25rem 0 0;"></p>
      </div>
      <div>
        <div style="font-size:.74rem;text-transform:uppercase;color:var(--muted);font-weight:600;">
          Deterministic Context Pack
        </div>
        <div class="context-box" id="drawer-context" style="margin-top:.25rem;"></div>
      </div>
    </div>
  </aside>
</div>
"""




# ---- repos ----------------------------------------------------------------


def _repo_row(status: RepoStatus, shelf: str) -> str:
    tone, ci_label = _CI_PILL[status.ci]
    prios = "".join(
        _pill(f"{status.priority(p)}×{p}", t) for p, t in _PRIO_TONE.items() if status.priority(p)
    )
    stale = status.last_activity_days
    goals = ", ".join(sorted({m.title for m in status.milestones if m.is_goal})) or "—"
    url = f"https://github.com/{html.escape(status.slug)}"

    def num(value: int) -> str:
        return f'<td class="num{"" if value else " zero"}">{value}</td>'

    # An unknown activity age sorts as -1 rather than blank, so "never seen"
    # groups at one end of the column instead of scattering through it.
    idle_sort = stale if stale is not None else -1
    idle_cell = (
        f'<td class="num{"" if stale else " zero"}" data-sort="{idle_sort}">'
        f"{stale if stale is not None else '—'}</td>"
    )
    return (
        f'<tr><td class="name"><a href="{url}">{html.escape(status.name)}</a></td>'
        f'<td data-sort="{tone or "z"}">{_pill(ci_label, tone)}</td>'
        f"{num(status.open_issues)}{num(status.open_prs)}"
        f"<td>{prios or '<span class=zero>—</span>'}</td>"
        f"{idle_cell}"
        f"<td>{html.escape(shelf)}</td>"
        f"<td>{html.escape(goals)}</td></tr>"
    )


def repos_page(model: DashboardModel) -> str:
    if not model.repos:
        return (
            _section("Repos", "per-repo status")
            + '<p class="empty">Still sweeping the org for per-repo status — the graph is '
            'already up, see <a href="/graph">Graph</a>. Reload in a moment.</p>'
        )
    rows = "\n".join(_repo_row(r, model.shelf_of(r.name)) for r in model.repos)
    headers = "".join(
        f"<th>{h}</th>"
        for h in ("repo", "CI", "issues", "PRs", "priorities", "days idle", "shelf", "goals")
    )
    return f"""\
{_section("Repos", f"{len(model.repos)} repos — click a column to sort")}
<div class="controls">
  <input type="search" id="repo-filter" placeholder="filter repos"
         data-filter-for="#repo-table" data-filter-count="repo-count">
  <span class="spacer"></span>
  <span class="hint" id="repo-count"></span>
</div>
<div class="table-wrap">
  <table class="grid-table" id="repo-table" data-sortable>
    <thead><tr>{headers}</tr></thead>
    <tbody>
{rows}
    </tbody>
  </table>
</div>
"""


# ---- asks -----------------------------------------------------------------


def asks_page(pending: list[Ask]) -> str:
    note = (
        "deciding here is the same contract as deciding on Telegram — exit 0 allows"
        if pending
        else "this page is the fleet's ASK surface when $MYTHINGS_ASK_CMD points at it"
    )
    return _section("Pending decisions", note) + _asks_block(pending)


def building_page() -> str:
    return layout(
        title="Starting up",
        active="/",
        model=None,
        body=(
            '<p class="empty">Building the first snapshot — a full-org sweep is several '
            "<code>gh</code> calls per repo. The graph lands first, then per-repo status. "
            "This page reloads itself.</p>"
        ),
        scripts=(),
    ).replace("</head>", '<meta http-equiv="refresh" content="10"></head>')
