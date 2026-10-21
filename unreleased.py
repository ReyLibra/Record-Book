"""Unreleased characters and weapons: what Project Amber's "Unreleased Content" setting shows.

Project Amber doesn't serve these itself; like the website, this reads them from api.lunaris.moe and
turns them into the same shapes as Project Amber's data (CharInfo / WeaponInfo for the lists, and
detail objects with the attributes the pages read), so the rest of the app needs no special cases
beyond gamedata.fetch_* asking here first. The data is datamined and changes between beta builds.
"""

import json
import re
import threading
import urllib.request
from datetime import datetime
from functools import lru_cache
from types import SimpleNamespace as NS

import gamedata  # (only imported from gamedata's own functions, once it has loaded)

BASE = "https://api.lunaris.moe/data/"
ASSETS = BASE + "assets/"
_HEADERS = {"User-Agent": "RecordBook/1.0", "Referer": "https://gi.yatta.moe/"}
# sorts after every released character / weapon ("newest" first puts these at the top)
FUTURE = datetime(2100, 1, 1)
# entries the list has that aren't new playable characters
_NOT_NEW = ("Traveler", "Manekin", "Manekina")
# released quest variants Project Amber's list leaves out (the website skips the same ones)
_NOT_NEW_WEAPONS = {11419, 11420, 11421, 11429}

CHARACTER_IDS = set()  # str ids of unreleased characters in the last list read
WEAPON_IDS = set()  # int ids of unreleased weapons
_lock = threading.Lock()


