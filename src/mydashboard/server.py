from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

from mythings.github import CIStatus

from mydashboard.ask import Ask, AskStore
from mydashboard.graph import render_json, render_svg
from mydashboard.live import Live

_CI_LABEL = {
    CIStatus.SUCCESS: "CI ok",
    CIStatus.FAILURE: "CI failing",
    CIStatus.PENDING: "CI pending",
    CIStatus.NONE: "CI —",
}


class App:
    """Socket-free view, mirroring my-office's App: the transport (HTTP) is a
    thin shell over these pure methods, so responses are unit-tested without
    binding a port."""

    def __init__(self, live: Live, asks: AskStore) -> None:
        self.live = live
        self.asks = asks

    def graph_json(self) -> bytes:
        model = self.live.model
        return render_json(model.graph) if model is not None else b'{"nodes": [], "edges": []}'

    def dashboard_json(self) -> bytes:
        model = self.live.model
        if model is None:
            return b"{}"
        rows = [s for group in model.shelved.values() for s in group] + model.unshelved
        payload = {
            "generated_at": model.generated_at,
            "repos": [
                {
                    "name": r.name,
                    "slug": r.slug,
                    "ci": r.ci.value,
                    "open_issues": r.open_issues,
                    "open_prs": r.open_prs,
                    "last_activity_days": r.last_activity_days,
                }
                for r in rows
            ],
        }
        return json.dumps(payload, indent=2).encode("utf-8")

    def page(self) -> bytes:
        model = self.live.model
        if model is None:
            return b"<p>building the first snapshot -- reload in a moment</p>"

        rows = [s for group in model.shelved.values() for s in group] + model.unshelved
        total_repos = len(rows)
        green_ci = sum(1 for r in rows if r.ci == CIStatus.SUCCESS)
        total_issues = sum(r.open_issues for r in rows)
        total_prs = sum(r.open_prs for r in rows)

        repo_rows = "\n".join(
            f"      <tr><td class=\"mono\"><strong>{html.escape(r.name)}</strong></td>"
            f"<td><span class=\"pill {'good' if r.ci == CIStatus.SUCCESS else 'crit'}\">"
            f"{_CI_LABEL[r.ci]}</span></td>"
            f"<td class=\"mono\">{r.open_issues}</td><td class=\"mono\">{r.open_prs}</td></tr>"
            for r in sorted(rows, key=lambda r: r.name)
        )
        pending = self.asks.pending()
        pending_count = len(pending)
        no_asks = '<p class="subtle-msg">No pending ASKs — autonomous loop nominal.</p>'
        ask_cards = "\n".join(_ask_card(a) for a in pending) or no_asks
        cycle_note = (
            f'<div class="callout warn"><strong>{len(model.graph.cycles)} '
            'dependency cycle(s) flagged</strong> — '
            'shown with warning outlines below, never auto-resolved.</div>'
            if model.graph.cycles
            else ""
        )
        pending_color = "var(--warn)" if pending_count > 0 else "inherit"
        pending_pill_class = "warn" if pending_count > 0 else "good"
        pending_status_text = "Needs Input" if pending_count > 0 else "Clear"

        return _PAGE.format(
            generated_at=model.generated_at,
            total_repos=total_repos,
            green_ci=green_ci,
            total_issues=total_issues,
            total_prs=total_prs,
            pending_count=pending_count,
            pending_color=pending_color,
            pending_pill_class=pending_pill_class,
            pending_status_text=pending_status_text,
            graph=render_svg(model.graph),
            cycle_note=cycle_note,
            ask_cards=ask_cards,
            repo_rows=repo_rows,
        ).encode("utf-8")


def _decide_form(ask_id: str, decision: str, label: str, btn_class: str) -> str:
    return (
        f'<form method="POST" action="/asks/{ask_id}/decide?decision={decision}" '
        f'style="display:inline"><button class="btn {btn_class}">{label}</button></form>'
    )


