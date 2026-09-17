from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

import mydashboard.cli as cli
from mydashboard.cli import _derive_slug, main
from mydashboard.graph import GraphModel
from mydashboard.live import DashboardModel


def test_derive_slug_reads_the_origin_remote(tmp_path: Path) -> None:
    repo = tmp_path / "work"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", "git@github.com:MyThingsLab/my-x.git"],
        check=True,
    )
    assert _derive_slug(repo) == "MyThingsLab/my-x"


def test_missing_subcommand_errors() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_serve_builds_a_snapshot_then_hands_off_to_the_http_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_model = DashboardModel(shelved={}, unshelved=[], graph=GraphModel(), generated_at="ts")
    monkeypatch.setattr(cli, "build_model", lambda **_kw: stub_model)
    served = {}
    monkeypatch.setattr(cli, "serve_http", lambda app, **kw: served.update(kw, app=app))

    rc = main(["serve", "--ledger", str(tmp_path / ".mythings/ledger.jsonl"), "--port", "9"])
    assert rc == 0
    assert served["port"] == 9
    # Live's first build now runs on a background thread (so the HTTP
    # socket can bind immediately, see live.Live.start) -- give it a moment.
    deadline = time.time() + 2.0
    while served["app"].live.model is None and time.time() < deadline:
        time.sleep(0.005)
    assert served["app"].live.model is stub_model


def test_ask_exits_zero_when_allowed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "wait_for_decision", lambda *a, **kw: True)
    rc = main(
        [
            "ask",
            "--ledger",
            str(tmp_path / ".mythings/ledger.jsonl"),
            "--action-kind",
            "pr-merge",
            "--payload-json",
            '{"pr": 1}',
        ]
    )
    assert rc == 0


def test_ask_exits_nonzero_when_denied(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "wait_for_decision", lambda *a, **kw: False)
    rc = main(
        [
            "ask",
            "--ledger",
            str(tmp_path / ".mythings/ledger.jsonl"),
            "--action-kind",
            "pr-merge",
        ]
    )
    assert rc == 1
