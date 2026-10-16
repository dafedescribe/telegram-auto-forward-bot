import asyncio
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
REMOTE_RE = re.compile(r"\bremote\b|work\s*from\s*home|work-from-home|\bwfh\b|telecommut", re.IGNORECASE)
HYBRID_RE = re.compile(r"\bhybrid\b", re.IGNORECASE)


def _message_text(msg) -> str:
    return (getattr(msg, "text", None) or getattr(msg, "message", None)) or ""


def has_email(msg) -> bool:
    """Return True if the message text or caption contains an email address."""
    return bool(EMAIL_RE.search(_message_text(msg)))


def is_remote(msg_or_text) -> bool:
    """Return True if the text signals a remote (or hybrid) role.

    Strict on purpose: bare 'virtual' is excluded ('virtual classroom'
    skills, 'Virtual Assistant' titles with a physical location).
    """
    text = msg_or_text if isinstance(msg_or_text, str) else _message_text(msg_or_text)
    return bool(REMOTE_RE.search(text or "") or HYBRID_RE.search(text or ""))


def parse_source_chats(raw: str) -> set:
    """Parse comma-separated chat IDs into a set of ints. Raises ValueError on garbage."""
    chats = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            chats.add(int(part))
        except ValueError:
            raise ValueError(f"Invalid chat ID in SOURCE_CHATS: {part!r} (expected integer)")
    return chats


def chunk_messages(items: list, size: int) -> list:
    size = max(1, int(size))
    return [items[i:i + size] for i in range(0, len(items), size)]


def _get(env, name: str, default=None):
    if isinstance(env, dict):
        return env.get(name, default)
    return os.environ.get(name, default)


def validate_config(env=None) -> dict:
    """Validate env mapping and return a typed config dict. Raises RuntimeError."""
    src = env if isinstance(env, dict) else dict(os.environ)

    def req(name: str) -> str:
        value = src.get(name) or os.environ.get(name) if isinstance(env, dict) else os.environ.get(name)
        # When env dict is passed, prefer it; fall back to os.environ for convenience.
        if isinstance(env, dict):
            value = env.get(name, os.environ.get(name))
        if not value:
            raise RuntimeError(f"Missing required environment variable: {name}")
        return value

    api_id_raw = req("API_ID")
    try:
        api_id = int(str(api_id_raw).strip())
    except ValueError:
        raise RuntimeError("API_ID must be an integer")

    api_hash = req("API_HASH").strip()
    session_string = (src.get("SESSION_STRING") or os.environ.get("SESSION_STRING") or "").strip()
    if not session_string:
        raise RuntimeError("Missing required environment variable: SESSION_STRING")

    source_raw = req("SOURCE_CHATS")
    try:
        source_chats = parse_source_chats(source_raw)
    except ValueError as exc:
        raise RuntimeError(str(exc))
    if not source_chats:
        raise RuntimeError("SOURCE_CHATS is empty (expected comma-separated chat IDs)")

    destination_url = req("DESTINATION_URL").strip()
    parsed = urlparse(destination_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise RuntimeError("DESTINATION_URL must be a valid http(s) URL")

    def _int(name: str, default: int) -> int:
        raw = src.get(name, os.environ.get(name, default))
        try:
            return int(str(raw).strip())
        except (ValueError, AttributeError):
            raise RuntimeError(f"{name} must be an integer, got {raw!r}")

    lookback_hours = _int("LOOKBACK_HOURS", 24)
    max_backfill = _int("MAX_BACKFILL", 50)
    chunk_size = _int("CHUNK_SIZE", 10)
    if lookback_hours <= 0 or max_backfill <= 0 or chunk_size <= 0:
        raise RuntimeError("LOOKBACK_HOURS, MAX_BACKFILL and CHUNK_SIZE must be > 0")

    log_file = (src.get("LOG_FILE") or os.environ.get("LOG_FILE") or "").strip() or None

    remote_raw = (src.get("REMOTE_ONLY") or os.environ.get("REMOTE_ONLY") or "").strip().lower()
    remote_only = remote_raw in ("1", "true", "yes")

    return {
        "api_id": api_id,
        "api_hash": api_hash,
        "session_string": session_string,
        "source_chats": source_chats,
        "destination_url": destination_url,
        "lookback_hours": lookback_hours,
        "max_backfill": max_backfill,
        "chunk_size": chunk_size,
        "log_file": log_file,
        "remote_only": remote_only,
    }


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def build_client(cfg: dict = None):
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    if cfg is None:
        cfg = validate_config()
    return TelegramClient(StringSession(cfg["session_string"]), cfg["api_id"], cfg["api_hash"])


def serialize_message(chat_id: int, msg) -> dict:
    chat = getattr(msg, "chat", None)
    sender = getattr(msg, "sender", None)
    return {
        "chat_id": chat_id,
        "chat_title": getattr(chat, "title", None) or str(chat_id),
        "message_id": getattr(msg, "id", None),
        "text": getattr(msg, "text", None) or getattr(msg, "message", None) or "",
        "date": msg.date.isoformat() if getattr(msg, "date", None) else None,
        "sender": {
            "id": getattr(sender, "id", None) if sender else None,
            "name": getattr(sender, "first_name", None) or "",
        },
    }


async def post_chunk(http, url: str, chunk: list, retries: int = 3) -> None:
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            resp = await http.post(url, json=chunk)
            resp.raise_for_status()
            logging.info("Chunk sent (%d msgs) — %s", len(chunk), resp.status_code)
            return
        except Exception as exc:
            last_exc = exc
            logging.warning("POST attempt %d/%d failed: %s", attempt, retries, exc)
            if attempt < retries:
                await asyncio.sleep(2 * attempt)
    raise last_exc


async def send_batch(client, messages_by_chat: dict, cfg: dict, dry_run: bool = False) -> int:
    all_msgs = []
    for chat_id, items in messages_by_chat.items():
        for msg in items:
            all_msgs.append(serialize_message(chat_id, msg))

    chunks = chunk_messages(all_msgs, cfg["chunk_size"])
    logging.info("Sending %d messages in %d chunk(s)...", len(all_msgs), len(chunks))

    if dry_run:
        for c in chunks:
            logging.info("[dry-run] would POST %d msgs to %s", len(c),
                         urlparse(cfg["destination_url"]).netloc)
        logging.info("[dry-run] Done. %d messages across %d chats (not sent).",
                     len(all_msgs), len(messages_by_chat))
        return len(all_msgs)

    import httpx

    async with httpx.AsyncClient(timeout=60) as http:
        for idx, chunk in enumerate(chunks, 1):
            await post_chunk(http, cfg["destination_url"], chunk)
            logging.info("Chunk %d/%d sent", idx, len(chunks))
            await asyncio.sleep(1)

    logging.info("Done. Sent %d messages across %d chats.", len(all_msgs), len(messages_by_chat))
    return len(all_msgs)


async def fetch_recent(client, cfg: dict) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=cfg["lookback_hours"])
    logging.info("Fetching messages since %s from %d chat(s)...",
                 since.isoformat(), len(cfg["source_chats"]))

    messages_by_chat = {}
    for chat_id in cfg["source_chats"]:
        try:
            msgs = await client.get_messages(chat_id, offset_date=since, limit=cfg["max_backfill"])
            if not msgs:
                logging.info("No recent messages in %s", chat_id)
                continue
            msgs = [m for m in msgs if has_email(m)]
            if cfg.get("remote_only"):
                before = len(msgs)
                msgs = [m for m in msgs if is_remote(m)]
                logging.info("Remote filter: %d/%d with email kept in %s",
                             len(msgs), before, chat_id)
            if not msgs:
                logging.info("No messages with email in %s", chat_id)
                continue
            msgs.reverse()
            messages_by_chat[chat_id] = msgs
            logging.info("Fetched %d message(s) with email from %s", len(msgs), chat_id)
        except Exception:
            logging.exception("Failed to fetch from %s", chat_id)

    if not messages_by_chat:
        logging.info("No messages to send.")
    return messages_by_chat


