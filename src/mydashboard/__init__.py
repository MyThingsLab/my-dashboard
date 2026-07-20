from __future__ import annotations

from importlib.metadata import version

from mydashboard.dashboard import Dashboard, RenderResult, StatusResult
from mydashboard.fleet import RepoStatus, gather_status, list_org_repos
from mydashboard.render import render_org_page, render_repo_card
from mydashboard.shelves import Shelf, Shelving, load_shelves

__version__ = version("my-dashboard")

__all__ = [
    "Dashboard",
    "RenderResult",
    "StatusResult",
    "RepoStatus",
    "gather_status",
    "list_org_repos",
    "render_org_page",
    "render_repo_card",
    "Shelf",
    "Shelving",
    "load_shelves",
]