def _ask_card(ask: Ask) -> str:
    kind = html.escape(ask.action_kind)
    payload = html.escape(str(ask.payload))
    forms = (
        f"{_decide_form(ask.id, 'allow', 'Allow Action', 'btn-success')} "
        f"{_decide_form(ask.id, 'deny', 'Deny', 'btn-danger')}"
    )
    badge = '<span class="ask-badge">ASK REQUIRED</span>'
    return (
        f'<div class="ask-alert-card">'
        f'<div class="ask-info">'
        f'<div class="ask-header-row">{badge}<span class="ask-title">{kind}</span></div>'
        f'<div class="ask-details">Payload: <span class="ask-payload">{payload}</span></div>'
        f'</div>'
        f'<div class="ask-actions">{forms}</div>'
        f'</div>'
    )


def make_handler(app: App) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
            if self.path in ("/", "/index.html"):
                self._send(200, "text/html; charset=utf-8", app.page())
            elif self.path == "/graph.json":
                self._send(200, "application/json", app.graph_json())
            elif self.path == "/dashboard.json":
                self._send(200, "application/json", app.dashboard_json())
            else:
                self._send(404, "text/plain", b"not found")

        def do_POST(self) -> None:  # noqa: N802
            parts = urlsplit(self.path)
            segments = parts.path.strip("/").split("/")
            if len(segments) == 3 and segments[0] == "asks" and segments[2] == "decide":
                decision = parse_qs(parts.query).get("decision", [""])[0]
                app.asks.decide(segments[1], decision)
                self.send_response(303)
                self.send_header("Location", "/")
                self.end_headers()
                return
            self._send(404, "text/plain", b"not found")

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:  # silence default stderr spam
            pass

    return Handler


