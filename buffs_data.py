"""Definitions for the Buffs page. The buffs themselves are read from each character's kit by
buff_scan.py and saved in the database; this file says how they're grouped and labelled.

An entry is (source, tags, who, text, condition, flag):
  source     where it comes from: a talent (E(10), Q(10), A1, A4…), a constellation (C1–C6), or a
             special passive (Lunar, Stellar, Hexerei, Passive)
  tags       space-separated buff types (TYPES keys) and the elements the buff affects
             (ELEMENT_TAGS keys; "any" = whichever element the team uses, e.g. swirled/absorbed)
  who        who receives it (WHO keys)
  text       the kit's own sentence describing it (Skill/Burst values at talent level 10 added in brackets)
  condition  a special requirement beyond using the skill (team makeup, Moonsign, Hexerei, a state…)
  flag       unused for now ("" ), kept so entries can be marked later
"""

# buff types, in the order the filter buttons show them: key -> (button label, tooltip)
TYPES = {
    "atk": ("ATK", "Flat or % ATK buffs"),
    "def": ("DEF", "DEF buffs"),
    "hp": ("HP", "HP buffs"),
    "em": ("EM", "Elemental Mastery buffs"),
    "crit": ("Crit", "Crit Rate and Crit DMG buffs"),
    "dmg": ("DMG Bonus", "DMG% buffs: elemental, physical and N/C/P/E/Q damage"),
    "reaction": ("Reaction", "Reaction damage: Lunar, Stellar, Bloom-related, Swirl, Aggravate…"),
    "quills": ("Quills", "Additive (flat) damage, usually used up on hit"),
    "spd": ("ATK SPD", "Attack speed"),
    "res": ("RES Shred", "Lowers enemy elemental or physical RES"),
    "defshred": ("DEF Shred", "Lowers or ignores enemy DEF"),
    "taken": ("DMG Taken", "Enemies take more damage"),
    "utility": ("Utility", "Stamina, cooldowns, infusions"),
}

# who a buff goes to: key -> (badge label, tooltip)
WHO = {
    "team": ("Team", "The whole party, including the character giving it"),
    "others": ("Team · excl. self", "The rest of the party, not the character giving it"),
    "active": ("Active", "Only the character on the field"),
    "self_active": ("Self + Active", "The character giving it and the one on the field"),
    "enemy": ("Enemies", "A debuff on enemies, so it helps everyone hitting them"),
    "self": ("Self only", "Only the character giving it"),
}

# elements a buff can affect, in filter order: key -> game element (None: physical)
ELEMENT_TAGS = {
    "pyro": "PYRO",
    "hydro": "HYDRO",
    "dendro": "DENDRO",
    "electro": "ELECTRO",
    "anemo": "ANEMO",
    "cryo": "CRYO",
    "geo": "GEO",
    "phys": None,
}

# entry flags: key -> (label, tooltip); none in use at the moment
FLAGS = {}

LEGEND = (
    "Read automatically from each character's kit (the updated text where a kit was reworked), so double-check "
    "in game. Hover an underlined name for what it is and where it comes from. "
    "E = Skill · Q = Burst · A1/A4 = Ascension passives · C1–C6 = Constellations · "
    "Quills = additive DMG that depletes on hit"
)

HEXEREI = "Hexerei: 2+ Hexerei characters in the party"
ASCENDANT = "Moonsign: Ascendant Gleam"


def source_kind(source):
    """'constellation' (C1–C6), 'special' (Lunar / Stellar / Hexerei / Passive) or 'talent'."""
    if source[:1] == "C" and source[1:2].isdigit():
        return "constellation"
    if source in ("Lunar", "Stellar", "Hexerei", "Passive"):
        return "special"
    return "talent"
