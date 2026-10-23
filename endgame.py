"""Spiral Abyss, Stygian Onslaught and Imaginarium Theater: their schedules and line-ups, from Lunaris
(lunaris.moe), with the dates corrected.

Lunaris reads the game's own data, whose dates for the newest entries are test-server placeholders (a
day long, or in 2099). So each schedule is checked: the Abyss changes on the 16th of every month and the
Theater on the 1st (each at 4:00 server time), and Stygian Onslaught opens a week into each version and
runs 34 days. Entries with placeholder dates get the window after the one before them; anything that
hasn't started yet is "upcoming" (its dates are To Be Decided, and its line-up comes from the test server).

The fetch_* functions block; the UI calls them through gamedata.run_async().
"""

import json
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

from gamedata import ASSETS, CACHE_DIR

DATA = "https://api.lunaris.moe/data/"
STYGIAN_DATA = "https://lunaris.moe/data/leylinechallenge/"
STYGIAN_FIRST = 5269001  # 5.7's; the next ones count up from it
LUNARIS_ASSETS = "https://api.lunaris.moe/data/assets/"
MAX_AGE = 6 * 3600
FMT = "%Y-%m-%d %H:%M:%S"
THEATER_LAUNCH = "2024-07-01"  # older Theater entries are the game's tests from before it came out
THEATER_SEASON_OFFSET = 0  # a season's number is its id
STYGIAN_LEVELS = ["Hard", "Menacing", "Fearless", "Dire"]  # its four level-90+ difficulties, in order
THEATER_LEVELS = {"1": "Easy", "2": "Normal", "3": "Hard", "4": "Visionary", "5": "Lunar"}
THEATER_ELEMENTS = {2: "PYRO", 3: "HYDRO", 4: "DENDRO", 5: "ELECTRO", 6: "CRYO", 7: "ANEMO", 8: "GEO"}
# Version start dates: 6.0 came out on 2025-09-10, and a version lasts 6 weeks; from 6.6 on, Stygian
# Onslaught opens a week after the version (10:00) and closes 34 days later (03:59:59).
VERSION_ZERO = ("6.0", date(2025, 9, 10))
VERSION_DAYS = 42
STYGIAN_FIXED_FROM = (6, 6)


def _get(url, name):
    """JSON from Lunaris, kept on disk for a few hours (and used as it is when offline)."""
    file = CACHE_DIR / "endgame" / name
    if file.exists() and time.time() - file.stat().st_mtime < MAX_AGE:
        return json.loads(file.read_text(encoding="utf-8"))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://lunaris.moe/"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        if file.exists():
            return json.loads(file.read_text(encoding="utf-8"))
        raise
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(data), encoding="utf-8")
    return data


@lru_cache(maxsize=None)
def versions():
    """Lunaris's data versions, newest first."""
    info = _get(DATA + "version.json", "version.json")
    return info.get("versions") or [info["version"]]


def _parse(text):
    return datetime.strptime(text[:19], FMT)


