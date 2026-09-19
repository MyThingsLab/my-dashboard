# Changelog

## [Unreleased]
### Added/Changed
- implemented org-wide render (shelves.toml, gh status, staleness-hash PR) and single-repo status card (local mode)
- adopted the user-approved claude.ai artifact mockup as the real render output: dashboard/index.html (cards, pills, tiles, unshelved drift section) replaces the markdown table; Engine banner prompt stays the deterministic markdown table
- Mechanical migration to mythings.testing: the dispatch-table FakeGh became fake_gh wiring over the shared FakeGh (repo/issue/pr/run/api handlers); the empty-tree make_site_repo stays local by design.
- Adopt canonical AGENTS.md with symlinks and support AGENTS.md in dashboard fleet status
- Add P0 focus and open PRs overview sections to dashboard render
- Implemented multi-page operative workstation with /goal focus and /queue conveyor belt
- Refined operative dashboard views to formal mission-control engineering standards
- Implemented multi-goal switcher and all-milestones portfolio table
### Fixed
- Bump my-things-core pin to v1.7.0 in CI workflow
- Update CI siblings install of my-things-core to @main to include mythings.deps

All notable changes to `my-dashboard` are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is
[semver](https://semver.org/), per the rules in `RELEASE.md`.

## [1.0.0] - 2026-07-20

First stable release. Baseline of the org-wide dashboard render and
single-repo status cards as they already existed. No behavior changes in
this release. Adopts the v1 release contract (`RELEASE.md`) and pins its
`my-things-core` and `my-guard` dependencies to `@v1.0.0` instead of floating
on `@main`.
