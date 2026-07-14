"""
relay.py -- fans one alert out to every other server.

Handles images, long messages, missing channels, and per-server failures
without crashing the rest.
"""
import io

import discord

MAX_LEN = 2000                # discord message cap
MAX_FILE = 8 * 1024 * 1024    # re-upload attachments under this; bigger fall back to URL


def should_mirror(channel_id, author_is_bot, source_channel_id):
    """True if this should mirror: right channel, and not the bot's own message
    (skipping bot authors avoids relay loops)."""
    return channel_id == source_channel_id and not author_is_bot


def build_message(clean_text, fallback_urls, ping_mention=""):
    """Ping (if any) + text, then any fallback image links, one per line."""
    parts = []
    lead = " ".join(x for x in (ping_mention, clean_text) if x).strip()
    if lead:
        parts.append(lead)
    parts.extend(fallback_urls)
    return "\n".join(parts)


def chunked(text, size=MAX_LEN):
    """Split into <=size pieces, breaking at a newline when possible so a line
    never gets cut mid-word or mid-URL."""
    pieces = []
    while len(text) > size:
        cut = text.rfind("\n", 1, size + 1)
        if cut == -1:
            cut = size
        pieces.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        pieces.append(text)
    return pieces


import re

# keep only what's actually meaningful in a channel name -- letters, numbers,
# dashes. Discord channel names admins decorate with all kinds of separators
# ("🥇┃alerts", "🚨-alerts", "» alerts «"), and trying to denylist every emoji
# and box-drawing/bullet/pipe character individually is a losing game. Instead
# strip everything that ISN'T alphanumeric-or-dash and collapse what's left.
_NON_CORE_RE = re.compile(r"[^a-z0-9-]+")
_MULTI_DASH_RE = re.compile(r"-+")


def normalize_channel_name(name):
    """Both the env var and every real channel name get run through this
    before comparing, so decorative prefixes/separators (emoji, box-drawing
    characters, bullets, pipes -- whatever an admin used) don't block a match
    on the actual text."""
    lowered = name.strip().lower().replace(" ", "-")
    core_only = _NON_CORE_RE.sub("-", lowered)   # any decorative char -> dash
    collapsed = _MULTI_DASH_RE.sub("-", core_only)  # "🥇┃" -> multiple dashes -> one
    return collapsed.strip("-")


def find_target(guild, target_name):
    """This guild's receiving channel, or None if it's missing or unwritable."""
    wanted = normalize_channel_name(target_name)
    ch = next((c for c in guild.text_channels
               if normalize_channel_name(c.name) == wanted), None)
    return ch if ch and ch.permissions_for(guild.me).send_messages else None


def find_role(guild, role_name):
    """Case-insensitive role lookup -- admins across servers won't all match casing."""
    if not role_name:
        return None
    target = role_name.casefold()
    return next((r for r in guild.roles if r.name.casefold() == target), None)


async def read_attachments(msg):
    """Download attachments once for re-upload (Discord's CDN links expire in
    ~24h, so a plain re-post would quietly break the next day). Oversized or
    failed downloads fall back to the original URL instead of dropping the image."""
    uploads, fallback_urls = [], []
    for a in msg.attachments:
        try:
            if a.size <= MAX_FILE:
                uploads.append((a.filename, await a.read()))
            else:
                fallback_urls.append(a.url)
        except Exception:  # CDN/network hiccup — the original link is better than a lost alert
            fallback_urls.append(a.url)
    return uploads, fallback_urls


async def mirror(msg, guilds, target_name, ping_role_name):
    """Fan one message out to every other guild. Returns (delivered, failed)
    guild lists -- one guild failing doesn't block the rest."""
    text = msg.clean_content  # mentions -> plain text, so no "@unknown" in other servers
    uploads, fallback_urls = await read_attachments(msg)
    source_guild = msg.guild.id if msg.guild else None
    delivered, failed = [], []
    # sequential fan-out; fine under ~50 servers, would need a queue past that
    for guild in guilds:
        if guild.id == source_guild:
            continue
        target = find_target(guild, target_name)
        if not target:
            continue
        role = find_role(guild, ping_role_name)
        body = build_message(text, fallback_urls, role.mention if role else "")
        if not (body or uploads):
            continue
        mentions = discord.AllowedMentions(
            everyone=False, users=False, roles=[role] if role else False)
        try:
            # a mirrored image is a real upload, not a CDN link that dies when the signed URL expires
            files = [discord.File(io.BytesIO(b), filename=fn) for fn, b in uploads]
            pieces = chunked(body) if body else [""]
            for piece in pieces[:-1]:
                await target.send(piece, allowed_mentions=mentions)
            # files ride on the last piece so text sits above the image, like the original
            await target.send(pieces[-1] or None, files=files or None,
                              allowed_mentions=mentions)
            delivered.append(guild)
        except Exception as e:
            print(f"failed in {guild.name}: {e}")  # one bad server must not block the rest
            failed.append(guild)
    return delivered, failed
