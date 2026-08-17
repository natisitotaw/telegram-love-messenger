"""
telegram_client.py
-------------------
Thin wrapper around Telethon for sending a message (optionally with an
image attachment) from a *personal* Telegram account, using a pre-generated
StringSession. Includes retry-with-backoff for transient failures.

This module deliberately does NOT prompt for login (no phone number /
verification code). It only ever calls `client.start()` with an existing
StringSession, which is designed to run non-interactively in CI. If the
session is invalid/expired, it raises instead of hanging on a prompt.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError,
    RPCError,
)

logger = logging.getLogger("love_messenger")


class TelegramSendError(RuntimeError):
    """Raised after all retry attempts have been exhausted."""


async def _build_client(api_id: int, api_hash: str, string_session: str) -> TelegramClient:
    client = TelegramClient(StringSession(string_session), api_id, api_hash)
    await client.connect()

    if not await client.is_user_authorized():
        await client.disconnect()
        raise TelegramSendError(
            "StringSession is invalid or expired. Re-run auth.py locally to "
            "generate a fresh session and update the STRING_SESSION secret."
        )
    return client


async def send_message_async(
    api_id: int,
    api_hash: str,
    string_session: str,
    recipient: str,
    text: str,
    image_path: Optional[str] = None,
    dry_run: bool = False,
    max_retries: int = 3,
) -> None:
    """
    Send `text` (Markdown-formatted) to `recipient`, optionally attaching
    an image. Retries up to `max_retries` times on transient errors, with
    exponential backoff. Respects Telegram's FloodWait by sleeping the
    required duration before retrying.
    """
    if dry_run:
        logger.info("[DRY RUN] Would send to %s: %s", recipient, text)
        if image_path:
            logger.info("[DRY RUN] Would attach image: %s", image_path)
        return

    last_exc: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        client: Optional[TelegramClient] = None
        try:
            client = await _build_client(api_id, api_hash, string_session)
            entity = await client.get_entity(recipient)

            if image_path:
                await client.send_file(
                    entity,
                    image_path,
                    caption=text,
                    parse_mode="md",
                )
            else:
                await client.send_message(
                    entity,
                    text,
                    parse_mode="md",
                )

            logger.info(
                "Message sent successfully to %s on attempt %d/%d",
                recipient,
                attempt,
                max_retries,
            )
            return

        except FloodWaitError as exc:
            logger.warning(
                "FloodWait: Telegram asked us to wait %ds (attempt %d/%d)",
                exc.seconds,
                attempt,
                max_retries,
            )
            last_exc = exc
            await asyncio.sleep(exc.seconds + 1)

        except RPCError as exc:
            logger.warning(
                "Telegram RPC error on attempt %d/%d: %s", attempt, max_retries, exc
            )
            last_exc = exc
            await asyncio.sleep(min(2 ** attempt, 30))

        except Exception as exc:  # noqa: BLE001 - we want to retry broadly
            logger.warning(
                "Unexpected error on attempt %d/%d: %s", attempt, max_retries, exc
            )
            last_exc = exc
            await asyncio.sleep(min(2 ** attempt, 30))

        finally:
            if client is not None:
                await client.disconnect()

    raise TelegramSendError(
        f"Failed to send message after {max_retries} attempts: {last_exc}"
    )


def send_message(
    api_id: int,
    api_hash: str,
    string_session: str,
    recipient: str,
    text: str,
    image_path: Optional[str] = None,
    dry_run: bool = False,
    max_retries: int = 3,
) -> None:
    """Synchronous convenience wrapper around send_message_async."""
    asyncio.run(
        send_message_async(
            api_id=api_id,
            api_hash=api_hash,
            string_session=string_session,
            recipient=recipient,
            text=text,
            image_path=image_path,
            dry_run=dry_run,
            max_retries=max_retries,
        )
    )
