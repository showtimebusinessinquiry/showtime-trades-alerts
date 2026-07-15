import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alertmirror.relay import (
    MAX_FILE, should_mirror, build_message, chunked, mirror,
    build_embeds, normalize_channel_name, find_target,
)
from alertmirror.allowlist import parse_allowlist, is_allowed
from alertmirror.status import guild_status, fmt_uptime, status_report, digest_report

SRC = 111


# ---- fakes standing in for discord objects -------------------------------

class Perms:
    def __init__(self, send=True, attach=True):
        self.send_messages = send
        self.attach_files = attach


class Chan:
    _seq = 1000

    def __init__(self, name="alerts", send_ok=True, attach_ok=True, fail=False, cid=None):
        Chan._seq += 1
        self.id = cid if cid is not None else Chan._seq
        self.name, self._ok, self._attach, self._fail = name, send_ok, attach_ok, fail
        self.sent = []          # (content, file_count, allowed_mentions) per send
        self.embeds_sent = []   # list of embeds per send (None when not embed mode)

    def permissions_for(self, member):
        return Perms(send=self._ok, attach=self._attach)

    async def send(self, content=None, files=None, allowed_mentions=None, embed=None, embeds=None):
        if self._fail:
            raise RuntimeError("boom")
        self.sent.append((content, len(files or []), allowed_mentions))
        got = embeds if embeds else ([embed] if embed else None)
        self.embeds_sent.append(list(got) if got else None)


class Role:
    def __init__(self, name):
        self.name, self.mention = name, f"<@&{name}>"


class Guild:
    _seq = 0

    def __init__(self, channels=(), roles=(), name="g"):
        Guild._seq += 1
        self.id, self.name = Guild._seq, name
        self.text_channels, self.roles = list(channels), list(roles)
        self.me = object()


class Attachment:
    def __init__(self, filename="chart.png", size=1000, url="http://cdn/x.png", broken=False):
        self.filename, self.size, self.url, self._broken = filename, size, url, broken

    async def read(self):
        if self._broken:
            raise RuntimeError("cdn 404")
        return b"png-bytes"


class Msg:
    def __init__(self, text="", attachments=(), guild=None, created_at=None):
        self.clean_content = text
        self.attachments = list(attachments)
        self.guild = guild
        self.created_at = created_at


def run(msg, guilds, target="alerts", ping="", use_embeds=False, **kw):
    return asyncio.run(mirror(msg, guilds, target, ping, use_embeds, **kw))


def alerts_of(guild):
    return guild.text_channels[0].sent


def embeds_of(guild):
    """Embeds from the first (usually only) send in this guild."""
    return guild.text_channels[0].embeds_sent[0]


# ---- pure functions -------------------------------------------------------

def test_should_mirror():
    assert should_mirror(SRC, False, SRC)       # right channel, human -> mirror
    assert not should_mirror(SRC, True, SRC)    # bot message -> ignore (no relay loops)
    assert not should_mirror(222, False, SRC)   # other channel -> ignore


def test_build_message():
    assert build_message("SPY 450c", [], "") == "SPY 450c"
    assert build_message("SPY 450c", [], "<@&9>") == "<@&9> SPY 450c"
    assert build_message("", ["http://img"], "<@&9>") == "<@&9>\nhttp://img"
    assert build_message("hi", ["http://img"], "") == "hi\nhttp://img"
    assert build_message("", [], "") == ""


def test_chunked():
    assert chunked("ab", 2) == ["ab"]                     # exact fit
    assert chunked("abc", 2) == ["ab", "c"]               # hard split when no newline
    assert chunked("a\nbb\ncc", 5) == ["a\nbb", "cc"]     # prefers newline: URL lines stay whole
    assert len(chunked("x" * 4001)) == 3                  # 2000 + 2000 + 1


# ---- fan-out behavior ------------------------------------------------------

def test_text_mirrors_everywhere_but_source():
    src, g1, g2 = Guild(name="src"), Guild([Chan()]), Guild([Chan()])
    delivered, failed = run(Msg("BTO SPY 450c", guild=src), [src, g1, g2])
    assert delivered == [g1, g2] and failed == []  # both destinations, never the source
    for g in (g1, g2):
        assert [(c, n) for c, n, _ in alerts_of(g)] == [("BTO SPY 450c", 0)]


def test_image_reuploads_as_real_file():
    src, g = Guild(name="src"), Guild([Chan()])
    run(Msg("", [Attachment()], guild=src), [src, g])
    content, file_count, _ = alerts_of(g)[0]
    assert content is None and file_count == 1


def test_text_plus_image_is_one_message():
    src, g = Guild(name="src"), Guild([Chan()])
    run(Msg("chart:", [Attachment()], guild=src), [src, g])
    assert alerts_of(g) == [("chart:", 1, alerts_of(g)[0][2])]