@lru_cache(maxsize=None)
def _get(path):
    req = urllib.request.Request(BASE + path, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def _version():
    return _get("version.json")["version"]


def clear_cache():
    _get.cache_clear()
    character_detail.cache_clear()
    character_markup.cache_clear()
    weapon_detail.cache_clear()


def fetch_lists(known_characters, known_weapons, known_ids=()):
    """({id: CharInfo}, {id: WeaponInfo}) for characters and weapons the released lists don't have.
    known_*: the names already in Project Amber's lists (alternate copies of those are skipped);
    known_ids: their ids. Once Project Amber has an entry, it isn't taken from here any more."""
    known_ids = set(known_ids)
    version = _version()
    chars, weapons = {}, {}
    for cid, c in _get(f"{version}/charlist.json").items():
        name = c.get("enName") or ""
        element = (c.get("element") or "").upper()
        if cid in known_ids or name in known_characters or name in _NOT_NEW or element not in gamedata.ELEMENTS:
            continue
        chars[cid] = UnreleasedChar(
            cid, name, element, c.get("weaponType") or "", 5 if c.get("qualityType") == "QUALITY_ORANGE" else 4,
            f"{ASSETS}avataricon/UI_AvatarIcon_{_icon_name(c)}.webp", "", FUTURE,
            gacha=c.get("GachaImg") or "",
        )
    for wid, w in _get(f"{version}/weaponlist.json").items():
        name = w.get("enName") or ""
        if not wid.isdigit() or int(wid) in known_ids or name in known_weapons or int(wid) in _NOT_NEW_WEAPONS:
            continue
        weapons[int(wid)] = gamedata.WeaponInfo(
            int(wid), name, w.get("weaponType") or "", _rarity(w.get("qualityType")),
            f"{ASSETS}weaponicon/{w.get('weaponIcon')}.webp", (10 ** 9, int(wid) % 100),
        )
    with _lock:
        CHARACTER_IDS.clear()
        CHARACTER_IDS.update(chars)
        WEAPON_IDS.clear()
        WEAPON_IDS.update(weapons)
    return chars, weapons


def _icon_name(c):
    return (c.get("CardImg") or "").replace("UI_Gacha_AvatarIcon_", "") or c.get("enName", "")


def _rarity(quality):
    return {"QUALITY_ORANGE": 5, "QUALITY_PURPLE": 4, "QUALITY_BLUE": 3, "QUALITY_GREEN": 2}.get(quality, 1)


def is_character(char_id):
    return str(char_id) in CHARACTER_IDS


def is_weapon(weapon_id):
    try:
        return int(weapon_id) in WEAPON_IDS
    except (TypeError, ValueError):
        return False


class UnreleasedChar(gamedata.CharInfo):
    """A CharInfo whose splash art lives on lunaris' own path."""

    def __init__(self, *args, gacha=""):
        super().__init__(*args)
        self.gacha = gacha

    @property
    def splash(self):
        return f"{ASSETS}gachaimg/{self.gacha}.webp" if self.gacha else self.icon


# ----- stats -----
_STATS = {
    "hp": "FIGHT_PROP_BASE_HP", "atk": "FIGHT_PROP_BASE_ATTACK", "def": "FIGHT_PROP_BASE_DEFENSE",
    "em": "FIGHT_PROP_ELEMENT_MASTERY", "elemental mastery": "FIGHT_PROP_ELEMENT_MASTERY",
    "crit dmg": "FIGHT_PROP_CRITICAL_HURT", "crit rate": "FIGHT_PROP_CRITICAL", "atk%": "FIGHT_PROP_ATTACK_PERCENT",
    "hp%": "FIGHT_PROP_HP_PERCENT", "def%": "FIGHT_PROP_DEFENSE_PERCENT", "energy recharge": "FIGHT_PROP_CHARGE_EFFICIENCY",
    "healing bonus": "FIGHT_PROP_HEAL_ADD", "physical dmg": "FIGHT_PROP_PHYSICAL_ADD_HURT",
    "pyro dmg": "FIGHT_PROP_FIRE_ADD_HURT", "hydro dmg": "FIGHT_PROP_WATER_ADD_HURT", "electro dmg": "FIGHT_PROP_ELEC_ADD_HURT",
    "cryo dmg": "FIGHT_PROP_ICE_ADD_HURT", "anemo dmg": "FIGHT_PROP_WIND_ADD_HURT", "geo dmg": "FIGHT_PROP_ROCK_ADD_HURT",
    "dendro dmg": "FIGHT_PROP_GRASS_ADD_HURT",
}


def _stat(key, value):
    """('CRIT DMG%', '38.4') -> ('FIGHT_PROP_CRITICAL_HURT', 0.384); None for keys it doesn't know."""
    k = key.strip().lower()
    percent = k.endswith("%")
    k = k.rstrip("%").replace(" bonus", "").strip()
    prop = _STATS.get(k + "%") if percent and k in ("atk", "hp", "def") else _STATS.get(k)
    if not prop:
        return None, None
    try:
        number = float(str(value).rstrip("%"))
    except ValueError:
        return None, None
    return prop, number / 100 if percent else number


def _level_table(rows):
    """{level: {prop: value}} from per-level rows, taking the first (lowest-ascension) row of a level:
    the same choice Project Amber's curves make at the level caps."""
    table = {}
    for row in rows:
        level = int(row.get("level") or 0)
        if level in table:
            continue
        stats = {}
        for key, value in row.items():
            if key in ("level", "ascension"):
                continue
            prop, number = _stat(key, value)
            if prop:
                stats[prop] = number
        table[level] = stats
    return table


def stats_at(table, level):
    """The row for a level, or the closest level below it."""
    levels = sorted(table)
    best = next((lv for lv in reversed(levels) if lv <= level), levels[0])
    return dict(table[best])


# ----- characters -----
def _number(text):
    m = re.search(r"[\d.]+", str(text or ""))
    return float(m.group()) if m else None


def _talent(skill, levelled):
    mult = skill.get("multipliers") or {}
    rows = [k for k in mult if k not in ("CD", "Energy Cost")]
    count = max((len(v) for v in mult.values()), default=0) if levelled else 0
    upgrades = [
        NS(level=i + 1, description=[f"{k}|{mult[k][i]}" for k in rows if i < len(mult[k])], params=[])
        for i in range(count)
    ]
    cost = _number((mult.get("Energy Cost") or [None])[0])
    return NS(
        name=skill.get("name") or "", description=skill.get("description") or "",
        icon=f"{ASSETS}skills/{skill.get('icon')}.webp", upgrades=upgrades,
        cooldown=_number((mult.get("CD") or [None])[0]), cost=int(cost) if cost else None,
    )


@lru_cache(maxsize=None)
def character_detail(char_id):
    """A character's detail in the shape of Project Amber's (talents, constellations, info…)."""
    raw = _get(f"{_version()}/en/char/{char_id}.json")
    info = raw.get("info") or {}
    skills = raw.get("skills") or {}
    talents = [_talent(skills[k], True) for k in ("normalattack", "elementalskill", "elementalburst") if skills.get(k)]
    passives = raw.get("passives") or {}
    talents += [_talent(passives[k], False) for k in sorted(passives)]
    constellations = raw.get("constellations") or {}
    month, _, day = (info.get("birthday") or "0/0").partition("/")
    known = lambda v: "" if not v or "???" in str(v) else v  # noqa: E731
    return NS(
        unreleased=True,
        info=NS(title=info.get("title") or "", detail=info.get("description") or "",
                constellation=info.get("constellation") or "", native=known(info.get("affiliation")),
                cv=[NS(lang=lang, va=va) for lang, va in (info.get("cv") or {}).items() if known(va)]),
        birthday=NS(month=int(month or 0), day=int(day or 0)),
        region="", release=None,
        talents=talents,
        constellations=[
            NS(name=c.get("name") or "", description=c.get("description") or "",
               icon=f"{ASSETS}skills/{c.get('icon')}.webp")
            for _k, c in sorted(constellations.items(), key=lambda kv: int(re.sub(r"\D", "", kv[0]) or 0))
        ],
        level_stats=_level_table(info.get("attributes") or []),
        hyperlinks=raw.get("hyperlinks") or [],
    )


@lru_cache(maxsize=None)
def character_markup(char_id):
    """(texts, buffed, glossary) like gamedata.fetch_character_markup: descriptions with the game's
    markup by name, no reworked text, and [(link id, name, description)] for the linked terms."""
    detail = character_detail(char_id)
    texts = {gamedata.clean(e.name): e.description for e in detail.talents + detail.constellations if e.name}
    glossary = [(f"N{h.get('id')}", h.get("name") or "", h.get("description") or "") for h in detail.hyperlinks]
    return texts, {}, glossary


# ----- weapons -----
@lru_cache(maxsize=None)
def weapon_detail(weapon_id):
    raw = _get(f"{_version()}/en/weapon/{int(weapon_id)}.json")
    passive = raw.get("passive") or {}
    refinements = passive.get("refinements") or {}
    rows = [{"level": int(level), **stats} for level, stats in (raw.get("stats") or {}).items() if level.isdigit()]
    return NS(
        unreleased=True,
        rarity=_rarity(raw.get("qualityType")),
        description=raw.get("weaponDesc") or "",
        affix=NS(name=passive.get("name") or "",
                 upgrades=[NS(description=refinements[k].get("description") or "") for k in sorted(refinements, key=int)])
        if refinements else None,
        level_stats=_level_table(sorted(rows, key=lambda r: r["level"])),
    )


def weapon_markup(weapon_id):
    return [u.description for u in (weapon_detail(weapon_id).affix.upgrades if weapon_detail(weapon_id).affix else [])]
