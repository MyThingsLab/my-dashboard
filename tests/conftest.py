from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _clean_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # pre-commit runs hooks with GIT_DIR/GIT_INDEX_FILE set; they leak into the
    # git subprocesses these tests spawn (and into isolation.Workspace) and break
    # worktree ops on the throwaway repo. Real my-dashboard runs aren't inside a hook.
    for var in ("GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_OBJECT_DIRECTORY"):
        monkeypatch.delenv(var, raising=False)


def git(repo: Path, *argv: str) -> None:
    subprocess.run(["git", "-C", str(repo), *argv], check=True, capture_output=True, text=True)


def make_site_repo(tmp_path: Path) -> Path:
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


class FakeGh:
    """Mocks the `gh` boundary used by fleet.py + Dashboard's PR flow."""

    def __init__(
        self,
        *,
        repos: list[str] | None = None,
        issues: dict[str, list[dict]] | None = None,
        prs: dict[str, list[dict]] | None = None,
        runs: dict[str, list[dict]] | None = None,
        contents: dict[str, str] | None = None,
        pr_create_url: str = "https://github.com/MyThingsLab/mythingslab.github.io/pull/9",
    ) -> None:
        self.repos = repos or []
        self.issues = issues or {}
        self.prs = prs or {}
        self.runs = runs or {}
        self.contents = contents or {}
        self.pr_create_url = pr_create_url
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        if argv[:2] == ["repo", "list"]:
            return json.dumps([{"name": name} for name in self.repos])
        if argv[:2] == ["issue", "list"]:
            slug = argv[argv.index("--repo") + 1]
            return json.dumps(self.issues.get(slug, []))
        if argv[:2] == ["pr", "list"]:
            if "--head" in argv:
                return json.dumps([])
            slug = argv[argv.index("--repo") + 1]
            return json.dumps(self.prs.get(slug, []))
        if argv[:2] == ["run", "list"]:
            slug = argv[argv.index("--repo") + 1]
            return json.dumps(self.runs.get(slug, []))
        if argv[0] == "api":
            path = argv[1]
            if path not in self.contents:
                raise RuntimeError(f"gh api {path} failed (404)")
            return self.contents[path]
        if argv[:2] == ["pr", "create"]:
            return self.pr_create_url + "\n"
        raise AssertionError(f"unexpected gh call: {argv}")


def issue(number: int) -> dict:
    return {"number": number}


def run_row(status: str = "completed", conclusion: str = "success") -> dict:
    return {"status": status, "conclusion": conclusion}
