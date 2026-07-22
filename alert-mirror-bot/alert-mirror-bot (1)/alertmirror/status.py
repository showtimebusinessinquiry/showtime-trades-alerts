"""
status.py -- health checks: !status, the daily digest, and the startup log.

Doesn't change what the bot does, just reports on it.
"""
from alertmirror.relay import find_target


def guild_status(guild, target_name):
    """One-line health check: channel present? can it post images?"""
    ch = find_target(guild, target_name)
    if not ch:
        return f"MISSING #{target_name}"
    if not ch.permissions_for(guild.me).attach_files:
        return "ok, can't attach images"
    return "ok"


def fmt_uptime(seconds):
    """Turn a number of seconds into something readable: 45s / 12m / 3h 07m / 2d 5h."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m"
    return f"{s}s"


def digest_report(period_label, mirrored_count, failed_count):
    """Text for the daily summary DM (see send_digest in bot.py)."""
    return (f"daily update ({period_label}): {mirrored_count} alert(s) mirrored, "
            f"{failed_count} had a delivery failure somewhere")


def status_report(guilds, target_name, source_channel_id, uptime, mirrored_count):
    """Text for !status: uptime, alert count, one line per connected server."""
    lines = [f"online {uptime} | {mirrored_count} alert(s) mirrored since restart"]
    for g in guilds:
        if any(c.id == source_channel_id for c in g.text_channels):
            lines.append(f"[source] {g.name}")
        else:
            lines.append(f"[{guild_status(g, target_name)}] {g.name}")
    return "\n".join(lines)
