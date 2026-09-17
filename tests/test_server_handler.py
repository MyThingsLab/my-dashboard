from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

import pytest

from mydashboard.ask import AskStore
from mydashboard.graph import GraphModel
from mydashboard.live import DashboardModel
from mydashboard.server import App, make_handler


class _StubLive:
    def __init__(self, model: DashboardModel | None) -> None:
        self.model = model


@pytest.fixture()
def server(tmp_path: Path):
    model = DashboardModel(graph=GraphModel(), generated_at="ts", complete=True)
    asks = AskStore(tmp_path / "asks")
    httpd = HTTPServer(("127.0.0.1", 0), make_handler(App(_StubLive(model), asks)))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        yield base, asks
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def _get(url: str) -> tuple[int, bytes, str]:
    with urllib.request.urlopen(url) as resp:  # noqa: S310 (localhost test server)
        return resp.status, resp.read(), resp.headers.get("Content-Type", "")


@pytest.mark.parametrize(
    "path",
    ["/", "/index.html", "/goal", "/queue", "/graph", "/goals", "/repos", "/asks"],
)
def test_every_page_route_serves_html(server, path: str) -> None:
    base, _ = server
    status, body, ctype = _get(f"{base}{path}")
    assert status == 200
    assert "text/html" in ctype
    assert b"operative dashboard" in body


def test_the_graph_page_pulls_in_the_canvas_script(server) -> None:
    base, _ = server
    _, body, _ = _get(f"{base}/graph")
    assert b'src="/static/graph.js"' in body
    assert b'id="canvas"' in body


def test_a_page_that_is_not_the_graph_does_not_load_the_canvas_script(server) -> None:
    base, _ = server
    _, body, _ = _get(f"{base}/repos")
    assert b'src="/static/graph.js"' not in body


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/graph", {"nodes": [], "edges": [], "cycles": []}),
        ("/api/asks", []),
    ],
)
def test_json_api_routes(server, path: str, expected) -> None:
    base, _ = server
    status, body, ctype = _get(f"{base}{path}")
    assert status == 200 and "application/json" in ctype
    assert json.loads(body) == expected


def test_queue_json_api_route(server) -> None:
    base, _ = server
    status, body, ctype = _get(f"{base}/api/queue")
    assert status == 200 and "application/json" in ctype
    payload = json.loads(body)
    assert "stages" in payload
    assert len(payload["stages"]) == 5



def test_static_assets_are_served_with_a_javascript_content_type(server) -> None:
    base, _ = server
    status, body, ctype = _get(f"{base}/static/serve.js")
    assert status == 200
    assert "javascript" in ctype
    assert b"data-sortable" in body


def test_a_static_path_outside_the_allowlist_404s(server) -> None:
    base, _ = server
    for path in ("/static/../server.py", "/static/shelves.toml", "/static/nope.js"):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(f"{base}{path}")
        assert exc.value.code == 404


def test_unknown_path_404s(server) -> None:
    base, _ = server
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{base}/nope")
    assert exc.value.code == 404


def test_post_decide_flips_the_ask_and_redirects(server) -> None:
    base, asks = server
    ask = asks.create(action_kind="pr-merge", payload={"pr": 1}, timeout=30)
    req = urllib.request.Request(
        f"{base}/asks/{ask.id}/decide?decision=allow&from=%2Frepos", method="POST", data=b""
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200  # urllib follows the 303
        assert resp.url.endswith("/repos")  # ...to the page that submitted
    assert asks.get(ask.id).status == "allow"


def test_a_redirect_target_outside_the_known_pages_is_not_echoed(server) -> None:
    # `from` lands in a Location header, so echoing it would be an open
    # redirect. Anything unrecognized falls back to the decisions page.
    base, asks = server
    ask = asks.create(action_kind="pr-merge", payload={}, timeout=30)
    req = urllib.request.Request(
        f"{base}/asks/{ask.id}/decide?decision=deny&from=https%3A%2F%2Fevil.example",
        method="POST",
        data=b"",
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.url.endswith("/asks")
    assert asks.get(ask.id).status == "deny"


def test_post_to_an_unknown_route_404s(server) -> None:
    base, _ = server
    req = urllib.request.Request(f"{base}/nope", method="POST", data=b"")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 404
