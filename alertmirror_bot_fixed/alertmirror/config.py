"""
config.py -- reads all bot settings from environment variables.

Nothing is hardcoded; nothing sensitive (the token) lives in the code.
"""
import os

from alertmirror.allowlist import parse_allowlist


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
