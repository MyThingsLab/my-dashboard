from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mydashboard.cli import _derive_slug, main


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
