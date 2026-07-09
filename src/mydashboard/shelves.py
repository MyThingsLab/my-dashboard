from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path


@dataclass(frozen=True)
class Shelf:
    key: str
    label: str
    repos: tuple[str, ...]


@dataclass(frozen=True)
class Shelving:
    shelves: tuple[Shelf, ...]

    def classify(self, repos: list[str]) -> tuple[dict[str, list[str]], list[str]]:
        """Split ``repos`` into {shelf label: repo names} plus the unshelved leftover."""
        mapped: dict[str, list[str]] = {shelf.label: [] for shelf in self.shelves}
        known: dict[str, str] = {
            name: shelf.label for shelf in self.shelves for name in shelf.repos
        }
        unshelved: list[str] = []
        for repo in repos:
            label = known.get(repo)
            if label is None:
                unshelved.append(repo)
            else:
                mapped[label].append(repo)
        return mapped, unshelved


def load_shelves(path: str | Path | None = None) -> Shelving:
    if path is not None:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = resources.files("mydashboard").joinpath("shelves.toml").read_text(encoding="utf-8")
    obj = tomllib.loads(text)
    shelves = tuple(
        Shelf(key=key, label=body["label"], repos=tuple(body.get("repos", [])))
        for key, body in obj.get("shelves", {}).items()
    )
    return Shelving(shelves=shelves)
