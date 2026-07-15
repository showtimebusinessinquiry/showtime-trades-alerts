"""
config.py -- reads all bot settings from environment variables.

Nothing is hardcoded; nothing sensitive (the token) lives in the code.
"""
import os

from alertmirror.allowlist import parse_allowlist
from alertmirror.relay import EMBED_COLOR


def _parse_color(raw):
    """Accept a hex accent color as "#5865F2", "0x5865F2", or "5865F2".
    Anything unset or unparseable falls back to the default -- a mistyped color
    should never stop the bot from booting."""
    raw = raw.strip().lstrip("#").removeprefix("0x")
    if not raw:
        return EMBED_COLOR
    try:
        return int(raw, 16)
    except ValueError:
        return EMBED_COLOR


class Config:
    """Every setting the bot reads on startup, in one place."""

    def __init__(self):
        self.token = os.environ["DISCORD_TOKEN"]
        self.source_channel_id = int(os.environ["SOURCE_CHANNEL_ID"])
        # discord forces text-channel names lowercase; strip guards Railway UI paste whitespace
        self.target_name = os.environ.get("TARGET_CHANNEL_NAME", "alerts").strip().lower()
        self.ping_role_name = os.environ.get("PING_ROLE_NAME", "").strip()  # empty = don't ping
        self.allowlist = parse_allowlist(os.environ.get("GUILD_ALLOWLIST", ""))  # empty = open to anyone
        digest_id_raw = os.environ.get("DIGEST_USER_ID", "").strip()
        self.digest_user_id = int(digest_id_raw) if digest_id_raw else None  # unset = no digest DM
        # embed "card" mode -- all optional; unset = plain text, exactly like before
        self.use_embeds = os.environ.get("USE_EMBEDS", "").strip().lower() in ("1", "true", "yes", "on")
        self.embed_author = os.environ.get("EMBED_AUTHOR", "").strip()      # brand name atop the card
        self.embed_icon_url = os.environ.get("EMBED_ICON_URL", "").strip()  # small logo by the name
        self.embed_footer = os.environ.get("EMBED_FOOTER", "").strip()      # footer line
        self.embed_color = _parse_color(os.environ.get("EMBED_COLOR", ""))  # accent bar color
