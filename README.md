# Telegram Daily Love Messenger 💌

Automatically sends your sister one unique heartfelt message every day, from
**your own personal Telegram account** (not a bot), via Telethon +
GitHub Actions. No server, no local computer needed after setup — 100% free.

---

## How it works

- `messages.json` holds your bank of messages (130 included, expandable to 365+).
- `state.json` tracks which messages have been used and when the last one
  was sent, so nothing repeats until the whole bank is exhausted, and the
  bot never double-sends on the same day.
- A GitHub Actions workflow runs `app.py` every day at **8:00 AM
  Africa/Addis_Ababa**, sends the next message via Telethon, then commits
  the updated `state.json` back to the repo so the next run knows where it
  left off.

---

## 1. Prerequisites

- A GitHub account (free tier is enough).
- Python 3.12+ and [uv](https://docs.astral.sh/uv/) installed locally, just
  for the one-time setup steps below.
- Your own Telegram account (the one you'll send messages *from*).
- Your sister's Telegram `@username` (or numeric user ID) — she must have
  started a chat with you at least once, or have an open username, so
  Telethon can resolve her as an entity.

Install uv if you don't have it:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## 2. Get Telegram API credentials

1. Go to <https://my.telegram.org> and log in with your phone number.
2. Open **API Development Tools**.
3. Create an app (any name/description works). You'll get an `api_id` and
   `api_hash` — copy both.

---

## 3. Clone and configure locally

```bash
git clone <your-fork-url> telegram-love-messenger
cd telegram-love-messenger
uv venv
uv pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and fill in:
```
API_ID=your_api_id
API_HASH=your_api_hash
SISTER_USERNAME=her_username_without_at_sign
```
Leave `STRING_SESSION` empty for now — the next step generates it.

---

## 4. Generate your StringSession (one time, local only)

This step logs you into Telegram interactively (phone number → login code →
2FA password if enabled) and prints a `StringSession`, which lets the app
authenticate as you **without** needing your phone again.

```bash
uv run python auth.py
```

Copy the printed string. **Never run `auth.py` in GitHub Actions** — it's
interactive and has no place in automation. **Never commit this string to
the repo** — it's equivalent to your Telegram login credentials.

---

## 5. Push the repo to GitHub

```bash
git init   # if not already a git repo
git add .
git commit -m "Initial commit: Telegram Daily Love Messenger"
git branch -M main
git remote add origin https://github.com/<you>/telegram-love-messenger.git
git push -u origin main
```

`.env` is git-ignored, so your secrets stay off GitHub as plaintext — they go
into encrypted Secrets instead (next step).

---

## 6. Add GitHub Secrets

In your repo: **Settings → Secrets and variables → Actions → New repository
secret**. Add each of these:

| Secret name        | Value                                      |
|---------------------|---------------------------------------------|
| `API_ID`            | Your numeric API ID                        |
| `API_HASH`          | Your API hash                              |
| `STRING_SESSION`    | The string printed by `auth.py`            |
| `SISTER_USERNAME`   | Her Telegram username (no `@`) or user ID  |

---

## 7. Enable the workflow

The workflow file is already at `.github/workflows/daily.yml`. It:

- Runs every day at **05:00 UTC = 08:00 Africa/Addis_Ababa** (EAT has no
  DST, so this offset is fixed year-round).
- Can be triggered manually from the **Actions** tab (`workflow_dispatch`),
  with an optional `dry_run` toggle for safe testing.
- Installs dependencies with `uv`.
- Runs `app.py`, which picks and sends the next message.
- Commits the updated `state.json` / `send_log.txt` back to the repo so
  progress persists between runs (GitHub Actions runners are ephemeral,
  so without this commit-back step, state would reset every day).

To test it immediately instead of waiting for 8 AM: go to **Actions → Daily
Love Message → Run workflow**, optionally set `dry_run: true` for a safe
test that doesn't actually message your sister, then `dry_run: false` for
the real thing.

---

## 8. Adding a Sunday image (optional)

Drop a few `.jpg` / `.png` / `.gif` / `.webp` files into an `images/`
folder at the repo root and commit them. Every Sunday, the app will
randomly pick one and attach it to that day's message. If the folder is
empty or missing, it just sends text as usual — no error.

---

## Configuration reference (`.env` / GitHub Secrets)

| Variable          | Default                | Notes                                                          |
|-------------------|-------------------------|------------------------------------------------------------------|
| `API_ID`           | —                       | Required. From my.telegram.org                                  |
| `API_HASH`         | —                       | Required. From my.telegram.org                                  |
| `STRING_SESSION`   | —                       | Required. Generated by `auth.py`                                 |
| `SISTER_USERNAME`  | —                       | Required. Recipient username or numeric ID                       |
| `TIMEZONE`         | `Africa/Addis_Ababa`    | IANA tz used for the "already sent today" and Sunday checks      |
| `SELECTION_MODE`   | `random`                | `random` or `sequential`; both guarantee no repeats until exhausted |
| `SUNDAY_IMAGE`     | `true`                  | Attach a random image from `images/` every Sunday                |
| `DRY_RUN`          | `false`                 | If `true`, simulates the whole pipeline without calling Telegram |
| `MESSAGES_FILE`    | `messages.json`         | Path to the message bank                                          |
| `STATE_FILE`       | `state.json`            | Path to the persisted state                                       |
| `IMAGES_DIR`       | `images`                | Folder to pick Sunday images from                                  |
| `LOG_FILE`         | `send_log.txt`          | Append-only send log                                               |

To change the send time, edit the `cron` line in
`.github/workflows/daily.yml` (GitHub Actions cron is always UTC — convert
your desired Addis Ababa time by subtracting 3 hours).

---

## Reliability details

- **Duplicate-send guard**: `app.py` checks `state.last_sent` against
  today's date (in `TIMEZONE`) before doing anything else, and exits
  cleanly (code `2`) if a message already went out today — so a manual
  re-run or an accidental double-trigger never sends twice.
- **Retries**: Telegram sends retry up to 3 times with exponential backoff,
  and correctly respect `FloodWaitError` by sleeping the exact duration
  Telegram requests.
- **No-repeat-until-exhausted**: `used_indices` tracks every message sent
  in the current cycle; once all messages are used, the cycle resets and
  `cycle` increments, so the whole bank cycles indefinitely (130 messages
  included, easily expandable to 365+ by adding more entries to
  `messages.json`).
- **Atomic state writes**: `state.json` is written to a temp file and
  swapped in with `os.replace`, so a crash mid-write can't corrupt it.
- **Exit codes**: `0` success, `1` config error, `2` already sent today,
  `3` storage error, `4` Telegram send failure after retries — useful for
  monitoring/alerting on workflow failures.

---

## Project structure

```
telegram-love-messenger/
├── app.py                      # Main entrypoint, run daily by CI
├── auth.py                     # One-time local StringSession generator
├── messages.json                # 130 heartfelt messages (expand freely)
├── state.json                   # Persisted progress (auto-updated)
├── requirements.txt
├── .env.example
├── utils/
│   ├── scheduler.py             # Message selection + date/day logic
│   ├── storage.py                # messages.json / state.json I/O
│   └── telegram_client.py        # Telethon wrapper with retries
└── .github/workflows/daily.yml   # Cron schedule + CI job
```

---

## Local testing

```bash
# Safe dry run - won't actually message anyone
DRY_RUN=true uv run python app.py

# Real send, for a final check before relying on the cron
uv run python app.py
```

---

## Security notes

- `STRING_SESSION` grants full access to your Telegram account — store it
  only in GitHub Secrets, never in code or plaintext files that get committed.
- You can revoke a session anytime from Telegram: **Settings → Devices**,
  then terminate the corresponding session.
- `.env` and `*.session` files are git-ignored by default.
