from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from myguard import Guard
from mythings.engine import Engine, EngineRequest
from mythings.github import GitHub, PullRequest, Runner, _gh, _pr_number
from mythings.isolation import Workspace, in_github_actions
from mythings.ledger import Ledger
from mythings.policy import Action, Decision, Policy

from mydashboard.fleet import ORG, RepoStatus, gather_status, list_org_repos
from mydashboard.render import render_org_page, render_repo_card
from mydashboard.shelves import Shelving, load_shelves

DEFAULT_SITE = "MyThingsLab/mythingslab.github.io"
_PAGE_PATH = "dashboard/index.md"

_BANNER_SYSTEM = (
    "Write a two-sentence 'state of the fleet' banner from this deterministic "
    "status table. Use only the information already present; never invent a "
    "capability, count, or status not shown in the table."
)


class PolicyDenied(RuntimeError):
    pass


@dataclass(frozen=True)
class RenderResult:
    outcome: str  # success | skipped | failure
    pr: int | None
    detail: str
    page_hash: str | None = None


@dataclass(frozen=True)
class StatusResult:
    outcome: str  # success | failure
    detail: str
    card: str = ""


class Dashboard:
    def __init__(
        self,
        *,
        repo_root: str | Path = ".",
        repo: str = DEFAULT_SITE,
        ledger: Ledger,
        base: str = "main",
        org: str = ORG,
        workspace: Path | None = None,
        shelves_path: str | Path | None = None,
        engine: Engine | None = None,
        policy: Policy | None = None,
        runner: Runner = _gh,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.repo = repo
        self.ledger = ledger
        self.base = base
        self.org = org
        self.workspace = workspace
        self.shelving: Shelving = load_shelves(shelves_path)
        self.engine = engine
        self.policy: Policy = policy or Guard()
        self.runner = runner
        self.github = GitHub(repo, runner=runner)

    def render(self, *, summarize: bool = False, no_pr: bool = False) -> RenderResult:
        names = list_org_repos(self.org, runner=self.runner)
        statuses = {
            name: gather_status(name, org=self.org, runner=self.runner, workspace=self.workspace)
            for name in names
        }
        mapped, unshelved_names = self.shelving.classify(names)
        shelved = {label: [statuses[n] for n in repo_names] for label, repo_names in mapped.items()}

        banner = self._banner(shelved) if summarize else None
        page = render_org_page(shelved, unshelved_names, banner=banner)
        page_hash = hashlib.sha256(page.encode("utf-8")).hexdigest()

        try:
            pr, changed = self._write(page) if not no_pr else (None, None)
        except PolicyDenied as denied:
            return self._fail(str(denied))

        if not no_pr and changed is False:
            detail = "dashboard page already up to date"
            self._record("skipped", detail, page_hash)
            return RenderResult("skipped", None, detail, page_hash)

        detail = f"rendered dashboard for {len(names)} repo(s)"
        self._record("success", detail, page_hash, pr.number if pr else None)
        return RenderResult("success", pr.number if pr else None, detail, page_hash)

    def status(self, name: str, *, org: str | None = None) -> StatusResult:
        status = gather_status(
            name, org=org or self.org, runner=self.runner, workspace=self.workspace
        )
        card = render_repo_card(status)
        self.ledger.record(
            tool="mydashboard",
            kind="status",
            outcome="success",
            detail=f"status card for {status.slug}",
            repo=status.slug,
        )
        return StatusResult("success", f"status card for {status.slug}", card)

    # ---- engine --------------------------------------------------------

    def _banner(self, shelved: dict[str, list[RepoStatus]]) -> str | None:
        if self.engine is None:
            return None
        table = render_org_page(shelved, [])
        reply = self.engine.run(EngineRequest(prompt=table, system=_BANNER_SYSTEM)).text.strip()
        return reply or None

    # ---- pr / git --------------------------------------------------------

    def _write(self, page: str) -> tuple[PullRequest | None, bool]:
        with Workspace(self.repo_root, self.base) as tree:
            target = tree / _PAGE_PATH
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(page, encoding="utf-8")
            if not self._has_changes(tree):
                return None, False
            pr = self._open_pr(tree)
        return pr, True

    def _has_changes(self, tree: Path) -> bool:
        proc = subprocess.run(
            ["git", "-C", str(tree), "status", "--porcelain", "--", _PAGE_PATH],
            capture_output=True,
            text=True,
        )
        return bool(proc.stdout.strip())

    def _open_pr(self, tree: Path) -> PullRequest:
        branch = "my-dashboard/render"
        existing = self._existing_pr(branch)
        self._git(tree, ["checkout", "-B", branch])
        self._git(tree, ["add", _PAGE_PATH])
        self._git(tree, ["commit", "-m", "docs: refresh fleet dashboard"])
        if existing is None:
            self._git(tree, ["push", "-u", "origin", branch])
        else:
            self._git(tree, ["push", "origin", branch])
        if existing is not None:
            return existing
        self._guard(f"gh pr create --head {branch} --base {self.base}")
        return self.github.open_pr(
            title="docs: refresh fleet dashboard",
            body="Refreshes the org-wide fleet dashboard page.",
            base=self.base,
            head=branch,
        )

    def _existing_pr(self, branch: str) -> PullRequest | None:
        argv = ["pr", "list", "--head", branch, "--state", "open", "--json", "number,url"]
        argv += ["--repo", self.repo]
        rows = json.loads(self.runner(argv))
        if not rows:
            return None
        row = rows[0]
        return PullRequest(number=row.get("number") or _pr_number(row["url"]), url=row["url"])

    def _git(self, tree: Path, argv: list[str]) -> None:
        self._guard("git " + " ".join(argv))
        proc = subprocess.run(["git", "-C", str(tree), *argv], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(argv)} failed: {proc.stderr.strip()}")

    def _guard(self, command: str) -> None:
        result = self.policy.evaluate(Action(kind="bash", payload={"command": command}))
        if result.under(unattended=in_github_actions()) is not Decision.ALLOW:
            raise PolicyDenied(f"policy blocked: {command} ({result.reason or result.decision})")

    # ---- ledger / results --------------------------------------------------

    def _record(self, outcome: str, detail: str, page_hash: str, pr: int | None = None) -> None:
        self.ledger.record(
            tool="mydashboard",
            kind="dashboard_render",
            outcome=outcome,
            detail=detail,
            page_hash=page_hash,
            pr=pr,
        )

    def _fail(self, detail: str) -> RenderResult:
        self.ledger.record(
            tool="mydashboard", kind="dashboard_render", outcome="failure", detail=detail
        )
        return RenderResult("failure", None, detail)
