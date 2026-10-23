"""Genshin game data from Project Amber (gi.yatta.moe) via ambr-py, plus an image cache.

The fetch_* functions block, so the UI calls them through run_async(), which runs
them on a worker thread and hands the result back on the UI thread.
API responses are cached by ambr for an hour; images are cached on disk forever.
"""

import asyncio
import hashlib
import html
import os
import re
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage, QPixmap

from app_info import APP_DIR

# ambr-py and aiohttp take about a second to import. Only downloads need them, so they're loaded on a
# background thread while the window opens instead of delaying it (_api() waits for them if needed).
_api_modules = {}
_api_lock = threading.Lock()


def _api():
    with _api_lock:
        if not _api_modules:
            import ambr
            from aiohttp_client_cache.backends.sqlite import SQLiteBackend
            from aiohttp_client_cache.session import CachedSession
            from loguru import logger

            logger.disable("ambr")  # ambr logs every request at DEBUG level
            _api_modules.update(ambr=ambr, SQLiteBackend=SQLiteBackend, CachedSession=CachedSession)
    return _api_modules


threading.Thread(target=_api, daemon=True, name="preload ambr").start()

HERE = APP_DIR
CACHE_DIR = HERE / ".cache"
IMG_DIR = CACHE_DIR / "img"
ASSETS = "https://gi.yatta.moe/assets/UI/"

ELEMENTS = ["PYRO", "HYDRO", "DENDRO", "ELECTRO", "ANEMO", "CRYO", "GEO"]  # the DPS Log's column order
ELEMENT_COLORS = {
    "PYRO": "#ef7a35",
    "HYDRO": "#4cc2f1",
    "ELECTRO": "#b08fc2",
    "CRYO": "#9fd6e3",
    "ANEMO": "#74c2a8",
    "GEO": "#fab632",
    "DENDRO": "#a5c83b",
}
_ELEMENT_ICON_NAMES = {
    "PYRO": "Fire",
    "HYDRO": "Water",
    "ELECTRO": "Electric",
    "CRYO": "Ice",
    "ANEMO": "Wind",
    "GEO": "Rock",
    "DENDRO": "Grass",
}

_MARKUP = re.compile(r"<[^>]+>|\{LINK#\w+\}|\{/LINK\}")


_LAYOUT_PC = re.compile(r"\{LAYOUT_PC#([^}]*)\}")
_LAYOUT_OTHER = re.compile(r"\{LAYOUT_[A-Z]+#[^}]*\}")


def resolve_layout(text):
    """Fill in the game's text placeholders.

    - Platform wording: '#{LAYOUT_MOBILE#Tap}{LAYOUT_PC#Press}{LAYOUT_PS#Press} DMG' -> 'Press DMG'
    - '{TIMEZONE}' (your server's time zone) -> 'server time'
    A leading '#' only marks that the text contains placeholders, so it is dropped.
    """
    if not text or "{" not in text:
        return text or ""
    text = _LAYOUT_PC.sub(r"\1", text)
    text = _LAYOUT_OTHER.sub("", text)
    text = text.replace("{TIMEZONE}", "server time")
    return text[1:] if text.startswith("#") else text


def clean(text):
    """Strip Project Amber's color/link markup and platform placeholders from game text."""
    return _MARKUP.sub("", resolve_layout(text)).replace("\\n", "\n").strip()


def html_text(text):
    """Game text as safe HTML with line breaks kept."""
    return html.escape(clean(text)).replace("\n", "<br>")


_COLOR_TAG = re.compile(r"&lt;color=#([0-9A-Fa-f]{6})[0-9A-Fa-f]{0,2}&gt;(.*?)&lt;/color&gt;", re.S)
_ITALIC_TAG = re.compile(r"&lt;i&gt;(.*?)&lt;/i&gt;", re.S)
_OTHER_TAG = re.compile(r"&lt;/?[a-zA-Z][^&]*?&gt;")
_LINK_TAG = re.compile(r"\{LINK#(\w+)\}(.*?)\{/LINK\}", re.S)
_HTML_TAG = re.compile(r"(<[^>]+>)")
_NUMBER = re.compile(r"(?<![\w#&.])(\d+(?:\.\d+)?(?:%|s\b)?)")
_ELEMENT_WORD = re.compile(r"\b(Pyro|Hydro|Electro|Cryo|Anemo|Geo|Dendro)\b")
LINK_COLOR = "#e6c88f"

