"""
allowlist.py -- server whitelist (anti-stealing).

Discord bots have to be marked "public" for different servers to add them,
which means anyone with the invite link could otherwise add this bot and
start getting your alerts for free. Set GUILD_ALLOWLIST and the bot leaves
anything not on the list (see on_guild_join / on_ready in bot.py). Unset =
open to whoever you invite it to, same as before this existed.
"""


def parse_allowlist(raw):
    """"111,222, 333" -> {111, 222, 333}. Blank input means no restriction."""
    return {int(x) for x in raw.split(",") if x.strip()}


def is_allowed(guild, allowlist):
    """No allowlist configured = open to anyone. Otherwise must be listed."""
    return not allowlist or guild.id in allowlist
