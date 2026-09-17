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
        repo_rows = "\n".join(
            f"      <tr><td>{html.escape(r.name)}</td><td>{_CI_LABEL[r.ci]}</td>"
            f"<td>{r.open_issues}</td><td>{r.open_prs}</td></tr>"
            for r in sorted(rows, key=lambda r: r.name)
        )
        pending = self.asks.pending()
        ask_rows = "\n".join(_ask_row(a) for a in pending) or "<p>No pending ASKs.</p>"
        cycle_note = (
            f"<p><strong>{len(model.graph.cycles)} dependency cycle(s) flagged</strong> -- "
            "shown ringed in black below, never auto-resolved.</p>"
            if model.graph.cycles
            else ""
        )
        return _PAGE.format(
            generated_at=model.generated_at,
            graph=render_svg(model.graph),
            cycle_note=cycle_note,
            ask_rows=ask_rows,
            repo_rows=repo_rows,
        ).encode("utf-8")


def _decide_form(ask_id: str, decision: str, label: str) -> str:
    return (
        f'<form method="POST" action="/asks/{ask_id}/decide?decision={decision}" '
        f'style="display:inline"><button>{label}</button></form>'
    )


def _ask_row(ask: Ask) -> str:
    kind = html.escape(ask.action_kind)
    payload = html.escape(str(ask.payload))
    forms = f"{_decide_form(ask.id, 'allow', 'Allow')} {_decide_form(ask.id, 'deny', 'Deny')}"
    return f"<tr><td>{kind}</td><td>{payload}</td><td>{forms}</td></tr>"


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
<html><head><meta charset="utf-8"><title>MyThingsLab -- operative dashboard</title>
<meta http-equiv="refresh" content="30">
<style>body{{font-family:system-ui,sans-serif;margin:2rem;max-width:70rem}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:.3rem .6rem}}
form{{margin:0}}</style></head>
<body>
<h1>MyThingsLab -- operative dashboard</h1>
<p><em>Generated {generated_at}</em></p>

<h2>Pending ASKs</h2>
<table><thead><tr><th>kind</th><th>payload</th><th>decision</th></tr></thead>
<tbody>
{ask_rows}
</tbody></table>

<h2>Issue-blocking / workflow graph</h2>
{cycle_note}
{graph}

<h2>Repos</h2>
<table><thead><tr><th>repo</th><th>CI</th><th>open issues</th><th>open PRs</th></tr></thead>
<tbody>
{repo_rows}
</tbody></table>
</body></html>
"""
