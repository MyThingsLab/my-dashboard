# my-dashboard — agent instructions

You are developing **my-dashboard**, a MyThingsLab My[X] tool.

**Inherited rules:** obey [`./HARNESS.md`](./HARNESS.md) in full — the vendored
MyThingsLab build-harness rules. Do not restate or override them. Anything not
covered here defers to `HARNESS.md`, then `my-things-core/docs/CONVENTIONS.md`.

## This tool

- **Purpose:** Renders the fleet's status three ways — an org-wide front page
  (every repo grouped into development-harness/services/casual-development
  shelves via `shelves.toml`, published as a PR to the docs site), a
  single-repo status card (purpose, CI, open issues/PRs, last activity;
  local mode — stdout or a local file, never a PR), and `serve`: a live,
  read-only HTTP view of the fleet as an operative graph — issues blocking
  one another (`mythings.deps`), grouped by shared goal milestone
  (`mythings.goals`), and my-pipeline's declared workflow DAG (read as a data
  file, never imported) — plus a panel for any pending ASK (see below).
- **The single Engine call:** optional, behind `--summarize` on `render`: from
  the deterministic status table, write the two-sentence "state of the fleet"
  banner. Default run, `status` (single-repo mode), and `serve` are fully
  deterministic — no Engine call.
- **Invariants / rules:** never fabricate a status field — a value that can't
  be determined (no local checkout, unreachable `gh` data) renders as absent,
  not guessed. `render` only ever proposes a PR to the docs-site repo through
  `Policy`; it never merges. `status` never opens a PR. `serve` renders and
  serves read-only — same as `render`/`status`, it never merges and never
  opens a PR; the one write path it exposes is deciding a pending ASK, which
  only flips a status field the `$MYTHINGS_ASK_CMD` contract already defines
  (`myguard.ask`), nothing this tool owns. An org repo missing from
  `shelves.toml` renders in an "Unshelved" section — never silently dropped.
- **`mydashboard ask`:** a second `$MYTHINGS_ASK_CMD`-compatible implementation
  (alongside `mytelegrambot ask`) that blocks until a human decides via
  `serve`'s panel instead of Telegram. The two are interchangeable — point
  `$MYTHINGS_ASK_CMD` at whichever one the deployment should use, never both
  for the same channel at once. Wiring the live fleet over to it is a
  deliberate operator decision, not something this tool does on its own.
- **Backlog label:** `my-dashboard`
