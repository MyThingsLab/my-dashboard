from __future__ import annotations

from pathlib import Path

from mydashboard.shelves import load_shelves

FIXTURE = """
[shelves.harness]
label = "Harness"
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


def test_load_default_shelves_covers_known_tools() -> None:
    shelving = load_shelves()
    mapped, unshelved = shelving.classify(["my-things-core", "my-server", "my-idea"])
    assert unshelved == []
    assert mapped["Development harness"] == ["my-things-core"]
    assert mapped["Services"] == ["my-server"]
    assert mapped["Casual development"] == ["my-idea"]