def test_guild_without_channel_or_perms_is_skipped():
    src = Guild(name="src")
    wrong = Guild([Chan(name="general")])
    noperm = Guild([Chan(send_ok=False)])
    ok = Guild([Chan()])
    delivered, failed = run(Msg("x", guild=src), [src, wrong, noperm, ok])
    assert delivered == [ok] and failed == []  # skips are not failures
    assert not alerts_of(wrong) and not alerts_of(noperm)


def test_one_failing_server_does_not_block_the_rest():
    src = Guild(name="src")
    bad, good = Guild([Chan(fail=True)], name="bad"), Guild([Chan()], name="good")
    delivered, failed = run(Msg("x", guild=src), [src, bad, good])
    assert delivered == [good] and failed == [bad]  # failure reported, not swallowed
    assert len(alerts_of(good)) == 1


def test_ping_role_only_where_it_exists():
    src = Guild(name="src")
    vip = Role("vip")
    with_role, without = Guild([Chan()], roles=[vip]), Guild([Chan()])
    run(Msg("go", guild=src), [src, with_role, without], ping="vip")
    content, _, mentions = alerts_of(with_role)[0]
    assert content == "<@&vip> go" and mentions.roles == [vip]
    content, _, mentions = alerts_of(without)[0]
    assert content == "go" and mentions.roles is False


def test_ping_role_matches_regardless_of_case():
    # different server admins won't all name the role identically-cased
    src = Guild(name="src")
    role = Role("ShowTime Alerts")
    g = Guild([Chan()], roles=[role])
    run(Msg("go", guild=src), [src, g], ping="showtime alerts")
    content, _, mentions = alerts_of(g)[0]
    assert content == "<@&ShowTime Alerts> go" and mentions.roles == [role]


def test_embed_mode_puts_ping_in_content_not_embed():
    # discord doesn't notify on mentions inside an embed -- the ping must stay in plain content
    src = Guild(name="src")
    vip = Role("vip")
    g = Guild([Chan()], roles=[vip])
    run(Msg("BTO SPY 450c", guild=src), [src, g], ping="vip", use_embeds=True)
    content, _, mentions = alerts_of(g)[0]
    assert content == "<@&vip>" and mentions.roles == [vip]
    assert embeds_of(g)[0].description == "BTO SPY 450c"  # ping is NOT in the embed body


def test_embed_mode_off_by_default():
    src, g = Guild(name="src"), Guild([Chan()])
    run(Msg("BTO SPY 450c", guild=src), [src, g])
    assert embeds_of(g) is None  # no embeds sent -- plain text like before
    assert alerts_of(g)[0][0] == "BTO SPY 450c"


def test_embed_mode_image_goes_inline():
    src, g = Guild(name="src"), Guild([Chan()])
    run(Msg("chart:", [Attachment(filename="spy.png")], guild=src), [src, g], use_embeds=True)
    embed = embeds_of(g)[0]
    assert embed.description == "chart:"
    assert embed.image.url == "attachment://spy.png"


def test_embed_first_line_becomes_title():
    src, g = Guild(name="src"), Guild([Chan()])
    run(Msg("Trimming SHEL 84C 7/31\nValue: @1.80\nNotes: first target", guild=src),
        [src, g], use_embeds=True)
    embed = embeds_of(g)[0]
    assert embed.title == "Trimming SHEL 84C 7/31"
    assert embed.description == "Value: @1.80\nNotes: first target"


def test_embed_single_line_has_no_title():
    src, g = Guild(name="src"), Guild([Chan()])
    run(Msg("BTO SPY 450c", guild=src), [src, g], use_embeds=True)
    embed = embeds_of(g)[0]
    assert embed.title is None and embed.description == "BTO SPY 450c"


def test_embed_branding_applies():
    src, g = Guild(name="src"), Guild([Chan()])
    run(Msg("title\nbody", guild=src), [src, g], use_embeds=True,
        author="ShowTime Trades", icon_url="http://logo.png",
        color=0xFF0000, footer="not financial advice")
    embed = embeds_of(g)[0]
    assert embed.author.name == "ShowTime Trades"
    assert embed.author.icon_url == "http://logo.png"
    assert embed.color.value == 0xFF0000
    assert embed.footer.text == "not financial advice"


def test_build_embeds_long_text_splits_without_data_loss():
    # a huge alert splits across stacked embeds; every character survives
    text = "x" * (4096 + 500)
    embeds = build_embeds(text)
    assert len(embeds) == 2
    assert sum(len(e.description) for e in embeds) == len(text)


def test_build_embeds_image_and_footer_on_last_only():
    embeds = build_embeds("title\n" + "y" * (4096 + 10), image_filename="c.png",
                          footer="ft", author="brand")
    assert embeds[0].author.name == "brand" and embeds[0].image.url is None
    assert embeds[-1].image.url == "attachment://c.png"
    assert embeds[-1].footer.text == "ft" and embeds[0].footer.text is None


