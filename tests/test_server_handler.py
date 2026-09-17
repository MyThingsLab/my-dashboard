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
    model = DashboardModel(shelved={}, unshelved=[], graph=GraphModel(), generated_at="ts")
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


def test_index_serves_the_page(server) -> None:
    base, _ = server
    status, body, ctype = _get(f"{base}/")
    assert status == 200
    assert "text/html" in ctype
    assert b"operative dashboard" in body


def test_graph_json_is_served(server) -> None:
    base, _ = server
    status, body, ctype = _get(f"{base}/graph.json")
    assert status == 200 and "application/json" in ctype
    assert json.loads(body) == {"nodes": [], "edges": [], "cycles": []}


def test_unknown_path_404s(server) -> None:
    base, _ = server
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{base}/nope")
    assert exc.value.code == 404


def test_post_decide_flips_the_ask_and_redirects(server) -> None:
    base, asks = server
    ask = asks.create(action_kind="pr-merge", payload={"pr": 1}, timeout=30)
    req = urllib.request.Request(
        f"{base}/asks/{ask.id}/decide?decision=allow", method="POST", data=b""
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200  # urllib follows the 303 redirect to "/"
    assert asks.get(ask.id).status == "allow"


def test_post_to_an_unknown_route_404s(server) -> None:
    base, _ = server
    req = urllib.request.Request(f"{base}/nope", method="POST", data=b"")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 404