# Terms explained on hover. The game's own glossary entries ("N..." keys) are added per character by
# fetch_character_glossary(); MECHANICS are short Record Book summaries of recurring game systems
# the game text mentions without explaining.
GLOSSARY = {}
CHAR_GLOSSARY = {}  # char_id -> [(term, description)] from that character's game glossary
MECHANICS = {
    "Nightsoul's Blessing": "Natlan's special state. While in it, the character's attacks are Nightsoul-aligned and "
    "most of their abilities drain Nightsoul points; the state ends when the points run out or its duration ends.",
    "Nightsoul points": "The resource a Natlan character spends while in Nightsoul's Blessing.",
    "Phlogiston": "Natlan's energy resource, consumed by some characters' special movement and abilities while in "
    "Nightsoul's Blessing.",
    "Bond of Life": "A marker that absorbs healing: incoming healing first clears the Bond of Life before restoring "
    "any HP. Some abilities grow stronger with the amount of Bond of Life.",
    "Ousia": "One of Fontaine's two kinds of Arkhe (the other is Pneuma). Some attacks are aligned with one of them "
    "and periodically trigger an extra Arkhe attack.",
    "Pneuma": "One of Fontaine's two kinds of Arkhe (the other is Ousia). Some attacks are aligned with one of them "
    "and periodically trigger an extra Arkhe attack.",
    "Moonsign": "Nod-Krai's party-wide mechanic. Each Moonsign character in the party raises the Moonsign level "
    "(Nascent Gleam, then Ascendant Gleam at 2 or more), unlocking extra effects and Lunar reactions.",
    "Lunar-Charged": "A Lunar reaction: Electro-Charged transformed by Moonsign characters, dealing its own reaction "
    "DMG.",
    "Lunar-Bloom": "A Lunar reaction: Bloom transformed by Moonsign characters, dealing its own reaction DMG.",
    "Lunar-Crystallize": "A Lunar reaction: Crystallize transformed by Moonsign characters, dealing its own "
    "reaction DMG.",
}
_MECHANIC_KEYS = {term: "m" + str(i) for i, term in enumerate(MECHANICS)}
_MECHANIC_WORD = re.compile(
    r"(?<![\w-])(" + "|".join(re.escape(html.escape(t)) for t in sorted(MECHANICS, key=len, reverse=True)) + r")(?![\w-])"
)
for _term, _key in _MECHANIC_KEYS.items():
    GLOSSARY[_key] = (_term, MECHANICS[_term], "Record Book summary")


def _decorate(s):
    """Bold numbers, color bare element names and link known mechanics in the text between tags."""
    out = []
    span_depth = anchor_depth = 0
    for part in _HTML_TAG.split(s):
        if part.startswith("<"):
            if part.startswith("<span"):
                span_depth += 1
            elif part == "</span>":
                span_depth -= 1
            elif part.startswith("<a "):
                anchor_depth += 1
            elif part == "</a>":
                anchor_depth -= 1
            out.append(part)
            continue
        part = _NUMBER.sub(r"<b>\1</b>", part)  # first, so it never touches the markup added below
        if not anchor_depth:
            part = _MECHANIC_WORD.sub(
                lambda m: f"<a href='term:{_MECHANIC_KEYS[html.unescape(m.group(1))]}' "
                f"style='color:{LINK_COLOR}; text-decoration:underline'><b>{m.group(1)}</b></a>",
                part,
            )
        if not span_depth:
            part = _ELEMENT_WORD.sub(
                lambda m: f"<span style='color:{ELEMENT_COLORS[m.group(1).upper()]}'><b>{m.group(1)}</b></span>", part
            )
        out.append(part)
    return "".join(out)


def rich_html(text):
    """Game text as HTML: the game's colored keywords in bold, numbers in bold, element names in their
    color, and glossary terms as links whose explanation shows on hover (see glossary_html)."""
    s = html.escape(resolve_layout(text).replace("\\n", "\n"))

    def link(m):
        key, inner = m.group(1), m.group(2)
        if key not in GLOSSARY:
            return inner
        return f"<a href='term:{key}' style='color:{LINK_COLOR}; text-decoration:underline'>{inner}</a>"

    s = _LINK_TAG.sub(link, s)
    s = _COLOR_TAG.sub(r"<span style='color:#\1'><b>\2</b></span>", s)
    s = _ITALIC_TAG.sub(r"<i>\1</i>", s)
    s = _OTHER_TAG.sub("", s)
    return _decorate(s.strip()).replace("\n", "<br>")


