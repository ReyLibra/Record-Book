"""Search matching that understands the community's shorthand: "VV", "TotM", "Childe", "HT"…

matches(query, name) is true when the query is part of the name (ignoring spaces and
punctuation), the start of one of its initialisms, or the start of a known nickname.
"""

import re
from functools import lru_cache

_SMALL_WORDS = {"of", "the", "and", "a", "an", "to", "in", "for", "from", "on", "at"}

# Nicknames that can't be worked out from the name itself (lower case, any punctuation).
NICKNAMES = {
    # artifact sets
    "Crimson Witch of Flames": ["cw", "cwof"],
    "Emblem of Severed Fate": ["emblem"],
    "Noblesse Oblige": ["no"],
    "Viridescent Venerer": ["vv"],
    "Tenacity of the Millelith": ["totm", "tom"],
    "Shimenawa's Reminiscence": ["shime", "shimenawa"],
    "Heart of Depth": ["hod"],
    "Blizzard Strayer": ["bs"],
    "Thundering Fury": ["tf"],
    "Thundersoother": ["ts"],
    "Gladiator's Finale": ["glad"],
    "Wanderer's Troupe": ["wt"],
    "Archaic Petra": ["petra"],
    "Retracing Bolide": ["bolide"],
    "Pale Flame": ["pf"],
    "Husk of Opulent Dreams": ["husk", "hood"],
    "Ocean-Hued Clam": ["ohc", "clam"],
    "Vermillion Hereafter": ["vh"],
    "Echoes of an Offering": ["echoes", "eoao"],
    "Deepwood Memories": ["dm", "deepwood"],
    "Gilded Dreams": ["gd"],
    "Flower of Paradise Lost": ["fopl"],
    "Desert Pavilion Chronicle": ["dpc"],
    "Nymph's Dream": ["nd", "nymph"],
    "Vourukasha's Glow": ["vg", "vourukasha"],
    "Marechaussee Hunter": ["mh", "hunter"],
    "Golden Troupe": ["gt"],
    "Song of Days Past": ["sodp"],
    "Nighttime Whispers in the Echoing Woods": ["nwew", "nighttime"],
    "Fragment of Harmonic Whimsy": ["fohw", "whimsy"],
    "Unfinished Reverie": ["ur", "reverie"],
    "Scroll of the Hero of Cinder City": ["scroll", "sothocc", "cinder"],
    "Obsidian Codex": ["codex", "oc"],
    "Long Night's Oath": ["lno"],
    "Finale of the Deep Galleries": ["fotdg", "galleries"],
    "Instructor": ["instructor"],
    "The Exile": ["exile"],
    "Maiden Beloved": ["mb", "maiden"],
    "Bloodstained Chivalry": ["bsc", "chivalry"],
    "Lavawalker": ["lw"],
    # characters
    "Tartaglia": ["childe"],
    "Wanderer": ["scara", "scaramouche", "kunikuzushi"],
    "Raiden Shogun": ["ei", "raiden", "baal"],
    "Kamisato Ayaka": ["ayaka"],
    "Kamisato Ayato": ["ayato"],
    "Kaedehara Kazuha": ["kazu", "kazuha"],
    "Sangonomiya Kokomi": ["koko", "kokomi"],
    "Arataki Itto": ["itto"],
    "Kuki Shinobu": ["kuki", "shinobu"],
    "Shikanoin Heizou": ["heizou"],
    "Kujou Sara": ["sara"],
    "Yae Miko": ["yae", "miko"],
    "Hu Tao": ["ht", "hutao"],
    "Zhongli": ["zl", "morax"],
    "Xiangling": ["xl"],
    "Xingqiu": ["xq"],
    "Bennett": ["benny"],
    "Sucrose": ["sucy"],
    "Neuvillette": ["neuv", "neuvi"],
    "Arlecchino": ["arle", "father", "knave"],
    "Furina": ["focalors"],
    "Nahida": ["kusanali", "buer"],
    "Venti": ["barbatos"],
    "Traveler": ["mc", "aether", "lumine"],
    "Kirara": ["kirara"],
    "Lyney": ["lyney"],
    "Chevreuse": ["chev"],
    "Kinich": ["kinich"],
    "Mavuika": ["mav", "pyro archon"],
    "Xilonen": ["xilo"],
    "Kaveh": ["kaveh"],
    "Alhaitham": ["al haitham", "haitham"],
    "Cyno": ["cyno"],
    "Yun Jin": ["yj"],
    "Yelan": ["yelan"],
    "Kaeya": ["kaeya"],
    "Keqing": ["kq"],
    "Ningguang": ["ning", "ng"],
    "Beidou": ["bd"],
    # weapons
    "Wolf's Gravestone": ["wgs", "wolfs"],
    "Primordial Jade Winged-Spear": ["pjws"],
    "Primordial Jade Cutter": ["pjc", "jade cutter"],
    "Staff of Homa": ["homa"],
    "Staff of the Scarlet Sands": ["sss", "scarlet sands"],
    "Thrilling Tales of Dragon Slayers": ["ttds"],
    "Mistsplitter Reforged": ["mist", "mistsplitter"],
    "Engulfing Lightning": ["el"],
    "Elegy for the End": ["elegy"],
    "Aquila Favonia": ["aqua", "aquila"],
    "Freedom-Sworn": ["fs"],
    "Song of Broken Pines": ["sobp", "pines"],
    "Light of Foliar Incision": ["lofi"],
    "Key of Khaj-Nisut": ["kokn", "key"],
    "Calamity Queller": ["cq"],
    "Kagura's Verity": ["kv", "kagura"],
    "Polar Star": ["ps"],
    "Hunter's Path": ["hp"],
    "Haran Geppaku Futsu": ["haran", "hgf"],
    "Redhorn Stonethresher": ["redhorn", "rhs"],
    "Everlasting Moonglow": ["moonglow", "em"],
    "Lost Prayer to the Sacred Winds": ["lptsw", "lost prayer"],
    "Skyward Harp": ["sky harp"],
    "Amos' Bow": ["amos"],
    "The Catch": ["catch", "fish"],
    "Splendor of Tranquil Waters": ["sotw"],
    "Tome of the Eternal Flow": ["tome", "toef"],
    "Crimson Moon's Semblance": ["cms"],
    "Sacrificial Sword": ["sac sword"],
    "Sacrificial Fragments": ["sac frags", "frags"],
    "Favonius Sword": ["fav sword"],
    "Favonius Warbow": ["fav bow"],
    "Favonius Lance": ["fav lance"],
    "Favonius Codex": ["fav codex"],
    "Favonius Greatsword": ["fav gs"],
    "Dragon's Bane": ["db"],
    "Deathmatch": ["dm"],
    "Kitain Cross Spear": ["kcs", "kitain"],
    "Widsith": ["widsith"],
    "Hakushin Ring": ["hakushin"],
}


