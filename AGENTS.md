# my-dashboard — agent instructions

You are developing **my-dashboard**, a MyThingsLab My[X] tool.

**Inherited rules:** obey [`./HARNESS.md`](./HARNESS.md) in full — the vendored
MyThingsLab build-harness rules. Do not restate or override them. Anything not
covered here defers to `HARNESS.md`, then `my-things-core/docs/CONVENTIONS.md`.

## This tool

- **Purpose:** Renders the fleet's status two ways — an org-wide front page
  (every repo grouped into development-harness/services/casual-development
  shelves via `shelves.toml`, published as a PR to the docs site) and a
  single-repo status card (purpose, CI, open issues/PRs, last activity;
  local mode — stdout or a local file, never a PR).
- **The single Engine call:** optional, behind `--summarize` on `render`: from
  the deterministic status table, write the two-sentence "state of the fleet"
  banner. Default run and `status` (single-repo mode) are fully
  deterministic — no Engine call.
- **Invariants / rules:** never fabricate a status field — a value that can't
  be determined (no local checkout, unreachable `gh` data) renders as absent,
  not guessed. `render` only ever proposes a PR to the docs-site repo through
  `Policy`; it never merges and never serves a live page. `status` never
  opens a PR. An org repo missing from `shelves.toml` renders in an
  "Unshelved" section — never silently dropped.
- **Backlog label:** `my-dashboard`