def glossary_html(href):
    """Tooltip HTML for a 'term:<key>' link, or '' if unknown."""
    if not href.startswith("term:"):
        return ""
    entry = GLOSSARY.get(href[5:])
    if not entry:
        return ""
    name, description, source = entry
    body = description if source != "Game glossary" else _GLOSSARY_LINK.sub(r"\1", description)
    return (
        "<table width='340'><tr><td>"
        f"<b style='color:{LINK_COLOR}'>{html.escape(name)}</b><br>"
        f"{rich_html(body) if source == 'Game glossary' else html.escape(body).replace(chr(10), '<br>')}"
        f"<br><span style='color:#8a91a0; font-size:8pt'>{source}</span>"
        "</td></tr></table>"
    )


_GLOSSARY_LINK = re.compile(r"\{LINK#\w+\}(.*?)\{/LINK\}", re.S)
_GLOSSARY_PARAM = re.compile(r"\{PARAM#([^}]+)\}")


def _fill_params(text, params):
    """'{PARAM#P1222101|6S100}' -> the value from the entry's params (times the multiplier)."""
    values = {}
    for p in params or []:
        sp = p.get("skillParam") or {}
        value = (sp.get("paramValue") or 0) * (sp.get("paramMultiplier") or 1)
        values[p.get("skillFull")] = f"{value:.1f}".rstrip("0").rstrip(".")
    return _GLOSSARY_PARAM.sub(lambda m: values.get(m.group(1), "?"), text)


@lru_cache(maxsize=None)
def fetch_character_markup(char_id):
    """Talent and constellation descriptions with the game's markup intact, keyed by cleaned name,
    as (texts, buffed). `buffed` holds the updated text of kits the game has reworked
    ("descriptionBuff", what Project Amber's Buff toggle shows), only where it differs.

    ambr-py strips the color and link tags from its models, so this reads the same (cached) API
    response directly. It also loads the character's glossary of linked terms (newer characters
    have one) into GLOSSARY.
    """
    import unreleased

    if unreleased.is_character(char_id):
        texts, buffed, glossary = unreleased.character_markup(char_id)
        CHAR_GLOSSARY[char_id] = []
        for key, name, description in glossary:
            GLOSSARY[key] = (clean(name or key), description, "Game glossary")
            CHAR_GLOSSARY[char_id].append((clean(name or key), description))
        return texts, buffed
    data = _run(lambda api: api._request(f"avatar/{char_id}", use_cache=True)).get("data") or {}
    effects = (data.get("dictionary") or {}).get("effectsInfo") or {}
    CHAR_GLOSSARY[char_id] = []
    for key, e in effects.items():
        description = _fill_params(e.get("description") or "", e.get("params"))
        GLOSSARY[key] = (clean(e.get("name") or key), description, "Game glossary")
        CHAR_GLOSSARY[char_id].append((clean(e.get("name") or key), description))
    texts, buffed = {}, {}
    for section in ("talent", "constellation"):
        entries = data.get(section) or {}
        for entry in entries.values() if isinstance(entries, dict) else entries:
            if entry.get("name") and entry.get("description"):
                name = clean(entry["name"])
                texts[name] = entry["description"]
                buff = entry.get("descriptionBuff")
                if buff and clean(buff) != clean(entry["description"]):
                    buffed[name] = buff
    return texts, buffed


@lru_cache(maxsize=None)
def fetch_weapon_markup(weapon_id):
    """A weapon's refinement descriptions (R1 first) with the game's color markup intact."""
    import unreleased

    if unreleased.is_weapon(weapon_id):
        return unreleased.weapon_markup(weapon_id)
    data = _run(lambda api: api._request(f"weapon/{int(weapon_id)}", use_cache=True)).get("data") or {}
    affix = next(iter((data.get("affix") or {}).values()), None) or {}
    upgrades = affix.get("upgrade") or {}
    return [upgrades[k] for k in sorted(upgrades, key=int)]


def pretty(name):
    return name.replace("_", " ").title()