def _months_later(day, months, reset_day):
    month = day.month - 1 + months
    return datetime(day.year + month // 12, month % 12 + 1, reset_day, 4, 0, 0)


def _monthly(entries, reset_days, start_key, end_key):
    """Correct monthly schedules: a real one starts on a reset day at 4:00 and lasts half a month to a
    month (the Abyss changed twice a month until mid-2024); a placeholder is replaced by the month after
    the entry before it."""
    previous = None
    for entry in entries:
        start, end = _parse(entry[start_key]), _parse(entry[end_key])
        real = start.day in reset_days and start.hour == 4 and 12 <= (end - start).days <= 40 and start.year < 2090
        if not real and previous is not None:
            start = previous
            end = _months_later(start, 1, start.day) - timedelta(seconds=1)
        entry["start"], entry["end"] = start, end
        previous = end + timedelta(seconds=1)
    return entries


def _version_key(text):
    try:
        major, minor = text.split(".")[:2]
        return int(major), int(minor)
    except ValueError:
        return (0, 0)


def _version_start(name, known):
    """When a version came out, from 6.0's date and the 6-week cycle (counting only the versions that
    exist: 6.7 was followed by 7.0)."""
    order = sorted({v for v in known if _version_key(v) >= _version_key(VERSION_ZERO[0])}, key=_version_key)
    if name not in order:
        return None
    return VERSION_ZERO[1] + timedelta(days=VERSION_DAYS * order.index(name))


def _status(entry, now):
    """'past', 'live' or 'upcoming' (by the server's clock, passed in as a naive datetime)."""
    if entry["end"] < now:
        return "past"
    return "live" if entry["start"] <= now else "upcoming"


# ----- lists -----
def fetch_abyss_list():
    latest = versions()[0]
    raw = _get(f"{DATA}{latest}/towerlist.json", f"towerlist-{latest}.json")
    entries = []
    for key in sorted(raw, key=lambda k: _parse(raw[k]["openTime"])):
        item = raw[key]
        entries.append({"id": key, "name": item.get("enBuffName") or "Unnamed Moon", "icon": item.get("icon"),
                        "openTime": item["openTime"], "closeTime": item["closeTime"]})
    return _monthly(entries, (1, 16), "openTime", "closeTime")


def fetch_theater_list():
    latest = versions()[0]
    raw = _get(f"{DATA}{latest}/roleplaylist.json", f"roleplaylist-{latest}.json")
    entries = []
    for key in sorted(raw, key=int):
        item = raw[key]
        if item["beginTime"] < THEATER_LAUNCH or item["beginTime"] >= "2090":
            continue  # the game's tests from before it came out, and far-future placeholders
        entries.append({"id": key, "season": int(key) - THEATER_SEASON_OFFSET,
                        "elements": [THEATER_ELEMENTS[e] for e in item.get("elementRestrictions") or [] if e in THEATER_ELEMENTS],
                        "featured": item.get("featuredAvatars") or [],
                        "beginTime": item["beginTime"], "endTime": item["endTime"]})
    return _monthly(entries, (1,), "beginTime", "endTime")


def fetch_stygian_list():
    entries = []
    schedule_id = STYGIAN_FIRST
    while True:  # one per version; the newest is the first that isn't there
        try:
            item = _get(f"{STYGIAN_DATA}{schedule_id}.json", f"stygian-{schedule_id}.json")
        except Exception:
            break
        entries.append(item)
        schedule_id += 1
    known = [e.get("challengeName", "") for e in entries]
    out = []
    previous_end = None
    for item in entries:
        version = item.get("challengeName", "")
        start, end = _parse(item["scheduleStartTime"]), _parse(item["scheduleEndTime"])
        released = _version_start(version, known)
        if _version_key(version) >= STYGIAN_FIXED_FROM and released:
            start = datetime.combine(released + timedelta(days=7), datetime.min.time()).replace(hour=10)
            end = datetime.combine((start + timedelta(days=34)).date(), datetime.min.time()).replace(hour=3, minute=59, second=59)
        elif previous_end and start < previous_end:  # a placeholder overlapping the one before
            start, end = previous_end + timedelta(seconds=1), previous_end + timedelta(days=VERSION_DAYS)
        previous_end = end
        out.append({"id": item["scheduleId"], "version": version,
                    "name": item.get("enChallengeName") or f"Version {version}", "start": start, "end": end,
                    "levels": item.get("levels") or []})
    return out


def fetch_all():
    """{"abyss", "theater", "stygian"}: each a list of entries, oldest first."""
    result = {}
    for key, fn in (("abyss", fetch_abyss_list), ("theater", fetch_theater_list), ("stygian", fetch_stygian_list)):
        try:
            result[key] = fn()
        except Exception:
            result[key] = []
    return result


def mark(entries, now):
    """Give each entry its status ('past' / 'live' / 'upcoming') by the server's clock (naive datetime)."""
    for entry in entries:
        entry["status"] = _status(entry, now)
    return entries


# ----- details -----
def _detail(kind, entry_id):
    """An Abyss ('tower') or Theater ('roleplay') entry's line-up, from the newest data version that has it."""
    for version in versions()[:6]:
        try:
            return _get(f"{DATA}{version}/en/{kind}/{entry_id}.json", f"{kind}-{version}-{entry_id}.json")
        except Exception:
            continue
    raise LookupError(f"No {kind} data for {entry_id}")


def fetch_abyss(entry_id):
    return _detail("tower", entry_id)


def fetch_theater(entry_id):
    return _detail("roleplay", entry_id)


def stygian_levels(entry):
    """The four level-90+ difficulties: [(name, level data)]."""
    levels = sorted((lv for lv in entry["levels"] if lv.get("monsterLevel", 0) >= 90), key=lambda lv: lv["monsterLevel"])
    return list(zip(STYGIAN_LEVELS, levels[-4:]))


# ----- the current Stygian bosses' resistances, from stygian.moe -----
STYGIAN_MOE = "https://www.stygian.moe"


def _page(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def fetch_stygian_moe():
    """{boss name: {"url", "tldr": [point as HTML, …]}} for the current Stygian Onslaught's bosses, from
    stygian.moe's front page: its "Insider's TLDR" of each fight (key numbers highlighted) and the boss's
    page there (resistances in each phase, clears). Kept on disk for a few hours."""
    file = CACHE_DIR / "endgame" / "stygian-moe-tldr.json"
    if file.exists() and time.time() - file.stat().st_mtime < MAX_AGE:
        return json.loads(file.read_text(encoding="utf-8"))
    import html as _html
    import re

    page = _page(STYGIAN_MOE + "/")
    starts = [m.start() for m in re.finditer(r"Insider(?:&#x27;|&apos;|')s TLDR</h3>", page)]
    bosses = {}
    for n, start in enumerate(starts):
        before = page[max(0, start - 8000):start]
        names = re.findall(r"<h[23][^>]*>([^<]{5,160})</h[23]>", before)
        links = re.findall(r'href="(/boss/[^"#?]+)"', before)
        if not names:
            continue
        name = _html.unescape(names[-1]).strip()
        block = page[start:starts[n + 1] if n + 1 < len(starts) else start + 20000]
        block = block[:block.find("</div></div>")] if "</div></div>" in block else block
        points = []
        for item in re.findall(r'<p class="text-boss-text[^"]*">(.*?)</p>', block, re.S):
            item = re.sub(r"<!-- -->", "", item).strip().lstrip("•").strip()
            # the highlighted numbers and effects stay highlighted; everything else is plain text
            item = re.sub(r'<span class="boss-rich-text-highlight"[^>]*>(.*?)</span>', lambda m: f"\x01{m.group(1)}\x02",
                          item, flags=re.S)
            item = _html.escape(_html.unescape(re.sub(r"<[^>]+>", "", item)))
            item = item.replace("\x01", "<b style='color:#fde047'>").replace("\x02", "</b>")
            points.append(item.replace("\n", "<br>"))
        if points:
            bosses[name] = {"url": STYGIAN_MOE + links[-1] if links else STYGIAN_MOE, "tldr": points}
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(bosses), encoding="utf-8")
    return bosses


def stygian_moe_entry(bosses, name):
    """stygian.moe's entry for a boss named as in the game data (its names add a phase: "… - Obliterator
    Panoply"), or None."""
    def words(text):
        import re

        return set(re.findall(r"[a-z']+", text.lower()))

    mine = words(name)
    best, score = None, 0.0
    for theirs, entry in bosses.items():
        common = len(mine & words(theirs)) / max(1, len(mine))
        if common > score:
            best, score = entry, common
    return best if score >= 0.75 else None


# ----- pictures -----
def monster_icon(icon):
    return f"{ASSETS}monster/{icon}.png" if icon else None


def blessing_icon(icon):
    return f"{LUNARIS_ASSETS}tower/{icon}.png" if icon else None


def stygian_image(icon):
    return f"{LUNARIS_ASSETS}leyline/{icon.replace('UI_MonsterIcon_', 'UI_Img_LeyLineChallenge_')}.png" if icon else None


def to_utc(naive, server_tz):
    """A schedule time (server clock) as an aware datetime."""
    return naive.replace(tzinfo=server_tz).astimezone(timezone.utc)
