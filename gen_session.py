"""Two-phase SESSION_STRING generator.

Phase 1:  API_ID=.. API_HASH=.. python gen_session.py request +15551234567
          -> sends login code via Telegram, prints phone_code_hash
Phase 2:  API_ID=.. API_HASH=.. python gen_session.py complete +15551234567 <hash> <code>
          -> prints SESSION_STRING (or NEED_2FA)
Phase 3 (only if 2FA): ... complete2fa +phone <hash> <code>  (prompts for password on stdin)

Secrets travel via env/argv only. Nothing is written to disk or git.
"""
import asyncio
import getpass
import os
import sys


def creds():
    try:
        return int(os.environ["API_ID"]), os.environ["API_HASH"]
    except KeyError as e:
        print(f"Missing {e} env var", file=sys.stderr)
        sys.exit(2)


async def request_code(phone: str) -> None:
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    api_id, api_hash = creds()
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
        print(f"CODE_SENT phone_code_hash={sent.phone_code_hash}")
        print("Check Telegram for the login code, then run the complete step.")
    finally:
        await client.disconnect()


async def complete(phone: str, phone_code_hash: str, code: str) -> None:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import SessionPasswordNeededError

    api_id, api_hash = creds()
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    try:
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        except SessionPasswordNeededError:
            print("NEED_2FA run the complete2fa step with your 2FA password")
            return
        except Exception as exc:
            print(f"SIGNIN_FAILED {type(exc).__name__}: {exc}")
            return
        print("SESSION_STRING=" + StringSession.save(client.session))
    finally:
        await client.disconnect()


async def complete_2fa(phone: str, phone_code_hash: str, code: str) -> None:
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    api_id, api_hash = creds()
    password = getpass.getpass("2FA password: ")
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        await client.sign_in(password=password)
        print("SESSION_STRING=" + StringSession.save(client.session))
    finally:
        await client.disconnect()


async def qr_approve(rounds: int = 6, wait_each: int = 25) -> None:
    """Print tg://login URLs; user taps one on their phone to approve. Polls until done."""
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    api_id, api_hash = creds()
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    try:
        qr = await client.qr_login()
        for i in range(1, rounds + 1):
            print(f"QR_LINK[{i}/{rounds}] {qr.url}", flush=True)
            try:
                approved = await qr.wait(wait_each)
            except Exception as exc:
                print(f"QR_WAIT {type(exc).__name__}")
                approved = False
            if approved:
                print("SESSION_STRING=" + StringSession.save(client.session))
                return
            await qr.recreate()
            print("QR_EXPIRED renewed, tap the new link", flush=True)
        print("QR_TIMEOUT no approval received")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    step = sys.argv[1]
    if step == "request" and len(sys.argv) == 3:
        asyncio.run(request_code(sys.argv[2]))
    elif step == "complete" and len(sys.argv) == 5:
        asyncio.run(complete(sys.argv[2], sys.argv[3], sys.argv[4]))
    elif step == "complete2fa" and len(sys.argv) == 5:
        asyncio.run(complete_2fa(sys.argv[2], sys.argv[3], sys.argv[4]))
    elif step == "qr":
        rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 6
        asyncio.run(qr_approve(rounds))
    else:
        print(__doc__)
        sys.exit(2)