STAT_NAMES = {
    "FIGHT_PROP_BASE_HP": "Base HP",
    "FIGHT_PROP_BASE_ATTACK": "Base ATK",
    "FIGHT_PROP_BASE_DEFENSE": "Base DEF",
    "FIGHT_PROP_HP_PERCENT": "HP",
    "FIGHT_PROP_ATTACK_PERCENT": "ATK",
    "FIGHT_PROP_DEFENSE_PERCENT": "DEF",
    "FIGHT_PROP_CRITICAL": "CRIT Rate",
    "FIGHT_PROP_CRITICAL_HURT": "CRIT DMG",
    "FIGHT_PROP_ELEMENT_MASTERY": "Elemental Mastery",
    "FIGHT_PROP_CHARGE_EFFICIENCY": "Energy Recharge",
    "FIGHT_PROP_HEAL_ADD": "Healing Bonus",
    "FIGHT_PROP_PHYSICAL_ADD_HURT": "Physical DMG Bonus",
    "FIGHT_PROP_FIRE_ADD_HURT": "Pyro DMG Bonus",
    "FIGHT_PROP_WATER_ADD_HURT": "Hydro DMG Bonus",
    "FIGHT_PROP_ELEC_ADD_HURT": "Electro DMG Bonus",
    "FIGHT_PROP_ICE_ADD_HURT": "Cryo DMG Bonus",
    "FIGHT_PROP_WIND_ADD_HURT": "Anemo DMG Bonus",
    "FIGHT_PROP_ROCK_ADD_HURT": "Geo DMG Bonus",
    "FIGHT_PROP_GRASS_ADD_HURT": "Dendro DMG Bonus",
}
FLAT_STATS = {"FIGHT_PROP_BASE_HP", "FIGHT_PROP_BASE_ATTACK", "FIGHT_PROP_BASE_DEFENSE", "FIGHT_PROP_ELEMENT_MASTERY"}


def stat_name(prop):
    return STAT_NAMES.get(prop, pretty((prop or "").replace("FIGHT_PROP_", "")))


def format_stat(prop, value):
    return f"{value:,.0f}" if prop in FLAT_STATS else f"{value * 100:.1f}%"


def character_stats(detail, curve, level):
    """Base HP/ATK/DEF and the ascension stat at a level (1–90), as {prop: value}."""
    if getattr(detail, "level_stats", None):
        import unreleased

        return unreleased.stats_at(detail.level_stats, level)
    promotes = sorted(detail.upgrade.promotes, key=lambda p: p.unlock_max_level)
    promote = next((p for p in promotes if p.unlock_max_level >= level), promotes[-1])
    bonus = {s.id: s.value for s in (promote.add_stats or [])}
    stats = {}
    for base in detail.upgrade.base_stats:
        mult = curve[str(level)]["curveInfos"][base.growth_type]
        stats[base.prop_type] = base.init_value * mult + bonus.get(base.prop_type, 0)
    special = getattr(detail.special_stat, "value", detail.special_stat)
    stats[special] = bonus.get(special, 0)
    return stats


def real_talents(talents):
    """Talents without the blank placeholder entries some characters have (Vesna's data, for example,
    includes empty ones for the Sprint and Jump buttons)."""
    return [t for t in talents if (t.name or "").strip() or (t.description or "").strip()]


def talent_labels(talents):
    """In-game category for each talent. ambr's own `type` field doesn't match, so go by order.
    Pass real_talents(...) so blank placeholders don't shift the labels."""
    levelled = [i for i, t in enumerate(talents) if t.upgrades]
    burst = levelled[-1] if levelled else -1
    labels = []
    # up to the burst: Normal Attack, Elemental Skill, then special movement (Ayaka's sprint, Ororon's jump)
    for i in range(burst + 1):
        if i == 0:
            labels.append("Normal Attack")
        elif i == burst:
            labels.append("Elemental Burst")
        elif i == 1:
            labels.append("Elemental Skill")
        else:
            labels.append("Special Jump" if "jump" in (talents[i].name or "").lower() else "Alternate Sprint")
    # after it: the two ascension passives, then the rest. Special passives are named by their category
    # ("Night Realm's Gift: ..."). A single other one is the utility passive; when there are two, their
    # order doesn't say which is which, so both get the neutral label.
    passives = talents[burst + 1:]

    def category(t):
        name = clean(t.name)
        return next((c for c in PASSIVE_CATEGORIES if name.startswith(c + ":")), None)

    others = [t for t in passives[2:] if not category(t)]
    for n, t in enumerate(passives):
        if n < 2:
            labels.append(("1st", "4th")[n] + " Ascension Passive")
        else:
            labels.append(category(t) or ("Utility Passive" if len(others) == 1 else "Passive Talent"))
    return labels


