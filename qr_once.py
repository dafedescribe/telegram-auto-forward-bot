"""One-shot QR login: writes token immediately, waits up to 120s for tap."""
import asyncio, os, sys

async def main():
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    import qrcode

    api_id = int(os.environ["API_ID"])
    api_hash = os.environ["API_HASH"]
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    try:
        for round_no in range(1, 7):
            qr = await client.qr_login()
            url = qr.url
            # write token file immediately so UI can show it
            with open("qr_token.txt", "w") as f:
                f.write(url)
            # QR png for phone scan: Settings > Devices > Link Desktop Device
            img = qrcode.make(url)
            img.save("qr_login.png")
            print(f"QR_URL[{round_no}/6]={url}", flush=True)
            print("PNG=qr_login.png", flush=True)
            try:
                approved = await qr.wait(25)
            except Exception as exc:
                print(f"QR_WAIT {type(exc).__name__}: {exc}")
                approved = False
            if approved:
                s = StringSession.save(client.session)
                with open("session_out.txt", "w") as f:
                    f.write(s)
                print("APPROVED session written to session_out.txt", flush=True)
                return
            try:
                await qr.recreate()
            except Exception:
                pass
        print("QR_TIMEOUT no approval in ~150s", flush=True)
    finally:
        await client.disconnect()

asyncio.run(main())
