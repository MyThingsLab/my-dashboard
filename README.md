# my-dashboard

[![CI](https://github.com/MyThingsLab/my-dashboard/actions/workflows/ci.yml/badge.svg)](https://github.com/MyThingsLab/my-dashboard/actions/workflows/ci.yml) [![codecov](https://codecov.io/gh/MyThingsLab/my-dashboard/branch/main/graph/badge.svg)](https://codecov.io/gh/MyThingsLab/my-dashboard) ![Python](https://img.shields.io/badge/python-3.11%2B-blue) [![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A [MyThingsLab](../my-things-core) tool that renders the fleet's status two ways:

- **`mydashboard render`** — the org-wide front page. Every repo is grouped
  into development-harness/services/casual-development shelves (explicit
  `shelves.toml` mapping — a repo missing from the map renders visibly in an
  "Unshelved" section, never silently dropped). Per repo: purpose (from its
  `CLAUDE.md`), CI status on `main`, open issue/PR counts, last dev-ledger and
  runtime-`Ledger` activity. Fully deterministic by default; `--summarize`
  adds an optional Engine-written two-sentence fleet banner. Publishes via a
  PR to the docs-site repo, skipping the PR when the rendered page is
  unchanged. Never merges, never serves a live page.
- **`mydashboard status`** — the same per-repo status card, scoped to one
  local checkout. Prints to stdout (or `--out <path>`); no PR, ever.

## CLI

```bash
mydashboard render --org MyThingsLab --repo-root <docs-site clone> \
                    [--workspace <fleet root>] [--summarize] \
                    [--engine noop|claude-cli] [--no-pr]

mydashboard status [--path <repo checkout>] [--repo <owner/name>] [--out <path>]
```

## Install (development)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ../my-things-core -e ".[dev]"
pytest
```

## License

MIT — see [`LICENSE`](LICENSE).