# Passive kinds the game names with a prefix, like "Night Realm's Gift: Exhaust Mode".
PASSIVE_CATEGORIES = ("Night Realm's Gift", "Moonsign Benediction", "Witch's Eve Rite", "Stellar Jubilee")
ACTIVE_LABELS = ("Normal Attack", "Elemental Skill", "Alternate Sprint", "Special Jump", "Elemental Burst")


_PARAM = re.compile(r"\{param(\d+):([A-Z0-9]+)\}")


def format_multiplier(template, params):
    """Fill a talent attribute template like '{param1:F1P}+{param2:F1P}' with level values."""

    def one(m):
        value = params[int(m.group(1)) - 1]
        fmt = m.group(2)
        if fmt == "I":
            return f"{value:,.0f}"
        decimals = int(fmt[1]) if fmt.startswith("F") and fmt[1:2].isdigit() else 0
        if fmt.endswith("P"):
            return f"{value * 100:.{decimals}f}%"
        return f"{value:,.{decimals}f}"

    return _PARAM.sub(one, template)


def element_icon_url(element):
    return f"{ASSETS}UI_Buff_Element_{_ELEMENT_ICON_NAMES[element]}.png"


_WEAPON_TYPE_NAMES = {"WEAPON_SWORD_ONE_HAND": "Sword", "WEAPON_CLAYMORE": "Claymore", "WEAPON_POLE": "Polearm",
                      "WEAPON_BOW": "Bow", "WEAPON_CATALYST": "Catalyst"}


def weapon_type_name(raw):
    return _WEAPON_TYPE_NAMES.get(raw, raw)


# Weapon types in the game's own order, for filter buttons.
WEAPON_TYPES = ["WEAPON_SWORD_ONE_HAND", "WEAPON_CLAYMORE", "WEAPON_POLE", "WEAPON_BOW", "WEAPON_CATALYST"]


def weapon_type_icon_url(raw):
    name = {"Polearm": "Pole"}.get(weapon_type_name(raw), weapon_type_name(raw))
    return f"{ASSETS}UI_GachaTypeIcon_{name}.png"


@dataclass
class CharInfo:
    id: str
    name: str
    element: str  # one of ELEMENTS
    weapon_type: str  # raw WeaponType value, e.g. WEAPON_SWORD_ONE_HAND
    rarity: int
    icon: str
    region: str
    release: object = None  # datetime, or None if Project Amber has no date

    @property
    def splash(self):
        return self.icon.replace("UI_AvatarIcon_", "UI_Gacha_AvatarImg_")


@dataclass
class WeaponInfo:
    id: int
    name: str
    type: str
    rarity: int
    icon: str
    release: tuple = (0, 0)  # sort key, larger = newer (see _release_order)


@dataclass
class ArtifactInfo:
    id: int
    name: str
    rarity: int  # highest rarity the set comes in
    icon: str
    bonuses: list  # set effect texts, 2-piece first
    release: tuple = (0, 0)  # sort key, larger = newer (see _release_order)


@dataclass
class GameIndex:
    characters: dict  # id -> CharInfo
    weapons: dict  # id -> WeaponInfo
    artifacts: dict  # id -> ArtifactInfo
    unreleased: set = field(default_factory=set)  # ids of the unreleased characters and weapons (unreleased.py)


# ---------- API ----------
def _run(fn):
    api_modules = _api()

    async def main():
        CACHE_DIR.mkdir(exist_ok=True)
        cache = api_modules["SQLiteBackend"](str(CACHE_DIR / "ambr-cache.db"), expire_after=3600)
        async with api_modules["CachedSession"](cache=cache) as session, api_modules["ambr"].AmbrAPI(session=session) as api:
            return await fn(api)

    return asyncio.run(main())


def _release_order(changelog, kind):
    """{item id: changelog entry number} from Project Amber's changelog, which lists the weapons and
    artifact sets each game version added (from 3.0 on). Items older than 3.0 aren't listed."""
    order = {}
    for key, entry in (changelog or {}).items():
        for item_id in (entry.get("items") or {}).get(kind) or []:
            try:
                order[int(str(item_id).split("-")[0])] = int(key)
            except ValueError:
                pass
    return order


TWINS = ("Aether", "Lumine")


