"""Where each weapon comes from (event, wish, crafting, Battle Pass…), from the Genshin Impact wiki.

Project Amber's data doesn't say how a weapon is obtained; the Fandom wiki files every weapon under
categories that do. Those lists are read with the wiki's API, kept in the cache folder, and re-read once
a day, on "Update data", and on every launch while a shown weapon is still missing a source (new and
upcoming weapons get their wiki categories a little after their data appears).
"""

import json
import re
import threading
import time
import urllib.parse
import urllib.request

API = "https://genshin-impact.fandom.com/api.php"
_HEADERS = {"User-Agent": "RecordBook/1.0 (personal Genshin tracker)"}

# (source, filter label, tooltip, wiki category), most specific first: a weapon takes the first that lists it
SOURCES = [
    ("event", "Event", "Free weapons from the main version events", "Flagship Event-Exclusive Weapons"),
    ("limited", "Limited Wish", "Only on a limited weapon banner", "Weapon Event Wish-Exclusive Weapons"),
    ("wish", "Wish", "From wishes (standard and event banners)", "Weapons with Wish Source"),
    ("craft", "Craftable", "Forged at a blacksmith", "Forging Weapons"),
    ("bp", "Battle Pass", "From the Battle Pass", "Battle Pass Weapons"),
    ("starglitter", "Starglitter", "Paimon's Bargains (Starglitter exchange)", "Paimon's Bargains Weapons"),
    ("fishing", "Fishing", "Fishing Association exchange", "Fishing Association-Exclusive Weapons"),
    ("quest", "Quest", "Quest rewards", "Quest Weapons"),
    ("other", "Other", "Chests, shops, starter weapons and other non-wish sources", "Weapons with Non-Wish Source"),
]
LABELS = {key: label for key, label, _tip, _cat in SOURCES}
UNKNOWN = "Not on the wiki yet"  # new / upcoming / unreleased weapons, until the wiki files them

MAX_AGE = 24 * 3600  # re-read at least daily
RETRY_AGE = 3600  # …and hourly while some weapon has no source yet

_lock = threading.Lock()
_by_name = {}  # normalized wiki title -> source key
_fetched = 0.0


def _norm(name):
    """'"The Catch"' and 'The Catch', 'Wavebreaker’s Fin' and "Wavebreaker's Fin" match."""
    return re.sub(r"[^a-z0-9]", "", name.lower().replace("’", "'"))


def _cache_path():
    import gamedata

    return gamedata.CACHE_DIR / "weapon_sources.json"


def load_cache():
    """The sources saved last time (instant, for startup); False when there's no cache yet."""
    global _fetched
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    with _lock:
        _by_name.clear()
        _by_name.update(data.get("sources") or {})
        _fetched = float(data.get("fetched") or 0)
    return True


def _members(category):
    """Every page title in a wiki category (follows the API's paging)."""
    titles, params = [], {"action": "query", "list": "categorymembers", "cmtitle": f"Category:{category}",
                          "cmlimit": "500", "cmtype": "page", "format": "json"}
    while True:
        url = f"{API}?{urllib.parse.urlencode(params)}"
        with urllib.request.urlopen(urllib.request.Request(url, headers=_HEADERS), timeout=20) as resp:
            data = json.load(resp)
        titles += [m["title"] for m in data.get("query", {}).get("categorymembers", [])]
        more = data.get("continue", {}).get("cmcontinue")
        if not more:
            return titles
        params["cmcontinue"] = more


def refresh():
    """Read every source category from the wiki and save them. Returns how many weapons have a source."""
    global _fetched
    found = {}
    for key, _label, _tip, category in SOURCES:
        for title in _members(category):
            found.setdefault(_norm(title), key)  # the first (most specific) category wins
    with _lock:
        _by_name.clear()
        _by_name.update(found)
        _fetched = time.time()
    try:
        path = _cache_path()
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"fetched": _fetched, "sources": found}), encoding="utf-8")
    except OSError:
        pass
    return len(found)


def source_of(weapon):
    """A WeaponInfo's source key, or None when the wiki doesn't list it (yet)."""
    with _lock:
        return _by_name.get(_norm(weapon.name))


def label_of(weapon):
    key = source_of(weapon)
    return LABELS[key] if key else UNKNOWN


def needs_refresh(weapons):
    """Whether to read the wiki again: the saved copy is old, or some weapon still has no source and it's
    been a while (so upcoming / unreleased weapons get theirs as soon as the wiki adds them)."""
    age = time.time() - _fetched
    if not _by_name or age > MAX_AGE:
        return True
    return age > RETRY_AGE and any(source_of(w) is None for w in weapons)
