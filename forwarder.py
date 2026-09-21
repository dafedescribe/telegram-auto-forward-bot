import asyncio
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient
from telethon.sessions import StringSession


DESTINATION_URL = os.environ.get(
    "DESTINATION_URL",
    "https://example.com/webhook",
)
SESSION_STRING = os.environ.get("SESSION_STRING")
LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", "24"))
MAX_BACKFILL = int(os.environ.get("MAX_BACKFILL", "50"))
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "10"))
LOG_FILE = os.environ.get("LOG_FILE")

_source_raw = os.environ.get("SOURCE_CHATS", "")
SOURCE_CHATS = {int(x.strip()) for x in _source_raw.split(",") if x.strip()}

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def has_email(msg) -> bool:
    """Return True if the message text or caption contains an email address."""
    content = msg.text or msg.message or ""
    return bool(EMAIL_RE.search(content))


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def build_client() -> TelegramClient:
    api_id = int(require_env("API_ID"))
    api_hash = require_env("API_HASH")
    if SESSION_STRING:
        return TelegramClient(StringSession(SESSION_STRING), api_id, api_hash)
    return TelegramClient("forwarder_session", api_id, api_hash)


async def send_batch(client: TelegramClient, messages_by_chat: dict) -> None:
    import httpx

    all_msgs = []
    for chat_id, items in messages_by_chat.items():
        for msg in items:
            all_msgs.append({
                "chat_id": chat_id,
                "chat_title": getattr(msg.chat, "title", None) or str(chat_id),
                "message_id": msg.id,
                "text": msg.text or msg.message or "",
                "date": msg.date.isoformat() if msg.date else None,
                "sender": {
                    "id": msg.sender.id if msg.sender else None,
                    "name": getattr(msg.sender, "first_name", None) or "",
                },
            })

    chunks = [all_msgs[i:i + CHUNK_SIZE] for i in range(0, len(all_msgs), CHUNK_SIZE)]
    logging.info("Sending %d messages in %d chunk(s)...", len(all_msgs), len(chunks))

    async with httpx.AsyncClient(timeout=60) as http:
        for idx, chunk in enumerate(chunks, 1):
            resp = await http.post(DESTINATION_URL, json=chunk)
            resp.raise_for_status()
            logging.info("Chunk %d/%d sent — %s", idx, len(chunks), resp.status_code)
            await asyncio.sleep(1)

    logging.info("Done. Sent %d messages across %d chats.", len(all_msgs), len(messages_by_chat))


async def fetch_recent(client: TelegramClient) -> None:
    since = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    logging.info("Fetching messages since %s from %d chat(s)...", since.isoformat(), len(SOURCE_CHATS))

    messages_by_chat = {}
    for chat_id in SOURCE_CHATS:
        try:
            msgs = await client.get_messages(chat_id, offset_date=since, limit=MAX_BACKFILL)
            if not msgs:
                logging.info("No recent messages in %s", chat_id)
                continue
            msgs = [m for m in msgs if has_email(m)]
            if not msgs:
                logging.info("No messages with email in %s", chat_id)
                continue
            msgs.reverse()
            messages_by_chat[chat_id] = msgs
            logging.info("Fetched %d message(s) with email from %s", len(msgs), chat_id)
        except Exception:
            logging.exception("Failed to fetch from %s", chat_id)

    if messages_by_chat:
        try:
            await send_batch(client, messages_by_chat)
        except Exception:
            logging.exception("Failed to send batch")
    else:
        logging.info("No messages to send.")


async def list_groups() -> None:
    client = build_client()
    async with client:
        await client.start()
        dialogs = await client.get_dialogs()
        print(f"{'ID':<20} {'TYPE':<12} {'TITLE'}")
        print("-" * 80)
        for d in dialogs:
            kind = type(d.entity).__name__
            print(f"{d.id:<20} {kind:<12} {d.name}")
    print(f"\nFound {len(dialogs)} dialogs.")


async def export_session() -> None:
    client = build_client()
    async with client:
        await client.start()
        s = StringSession.save(client.session)
        print("\n--- SESSION_STRING ---")
        print(s)
        print("----------------------\n")


async def main() -> None:
    if not SOURCE_CHATS:
        raise RuntimeError("SOURCE_CHATS is empty")

    client = build_client()
    await client.start()

    try:
        await fetch_recent(client)
    except BaseException:
        logging.exception("Backfill failed")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    kw = {"level": logging.INFO, "format": "%(asctime)s %(levelname)s %(message)s"}
    if LOG_FILE:
        kw["handlers"] = [logging.FileHandler(LOG_FILE)]
    logging.basicConfig(**kw)

    if "--list-groups" in sys.argv[1:]:
        asyncio.run(list_groups())
    elif "--export-session" in sys.argv[1:]:
        asyncio.run(export_session())
    else:
        asyncio.run(main())
