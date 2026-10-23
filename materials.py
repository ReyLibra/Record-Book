"""What the To Do List's goals cost: the materials to level and ascend a character or weapon and to
raise talents, from Project Amber (gi.yatta.moe), and which domains are open on which days.

Everything here blocks (downloads), so the UI calls it through gamedata.run_async(). Answers are kept
on disk for a day, and an old copy is used when the site can't be reached.
"""

import json
import math
import time
import urllib.request
from collections import Counter
from functools import lru_cache

from gamedata import ASSETS, CACHE_DIR
from materials_data import CHARACTER_EXP, WEAPON_EXP

API = "https://gi.yatta.moe/api/v2/en/"
MAX_AGE = 24 * 3600
MORA = 202
HEROS_WIT, HEROS_WIT_EXP = 104003, 20000  # the biggest character EXP book
MYSTIC_ORE, MYSTIC_ORE_EXP = 104013, 10000  # the biggest weapon enhancement ore
EXP_MORA = {"character": 1 / 5, "weapon": 1 / 10}  # mora spent per point of EXP
TALENT_NAMES = ["Normal Attack", "Elemental Skill", "Elemental Burst"]
DOMAIN_TYPES = {"characterTalentMaterial": "talent", "weaponAscensionMaterial": "weapon"}


def _get(path):
    """Project Amber's answer for an API path ('material', 'avatar/10000046'…), cached on disk for a day."""
    file = CACHE_DIR / "planner" / (path.replace("/", "_") + ".json")
    if file.exists() and time.time() - file.stat().st_mtime < MAX_AGE:
        return json.loads(file.read_text(encoding="utf-8"))
    try:
        req = urllib.request.Request(API + path, headers={"User-Agent": "RecordBook/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)["data"]
    except Exception:
        if file.exists():  # offline: an old copy is better than nothing
            return json.loads(file.read_text(encoding="utf-8"))
        raise
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(data), encoding="utf-8")
    return data


@lru_cache(maxsize=None)
def items():
    """{item id (int): {"name", "type", "icon", "rank"}} for every material."""
    return {int(k): v for k, v in _get("material")["items"].items()}


def icon_url(item_id):
    item = items().get(int(item_id))
    return f"{ASSETS}{item['icon']}.png" if item else None


def name(item_id):
    item = items().get(int(item_id))
    return item["name"] if item else f"Item {item_id}"


@lru_cache(maxsize=None)
def domains():
    """{material id: {"domain", "kind" ('talent' / 'weapon'), "days": {weekday, …}}} for every talent book
    and weapon ascension material a domain drops (weekday 0 = Monday; Sunday has them all)."""
    from servers import WEEKDAYS

    found = {}
    for day, entries in _get("dailyDungeon").items():
        weekday = WEEKDAYS.index(day)
        for entry in entries.values():
            for item_id in entry.get("reward") or []:
                item = items().get(int(item_id))
                kind = DOMAIN_TYPES.get(item["type"]) if item else None
                if kind:
                    info = found.setdefault(int(item_id), {"domain": entry["name"], "kind": kind, "days": set()})
                    info["days"].add(weekday)
    return found


def open_domains(weekday):
    """[(domain name, kind, [material ids, best first])] open on a weekday."""
    by_domain = {}
    for item_id, info in domains().items():
        if weekday in info["days"]:
            by_domain.setdefault((info["domain"], info["kind"]), []).append(item_id)
    return [(d, kind, sorted(ids, key=lambda i: -items()[i]["rank"])) for (d, kind), ids in sorted(by_domain.items())]


@lru_cache(maxsize=None)
def character(char_id):
    return _get(f"avatar/{char_id}")


@lru_cache(maxsize=None)
def weapon(weapon_id):
    return _get(f"weapon/{weapon_id}")


# ----- levels -----
def level_steps(detail):
    """The levels a character or weapon goes through, as [(level, ascension phase)]: 1, 20, 20+ (ascended),
    40, 40+ … up to its max (90 for characters and 3-5★ weapons, 70 for 1-2★)."""
    promotes = sorted(detail["upgrade"]["promote"], key=lambda p: p.get("promoteLevel", 0))
    steps = [(1, 0)]
    for promote in promotes:
        phase, top = promote.get("promoteLevel", 0), promote["unlockMaxLevel"]
        steps.append((top, phase))
        if phase + 1 < len(promotes):
            steps.append((top, phase + 1))
    return steps


def step_label(steps, index):
    level, phase = steps[index]
    ascended = index > 0 and steps[index - 1][0] == level
    return f"{level}+" if ascended else str(level)


def _level_costs(detail, steps, start, end, exp_table, book, book_exp, kind):
    """Materials to go from steps[start] to steps[end]: the ascensions' items and mora, then EXP as the
    biggest EXP item (rounded up) and the mora it takes to use it."""
    need = Counter()
    if end <= start:
        return need
    (from_level, from_phase), (to_level, to_phase) = steps[start], steps[end]
    for promote in detail["upgrade"]["promote"]:
        if from_phase < promote.get("promoteLevel", 0) <= to_phase:
            for item_id, count in (promote.get("costItems") or {}).items():
                need[int(item_id)] += count
            need[MORA] += promote.get("coinCost") or 0
    exp = sum(exp_table[level - 1] for level in range(from_level, to_level))
    if exp:
        need[book] += math.ceil(exp / book_exp)
        need[MORA] += round(exp * EXP_MORA[kind])
    return need


def character_talents(detail):
    """The three talents that level up (Normal Attack, Skill, Burst), as Amber's talent entries."""
    talents = detail.get("talent") or {}
    levelled = [talents[k] for k in sorted(talents, key=int) if talents[k].get("promote")]
    return levelled[:3]


def character_costs(char_id, level_from, level_to, talents):
    """({"level": Counter, "talents": Counter}) for a character goal. level_*: indices into level_steps();
    talents: [(from, to)] for Normal Attack, Skill and Burst."""
    detail = character(char_id)
    steps = level_steps(detail)
    level = _level_costs(detail, steps, level_from, level_to, CHARACTER_EXP, HEROS_WIT, HEROS_WIT_EXP, "character")
    talent_need = Counter()
    for talent, (start, end) in zip(character_talents(detail), talents):
        for lv in range(start + 1, end + 1):
            cost = (talent.get("promote") or {}).get(str(lv)) or {}
            for item_id, count in (cost.get("costItems") or {}).items():
                talent_need[int(item_id)] += count
            talent_need[MORA] += cost.get("coinCost") or 0
    return {"level": level, "talents": talent_need}


def weapon_costs(weapon_id, rarity, level_from, level_to):
    detail = weapon(weapon_id)
    steps = level_steps(detail)
    table = WEAPON_EXP[max(1, min(5, rarity))]
    return {"level": _level_costs(detail, steps, level_from, level_to, table, MYSTIC_ORE, MYSTIC_ORE_EXP, "weapon")}


def total(costs):
    out = Counter()
    for part in costs.values():
        out.update(part)
    return out


def domain_days(costs):
    """The weekdays a goal's domain materials can be farmed on, as {(domain, kind): days}."""
    found = {}
    for item_id in total(costs):
        info = domains().get(item_id)
        if info:
            found[(info["domain"], info["kind"])] = info["days"]
    return found


_boss_drops = {}  # boss material id -> its boss's drops (filled by boss_drops(), read by known_boss_drops())


def boss_drops(item_id):
    """What the boss that drops a boss material drops besides: {"boss": name, "materials": [its boss materials],
    "gems": [one id of each gem family it drops]}, from the boss's rewards on Project Amber (some drop gems of
    several elements: Childe's Hydro, Electro and Cryo). None if it isn't known. Blocks (downloads)."""
    if item_id in _boss_drops:
        return _boss_drops[item_id]
    found = None
    for boss in (_get(f"material/{item_id}").get("additions") or {}).get("droppedBy") or []:
        rewards = {int(i) for entry in (_get(f"monster/{boss['id']}").get("entries") or {}).values()
                   for i in entry.get("reward") or {}}
        known = [i for i in sorted(rewards) if i in items()]
        bosses = [i for i in known if items()[i]["type"] == "characterLevelUpMaterial"]
        gems = [i for i in known if items()[i]["type"] == "characterAscensionMaterial" and items()[i]["rank"] == 2]
        if item_id in bosses:
            found = {"boss": boss["name"], "materials": bosses, "gems": gems}
            break
    _boss_drops[item_id] = found
    return found


def known_boss_drops(item_id):
    """boss_drops() if it's been looked up already (never blocks), else None."""
    return _boss_drops.get(item_id)


def sort_items(item_ids):
    """Mora first, then EXP items, then the rest by type and rarity (best last within a family)."""
    order = {"commonCurrency": 0, "characterEXPMaterial": 1, "weaponEnhancementMaterial": 1}

    def key(item_id):
        item = items().get(item_id) or {}
        return (order.get(item.get("type"), 2), item.get("type", ""), item_id)

    return sorted(item_ids, key=key)