async def list_groups(cfg: dict = None) -> None:
    cfg = cfg or validate_config()
    client = build_client(cfg)
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
    # Export works with API_ID/HASH only (interactive login), no SESSION_STRING needed.
    from telethon import TelegramClient

    api_id = int(require_env("API_ID"))
    api_hash = require_env("API_HASH")
    client = TelegramClient("forwarder_session", api_id, api_hash)
    async with client:
        await client.start()
        from telethon.sessions import StringSession
        s = StringSession.save(client.session)
        print("\n--- SESSION_STRING ---")
        print(s)
        print("----------------------\n")


def log_startup(cfg: dict) -> None:
    host = urlparse(cfg["destination_url"]).netloc
    logging.info("Config OK: %d chat(s), lookback=%dh, max_backfill=%d, chunk=%d, dest=%s, remote_only=%s",
                 len(cfg["source_chats"]), cfg["lookback_hours"],
                 cfg["max_backfill"], cfg["chunk_size"], host, cfg.get("remote_only"))


async def run_main(dry_run: bool = False) -> int:
    try:
        cfg = validate_config()
    except RuntimeError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    log_startup(cfg)

    client = build_client(cfg)
    await client.start()
    try:
        messages_by_chat = await fetch_recent(client, cfg)
        if messages_by_chat:
            try:
                await send_batch(client, messages_by_chat, cfg, dry_run=dry_run)
            except Exception:
                logging.exception("Failed to send batch")
                return 1
        return 0
    except BaseException:
        logging.exception("Backfill failed")
        return 1
    finally:
        await client.disconnect()


def check_config() -> int:
    try:
        cfg = validate_config()
    except RuntimeError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    print(f"Config OK: {len(cfg['source_chats'])} chat(s), "
          f"lookback={cfg['lookback_hours']}h, max_backfill={cfg['max_backfill']}, "
          f"chunk={cfg['chunk_size']}, dest={urlparse(cfg['destination_url']).netloc}, "
          f"remote_only={cfg.get('remote_only')}")
    return 0


def print_help() -> None:
    print("Usage: python forwarder.py [--check-config] [--dry-run] [--list-groups] [--export-session]")
    print("  --check-config    validate env and exit")
    print("  --dry-run         fetch and log without POSTing")
    print("  --list-groups     list accessible dialogs (needs API_ID/HASH + session)")
    print("  --export-session  interactive login, prints SESSION_STRING")


if __name__ == "__main__":
    args = sys.argv[1:]
    # Configure logging early so --check-config/--dry-run also log consistently.
    _log_file = os.environ.get("LOG_FILE")
    _kw = {"level": logging.INFO, "format": "%(asctime)s %(levelname)s %(message)s"}
    if _log_file:
        _kw["handlers"] = [logging.FileHandler(_log_file)]
    logging.basicConfig(**_kw)

    if "--help" in args or "-h" in args:
        print_help()
    elif "--check-config" in args:
        sys.exit(check_config())
    elif "--list-groups" in args:
        try:
            asyncio.run(list_groups())
        except RuntimeError as e:
            print(f"Config error: {e}", file=sys.stderr)
            sys.exit(2)
    elif "--export-session" in args:
        asyncio.run(export_session())
    elif "--dry-run" in args:
        sys.exit(asyncio.run(run_main(dry_run=True)))
    else:
        sys.exit(asyncio.run(run_main()))
