from __future__ import annotations

from mythings.github import CIStatus

from mydashboard.fleet import RepoStatus

_CI_BADGE = {
    CIStatus.SUCCESS: "✅",
    CIStatus.FAILURE: "❌",
    CIStatus.PENDING: "⏳",
    CIStatus.NONE: "—",
}


def _row(status: RepoStatus) -> str:
    purpose = status.purpose or "_(no purpose seam found)_"
    activity = status.last_dev_ledger or status.last_ledger or "—"
    return (
        f"| [{status.name}](https://github.com/{status.slug}) | {purpose} | "
        f"{_CI_BADGE[status.ci]} | {status.open_issues} | {status.open_prs} | {activity} |"
    )


def _table(statuses: list[RepoStatus]) -> str:
    header = "| Tool | Purpose | CI | Issues | PRs | Last activity |\n"
    header += "| --- | --- | --- | --- | --- | --- |\n"
    return header + "\n".join(_row(status) for status in statuses)


def render_org_page(
    shelved: dict[str, list[RepoStatus]],
    unshelved: list[str],
    *,
    banner: str | None = None,
) -> str:
    parts = ["---\ntitle: Dashboard\n---\n", "# MyThingsLab fleet dashboard"]
    if banner:
        parts.append(banner)
    for label, statuses in shelved.items():
        if not statuses:
            continue
        parts.append(f"## {label}\n\n{_table(statuses)}")
    if unshelved:
        listing = "\n".join(f"- {name}" for name in sorted(unshelved))
        parts.append(f"## Unshelved\n\n{listing}")
    return "\n\n".join(parts) + "\n"


def render_repo_card(status: RepoStatus) -> str:
    lines = [
        f"# {status.name}",
        "",
        f"Purpose: {status.purpose or '_(no purpose seam found)_'}",
        f"CI (main): {_CI_BADGE[status.ci]}",
        f"Open issues: {status.open_issues}",
        f"Open PRs: {status.open_prs}",
    ]
    if status.last_dev_ledger:
        lines.append(f"Last dev-ledger: {status.last_dev_ledger}")
    if status.last_ledger:
        lines.append(f"Last ledger activity: {status.last_ledger}")
    return "\n".join(lines) + "\n"