def for_traveler(index, twin, keep=(), show_unreleased=False):
    """The index with only one Traveler twin's entries (the other's are left out of every list), and
    unreleased characters and weapons only when show_unreleased, except ids in keep (e.g. a logged
    Traveler of the other twin, so its record still shows)."""
    hidden = tuple(f"{t} (" for t in TWINS if t != twin)

    def kept(cid):
        return cid in keep or str(cid) in keep

    return GameIndex(
        characters={cid: c for cid, c in index.characters.items()
                    if (not c.name.startswith(hidden) and (show_unreleased or cid not in index.unreleased)) or kept(cid)},
        weapons={wid: w for wid, w in index.weapons.items()
                 if show_unreleased or wid not in index.unreleased or kept(wid)},
        artifacts=index.artifacts,
        unreleased=index.unreleased,
    )


def fetch_index():
    async def changelog(api):
        try:
            return (await api._request("changelog", static=True, use_cache=True)).get("data")
        except Exception:  # ordering falls back to ids without it
            return {}

    async def go(api):
        return await asyncio.gather(
            api.fetch_characters(), api.fetch_weapons(), api.fetch_artifact_sets(), changelog(api)
        )

    chars, weapons, artifacts, log = _run(go)
    weapon_order = _release_order(log, "weapon")
    artifact_order = _release_order(log, "reliquary")
    characters = {}
    for c in chars:
        element = c.element.name
        if c.beta or element not in ELEMENTS:
            continue
        name = c.name
        if c.name == "Traveler":  # one entry per twin and element; 10000005 is Aether, 10000007 is Lumine
            twin = "Lumine" if str(c.id).startswith("10000007") else "Aether"
            name = f"{twin} ({pretty(element)})"
        characters[c.id] = CharInfo(c.id, name, element, c.weapon_type.value, c.rarity, c.icon, c.region or "", c.release)
    weapon_infos = {
        w.id: WeaponInfo(w.id, w.name, w.type, w.rarity, w.icon, (weapon_order.get(w.id, 0), w.id % 100))
        for w in weapons
        if w.id < 100000
    }
    # unreleased characters and weapons (shown when the nav's Unreleased toggle is on); the app works
    # without them if that site is down
    unreleased_ids = set()
    try:
        import unreleased

        # only what Project Amber actually serves as released (not its beta entries): the moment it does,
        # that copy is used instead and the Lunaris one is dropped, same id, so logged records carry over
        new_chars, new_weapons = unreleased.fetch_lists(
            {c.name for c in chars if not c.beta and c.element.name in ELEMENTS},
            {w.name for w in weapon_infos.values()},
            set(characters) | set(weapon_infos),
        )
        characters.update(new_chars)
        weapon_infos.update(new_weapons)
        unreleased_ids = set(new_chars) | set(new_weapons)
    except Exception:
        pass
    return GameIndex(
        characters=characters,
        # Release order: the version that added it, then (for pre-3.0 items, and within a version) the
        # id's running number, which the game assigns in release order within a weapon type and rarity.
        # Six-digit ids are weapon skins (e.g. "Serpent Devourer", "Exaiphanes Blade" 390002), not weapons.
        weapons=weapon_infos,
        artifacts={
            a.id: ArtifactInfo(
                a.id, a.name, max(a.rarity_list), a.icon, [clean(x.effect) for x in a.affix_list],
                (artifact_order.get(a.id, 0), a.id),
            )
            for a in artifacts
        },
        unreleased=unreleased_ids,
    )


@lru_cache(maxsize=None)
def fetch_character_detail(char_id):
    import unreleased

    if unreleased.is_character(char_id):
        return unreleased.character_detail(char_id)
    return _run(lambda api: api.fetch_character_detail(char_id))


@lru_cache(maxsize=None)
def fetch_avatar_curve():
    return _run(lambda api: api.fetch_avatar_curve())


@lru_cache(maxsize=None)
def fetch_weapon_detail(weapon_id):
    import unreleased

    if unreleased.is_weapon(weapon_id):
        return unreleased.weapon_detail(weapon_id)
    return _run(lambda api: api.fetch_weapon_detail(int(weapon_id)))


@lru_cache(maxsize=None)
def fetch_artifact_detail(set_id):
    return _run(lambda api: api.fetch_artifact_set_detail(int(set_id)))


@lru_cache(maxsize=None)
def fetch_weapon_curve():
    return _run(lambda api: api._request("weaponCurve", static=True, use_cache=True))["data"]


