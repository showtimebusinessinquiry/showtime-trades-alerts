# How it works

Notes on what the bot does, no code-reading required.

## The short version

You post in one channel. The bot copies it into every other server it's in.
Text, images, everything. Instant. That's the product — everything below is
just what makes that reliable instead of flaky.

## Settings

The bot reads its config from environment variables (set on Railway, not in
the code):

- **Bot token** — login credential. Never in the code, never shared.
- **Source channel** — the one channel that gets mirrored.
- **Target channel name** — what the receiving channel is called elsewhere (`alerts` by default).
- **Ping role** *(optional)* — pings a role when an alert lands.
- **Server whitelist** *(optional)* — anti-stealing. Give it a list of server IDs and it leaves anything not on the list.
- **Digest DM recipient** *(optional)* — daily summary DM if set.

Leave the last three blank and it just mirrors everything to everyone. Nothing breaks.

## What happens per message

1. **Filter.** Only messages in the source channel, from a person (not a bot — otherwise mirrored copies could trigger each other in a loop).
2. **Build the text.** Strips anything that'd look broken elsewhere (a role ping only valid in your server becomes plain text), adds fallback links for any image that couldn't be re-uploaded.
3. **Split if long.** Discord caps messages at 2000 characters. Long alerts get cut at line breaks, never mid-sentence or mid-URL.
4. **Find the channel per server.** Missing channel or no permission = that server's skipped, doesn't affect anyone else.
5. **Handle images.** Downloaded once, re-uploaded as real files everywhere. Discord's raw attachment links expire after ~24h — a lot of cheap mirror bots just copy the link and the image quietly dies the next day. This doesn't. Oversized/broken downloads fall back to the original link instead of dropping the image.
6. **Send, isolated per server.** One server erroring out gets logged and skipped; everyone else still gets their copy.
7. **Order.** Back-to-back alerts stay in the order you posted them (a lock serializes it).

## Checking on it

- **`!status`** — type it in the alert channel: uptime, alerts mirrored since restart, one health line per server.
- **✅ / ⚠️ reactions** — on every alert. ✅ = reached everywhere. ⚠️ = something failed somewhere (Railway logs say which).
- **Daily digest DM** *(if turned on)* — once a day, a count of alerts sent + failures, no log digging.
- **Startup/join logs** — every restart or new server prints a health line, so setup problems show up immediately instead of getting discovered later.

## If it crashes

Railway restarts it automatically. Nobody has to notice or fix it by hand — that's the actual "it just stays up" part, not a command anyone runs.

## Not built (yet)

- No slash commands — `!status` is the only one. No `/status`, `/restart`, nothing with a `/`.
- No manual restart command — don't need one (see above), but it's not there if you go looking.
- Built and tested for normal server counts (well under 100), not literally unlimited. Hundreds of servers would need a different setup.
- The whitelist does nothing until you send over server IDs to approve.