def serve(app: App, *, host: str = "127.0.0.1", port: int = 8010) -> None:
    httpd = HTTPServer((host, port), make_handler(app))
    print(f"mydashboard serving on http://{host}:{port} (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MyThingsLab -- operative dashboard</title>
<meta http-equiv="refresh" content="30">
<style>
:root {{
  --bg-page: #F8FAFC; --bg-surface: #FFFFFF; --bg-surface-subtle: #F1F5F9;
  --border-subtle: #E2E8F0; --border-strong: #CBD5E1;
  --text-primary: #0F172A; --text-secondary: #475569; --text-muted: #94A3B8;
  --accent-primary: #0D9488; --accent-surface: #F0FDFA; --accent-border: #99F6E4;
  --accent-text: #0F766E;
  --good: #059669; --good-bg: #ECFDF5; --good-border: #A7F3D0;
  --warn: #D97706; --warn-bg: #FFFBEB; --warn-border: #FDE68A;
  --crit: #DC2626; --crit-bg: #FEF2F2; --crit-border: #FECACA;
  --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
  --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
  --radius-sm: 6px; --radius-md: 8px; --radius-lg: 12px; --radius-full: 9999px;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg-page: #0B0F17; --bg-surface: #131B26; --bg-surface-subtle: #1C2636;
    --border-subtle: #243042; --border-strong: #334155;
    --text-primary: #F8FAFC; --text-secondary: #94A3B8; --text-muted: #64748B;
    --accent-primary: #14B8A6; --accent-surface: #042F2E; --accent-border: #115E59;
    --accent-text: #5EEAD4;
    --good: #6EE7B7; --good-bg: #064E3B; --good-border: #047857;
    --warn: #FCD34D; --warn-bg: #451A03; --warn-border: #78350F;
    --crit: #FCA5A5; --crit-bg: #450A0A; --crit-border: #7F1D1D;
    --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.4);
    --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.5);
  }}
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--bg-page); color: var(--text-primary); line-height: 1.5;
  padding: 1.5rem 2rem 4rem; max-width: 1400px; margin: 0 auto;
}}
.mono {{ font-family: ui-monospace, "SF Mono", "Cascadia Code", Menlo, Consolas, monospace; }}
header.masthead {{
  display: flex; justify-content: space-between; align-items: center;
  padding-bottom: 1.25rem; border-bottom: 1px solid var(--border-subtle); margin-bottom: 1.5rem;
}}
.brand-group {{ display: flex; align-items: center; gap: 0.85rem; }}
.brand-logo {{
  width: 32px; height: 32px; background: linear-gradient(135deg, var(--accent-primary), #0284C7);
  border-radius: var(--radius-sm); display: flex; align-items: center; justify-content: center;
  color: #FFF; font-weight: 700; font-size: 1rem;
}}
h1 {{ font-size: 1.25rem; font-weight: 700; }}
.subtitle {{ font-size: 0.82rem; color: var(--text-muted); }}
.status-pill {{
  display: inline-flex; align-items: center; gap: 0.45rem; padding: 0.3rem 0.75rem;
  border-radius: var(--radius-full); font-size: 0.78rem; font-weight: 600;
  font-family: ui-monospace, monospace; background: var(--accent-surface);
  color: var(--accent-text); border: 1px solid var(--accent-border);
}}
.status-dot {{
  width: 7px; height: 7px; border-radius: 50%; background: var(--accent-primary);
  box-shadow: 0 0 0 2px rgba(13, 148, 136, 0.25);
}}
.hud-grid {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem; margin-bottom: 1.75rem;
}}
.hud-card {{
  background: var(--bg-surface); border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md); padding: 1rem 1.25rem; box-shadow: var(--shadow-sm);
}}
.hud-card .label {{
  font-size: 0.75rem; font-weight: 600; text-transform: uppercase;
  color: var(--text-muted); margin-bottom: 0.25rem;
}}
.hud-card .value-row {{ display: flex; align-items: baseline; gap: 0.5rem; }}
.hud-card .value {{ font-size: 1.6rem; font-weight: 700; font-family: ui-monospace, monospace; }}
.hud-card .subtext {{ font-size: 0.78rem; color: var(--text-secondary); }}
.pill {{
  font-family: ui-monospace, monospace; font-size: 0.72rem; padding: 0.15rem 0.5rem;
  border-radius: var(--radius-full); background: var(--bg-surface-subtle);
  color: var(--text-secondary);
}}
.pill.good {{
  background: var(--good-bg); color: var(--good); border: 1px solid var(--good-border);
}}
.pill.warn {{
  background: var(--warn-bg); color: var(--warn); border: 1px solid var(--warn-border);
}}
.pill.crit {{
  background: var(--crit-bg); color: var(--crit); border: 1px solid var(--crit-border);
}}
.ask-alert-card {{
  background: linear-gradient(to right, var(--warn-bg), var(--bg-surface));
  border: 1px solid var(--warn-border); border-left: 4px solid var(--warn);
  border-radius: var(--radius-md); padding: 1.1rem 1.4rem; margin-bottom: 1.5rem;
  display: flex; align-items: center; justify-content: space-between; gap: 1.5rem;
  box-shadow: var(--shadow-sm);
}}
.ask-info {{ display: flex; flex-direction: column; gap: 0.25rem; }}
.ask-header-row {{ display: flex; align-items: center; gap: 0.6rem; }}
.ask-badge {{
  font-size: 0.72rem; font-weight: 700; font-family: ui-monospace, monospace;
  padding: 0.15rem 0.5rem; border-radius: var(--radius-sm); background: var(--warn); color: #FFF;
}}
.ask-title {{ font-size: 0.95rem; font-weight: 600; }}
.ask-details {{ font-size: 0.82rem; color: var(--text-secondary); }}
.ask-payload {{
  font-family: ui-monospace, monospace; background: rgba(0,0,0,0.05);
  padding: 0.1rem 0.35rem; border-radius: 4px;
}}
.ask-actions {{ display: flex; align-items: center; gap: 0.6rem; flex-shrink: 0; }}
.btn {{
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 0.82rem; font-weight: 600; padding: 0.4rem 0.9rem;
  border-radius: var(--radius-sm); border: 1px solid transparent; cursor: pointer;
}}
.btn-success {{ background: var(--good); color: #FFF; }}
.btn-danger {{ background: transparent; color: var(--crit); border-color: var(--crit-border); }}
.btn-danger:hover {{ background: var(--crit-bg); }}
.section-head {{ margin: 2rem 0 1rem; }}
.section-head h2 {{ font-size: 1.15rem; font-weight: 700; margin-bottom: 0.2rem; }}
.section-head p {{ font-size: 0.82rem; color: var(--text-muted); }}
.graph-container {{
  background: var(--bg-surface); border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg); padding: 1.5rem; margin-bottom: 2rem;
  box-shadow: var(--shadow-sm); overflow-x: auto;
}}
table {{
  width: 100%; border-collapse: collapse; background: var(--bg-surface);
  border: 1px solid var(--border-subtle); border-radius: var(--radius-md);
  overflow: hidden; box-shadow: var(--shadow-sm);
}}
th {{
  background: var(--bg-surface-subtle); font-size: 0.78rem; text-transform: uppercase;
  color: var(--text-muted); text-align: left; padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border-subtle);
}}
td {{ padding: 0.75rem 1rem; border-bottom: 1px solid var(--border-subtle); font-size: 0.88rem; }}
tr:last-child td {{ border-bottom: none; }}
.subtle-msg {{ font-size: 0.84rem; color: var(--text-muted); }}
.callout.warn {{
  background: var(--warn-bg); color: var(--warn); border: 1px solid var(--warn-border);
  padding: 0.75rem 1rem; border-radius: var(--radius-md); margin-bottom: 1rem; font-size: 0.84rem;
}}
</style>
</head>
<body>
<header class="masthead">
  <div class="brand-group">
    <div class="brand-logo">M</div>
    <div>
      <h1>MyThingsLab — Operative Dashboard</h1>
      <p class="subtitle">Live Autonomous Fleet State · Generated {generated_at}</p>
    </div>
  </div>
  <div class="status-pill">
    <span class="status-dot"></span>
    <span class="mono">LIVE SERVE ACTIVE</span>
  </div>
