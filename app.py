"""
app.py
------
Main entrypoint. Executed once per day by the GitHub Actions cron workflow
(and can be run manually / locally for testing).

Flow:
    1. Load configuration from environment (.env locally, GitHub Secrets in CI).
    2. Load the message bank and current state.
    3. Guard against double-sends on the same day.
    4. Pick the next unused message (random or sequential, no repeats
       until the whole pool has been used).
    5. On Sundays, optionally attach a random cute image.
    6. Send via Telegram (personal account, Telethon), with retries.
    7. Persist updated state and log the result.

Exit codes:
    0  - success (message sent, or correctly skipped as already-sent-today
         when DRY_RUN reporting requires no action)
    1  - configuration error
    2  - already sent today (not an error, but nothing to do)
    3  - message bank / state storage error
    4  - Telegram send failure after retries
"""

from __future__ import annotations

import logging
import os
import random
import sys
from pathlib import Path

from dotenv import load_dotenv

from utils.storage import State, load_messages, StorageError
from utils.scheduler import already_sent_today, pick_next_index, is_sunday, today_in_tz
from utils.telegram_client import send_message, TelegramSendError


BASE_DIR = Path(__file__).resolve().parent


def setup_logging(log_file: str) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(BASE_DIR / log_file, encoding="utf-8"),
        ],
    )


def get_env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def pick_random_image(images_dir: Path) -> str | None:
    """Return a random image file path from images_dir, or None if empty/missing."""
    if not images_dir.exists():
        return None
    exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    candidates = [p for p in images_dir.iterdir() if p.suffix.lower() in exts]
    if not candidates:
        return None
    return str(random.choice(candidates))


def main() -> int:
    load_dotenv(BASE_DIR / ".env")

    log_file = os.getenv("LOG_FILE", "send_log.txt")
    setup_logging(log_file)
    logger = logging.getLogger("love_messenger")

    # ---- 1. Configuration ----
    api_id_raw = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")
    string_session = os.getenv("STRING_SESSION")
    recipient = os.getenv("SISTER_USERNAME")
    tz_name = os.getenv("TIMEZONE", "Africa/Addis_Ababa")
    selection_mode = os.getenv("SELECTION_MODE", "random").lower()
    sunday_image = get_env_bool("SUNDAY_IMAGE", True)
    dry_run = get_env_bool("DRY_RUN", False)
    slot = os.getenv("SLOT", "morning").strip().lower()
    if slot not in ("morning", "night"):
        logger.error("SLOT must be 'morning' or 'night', got: %r", slot)
        return 1
    messages_file = BASE_DIR / os.getenv("MESSAGES_FILE", "messages.json")
    state_file = BASE_DIR / os.getenv("STATE_FILE", "state.json")
    images_dir = BASE_DIR / os.getenv("IMAGES_DIR", "images")

    missing = [
        name
        for name, val in [
            ("API_ID", api_id_raw),
            ("API_HASH", api_hash),
            ("STRING_SESSION", string_session),
            ("SISTER_USERNAME", recipient),
        ]
        if not val
    ]
    if missing:
        logger.error("Missing required environment variables: %s", ", ".join(missing))
        return 1

    try:
        api_id = int(api_id_raw)
    except ValueError:
        logger.error("API_ID must be an integer, got: %r", api_id_raw)
        return 1

    # ---- 2. Load message bank + state ----
    try:
        messages = load_messages(messages_file)
        state = State.load(state_file)
    except StorageError as exc:
        logger.error("Storage error: %s", exc)
        return 3

    logger.info(
        "Loaded %d messages | cycle=%d | used_this_cycle=%d",
        len(messages),
        state.cycle,
        len(state.used_indices),
    )

    # ---- 3. Duplicate-send guard (per slot: morning/night) ----
    if already_sent_today(state, tz_name, slot=slot):
        logger.info(
            "%s message already sent today (%s, tz=%s). Skipping.",
            slot.capitalize(),
            state.last_sent,
            tz_name,
        )
        return 2

    # ---- 4. Pick this day's pair (morning picks a new pair; night reuses
    #          the same pair morning used, so both texts come from one day) ----
    if slot == "night" and already_sent_today(state, tz_name, slot="morning"):
        index = state.last_index
    else:
        index = pick_next_index(len(messages), state, mode=selection_mode)
    text = messages[index][slot]

    # ---- 5. Sunday image attachment ----
    image_path = None
    if sunday_image and is_sunday(tz_name):
        image_path = pick_random_image(images_dir)
        if image_path:
            logger.info("Today is Sunday - attaching image: %s", image_path)
        else:
            logger.info(
                "Today is Sunday but no images found in %s - sending text only.",
                images_dir,
            )

    # ---- 6. Send ----
    try:
        send_message(
            api_id=api_id,
            api_hash=api_hash,
            string_session=string_session,
            recipient=recipient,
            text=text,
            image_path=image_path,
            dry_run=dry_run,
            max_retries=3,
        )
    except TelegramSendError as exc:
        logger.error("Failed to send message: %s", exc)
        return 4

    # ---- 7. Persist state ----
    today_str = today_in_tz(tz_name).isoformat()
    state.last_index = index
    state.last_sent = today_str
    state.last_slot = slot
    if slot == "night":
        state.used_indices = sorted(set(state.used_indices) | {index})

    try:
        state.save(state_file)
    except Exception as exc:  # noqa: BLE001
        # The message already went out; a state-save failure shouldn't be
        # reported as a send failure, but it MUST be visible in the logs
        # since a duplicate could be sent tomorrow if unresolved.
        logger.error(
            "Message sent, but FAILED to persist state.json: %s. "
            "Investigate before the next scheduled run.",
            exc,
        )
        return 3

    mode_note = " [DRY RUN]" if dry_run else ""
    logger.info(
        "Success%s: sent message #%d/%d to %s on %s (cycle %d).",
        mode_note,
        index,
        len(messages),
        recipient,
        today_str,
        state.cycle,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
