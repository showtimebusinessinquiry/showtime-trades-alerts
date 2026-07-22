# Alert Mirror Bot

Mirrors every message from one source channel into a channel named `alerts`
in every other server the bot is in. Text mirrors as text, images re-upload
as real files. No edit/delete syncing — post a new update instead.

See [HOW_IT_WORKS.md](HOW_IT_WORKS.md) for what the code actually does, no
Python required.

## Quick start

1. Unzip this folder.
2. Set up a Discord bot application (steps below) if you don't have one yet.
3. Deploy to Railway (steps below) and set your environment variables.
4. Post in your source channel and watch it mirror.

## Project layout

```
alertmirror/     the bot's code
  config.py        settings from environment variables
  allowlist.py     server whitelist / anti-stealing
  relay.py         core mirror logic
  status.py        !status, daily digest, health checks
  bot.py           Discord client + event handlers
run.py           starts the bot — this is what Railway runs
tests/           automated tests (21 checks): python tests/test_alertmirror.py
planning/        internal notes, not part of the product — ignore
```

## Discord setup (once)

1. <https://discord.com/developers/applications> → New Application → Bot
   - Privileged Gateway Intents: enable **Message Content Intent**
   - Reset Token → copy it (this is `DISCORD_TOKEN`; env var only, never in code/git)
2. OAuth2 → URL Generator → check the `bot` scope and these permissions:
   View Channels, Send Messages, Attach Files, Embed Links, Add Reactions
   (Add Reactions powers the ✅/⚠️ delivery receipts). Copy the generated URL.
3. Invite the bot to your source server AND every destination server with that link.
4. Every destination server creates a text channel named `alerts`
   (or set `TARGET_CHANNEL_NAME` to whatever name you use instead).
5. Discord → Settings → Advanced → **Developer Mode** on, then right-click your
   source alert channel → Copy Channel ID → that's `SOURCE_CHANNEL_ID`.
6. Lock the source channel so only you can post there — every human message
   posted there gets broadcast to every server.

## Deploy (Railway)

- New service from this folder (Procfile runs `python run.py`).
- Variables:
  - `DISCORD_TOKEN` — bot token
  - `SOURCE_CHANNEL_ID` — the channel to mirror from
  - `TARGET_CHANNEL_NAME` — optional, default `alerts`
  - `PING_ROLE_NAME` — optional, default off (no ping)
  - `DIGEST_USER_ID` — optional, a Discord user ID. If set, that user gets a DM
    every 24h with alerts mirrored + delivery failures since the last digest,
    then the counters reset. Unset = no digest.
  - `GUILD_ALLOWLIST` — optional, comma-separated server IDs. **Unset = anyone
    can invite the bot and receive alerts** (Public Bot has to stay on so
    servers can add it). Set this to lock it down — the bot auto-leaves
    anything not on the list, logged as `[NOT ALLOWLISTED] <server> — leaving`.
    Get each server's ID the same way as the channel ID.
  - `USE_EMBEDS` — optional, `true`/`false`. Posts alerts as styled embed
    "cards" (colored accent bar, optional logo + footer) instead of plain text.
    Unset/false = today's plain-text look, unchanged. A configured ping still
    notifies normally — it rides as plain message content above the card, since
    Discord doesn't notify on mentions written inside an embed. When on, the
    first line of an alert becomes the card's bold title if there's more text
    after it; the chart image sits inside the card.
  - `EMBED_AUTHOR` — optional, brand name shown at the top of the card (e.g.
    `ShowTime Trades`). Only used when `USE_EMBEDS` is on.
  - `EMBED_ICON_URL` — optional, URL of a small logo shown next to the author name.
    Must be a valid `http://` or `https://` URL; a malformed value is silently dropped.
  - `EMBED_FOOTER` — optional, footer line (e.g. `ShowTime Trades • not financial advice`).
  - `EMBED_COLOR` — optional, hex accent color as `5865F2` / `#5865F2` /
    `0x5865F2`. Default is Discord blurple. A mistyped value falls back to the
    default rather than stopping the bot.
  - `EMBED_DISCLAIMER_URL` — optional, legal disclaimer link appended to the bottom
    of every embed card (e.g. a Google Doc URL). Shows on the last embed only when
    an alert spans multiple embeds.
- Boot log prints one line per server: `[ok]`, `[ok, can't attach images]`,
  or `[MISSING #alerts]`. Fix any non-ok line before going live.
- Channel matching ignores decoration: a channel named `🚨・alerts` or
  `🥇┃alerts` still matches `TARGET_CHANNEL_NAME=alerts`.

## Built-in checks

- **`!status`** — type it in the source channel: replies with uptime, alerts
  mirrored since restart, and a health line per server (`[ok]`,
  `[MISSING #alerts]`, `[ok, can't attach images]`, `[source]`).
- **Delivery receipts** — every mirrored alert gets a ✅ reaction when it reached
  every server, or ⚠️ when at least one send failed (the Railway log names which).

## Pings

Set `PING_ROLE_NAME` (e.g. `alerts ping`). Each destination server needs a
role with exactly that name, set to "Allow anyone to @mention this role" (or
the bot needs Mention Everyone there) for pings to actually notify anyone.

## Test drive

Post in the source channel: a text alert, an image, text+image. Each should
appear once in every other server's `#alerts`. The bot ignores its own
mirrored posts (bot authors are always skipped, so no relay loop).
