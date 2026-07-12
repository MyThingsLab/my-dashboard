from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

# Shared fakes come from mythings.testing (plain imports; aliased fixture
# re-export + getfixturevalue wrapper per core docs/CONVENTIONS.md).
from mythings.testing import FakeGh
from mythings.testing import clean_git_env as _shared_clean_git_env  # noqa: F401


@pytest.fixture(autouse=True)
def _clean_git_env(request: pytest.FixtureRequest) -> None:
    # Real git worktrees in every test; hook-launched pytest (pre-commit)
    # must not leak GIT_* into them.
    request.getfixturevalue("_shared_clean_git_env")


def git(repo: Path, *argv: str) -> None:
    subprocess.run(["git", "-C", str(repo), *argv], check=True, capture_output=True, text=True)


def make_site_repo(tmp_path: Path) -> Path:
    # Deliberately an EMPTY tree (--allow-empty), not the shared make_git_repo:
    # the front page must render into a docs repo with no files yet.
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    repo = tmp_path / "work"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "Tester")
    git(repo, "commit", "-m", "init", "--allow-empty")
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "-u", "origin", "main")
    return repo


def fake_gh(
    *,
    repos: list[str] | None = None,
    issues: dict[str, list[dict]] | None = None,
    prs: dict[str, list[dict]] | None = None,
    runs: dict[str, list[dict]] | None = None,
    contents: dict[str, str] | None = None,
    pr_create_url: str = "https://github.com/MyThingsLab/mythingslab.github.io/pull/9",
) -> FakeGh:
    issues = issues or {}
    prs = prs or {}
    runs = runs or {}
    contents = contents or {}

    def _slug(argv: list[str]) -> str:
        return argv[argv.index("--repo") + 1]

    def pr_list(argv: list[str]) -> str:
        if "--head" in argv:
            return json.dumps([])
        return json.dumps(prs.get(_slug(argv), []))

    def api(argv: list[str]) -> str:
        path = argv[1]
        if path not in contents:
            raise RuntimeError(f"gh api {path} failed (404)")
        return contents[path]

    return FakeGh(
        {
            ("repo", "list"): json.dumps([{"name": name} for name in (repos or [])]),
            ("issue", "list"): lambda argv: json.dumps(issues.get(_slug(argv), [])),
            ("pr", "list"): pr_list,
            ("run", "list"): lambda argv: json.dumps(runs.get(_slug(argv), [])),
            ("api",): api,
            ("pr", "create"): pr_create_url + "\n",
        }
    )


def issue(number: int) -> dict:
    return {"number": number}


def run_row(status: str = "completed", conclusion: str = "success") -> dict:
    return {"status": status, "conclusion": conclusion}
