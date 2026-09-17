# my-dashboard

[![CI](https://github.com/MyThingsLab/my-dashboard/actions/workflows/ci.yml/badge.svg)](https://github.com/MyThingsLab/my-dashboard/actions/workflows/ci.yml) [![codecov](https://codecov.io/gh/MyThingsLab/my-dashboard/branch/main/graph/badge.svg)](https://codecov.io/gh/MyThingsLab/my-dashboard) ![Python](https://img.shields.io/badge/python-3.11%2B-blue) [![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A [MyThingsLab](../my-things-core) tool that renders the fleet's status three ways:

- **`mydashboard render`** — the org-wide front page. Every repo is grouped
  into development-harness/services/casual-development shelves (explicit
  `shelves.toml` mapping — a repo missing from the map renders visibly in an
  "Unshelved" section, never silently dropped). Per repo: purpose (from its
  `CLAUDE.md`), CI status on `main`, open issue/PR counts, last dev-ledger and
  runtime-`Ledger` activity. Fully deterministic by default; `--summarize`
  adds an optional Engine-written two-sentence fleet banner. Publishes via a
  PR to the docs-site repo, skipping the PR when the rendered page is
  unchanged. Never merges.
- **`mydashboard status`** — the same per-repo status card, scoped to one
  local checkout. Prints to stdout (or `--out <path>`); no PR, ever.
- **`mydashboard serve`** — a live, read-only, navigable view of the fleet as
  an *operative workstation*, across five pages:
  - `/` **Overview** — what should change what you do next, in that order:
    decisions waiting on you, blocked vs ready issues, red mains, then
    inventory. Red repos get a full card; flagged dependency cycles get a
    callout.
  - `/graph` **Graph** — issues blocking one another
    ([`mythings.deps`](../my-things-core)), grouped by shared goal milestone
    ([`mythings.goals`](../my-things-core)), plus
    [my-pipeline](../my-pipeline)'s declared workflow DAG (its
    `workflows.json` read as a data file, never imported — my-pipeline itself
    never imports another tool's package either). Drag to pan, scroll to
    zoom, filter by state/repo/goal/text, click a node for a drawer showing
    what it waits on and what it blocks, each with the verbatim clause the
    issue body used. Closed issues are hidden by default.
  - `/goals` **Goals** — per-goal progress, verdict, `done_when`, and a
    "falsely blocked" count (labelled blocked while every blocker it names is
    already closed — the condition that once left this fleet's queue empty
    while the board looked busy).
  - `/repos` **Repos** — every repo, sortable by any column and filterable.
  - `/asks` **Decisions** — the ASK queue, with a countdown, since a
    timed-out ASK denies.

  Snapshots rebuild on a background timer (`--refresh-seconds`, default 300s)
  and publish in two stages, so the graph is readable while the slower
  per-repo sweep is still running. Styling is shared with the published page
  (`dashboard.css`), and the only client-side code is two dependency-free
  files served from the package. Binds `127.0.0.1` by default. Read-only like
  `render`/`status` — the one write path is deciding a pending ASK.
- **`mydashboard ask`** — a second `$MYTHINGS_ASK_CMD`-compatible
  implementation (see `myguard.ask`), alongside `mytelegrambot ask`: blocks
  until a human decides via `serve`'s panel instead of Telegram, same
  exit-code contract (0 = allow). Point `$MYTHINGS_ASK_CMD` at whichever one
  a deployment should use — never both for the same channel at once.

## CLI

```bash
mydashboard render --org MyThingsLab --repo-root <docs-site clone> \
                    [--workspace <fleet root>] [--summarize] \
                    [--engine noop|claude-cli] [--no-pr]

mydashboard status [--path <repo checkout>] [--repo <owner/name>] [--out <path>]

mydashboard serve [--org MyThingsLab] [--workspace <fleet root>] \
                   [--shelves <path>] [--workflows <path>] \
                   [--host 127.0.0.1] [--port 8010] [--refresh-seconds 300]

mydashboard ask --ledger <path> --action-kind <kind> --payload-json '<json>' \
                 [--timeout 330]
```

`serve` also exposes a JSON API for anything that would rather read the data
than the page: `GET /api/graph` (nodes, edges, cycles — depths, not pixel
coordinates), `GET /api/repos`, `GET /api/asks`.

## Install (development)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ../my-things-core -e ".[dev]"
pytest
```

## License

MIT — see [`LICENSE`](LICENSE).
