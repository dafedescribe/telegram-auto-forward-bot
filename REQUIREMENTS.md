# Telegram Group to Bot Auto-Forwarder

## Goal

Forward new messages from one Telegram group or channel to another Telegram bot using a Python script.

## Important Telegram Constraint

The normal Telegram Bot API is not suitable for this exact job because Telegram bots generally cannot talk to other bots or read messages from other bots. To send group messages to another bot, this script logs in with a Telegram user account through Telethon.

Use this only for groups/channels you are allowed to monitor and messages you are allowed to forward.

## Requirements

- Python 3.10 or newer
- A Telegram account
- Telegram API credentials from `https://my.telegram.org`
- Access to the source group or channel from your Telegram account
- The destination bot username, for example `@SomeBot`

## Setup

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Open `forward_group_to_bot.py` and set the source group and destination bot:

   ```python
   SOURCE_CHAT = "@source_group_or_channel_username"
   DESTINATION_BOT = "@destination_bot_username"
   ```

## Getting API Credentials

1. Open `https://my.telegram.org`.
2. Log in with your Telegram phone number.
3. Open **API development tools**.
4. Create an app.
5. Copy the `api_id` and `api_hash` into `forward_group_to_bot.py`.

## Running

```bash
python forward_group_to_bot.py
```

On the first run, Telethon will ask for your phone number, login code, and possibly your 2FA password. It then creates a local session file so future runs do not need another login.

## Configuration

- `SOURCE_CHAT`: Source group/channel username, invite link, or numeric chat ID.
- `DESTINATION_BOT`: Destination bot username, for example `@SomeBot`.
- `FORWARD_MODE = "forward"`: Sends messages as Telegram forwards, preserving forwarded attribution where Telegram allows it.
- `FORWARD_MODE = "copy"`: Sends a fresh copy of the message where possible.
- `SESSION_NAME`: Local session filename prefix.

## Notes

- Protected content may not be forwardable.
- Private groups/channels may require numeric IDs or prior access through your Telegram account.
- If Telegram rate-limits the account, the script waits and continues.
- Do not use this for spam or for forwarding private content without permission.