def weapon_max_level(detail):
    if getattr(detail, "level_stats", None):
        return max(detail.level_stats)
    return max(p.unlock_max_level for p in detail.upgrade.promotes)


def weapon_stats(detail, curve, level):
    """Base ATK and the secondary stat at a level, as {prop: value} (same math as character_stats)."""
    if getattr(detail, "level_stats", None):
        import unreleased

        return unreleased.stats_at(detail.level_stats, level)
    promotes = sorted(detail.upgrade.promotes, key=lambda p: p.unlock_max_level)
    promote = next((p for p in promotes if p.unlock_max_level >= level), promotes[-1])
    bonus = {s.id: s.value for s in (promote.add_stats or [])}
    stats = {}
    for base in detail.upgrade.base_stats:
        if not base.prop_type or base.prop_type == "FIGHT_PROP_NONE":
            continue
        mult = curve[str(level)]["curveInfos"].get(base.growth_type, 1)
        stats[base.prop_type] = base.init_value * mult + bonus.get(base.prop_type, 0)
    return stats


BANNER_URL = "https://api.ennead.cc/mihoyo/genshin/calendar"


def refresh_index():
    """Forget every cached API response and fetch the character/weapon/artifact lists again, so new
    releases show up without waiting for the hour-long cache to run out. Images stay cached."""
    for fn in (
        fetch_character_detail, fetch_avatar_curve, fetch_weapon_detail, fetch_artifact_detail,
        fetch_weapon_curve, fetch_character_markup, fetch_weapon_markup,
    ):
        fn.cache_clear()
    import unreleased

    unreleased.clear_cache()
    cache = CACHE_DIR / "ambr-cache.db"
    try:
        cache.unlink(missing_ok=True)
    except OSError:  # in use by a background request; ambr's own expiry still applies
        pass
    return fetch_index()