</header>

<section class="hud-grid">
  <div class="hud-card">
    <div class="label">Fleet Health</div>
    <div class="value-row">
      <div class="value">{green_ci}/{total_repos}</div>
      <span class="pill good">CI Green</span>
    </div>
    <div class="subtext">Repos in nominal state</div>
  </div>
  <div class="hud-card">
    <div class="label">Open Backlog</div>
    <div class="value-row">
      <div class="value">{total_issues}</div>
      <span class="subtext">issues</span>
    </div>
    <div class="subtext">Active CAD tasks</div>
  </div>
  <div class="hud-card">
    <div class="label">In Flight PRs</div>
    <div class="value-row">
      <div class="value">{total_prs}</div>
      <span class="subtext">PRs</span>
    </div>
    <div class="subtext">Pending verification / merge</div>
  </div>
  <div class="hud-card">
    <div class="label">Pending Decisions</div>
    <div class="value-row">
      <div class="value" style="color: {pending_color};">{pending_count}</div>
      <span class="pill {pending_pill_class}">{pending_status_text}</span>
    </div>
    <div class="subtext">ASK channels active</div>
  </div>
</section>

<section>
  <div class="section-head">
    <h2>Pending Human-in-the-Loop Decisions (ASK)</h2>
    <p>Safety approvals requested by autonomous agents via $MYTHINGS_ASK_CMD</p>
  </div>
  {ask_cards}
</section>

<section>
  <div class="section-head">
    <h2>Operative Dependency & Workflow Graph</h2>
    <p>Topological graph of issue blockers and declared pipeline DAG triggers</p>
  </div>
  {cycle_note}
  <div class="graph-container">
    {graph}
  </div>
</section>

<section>
  <div class="section-head">
    <h2>Fleet Repositories</h2>
    <p>Status, CI health, and active work across all org tools</p>
  </div>
  <table>
    <thead><tr>
      <th>Repository</th><th>CI Health</th><th>Open Issues</th><th>Open PRs</th>
    </tr></thead>
    <tbody>
      {repo_rows}
    </tbody>
  </table>
</section>

</body>
</html>
"""
