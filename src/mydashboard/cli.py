from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from mythings.engine import build_engine_from_args
from mythings.ledger import Ledger

from mydashboard.ask import AskStore, wait_for_decision
from mydashboard.dashboard import DEFAULT_SITE, Dashboard, RenderResult, StatusResult
from mydashboard.fleet import ORG
from mydashboard.live import Live, build_model
from mydashboard.server import App
from mydashboard.server import serve as serve_http
from mydashboard.shelves import load_shelves

_ENGINES = ("noop", "claude-cli")
_REMOTE_RE = re.compile(r"github\.com[:/](?P<slug>[^/]+/[^/]+?)(?:\.git)?$")


def _render_result(result: RenderResult) -> str:
    line = f"{result.outcome}: {result.detail}"
    if result.pr is not None:
        line += f" (PR #{result.pr})"
    return line


def _derive_slug(path: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(path), "remote", "get-url", "origin"], capture_output=True, text=True
    )
    match = _REMOTE_RE.search(proc.stdout.strip()) if proc.returncode == 0 else None
    if match is None:
        raise SystemExit(f"could not derive a GitHub slug from {path} — pass --repo owner/name")
    return match.group("slug")


def _make_dashboard(args: argparse.Namespace) -> Dashboard:
    engine = build_engine_from_args(args) if args.summarize else None
    return Dashboard(
        repo_root=args.repo_root,
        repo=args.repo,
        ledger=Ledger(args.ledger),
        base=args.base,
        workspace=args.workspace,
        shelves_path=args.shelves,
        engine=engine,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mydashboard",
        description="Renders the fleet's org-wide dashboard and single-repo status cards.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    render = sub.add_parser("render", help="render the org-wide dashboard page and open a PR")
    render.add_argument("--org", default="MyThingsLab", help="GitHub org to enumerate")
    render.add_argument(
        "--repo", default=DEFAULT_SITE, help=f"docs-site slug owner/name (default: {DEFAULT_SITE})"
    )
    render.add_argument("--repo-root", type=Path, default=Path.cwd(), help="local docs-site clone")
    render.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="fleet workspace root with sibling repo checkouts (local dev-ledger/ledger reads)",
    )
    render.add_argument("--shelves", type=Path, default=None, help="override shelves.toml")
    render.add_argument("--base", default="main", help="base branch for the PR")
    render.add_argument("--ledger", type=Path, default=Path(".mythings/ledger.jsonl"))
    render.add_argument("--no-pr", action="store_true", help="render but skip opening the PR")
    render.add_argument(
        "--summarize", action="store_true", help="add an Engine-written 'state of the fleet' banner"
    )
    render.add_argument(
        "--engine",
        choices=sorted(_ENGINES),
        default="noop",
        help="Engine backend for --summarize (default: noop — banner omitted)",
    )
    render.add_argument("--engine-model", default=None, help="model for --engine claude-cli")

    status = sub.add_parser("status", help="print one repo's status card (local mode, no PR)")
    status.add_argument("--path", type=Path, default=Path.cwd(), help="local repo checkout")
    status.add_argument("--repo", default=None, help="GitHub slug (default: derive from remote)")
    status.add_argument("--ledger", type=Path, default=Path(".mythings/ledger.jsonl"))
    status.add_argument("--out", type=Path, default=None, help="write the card to a file")

    serve = sub.add_parser(
        "serve", help="serve a live, interactive graph of the fleet (read-only view + ASK panel)"
    )
    serve.add_argument("--org", default=ORG, help="GitHub org to enumerate")
    serve.add_argument(
        "--workspace", type=Path, default=None, help="fleet workspace root with sibling checkouts"
    )
    serve.add_argument("--shelves", type=Path, default=None, help="override shelves.toml")
    serve.add_argument(
        "--workflows", type=Path, default=None, help="override my-pipeline workflows.json"
    )
    serve.add_argument("--ledger", type=Path, default=Path(".mythings/ledger.jsonl"))
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8010)
    serve.add_argument(
        "--refresh-seconds", type=float, default=300.0, help="how often to rebuild the snapshot"
    )

    ask = sub.add_parser(
        "ask",
        help="$MYTHINGS_ASK_CMD-compatible: block until a human decides via `mydashboard serve`",
    )
    ask.add_argument("--ledger", type=Path, required=True)
    ask.add_argument("--timeout", type=float, default=330.0)
    ask.add_argument("--action-kind", required=True)
    ask.add_argument("--payload-json", default="{}")

    args = parser.parse_args(argv)

    if args.cmd == "render":
        dashboard = _make_dashboard(args)
        result = dashboard.render(summarize=args.summarize, no_pr=args.no_pr)
        print(_render_result(result))
        return 1 if result.outcome == "failure" else 0

    if args.cmd == "serve":
        shelving = load_shelves(args.shelves)
        live = Live(
            lambda: build_model(
                org=args.org,
                workspace=args.workspace,
                shelving=shelving,
                workflows_path=args.workflows,
            ),
            refresh_seconds=args.refresh_seconds,
        )
        live.start()
        asks = AskStore(args.ledger.parent / "asks")
        serve_http(App(live, asks), host=args.host, port=args.port)
        return 0

    if args.cmd == "ask":
        store = AskStore(args.ledger.parent / "asks")
        payload = json.loads(args.payload_json)
        pending = store.create(action_kind=args.action_kind, payload=payload, timeout=args.timeout)
        allowed = wait_for_decision(store, pending.id, timeout=args.timeout)
        return 0 if allowed else 1

    slug = args.repo or _derive_slug(args.path)
    org, name = slug.split("/", 1)
    dashboard = Dashboard(
        ledger=Ledger(args.ledger), org=org, workspace=args.path.resolve().parent
    )
    status_result: StatusResult = dashboard.status(name, org=org)
    if args.out is not None:
        args.out.write_text(status_result.card, encoding="utf-8")
        print(f"{status_result.outcome}: wrote {args.out}")
    else:
        print(status_result.card, end="")
    return 1 if status_result.outcome == "failure" else 0


if __name__ == "__main__":
    raise SystemExit(main())
