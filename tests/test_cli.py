from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from mythings.engine import ClaudeCLIEngine, NoopEngine

from mydashboard.cli import _derive_slug, build_engine, main


def test_build_engine_noop_by_default() -> None:
    assert isinstance(build_engine("noop"), NoopEngine)


def test_build_engine_claude_cli() -> None:
    assert isinstance(build_engine("claude-cli"), ClaudeCLIEngine)


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