def _norm(text):
    """Lower case, letters and digits only."""
    return re.sub(r"[^0-9a-z]", "", text.lower())


def _words(name):
    return [w for w in re.split(r"[\s\-–—:,.!?/()]+", name.lower().replace("'", "").replace("’", "")) if w]


@lru_cache(maxsize=4096)
def search_keys(name):
    """Everything a name can be searched by: the name itself and its shorthands, normalized."""
    words = _words(name)
    keys = {_norm(name)}
    if len(words) > 1:
        keys.add("".join(w[0] for w in words))  # Tenacity of the Millelith -> totm
        big = [w for w in words if w not in _SMALL_WORDS]
        if len(big) > 1:
            keys.add("".join(w[0] for w in big))  # Thrilling Tales of Dragon Slayers -> ttds
    keys.update(_norm(n) for n in NICKNAMES.get(name, ()))
    keys.discard("")
    return tuple(keys)


def matches(query, name):
    """True when `query` finds `name` (empty query finds everything)."""
    q = _norm(query)
    if not q:
        return True
    if q in _norm(name):
        return True
    # shorthands match from their start, so "v" doesn't pull in every set with a V somewhere
    return any(key.startswith(q) for key in search_keys(name)) or any(
        q in _norm(n) for n in NICKNAMES.get(name, ()) if len(q) >= 3
    )