def fetch_banners():
    """The wishes running right now, from a public Genshin event calendar (api.ennead.cc), as a list
    of {"name", "end", "characters": [(id, rarity)], "weapons": [(id, rarity)]}, characters first."""
    import json
    import time

    req = urllib.request.Request(BANNER_URL, headers={"User-Agent": "RecordBook/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.load(resp)
    now = time.time()
    banners = []
    for b in data.get("banners") or []:
        if not (b.get("start_time", 0) <= now <= b.get("end_time", 0)):
            continue
        banners.append({
            "name": b.get("name") or "Event Wish",
            "start": b.get("start_time") or 0,
            "end": b["end_time"],
            "characters": [(c["id"], int(c.get("rarity") or 4)) for c in b.get("characters") or []],
            "weapons": [(w["id"], int(w.get("rarity") or 4)) for w in b.get("weapons") or []],
        })
    banners.sort(key=lambda b: (not b["characters"], b["name"]))
    return banners


WISH_LIST_URL = ("https://genshin-impact.fandom.com/api.php?action=parse&page=Wish/List&prop=text&format=json")


def fetch_wish_art():
    """The current wishes' banner pictures from the Genshin wiki (Fandom's Wish/List, its newest phase), as
    [{"title", "image", "kind": 'character' / 'weapon' / 'chronicled'}] in the wiki's order."""
    import json

    req = urllib.request.Request(WISH_LIST_URL, headers={"User-Agent": "RecordBook/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        page = json.load(resp)["parse"]["text"]["*"]
    start = page.find("Event Wishes")
    rows = re.findall(r"<tr>(.*?)</tr>", page[start:], re.S)
    found, phases = [], 0
    for row in rows:
        if "<th colspan" in row:  # a phase's heading: the newest one comes first
            phases += 1
            if phases > 1:
                break
            continue
        for name, attrs in re.findall(r'data-image-name="([^"]+)"([^>]*)', row):
            kind = ("weapon" if name.startswith("Epitome Invocation")
                    else "chronicled" if name.startswith("Chronicled") else "character")
            src = re.search(r'data-src="([^"]+)"', attrs)
            src = src.group(1) if src else None
            if src is None:
                tag = row[:row.find(f'data-image-name="{name}"')]
                src = re.findall(r'src="(https://static[^"]+)"', tag)
                src = src[-1] if src else None
            if not src:
                continue
            image = re.sub(r"/scale-to-width-down/\d+", "/scale-to-width-down/640", html.unescape(src))
            image += "&format=original"  # PNG (the wiki otherwise sends WebP)
            title = html.unescape(re.sub(r"\s*\d{4}-\d{2}-\d{2}.*$", "", name.rsplit(".", 1)[0]))
            found.append({"title": title, "image": image, "kind": kind})
    return found


# ---------- images ----------
_UNCHECKED_IMAGE_HOSTS = ("https://static.wikia.nocookie.net/",)


def fetch_image(url):
    """Return image bytes from the disk cache or the web, or None if it doesn't exist."""
    path = IMG_DIR / (hashlib.sha1(url.encode()).hexdigest()[:20] + ".png")
    if path.exists():
        return path.read_bytes()
    headers = {"User-Agent": "RecordBook/1.0"}
    if "lunaris.moe" in url:
        headers["Referer"] = "https://gi.yatta.moe/"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except urllib.error.URLError as e:
        # the wiki's picture host has served an expired certificate: for its banner pictures only (no
        # sign-in or personal data involved), read them without the certificate check
        import ssl

        if not (isinstance(e.reason, ssl.SSLCertVerificationError) and url.startswith(_UNCHECKED_IMAGE_HOSTS)):
            raise
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=30, context=context) as resp:
            data = resp.read()
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{threading.get_ident()}.tmp")  # never let a reader see a half-written file
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return data


# ---------- running work off the UI thread ----------
class _Bridge(QObject):
    done = Signal(object, object, object)  # callback, result, error


_pool = ThreadPoolExecutor(max_workers=6)
_bulk_pool = ThreadPoolExecutor(max_workers=4)  # database-page thumbnails, so they never delay what you're looking at
_bridge = None


def _deliver(callback, result, error):
    try:
        callback(result, error)
    except RuntimeError as e:  # the widget that asked was closed meanwhile
        if "already deleted" not in str(e):
            raise


def run_async(fn, callback, bulk=False):
    """Run fn() on a worker thread, then callback(result, error) on the UI thread."""
    global _bridge
    if _bridge is None:
        _bridge = _Bridge()
        _bridge.done.connect(_deliver)

    def work():
        try:
            result, error = fn(), None
        except Exception as e:
            result, error = None, e
        _bridge.done.emit(callback, result, error)

    (_bulk_pool if bulk else _pool).submit(work)


_pixmaps = {}  # url -> QPixmap or None
_waiting = {}  # url -> callbacks waiting for that url
_bulk_only = set()  # urls whose only pending fetch is in the slow bulk queue


_tracked = None  # while a page is being built: the images it asked for that weren't cached yet


def track_images():
    """Start recording the uncached images requested from now on; returns the set they go into.
    Call stop_tracking() when done, then when_loaded() to wait for them."""
    global _tracked
    _tracked = set()
    return _tracked


def stop_tracking():
    global _tracked
    _tracked = None


def when_loaded(urls, callback):
    """Call callback() once every url has finished loading (successfully or not)."""
    left = [url for url in urls if url not in _pixmaps]
    if not left:
        callback()
        return
    remaining = [len(left)]

    def one_done(_pm):
        remaining[0] -= 1
        if remaining[0] == 0:
            callback()

    for url in left:
        _waiting.setdefault(url, []).append(one_done)


def load_pixmap(url, callback, fallback=None, bulk=False):
    """Call callback(QPixmap or None) once the image is available (immediately if cached).

    bulk=True queues it behind everything else (for big thumbnail grids).
    """
    if url in _pixmaps:
        callback(_pixmaps[url])
        return
    if _tracked is not None and url:
        _tracked.add(url)
    if url in _waiting:
        _waiting[url].append(callback)
        if not bulk and url in _bulk_only:  # someone is looking at it now: jump the queue
            _bulk_only.discard(url)
            _start_fetch(url, fallback, bulk=False)
        return
    _waiting[url] = [callback]
    if bulk:
        _bulk_only.add(url)
    _start_fetch(url, fallback, bulk)


def _start_fetch(url, fallback, bulk):
    def fetch():
        data = fetch_image(url)
        if data is None and fallback:
            data = fetch_image(fallback)
        return QImage.fromData(data) if data else None  # decode off the UI thread

    def done(image, _error):
        if url in _pixmaps:  # the other queue's copy already delivered it
            return
        _bulk_only.discard(url)
        pixmap = QPixmap.fromImage(image) if image is not None and not image.isNull() else None
        _pixmaps[url] = pixmap
        for cb in _waiting.pop(url, []):
            _deliver(lambda r, e, cb=cb: cb(r), pixmap, None)

    run_async(fetch, done, bulk=bulk)
