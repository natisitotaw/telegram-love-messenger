"""
storage.py
----------
Reads/writes the message bank (messages.json) and the run state (state.json).

State file schema:
{
    "last_index": 27,          # index (into a stable, sorted view) of the
                                # last message that was sent
    "last_sent": "2026-08-17", # ISO date (YYYY-MM-DD) of the last successful
                                # send, in the configured timezone
    "used_indices": [0, 5, 9], # indices already sent in the CURRENT cycle
                                # (used for the random, no-repeat-until-
                                # exhausted selection mode)
    "cycle": 1                 # increments every time the pool is exhausted
                                # and we start reusing messages
}

Design notes:
- We never mutate messages.json at runtime; it is a read-only content bank.
- All state mutation happens atomically (write to temp file, then replace)
  so a crash mid-write can never corrupt state.json.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List


DEFAULT_STATE = {
    "last_index": -1,
    "last_sent": None,
    "last_slot": None,
    "used_indices": [],
    "cycle": 1,
}


class StorageError(RuntimeError):
    """Raised when message/state files are missing or malformed."""


def load_messages(path: str | Path) -> List[dict]:
    """Load the message bank. Raises StorageError if invalid/empty.

    messages.json is a JSON array of one-day pairs:
        [{"morning": "...", "night": "..."}, ...]
    """
    path = Path(path)
    if not path.exists():
        raise StorageError(f"Messages file not found: {path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise StorageError(f"Messages file is not valid JSON: {exc}") from exc

    if not isinstance(data, list) or not all(
        isinstance(m, dict) and isinstance(m.get("morning"), str) and isinstance(m.get("night"), str)
        for m in data
    ):
        raise StorageError(
            'messages.json must be a JSON array of {"morning": "...", "night": "..."} pairs'
        )

    if len(data) == 0:
        raise StorageError("messages.json is empty; add at least one pair")

    return data


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically to avoid corrupting the file on interruption."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        # Best-effort cleanup of the temp file if something went wrong.
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


@dataclass
class State:
    last_index: int = -1
    last_sent: str | None = None
    last_slot: str | None = None
    used_indices: List[int] = field(default_factory=list)
    cycle: int = 1

    @classmethod
    def load(cls, path: str | Path) -> "State":
        path = Path(path)
        if not path.exists():
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError as exc:
            raise StorageError(f"state.json is not valid JSON: {exc}") from exc

        merged = {**DEFAULT_STATE, **raw}
        return cls(
            last_index=merged.get("last_index", -1),
            last_sent=merged.get("last_sent"),
            last_slot=merged.get("last_slot"),
            used_indices=list(merged.get("used_indices", [])),
            cycle=merged.get("cycle", 1),
        )

    def save(self, path: str | Path) -> None:
        _atomic_write_json(Path(path), asdict(self))
