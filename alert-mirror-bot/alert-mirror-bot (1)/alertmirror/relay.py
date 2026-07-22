"""
relay.py -- fans one alert out to every other server.

Handles images, long messages, missing channels, and per-server failures
without crashing the rest. Can post either as plain text or as a styled
embed "card" (USE_EMBEDS).
"""
import io
import re

import discord

MAX_LEN = 2000                # discord message cap
EMBED_LEN = 4096              # discord embed description cap (bigger than a plain message)
EMBED_TITLE_LEN = 256         # discord embed title cap
MAX_FILE = 8 * 1024 * 1024    # re-upload attachments under this; bigger fall back to URL
EMBED_COLOR = 0x5865F2        # default accent (discord blurple); override via EMBED_COLOR env


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
    if not wanted:  # a purely-decorative target name would otherwise match any decorative channel
        return None
    ch = next((c for c in guild.text_channels
               if normalize_channel_name(c.name) == wanted), None)
    return ch if ch and ch.permissions_for(guild.me).send_messages else None


def find_role(guild, role_name):
    """Case-insensitive role lookup -- admins across servers won't all match casing."""
    if not role_name:
        return None
    target = role_name.casefold()
    return next((r for r in guild.roles if r.name.casefold() == target), None)


def build_embeds(text, image_filename=None, *, author="", icon_url="",
                 color=EMBED_COLOR, footer="", timestamp=None, disclaimer_url=""):
    """Turn one alert into its embed card(s).

    The first line becomes a bold title when there's more text after it (so a
    "Trimming SHEL 84C" headline sits above the notes); otherwise the whole
    thing is the body. Long alerts split across stacked embeds rather than get
    truncated -- rare for a trade alert, but no data is ever dropped. Branding
    (author line, accent color, footer, chart image) is all optional and only
    shows when configured.
    """
    title, body = None, text
    if text:
        first, _, rest = text.partition("\n")
        if rest.strip() and len(first) <= EMBED_TITLE_LEN:
            title, body = first, rest.strip()
    pieces = chunked(body, EMBED_LEN) if body else [""]
    embeds = []
    for i, piece in enumerate(pieces):
        embed = discord.Embed(description=piece or None, color=color)
        if i == 0:  # title + author ride the first card
            if title:
                embed.title = title
            if author:
                # a bad icon URL would make Discord reject the whole embed, so
                # only pass one that's actually a URL -- else just drop the icon
                safe_icon = icon_url if icon_url.startswith(("http://", "https://")) else None
                embed.set_author(name=author, icon_url=safe_icon)
        if i == len(pieces) - 1:  # image + footer + disclaimer close out the last one
            if image_filename:
                embed.set_image(url=f"attachment://{image_filename}")
            if footer:
                embed.set_footer(text=footer)
            if disclaimer_url:
                # append disclaimer as a line above the footer
                current_desc = embed.description or ""
                embed.description = f"{current_desc}\n\n{disclaimer_url}" if current_desc else disclaimer_url
            if timestamp is not None:
                embed.timestamp = timestamp
        embeds.append(embed)
    return embeds


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


async def mirror(msg, guilds, target_name, ping_role_name, use_embeds=False, *,
                 author="", icon_url="", color=EMBED_COLOR, footer="", disclaimer_url=""):
    """Fan one message out to every other guild. Returns (delivered, failed)
    guild lists -- one guild failing doesn't block the rest.

    use_embeds=True posts each alert as a styled embed card instead of plain
    text. The ping (if any) always rides as plain message content, never inside
    the embed -- Discord doesn't notify on mentions written inside an embed,
    only on ones in the message's own content.
    """
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
        ping = role.mention if role else ""
        # ping stays out of the body in embed mode -- it rides in plain content to notify
        body = build_message(text, fallback_urls, "" if use_embeds else ping)
        # in embed mode, strip any typed mention of the role from the start so it doesn't clutter the title
        if use_embeds and role and body.startswith(f"{role.name} "):
            body = body[len(f"{role.name} "):].lstrip()
        if not (body or uploads):
            continue
        mentions = discord.AllowedMentions(
            everyone=False, users=False, roles=[role] if role else False)
        try:
            # a mirrored image is a real upload, not a CDN link that dies when the signed URL expires
            files = [discord.File(io.BytesIO(b), filename=fn) for fn, b in uploads]
            if use_embeds:
                embeds = build_embeds(
                    body, files[0].filename if files else None,
                    author=author, icon_url=icon_url, color=color, footer=footer,
                    timestamp=getattr(msg, "created_at", None), disclaimer_url=disclaimer_url)
                # one embed per message -- keeps every send under Discord's
                # per-message limits (<=10 embeds AND <=6000 chars total) no
                # matter how long the alert, so a big alert never fails wholesale
                last = len(embeds) - 1
                for i, embed in enumerate(embeds):
                    await target.send(
                        ping or None if i == 0 else None,      # ping notifies once, first card
                        embed=embed,
                        files=files or None if i == last else None,  # image rides its own card
                        allowed_mentions=mentions)
            else:
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
