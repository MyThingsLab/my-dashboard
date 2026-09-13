from __future__ import annotations

from pathlib import Path

from mydashboard.shelves import load_shelves

FIXTURE = """
[shelves.harness]
label = "Harness"
what = "runs the cycle"
repos = ["my-a", "my-b"]

[shelves.casual]
label = "Casual"
repos = ["my-c"]
"""


def test_classify_splits_mapped_and_unshelved(tmp_path: Path) -> None:
    path = tmp_path / "shelves.toml"
    path.write_text(FIXTURE, encoding="utf-8")
    shelving = load_shelves(path)

    mapped, unshelved = shelving.classify(["my-a", "my-b", "my-c", "my-mystery"])

    assert mapped == {"Harness": ["my-a", "my-b"], "Casual": ["my-c"]}
    assert unshelved == ["my-mystery"]
    assert shelving.taglines() == {"Harness": "runs the cycle"}  # shelves without `what` omitted


def test_load_default_shelves_covers_known_tools() -> None:
    shelving = load_shelves()
    mapped, unshelved = shelving.classify(["my-things-core", "my-server", "my-idea"])
    assert unshelved == []
    assert mapped["Development harness"] == ["my-things-core"]
    assert mapped["Services"] == ["my-server"]
    assert mapped["Casual development"] == ["my-idea"]


def test_governed_repos_are_the_union_of_governed_shelves(tmp_path: Path) -> None:
    path = tmp_path / "shelves.toml"
    path.write_text(
        '[shelves.a]\nlabel = "A"\ngoverned = true\nrepos = ["my-a", "my-b"]\n'
        '[shelves.b]\nlabel = "B"\nrepos = ["my-c"]\n',
        encoding="utf-8",
    )
    assert load_shelves(path).governed_repos() == frozenset({"my-a", "my-b"})


def test_shelves_default_to_ungoverned(tmp_path: Path) -> None:
    path = tmp_path / "shelves.toml"
    path.write_text(FIXTURE, encoding="utf-8")
    # Nothing is governed by accident — a shelf has to say so.
    assert load_shelves(path).governed_repos() == frozenset()


def test_shipped_shelves_govern_the_harness_but_not_coursework() -> None:
    governed = load_shelves().governed_repos()
    assert {"my-things-core", "my-fleet", "my-coder", "my-architect"} <= governed
    assert governed.isdisjoint({"study", "my-idea"})
