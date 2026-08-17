"""
auth.py
-------
ONE-TIME, LOCAL-ONLY script to log in to your personal Telegram account and
generate a Telethon StringSession.

This is interactive (it will ask for your phone number, the login code
Telegram sends you, and your 2FA password if you have one enabled). It must
NEVER be run inside GitHub Actions - it has no place in the automated
pipeline, and CI has no way to answer the interactive prompts anyway.

Usage:
    uv run python auth.py
    # or: python auth.py

What it does:
    1. Reads API_ID / API_HASH from your local .env file.
    2. Opens an interactive Telethon login flow.
    3. Prints a StringSession you paste into the STRING_SESSION GitHub
       Secret (Settings -> Secrets and variables -> Actions -> New secret).

Security notes:
    - The printed StringSession is equivalent to your Telegram login.
      Anyone who has it can access your account. Treat it like a password:
      only ever store it in GitHub Secrets (encrypted at rest), never commit
      it to the repo, never paste it anywhere public.
    - You can revoke it at any time from Telegram: Settings -> Devices ->
      terminate the corresponding session.
"""

from __future__ import annotations

import asyncio
import os
import sys

# Python 3.10+ deprecated (and 3.14 removed) the implicit "create a loop for
# me" behavior that telethon.sync depends on. Explicitly create and set one
# before telethon.sync is imported, since it grabs/creates a loop at import
# time.
asyncio.set_event_loop(asyncio.new_event_loop())

from dotenv import load_dotenv
from telethon.sync import TelegramClient
from telethon.sessions import StringSession


def main() -> int:
    load_dotenv()

    api_id_raw = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")

    if not api_id_raw or not api_hash:
        print(
            "ERROR: API_ID and API_HASH must be set in your local .env file.\n"
            "Get them from https://my.telegram.org -> API Development Tools.",
            file=sys.stderr,
        )
        return 1

    try:
        api_id = int(api_id_raw)
    except ValueError:
        print("ERROR: API_ID must be an integer.", file=sys.stderr)
        return 1

    print("Starting interactive Telegram login...")
    print("(You'll be asked for your phone number, then the login code "
          "Telegram sends you, and your 2FA password if enabled.)\n")

    with TelegramClient(StringSession(), api_id, api_hash) as client:
        session_string = client.session.save()

    print("\n" + "=" * 70)
    print("SUCCESS! Your StringSession has been generated.")
    print("=" * 70)
    print(
        "\nCopy the value below and save it as a GitHub Secret named "
        "STRING_SESSION:\n"
    )
    print(session_string)
    print(
        "\nGitHub: repo -> Settings -> Secrets and variables -> Actions -> "
        "New repository secret\n"
    )
    print(
        "Do NOT commit this value to the repository or share it with "
        "anyone - it grants full access to your Telegram account."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
