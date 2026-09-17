import threading
import time
from pathlib import Path

from mydashboard.ask import AskStore, wait_for_decision


def test_create_then_decide_round_trips(tmp_path: Path) -> None:
    store = AskStore(tmp_path / "asks")
    ask = store.create(action_kind="pr-merge", payload={"pr": 5}, timeout=30)
    assert ask.status == "pending"
    assert store.get(ask.id).status == "pending"

    assert store.decide(ask.id, "allow") is True
    assert store.get(ask.id).status == "allow"


def test_deciding_twice_the_second_time_fails(tmp_path: Path) -> None:
    store = AskStore(tmp_path / "asks")
    ask = store.create(action_kind="k", payload={}, timeout=30)
    assert store.decide(ask.id, "allow") is True
    assert store.decide(ask.id, "deny") is False  # already decided, first decision stands
    assert store.get(ask.id).status == "allow"


def test_deciding_an_unknown_id_fails(tmp_path: Path) -> None:
    store = AskStore(tmp_path / "asks")
    assert store.decide("nope", "allow") is False


def test_pending_excludes_decided_and_expired(tmp_path: Path) -> None:
    store = AskStore(tmp_path / "asks")
    live = store.create(action_kind="k", payload={}, timeout=30)
    decided = store.create(action_kind="k", payload={}, timeout=30)
    store.decide(decided.id, "deny")
    expired = store.create(action_kind="k", payload={}, timeout=-1)

    assert {a.id for a in store.pending()} == {live.id}
    assert expired.id not in {a.id for a in store.pending()}


def test_wait_for_decision_returns_true_on_allow(tmp_path: Path) -> None:
    store = AskStore(tmp_path / "asks")
    ask = store.create(action_kind="k", payload={}, timeout=30)

    def decide_soon() -> None:
        time.sleep(0.05)
        store.decide(ask.id, "allow")

    threading.Thread(target=decide_soon).start()
    assert wait_for_decision(store, ask.id, timeout=5, poll_seconds=0.01) is True


def test_wait_for_decision_times_out_to_deny(tmp_path: Path) -> None:
    store = AskStore(tmp_path / "asks")
    ask = store.create(action_kind="k", payload={}, timeout=0.05)
    assert wait_for_decision(store, ask.id, timeout=0.2, poll_seconds=0.01) is False
    assert store.get(ask.id).status == "deny"
