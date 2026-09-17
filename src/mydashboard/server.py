from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib import resources
from urllib.parse import parse_qs, urlsplit

from mydashboard import views
from mydashboard.ask import AskStore
from mydashboard.graph import render_json
from mydashboard.live import Live

# Served at /static/<name>. An allowlist rather than a path join under a
# directory: the package is the only source of these, and a lookup that can
# only ever return one of two known files cannot be walked out of.
_STATIC = {
    "serve.js": "application/javascript; charset=utf-8",
    "graph.js": "application/javascript; charset=utf-8",
}


class App:
    """Socket-free view, mirroring my-office's App: the transport (HTTP) is a
    thin shell over these pure methods, so responses are unit-tested without
    binding a port."""

    def __init__(self, live: Live, asks: AskStore) -> None:
        self.live = live
        self.asks = asks

    # ---- pages ----

    def page(self, path: str, query: str = "") -> bytes:
        model = self.live.model
        if model is None:
            return views.building_page().encode("utf-8")

        params = parse_qs(query)
        goal_slug = params.get("slug", [""])[0] or None

        pending = self.asks.pending()
        if path == "/graph":
            body, title = views.graph_page(model), "Graph"
            scripts = ("/static/serve.js", "/static/graph.js")
        elif path in ("/goal", "/goals"):
            body, title, scripts = (
                views.goal_focus_page(model, goal_slug),
                "Goal Focus",
                ("/static/serve.js",),
            )
        elif path == "/queue":
            body, title, scripts = views.queue_page(model), "LLM Queue", ("/static/serve.js",)
        elif path == "/repos":
            body, title, scripts = views.repos_page(model), "Repos", ("/static/serve.js",)
        elif path == "/asks":
            body, title, scripts = views.asks_page(pending), "Decisions", ("/static/serve.js",)
        else:
            body, title, scripts = views.overview(model, pending), "Overview", ("/static/serve.js",)

        return views.layout(
            title=title,
            active=path,
            body=body,
            model=model,
            pending=len(pending),
            scripts=scripts,
        ).encode("utf-8")

    # ---- json api ----

    def graph_json(self) -> bytes:
        model = self.live.model
        if model is None:
            return b'{"nodes": [], "edges": [], "cycles": []}'
        return render_json(model.graph)

    def queue_json(self) -> bytes:
        model = self.live.model
        if model is None:
            return b'{"stages": []}'
        ready_nodes = [n.id for n in model.graph.nodes if n.state == "ready"]
        blocked_nodes = [n.id for n in model.graph.nodes if n.state == "blocked"]
        in_flight = [r.name for r in model.repos if r.open_prs > 0]
        return json.dumps(
            {
                "generated_at": model.generated_at,
                "stages": [
                    {"stage": "context_prep", "count": len(blocked_nodes), "tasks": blocked_nodes},
                    {"stage": "llm_queue", "count": len(ready_nodes), "tasks": ready_nodes},
                    {"stage": "inference", "count": len(in_flight), "repos": in_flight},
                    {"stage": "policy_gate", "count": len(self.asks.pending())},
                    {
                        "stage": "verify_draft",
                        "count": sum(1 for r in model.repos if r.ci.value == "success"),
                    },
                ],
            },
            indent=2,
        ).encode("utf-8")

    def repos_json(self) -> bytes:
        model = self.live.model
        if model is None:
            return b"{}"
        return json.dumps(
            {
                "generated_at": model.generated_at,
                "complete": model.complete,
                "repos": [
                    {
                        "name": r.name,
                        "slug": r.slug,
                        "ci": r.ci.value,
                        "open_issues": r.open_issues,
                        "open_prs": r.open_prs,
                        "by_priority": r.by_priority,
                        "last_activity_days": r.last_activity_days,
                        "shelf": model.shelf_of(r.name),
                    }
                    for r in model.repos
                ],
            },
            indent=2,
        ).encode("utf-8")

    def asks_json(self) -> bytes:
        return json.dumps(
            [
                {
                    "id": a.id,
                    "action_kind": a.action_kind,
                    "payload": a.payload,
                    "created_at": a.created_at,
                    "deadline": a.deadline,
                }
                for a in self.asks.pending()
            ],
            indent=2,
        ).encode("utf-8")

    def static(self, name: str) -> tuple[bytes, str] | None:
        content_type = _STATIC.get(name)
        if content_type is None:
            return None
        text = resources.files("mydashboard").joinpath(name).read_text(encoding="utf-8")
        return text.encode("utf-8"), content_type


_PAGE_PATHS = ("/", "/index.html", "/goal", "/goals", "/queue", "/graph", "/repos", "/asks")


def make_handler(app: App) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
            split = urlsplit(self.path)
            path = split.path
            if path in _PAGE_PATHS:
                self._send(200, "text/html; charset=utf-8", app.page(path, split.query))
            elif path.startswith("/static/"):
                found = app.static(path.removeprefix("/static/"))
                if found is None:
                    self._send(404, "text/plain", b"not found")
                else:
                    body, content_type = found
                    self._send(200, content_type, body)
            elif path == "/api/graph":
                self._send(200, "application/json", app.graph_json())
            elif path == "/api/queue":
                self._send(200, "application/json", app.queue_json())
            elif path == "/api/repos":
                self._send(200, "application/json", app.repos_json())
            elif path == "/api/asks":
                self._send(200, "application/json", app.asks_json())
            else:
                self._send(404, "text/plain", b"not found")


        def do_POST(self) -> None:  # noqa: N802
            parts = urlsplit(self.path)
            segments = parts.path.strip("/").split("/")
            if len(segments) == 3 and segments[0] == "asks" and segments[2] == "decide":
                query = parse_qs(parts.query)
                app.asks.decide(segments[1], query.get("decision", [""])[0])
                # Back to the page that submitted, so deciding from the
                # overview doesn't dump the reader on the decisions tab.
                # Checked against the known pages rather than echoed: a
                # Location built from a query parameter is an open redirect.
                back = query.get("from", ["/asks"])[0]
                self.send_response(303)
                self.send_header("Location", back if back in _PAGE_PATHS else "/asks")
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
