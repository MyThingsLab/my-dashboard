from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_POLL_SECONDS = 1.0


@dataclass(frozen=True)
class Ask:
    id: str
    action_kind: str
    payload: dict[str, Any]
    created_at: float
    deadline: float
    status: str = "pending"  # "pending" | "allow" | "deny"


class AskStore:
    # The `$MYTHINGS_ASK_CMD` contract (myguard.ask.SubprocessAsk) is
    # exit-code-only: one process writes a pending ask and blocks, another
    # process (this dashboard's serve loop, driven by a human click) flips
    # its status. A JSON file per ask is the simplest thing that lets two
    # unrelated processes rendezvous without a socket or a database.
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, ask_id: str) -> Path:
        return self.root / f"{ask_id}.json"

    def create(self, *, action_kind: str, payload: dict[str, Any], timeout: float) -> Ask:
        now = time.time()
        ask = Ask(
            id=uuid.uuid4().hex,
            action_kind=action_kind,
            payload=payload,
            created_at=now,
            deadline=now + timeout,
        )
        self._write(ask)
        return ask

    def _write(self, ask: Ask) -> None:
        self._path(ask.id).write_text(json.dumps(asdict(ask)), encoding="utf-8")

    def get(self, ask_id: str) -> Ask | None:
        path = self._path(ask_id)
        if not path.exists():
            return None
        try:
            return Ask(**json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, TypeError):
            return None

    def decide(self, ask_id: str, decision: str) -> bool:
        ask = self.get(ask_id)
        if ask is None or ask.status != "pending" or decision not in ("allow", "deny"):
            return False
        self._write(Ask(**{**asdict(ask), "status": decision}))
        return True

    def pending(self) -> list[Ask]:
        out = []
        for path in sorted(self.root.glob("*.json")):
            try:
                ask = Ask(**json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, TypeError, OSError):
                continue
            if ask.status == "pending" and ask.deadline > time.time():
                out.append(ask)
        return out


def wait_for_decision(
    store: AskStore, ask_id: str, *, timeout: float, poll_seconds: float = _POLL_SECONDS
) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        ask = store.get(ask_id)
        if ask is None:
            return False
        if ask.status in ("allow", "deny"):
            return ask.status == "allow"
        time.sleep(poll_seconds)
    store.decide(ask_id, "deny")
    return False
