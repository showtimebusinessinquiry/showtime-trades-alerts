"""
bot.py -- connects to Discord, listens for messages, runs mirror/status/digest.

The file that actually starts the bot. To trace "what happens when an alert
gets posted," start at on_message below.
"""
import asyncio
import time

import discord
from discord.ext import tasks

from alertmirror.config import Config
from alertmirror.allowlist import is_allowed
from alertmirror.relay import should_mirror, mirror, chunked
from alertmirror.status import guild_status, fmt_uptime, status_report, digest_report


def main():
    cfg = Config()

    intents = discord.Intents.default()
    intents.message_content = True  # privileged — enable in the Discord dev portal
    client = discord.Client(intents=intents)
    lock = asyncio.Lock()  # needs py3.10+; serializes bursts so alerts land in posting order
    started = time.time()
    stats = {"mirrored": 0, "alerts_failed": 0}

    @tasks.loop(hours=24)
    async def send_digest():
        user = await client.fetch_user(cfg.digest_user_id)
        await user.send(digest_report("last 24h", stats["mirrored"], stats["alerts_failed"]))
        stats["mirrored"] = 0
        stats["alerts_failed"] = 0

    async def setup_hook():  # runs once, after login, before the gateway connects
        if cfg.digest_user_id:
            send_digest.start()
    client.setup_hook = setup_hook

    @client.event
    async def on_ready():
        print(f"up as {client.user} across {len(client.guilds)} guilds")
        for g in client.guilds:  # setup checklist: which servers are actually reachable
            if not is_allowed(g, cfg.allowlist):
                print(f"  [NOT ALLOWLISTED] {g.name} — leaving")
                await g.leave()
                continue
            if any(c.id == cfg.source_channel_id for c in g.text_channels):
                status = "source server"  # this one sends, it doesn't need #alerts
            else:
                status = guild_status(g, cfg.target_name)
            print(f"  [{status}] {g.name}")

    @client.event
    async def on_guild_join(guild):  # rollout visibility: each invite's health shows in logs live
        if not is_allowed(guild, cfg.allowlist):
            print(f"joined {guild.name}: not on the allowlist, leaving")
            await guild.leave()
            return
        print(f"joined {guild.name}: [{guild_status(guild, cfg.target_name)}]")

    @client.event
    async def on_guild_remove(guild):
        print(f"removed from {guild.name}")

    @client.event
    async def on_message(msg):
        if not should_mirror(msg.channel.id, msg.author.bot, cfg.source_channel_id):
            return
        if msg.content.strip().lower() == "!status":  # health check, right where he posts
            report = status_report(client.guilds, cfg.target_name, cfg.source_channel_id,
                                   fmt_uptime(time.time() - started), stats["mirrored"])
            for piece in chunked(report):  # ~50 servers can pass the 2000-char cap
                await msg.channel.send(piece)
            return
        async with lock:  # two quick alerts must not race each other out of order
            delivered, failed = await mirror(
                msg, client.guilds, cfg.target_name, cfg.ping_role_name, cfg.use_embeds,
                author=cfg.embed_author, icon_url=cfg.embed_icon_url,
                color=cfg.embed_color, footer=cfg.embed_footer)
        if delivered:
            stats["mirrored"] += 1
        if failed:
            stats["alerts_failed"] += 1
        print(f"mirrored to {len(delivered)} server(s)"
              + (f", FAILED in {[g.name for g in failed]}" if failed else ""))
        if delivered or failed:
            try:  # receipt on the alert itself: all good vs somewhere failed
                await msg.add_reaction("\N{WARNING SIGN}" if failed else "\N{WHITE HEAVY CHECK MARK}")
            except Exception:
                pass  # no Add Reactions perm — receipts are optional, mirroring already happened

    client.run(cfg.token)
