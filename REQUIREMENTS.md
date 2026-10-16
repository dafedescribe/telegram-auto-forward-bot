# Telegram Auto-Forwarder (email-filtered backfill → webhook)

## Goal

Hourly backfill Telegram source chats for messages containing an email
address and POST them as JSON chunks to `DESTINATION_URL`.

Uses a Telethon **user account** (bots can't read other bots / all group
messages via Bot API). Use only for groups/channels you may monitor.

## Requirements

- Python 3.12+ (Actions uses 3.12)
- Telegram account + API credentials from `https://my.telegram.org`
- Access to source chats from that account
- A webhook URL that accepts `POST` JSON arrays

## Setup (local)

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in values (never commit .env)
python forwarder.py --check-config
python forwarder.py --list-groups     # find numeric chat IDs
python forwarder.py --export-session  # prints SESSION_STRING (paste into .env)
python forwarder.py --dry-run         # fetch only, no POST
python forwarder.py                   # real backfill + POST
```

## Configuration (env)

- `API_ID`, `API_HASH` — from my.telegram.org (required)
- `SESSION_STRING` — from `--export-session` (required for headless runs)
- `SOURCE_CHATS` — comma-separated numeric IDs, e.g. `-100123,-100456` (required)
- `DESTINATION_URL` — `https://…` webhook (required)
- `LOOKBACK_HOURS=24`, `MAX_BACKFILL=50`, `CHUNK_SIZE=10`, `LOG_FILE=` (optional)
- `REMOTE_ONLY=1` — forward only remote/hybrid roles (matches `remote`,
  `work from home`, `WFH`, `telecommute`, `hybrid`); `0` forwards everything
  with an email (optional, default `0`)

Exit codes: `0` ok, `2` config error, `1` runtime/send failure.

## GitHub Actions (primary, hourly)

Workflow `.github/workflows/forwarder.yml`: cron `0 * * * *` + manual
`workflow_dispatch`, `LOOKBACK_HOURS=1`.

Secrets needed: `API_ID`, `API_HASH`, `SESSION_STRING`, `SOURCE_CHATS`,
`DESTINATION_URL`.

Test order: run workflow manually → `--check-config` step must go green →
real run POSTs. POSTs retry 3x with backoff; send failure turns the job red.

## Render (secondary)

`render.yaml` is a `cron` (`0 * * * *`), one-shot `python forwarder.py`.
Set the same env vars in Render dashboard (`sync: false`).

## Tests

```bash
pytest -q
```

Covers: email filter, chat-ID parsing, config validation, chunking.

## Notes

- Only email-containing messages are forwarded.
- Private chats need prior access + numeric IDs.
- Do not forward private content without permission.