def test_embed_mode_long_alert_is_one_embed_per_message():
    # a big alert must NOT be crammed into one send -- Discord caps a message at
    # <=6000 embed chars total, so we send one card per message and never fail wholesale
    src, g = Guild(name="src"), Guild([Chan()])
    delivered, failed = run(Msg("x" * (4096 + 500), guild=src), [src, g], use_embeds=True)
    assert delivered == [g] and failed == []
    sends = g.text_channels[0].embeds_sent
    assert len(sends) == 2 and all(len(s) == 1 for s in sends)  # 2 messages, 1 embed each


def test_embed_bad_icon_url_dropped_not_fatal():
    # a non-URL icon (bare filename) would make Discord reject every embed -- drop it instead
    src, g = Guild(name="src"), Guild([Chan()])
    run(Msg("t\nbody", guild=src), [src, g], use_embeds=True, author="brand", icon_url="logo.png")
    embed = embeds_of(g)[0]
    assert embed.author.name == "brand" and embed.author.icon_url is None


def test_find_target_decorative_only_target_matches_nothing():
    g = Guild([Chan(name="🚨")])  # both target and channel normalize to "" -> must NOT match
    assert find_target(g, "🚨") is None


def test_oversized_and_broken_attachments_fall_back_to_url():
    src, g = Guild(name="src"), Guild([Chan()])
    big = Attachment(size=MAX_FILE + 1, url="http://cdn/big.mp4")
    dead = Attachment(url="http://cdn/dead.png", broken=True)
    run(Msg("", [big, dead], guild=src), [src, g])
    content, file_count, _ = alerts_of(g)[0]
    assert file_count == 0
    assert "http://cdn/big.mp4" in content and "http://cdn/dead.png" in content


def test_long_text_chunks_and_file_rides_last_piece():
    src, g = Guild(name="src"), Guild([Chan()])
    run(Msg("x" * 4001, [Attachment()], guild=src), [src, g])
    counts = [file_count for _, file_count, _ in alerts_of(g)]
    assert counts == [0, 0, 1]  # 3 pieces, image on the final one


def test_parse_allowlist():
    assert parse_allowlist("") == set()
    assert parse_allowlist("  ") == set()
    assert parse_allowlist("123") == {123}
    assert parse_allowlist("123, 456,789") == {123, 456, 789}


def test_is_allowed():
    g = Guild(name="g")
    assert is_allowed(g, set())          # no allowlist configured -> open to anyone
    assert is_allowed(g, {g.id})         # explicitly listed
    assert not is_allowed(g, {g.id + 1})  # allowlist set, this guild isn't on it


def test_guild_status_flags_setup_problems():
    assert guild_status(Guild([Chan()]), "alerts") == "ok"
    assert guild_status(Guild([Chan(attach_ok=False)]), "alerts") == "ok, can't attach images"
    assert guild_status(Guild([Chan(name="general")]), "alerts") == "MISSING #alerts"


def test_normalize_channel_name_strips_decoration():
    # decorative prefixes/separators shouldn't block a match on the real text
    assert normalize_channel_name("alerts") == "alerts"
    assert normalize_channel_name("🚨-alerts") == "alerts"
    assert normalize_channel_name("🥇┃alerts") == "alerts"
    assert normalize_channel_name("» alerts «") == "alerts"
    assert normalize_channel_name("ShowTime Alerts") == "showtime-alerts"


def test_find_target_matches_decorated_channel():
    # env var says "alerts", the real channel is "🚨・alerts" -- still a match
    src = Guild(name="src")
    g = Guild([Chan(name="🚨・alerts")])
    assert find_target(g, "alerts") is g.text_channels[0]
    # a genuinely different channel still doesn't match
    assert find_target(Guild([Chan(name="general")]), "alerts") is None


def test_digest_report():
    assert digest_report("last 24h", 12, 0) == "daily update (last 24h): 12 alert(s) mirrored, 0 had a delivery failure somewhere"
    assert digest_report("last 24h", 0, 3) == "daily update (last 24h): 0 alert(s) mirrored, 3 had a delivery failure somewhere"


def test_empty_message_sends_nothing():
    src, g = Guild(name="src"), Guild([Chan()])
    assert run(Msg("", guild=src), [src, g]) == ([], []) and not alerts_of(g)


def test_fmt_uptime():
    assert fmt_uptime(59) == "59s"
    assert fmt_uptime(3 * 60) == "3m"
    assert fmt_uptime(3600 + 7 * 60) == "1h 07m"
    assert fmt_uptime(2 * 86400 + 5 * 3600) == "2d 5h"


def test_status_report():
    src = Guild([Chan(name="general", cid=111)], name="srv-source")
    ok = Guild([Chan()], name="srv-ok")
    missing = Guild([Chan(name="general")], name="srv-missing")
    out = status_report([src, ok, missing], "alerts", 111, "1h 02m", 5)
    assert out.splitlines() == [
        "online 1h 02m | 5 alert(s) mirrored since restart",
        "[source] srv-source",
        "[ok] srv-ok",
        "[MISSING #alerts] srv-missing",
    ]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  pass {name}")
    print("ok")
