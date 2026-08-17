"""
scheduler.py
------------
Pure logic for:
  - deciding whether today's message has already been sent (duplicate guard)
  - picking the next message (random-without-repeat, or sequential)
  - deciding whether today is "Sunday image day"

No Telegram or filesystem I/O lives here (aside from the State object passed
in) so this module is trivial to unit test.
"""

from __future__ import annotations

import random
from datetime import datetime, date
from zoneinfo import ZoneInfo

from utils.storage import State


def today_in_tz(tz_name: str) -> date:
    """Return today's date in the given IANA timezone."""
    return datetime.now(ZoneInfo(tz_name)).date()


def already_sent_today(state: State, tz_name: str, slot: str | None = None) -> bool:
    """True if the given slot ('morning'/'night') was already sent today.

    If slot is None, True if *any* message was sent today (legacy behavior).
    """
    if not state.last_sent:
        return False
    try:
        last_sent_date = date.fromisoformat(state.last_sent)
    except ValueError:
        # Corrupt/unexpected format - treat as "not sent" so we don't get
        # stuck forever, but this should never happen with atomic writes.
        return False
    if last_sent_date != today_in_tz(tz_name):
        return False
    if slot is None:
        return True
    return state.last_slot == slot


def pick_next_index(
    total_messages: int,
    state: State,
    mode: str = "random",
) -> int:
    """
    Choose the index of the next message to send, honoring the
    "no repeat until the whole pool is exhausted" rule.

    - "random": pick uniformly among indices not yet used this cycle.
    - "sequential": pick last_index + 1, wrapping around.

    When the pool is exhausted, the cycle resets (used_indices cleared,
    cycle counter incremented) and a fresh pick is made from the full pool.
    """
    if total_messages <= 0:
        raise ValueError("total_messages must be > 0")

    # Reset cycle if we've used every message already.
    if len(set(state.used_indices)) >= total_messages:
        state.used_indices = []
        state.cycle += 1

    if mode == "sequential":
        candidate = (state.last_index + 1) % total_messages
        # Skip already-used indices in this cycle (shouldn't normally
        # trigger, but keeps sequential mode consistent with the
        # no-repeat-until-exhausted contract).
        seen = set(state.used_indices)
        attempts = 0
        while candidate in seen and attempts < total_messages:
            candidate = (candidate + 1) % total_messages
            attempts += 1
        return candidate

    # Default: random mode.
    available = [i for i in range(total_messages) if i not in set(state.used_indices)]
    if not available:
        # Defensive fallback; the cycle-reset above should prevent this.
        available = list(range(total_messages))
    return random.choice(available)


def is_sunday(tz_name: str) -> bool:
    """True if today (in the given timezone) is a Sunday."""
    return today_in_tz(tz_name).weekday() == 6  # Monday=0 ... Sunday=6
