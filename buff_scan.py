"""Reads a character's kit and picks out the buffs and shreds they give others, written as Buffs-page
entries (source, tags, who, text, condition, "auto"), so new characters can join the list.

It works from the kit's wording ("nearby party members gain…", "opponents' Pyro RES is decreased by…"),
so it's a first pass to check in game. Self-only buffs are skipped. It also collects the kit terms
the entries mention ("Blood Blossom"), with their explanation and where they come from, for hover text.
"""

import re

import gamedata

# bump when the scanner changes, so saved results are read again from the kits
VERSION = 27
# {character: [(source, how its line starts)]}: buffs only the character gets, though the kit text reads like a
# team buff (Razor's C1 is his own DMG; Linnea's C6 doubles her own Field Catalog use)
SELF_ONLY = {
    "Razor": [("C1", "Picking up an Elemental Orb")],
    "Linnea": [("C6", "When consuming Field Catalog")],
}
from buffs_data import ASCENDANT, HEXEREI, TYPES

_TYPE_KEYS = set(TYPES)

ELEMENT_WORDS = {
    "pyro": "pyro", "hydro": "hydro", "electro": "electro", "cryo": "cryo",
    "anemo": "anemo", "geo": "geo", "dendro": "dendro", "physical": "phys",
}
# special passives, by the prefix the game gives their names
SPECIAL_SOURCES = {
    "Moonsign Benediction": "Lunar",
    "Witch's Eve Rite": "Hexerei",
    "Stellar Jubilee": "Stellar",
    "Night Realm's Gift": "Passive",
}
REACTIONS = (
    "lunar", "stellar", "bloom", "swirl", "vaporize", "melt", "aggravate", "spread", "electro-charged",
    "superconduct", "overloaded", "burning", "hyperbloom", "burgeon", "crystallize", "bountiful core", "reaction",
)
# words that say the effect reaches someone other than the character
OTHERS = ("excluding", "not including", "other party members", "other nearby", "other characters", "apart from", "other than")
TEAM = ("all party members", "nearby party members", "party members", "party member", "party characters", "your party",
        "all characters", "allies", "hexerei characters")
# the on-field character, named outright
ACTIVE_NAMED = ("active character", "active party member")
# characters picked out by where they are or what they have: usually the one on the field
ACTIVE_GENERIC = ("characters within", "character within", "characters in the", "characters inside", "characters under",
                  "character under the effect",
                  "characters affected by", "characters who", "characters with", "nearby characters", "character that",
                  "that character", "characters shielded", "characters protected", "grant characters", "grants characters",
                  "wielding characters", "triggering character", "picking up", "pick up", "cast within")
ACTIVE = ACTIVE_NAMED + ACTIVE_GENERIC
ENEMY = ("opponent", "enemies", "enemy", "targets")
# talent-table rows worth quoting for Skill/Burst buffs
VALUE_KEYS = ("bonus", "res decrease", "res reduction", "increase", "elevat", "atk spd")
SKIP_KEYS = ("healing", "regeneration", "shield", "cd", "duration", "energy", "stamina", "interval", "skill dmg",
             "absorption", "hp+", "hit dmg")


def _sentences(text):
    text = gamedata.clean(text or "")
    parts = re.split(r"(?<=[.!?])\s+|\n+|\s*·\s*", text)
    return [p.strip() for p in parts if p.strip()]


def _norm(sentence):
    """Lower case, with "damage" written the way the kit usually does ("DMG")."""
    return re.sub(r"\bdamage\b", "dmg", sentence.lower())


def _has(s, words):
    return any(w in s for w in words)


def _elements(s):
    found = [tag for word, tag in ELEMENT_WORDS.items() if re.search(rf"\b{word}\b", s)]
    if "elemental res" in s or "corresponding element" in s or "all elemental" in s or "absorbed" in s:
        found.append("any")
    return found


_TRIGGERS = re.compile(r"trigger\w* (an? )?[\w\s,/-]{0,40}?reactions?")
_REACTION_DMG = re.compile(r"(reactions?|lunar[\w-]*|stellar[\w-]*|" + "|".join(REACTIONS[2:-1])
                           + r")[\w\s,/'-]{0,30}?\bdmg")
_STAT = r"(atk|elemental mastery|def|max hp)"
_UTILITY = re.compile(r"(?<!swimming )(?<!climbing )(?<!sprinting )(?<!gliding )"
                      r"(stamina consumption|stamina cost|\bcd\b|cooldown)[^.]{0,80}(decreas|reduc)"
                      r"|(decreas|reduc)\w* [^.]{0,30}(stamina|\bcd\b|cooldown)|infused with|\binfusion\b")
_BUFF_VERBS = ("increas", "gain", "grant", "bonus", "elevat", "boost", "% more", "additional")


_OWN_DMG = re.compile(r"\bdmg (?:dealt )?(?:by|of) (?:the |that |this |its )?(?!(?:all |nearby |your |other |any |each |the active|"
                      r"party|characters?\b|allies|hexerei|active|opponents?|the opponent|these|those|them|"
                      r"bountiful|dendro core|(?:\w+[ -]){0,2}(?:reaction|vaporize|melt|swirl|bloom|lunar|stellar)))[a-z]")


def _types(s, table_values=False, enemy_context=False):
    """Buff types a sentence (normalized: lower case, "dmg") describes, or [] when it isn't one.
    table_values: Skill/Burst text, whose numbers are in the talent table rather than the sentence.
    enemy_context: an earlier line said these effects apply to opponents (Nahida's C2 list)."""
    s = s.replace("dmg absorption", "absorption")  # a shield's strength, not a DMG buff
    types = []
    pct = "%" in s or table_values
    shrink = _has(s, ("decreas", "reduc", "lower"))
    if enemy_context or _has(s, ENEMY):
        if re.search(r"\bres\b", s) and shrink and pct:
            types.append("res")
        # ignoring DEF only counts when it's party members' attacks, not the character's own
        ignores = "ignore" in s and _has(s, TEAM + ACTIVE)
        if re.search(r"\bdef\b", s) and (shrink or ignores) and pct:
            types.append("defshred")
        if "dmg taken" in s or "take increased dmg" in s or "takes increased dmg" in s:
            types.append("taken")
        if types:
            return types
    if _UTILITY.search(s) and not re.search(r"swimming|climbing|sprinting|gliding", s):
        types.append("utility")
    plus = _PLUS_STAT.findall(s)  # list style: "ATK +45%", "DMG dealt +50%"
    if not plus and not _has(s, _BUFF_VERBS):
        return types
    for stat in plus:
        types.append(_PLUS_TYPES[next(k for k in _PLUS_TYPES if stat.startswith(k))])
    # "<stat> of <who> will be increased by …" (Nahida's A1), "… ATK will additionally be increased"
    for stat, kind in (("elemental mastery", "em"), ("atk", "atk"), ("def", "def"), ("max hp", "hp")):
        if re.search(rf"(?<!of )(?<!on )\b{stat}\b(?! spd)(?: of [^.;]{{0,70}}?)? (?:will |is |are )?(?:additionally |further |also )?"
                     rf"(?:be )?(?:increased|increases|raised)\b", s):
            types.append(kind)
    # flat DMG added from someone's stat ("DMG is increased by 70% of X's ATK", "based on 5% of Layla's Max HP")
    if (re.search(r"dmg[^.]*increase[sd]?[^.%]*(by|equal to) [\d./%]+ of\b", s)
            or re.search(rf"(dmg|effect)[^.]{{0,60}}increase[sd]? based on [\w'%. ]{{0,30}}{_STAT}", s)
            or re.search(rf"deal [\d.]+% of [\w' ]{{0,25}}{_STAT} as (increased|additional)", s)
            or re.search(r"increase in dmg is (?:equal to|based on)", s)
            or re.search(r"increase[sd]? the dmg[^.]{0,60}by [\d./%]+ of\b", s)
            or re.search(r"(bonus|additional) dmg[^.]{0,30}based on", s)
            # a flat number rather than a %: "will increase the Stellar Swirl reaction DMG … by 260, as well as
            # Hydro DMG and Cryo DMG dealt by 140" (Vodyanitsa's Lead Vocal)
            or re.search(r"\bdmg\b[^.;%]{0,80}?\b(?:increase[sd]?|dealt) by [\d,]+(?![\d.,]*\s*(?:%|[a-z]))", s)):
        types.append("quills")
    if "atk spd" in s or "attack spd" in s:
        types.append("spd")
    if re.search(r"\batk\b(?: (?:is|will be|are))? (?:increased|bonus|by [\d.]+)|(?:increas|gain|boost)\w* (?:their |the |an? )?"
                 r"(?:[\d.]+%? )?(?:bonus )?atk\b(?! spd)|\batk bonus", s):
        types.append("atk")
    # not EM something else scales with ("every Elemental Mastery point she has will increase … DMG Bonus")
    em_s = re.sub(r"\b(every|each|per) (point of )?elemental mastery( points?)?( \w+ has)?|based on [^.;]{0,30}elemental mastery",
                  "", s)
    if (re.search(r"elemental mastery[^.]{0,25}(increase|by \d)|(increas|gain)\w*[^.]{0,20}\d+ (points of )?elemental mastery"
                  r"|increas\w* (the )?elemental mastery|increas\w* [^.]{0,60}elemental mastery by", em_s)
            or (table_values and re.search(r"gain\w* elemental mastery", s))):
        types.append("em")
    # not Max HP something else scales with ("based on Dahlia's Max HP: Every 1,000 Max HP will cause an increase")
    unscaled = re.sub(r"\b(every|per|each|for every) [\d,.]+ (points of )?max hp|based on [^.;]{0,30}max hp", "", s)
    if re.search(r"max hp[^.]{0,20}(increase|by \d)", unscaled):
        types.append("hp")
    if re.search(r"(?<!of )(?<!'s )\bdef\b (?:is |will be |are )?(?:increased|by \d)|(?:increas|gain)\w* (?:their |the )?"
                 r"(?:[\d.]+%? )?def\b|\bdef bonus", s):
        types.append("def")
    if "crit rate" in s or "crit dmg" in s:
        types.append("crit")
    # reaction DMG being boosted, not a reaction that merely triggers the effect
    boosted = re.sub(r"immune to [^.,]*", "", _TRIGGERS.sub("", s))
    if (_REACTION_DMG.search(boosted)
            or re.search(r"\bdmg from [^.]{0,90}reactions?\b", s)
            or re.search(r"\bdmg of (that |the |this )?(\w+[ -]){0,2}(" + "|".join(REACTIONS[:-2]) + r")\b", s)):
        types.append("reaction")
    if ("dmg bonus" in s
            or re.search(r"dmg[^.]{0,120}?(?:is |are |will be )?(?:\w+ )?(?:increased|increases|increase) by [\d.]+%(?! of)", s)
            or re.search(r"deal\w* [\d.]+% (?:increased|more) (?:\w+ ){0,2}dmg|\d% more (?:\w+ ){0,3}dmg", s)
            or re.search(r"deal\w* (?:an? )?(?:additional|extra) [\d.]+% (?:\w+ ){0,2}dmg", s)
            or re.search(r"dmg (?:is |are )?increased based on", s)
            or ("quills" not in types and re.search(r"increas\w* (?:the |their )?[\w ,'-]{0,40}\bdmg\b(?! bonus)", s))):
        types.append("dmg")
    # a reaction's Base DMG going up (the Lunar / Stellar passives: "the Base DMG of Lunar reactions is increased
    # by 0.2% for every 1,000 Max HP") is a reaction bonus, not flat DMG added on hit
    if "reaction" in types and re.search(r"\bbase (?:[\w-]+ ){0,2}dmg\b", s):  # "Base Stellar-Conduct DMG" too
        types = [t for t in types if t not in ("quills", "dmg")]
    # the DMG of one of the character's own attacks, not the party's
    if _OWN_DMG.search(s) and not _has(s, TEAM + OTHERS + ACTIVE_NAMED):
        types = [t for t in types if t not in ("dmg", "quills", "crit")]
    return list(dict.fromkeys(types))


_PLUS_TYPES = {"atk spd": "spd", "atk": "atk", "def": "def", "max hp": "hp", "hp": "hp", "elemental mastery": "em",
               "crit": "crit", "dmg": "dmg"}
_PLUS_STAT = re.compile(r"\b(atk spd|atk|def|max hp|hp|elemental mastery|crit rate|crit dmg|dmg(?: dealt| bonus)?)\s*\+\s?[\d.]+")


# "after a nearby party member triggers a reaction, …": says when, not who gets the buff
_TRIGGER_CLAUSE = re.compile(
    r"(after|when|if|upon|for \d+s after)\s[^,:]*?(party members?|characters?|allies)\s[^,:]*?"
    r"(trigger|hit|deal|use|pick|create)\w*[^,:]*[,:]"
)
# a party getting something in the same sentence ("…while nearby party members' ATK is increased by 8%")
_PARTY_GETS = re.compile(r"(party members?|allies|characters?)('s?)? [^.,]{0,40}(is increased|are increased|increase|gain|receive)"
                         r"|which \w+ [^.]{0,60}(active character|party member|allies)"
                         r"|grants? (all |nearby |other |your )*(party members?|allies|characters)")


def _self_buff(s, names):
    """True when the boosted thing is the character's own attacks or stats ("Clorinde's Normal Attacks",
    "his ATK"), as opposed to just scaling off their stats ("based on Lauma's Elemental Mastery")."""
    attacks = r"(normal\b|charged\b|plunging\b|elemental skill|elemental burst|crit|dmg\b)"
    stats = r"(atk|elemental mastery|def|max hp|crit)\b"
    # "her Normal and Plunging Attacks", "her Elemental Mastery", "that attack", "its DMG"
    if re.search(rf"\b(his|her) (\w+ ){{0,2}}({attacks}|{stats})|\b(that|this) attack\b|\bits dmg\b", s):
        return True
    return any(
        re.search(rf"\b{re.escape(n)}'s (\w+ ){{0,2}}{attacks}", s)  # "Kachina's Geo DMG Bonus", "Eula's Physical DMG"
        or re.search(rf"(?<!of )(?<!on ){re.escape(n)}'s {stats}[^.,]{{0,15}}(increase|is increased)", s)
        or re.search(rf"(?<!of )(?<!on ){re.escape(n)}'s atk\b", s)
        or re.search(rf"increas\w* {re.escape(n)}'s", s)  # "increase Furina's Max HP"
        for n in names
    )


def _self_subject(s, names):
    """The character is the one gaining it ("Chiori will gain 20% Geo DMG Bonus…")."""
    gains = r"(can |will )?(also )?(gain|gains|receive|receives|obtains?|deal|deals)\b"
    if re.search(r"\bwill (also )?join in\b", s):
        return True
    # "party members can accumulate Will to Win for Lohen" feeds the character's own attack
    if any(re.search(rf"\b(accumulate|gather|generate|collect)\w* [^.]{{0,40}}\bfor {re.escape(n)}\b", s) for n in names):
        return True
    return bool(re.search(rf"\b(she|he) {gains}", s)) or any(
        re.search(rf"\b{re.escape(n)} {gains}", s) or re.search(rf"\bgrants? {re.escape(n)}\b", s) for n in names
    )


def _who(s, names, types, term_who=None):
    """Who gets a buff, from the sentence's wording; term_who: {kit term: who} learned from the kit's other
    entries, for sentences that only name the effect ("characters under the Flying Cloud Flag Formation")."""
    if set(types) & {"res", "defshred", "taken"}:
        return "enemy"
    own = _self_buff(s, names)
    if own:  # party members only trigger it; look past "after a party member triggers…"
        s = _TRIGGER_CLAUSE.sub("", s)
        term_who = None  # it's the character's own attacks, whatever effect it mentions
    if _self_subject(s, names) and not _has(s, OTHERS) and not _PARTY_GETS.search(_TRIGGER_CLAUSE.sub("", s)):
        return None
    if _has(s, OTHERS):
        return "others"
    # handed to the party, but it only works for whoever is on the field ("grants all nearby party members
    # the Hunter's Precision effect, which increases their ATK when they are on the field")
    if re.search(r"\b(when|while) (they are |they're |the character is )?on[- ]?(the )?field\b", s) and _has(s, TEAM):
        return "active"
    if any(re.search(rf"\b{re.escape(n)}('s)? and (your )?(own )?(current )?active", s) for n in names):
        return "self_active"
    # whichever the sentence names first, past an opening "When …," clause: "The Elemental Mastery of the
    # active character … increased by 25% of the Elemental Mastery of the party member with …" is Active
    # ("your active party member" is Active, though it contains "party member")
    main = re.sub(r"^(when|after|if|upon|while|within|for)\b[^,]*,\s*", "", s)
    for text in (main, s):
        first = {kind: min((text.find(w) for w in words if w in text), default=-1)
                 for kind, words in (("team", TEAM), ("active", ACTIVE_NAMED))}
        found = {k: v for k, v in first.items() if v >= 0}
        if found:
            return min(found, key=found.get)
    for term in sorted(term_who or {}, key=len, reverse=True):
        if term in s:
            return term_who[term]
    if _has(s, ACTIVE_GENERIC):
        return "active"
    return None  # only the character themself


def _condition(paragraph_before, s):
    text = (paragraph_before + " " + s).lower()
    if "ascendant gleam" in text:
        return ASCENDANT
    if "nascent gleam" in text:
        return "Moonsign: Nascent Gleam"
    if "hexerei" in text:
        return HEXEREI
    m = re.search(r"radiance: (stellar[- ]\w+|stellar glimmer)", text)
    if m:
        return "Radiance: " + m.group(1).title()
    if re.search(r"when all (characters|party members) in the party|elemental types in the party|party (contains|has)", text):
        return "Depends on party elements"
    return ""


def _source(label, talent_type_level):
    if label == "1st Ascension Passive":
        return "A1"
    if label == "4th Ascension Passive":
        return "A4"
    if label == "Elemental Skill":
        return f"E({talent_type_level})"
    if label == "Elemental Burst":
        return f"Q({talent_type_level})"
    for prefix, source in SPECIAL_SOURCES.items():
        if label.startswith(prefix):
            return source
    return "Passive"


def _values(talent, level=10):
    """The Skill/Burst table rows that read like buffs, at a talent level."""
    if not talent.upgrades or len(talent.upgrades) < level:
        return ""
    up = talent.upgrades[level - 1]
    out = []
    for row in up.description or []:
        key, _, tmpl = row.partition("|")
        k = key.lower()
        if key and _has(k, VALUE_KEYS) and not _has(k, SKIP_KEYS):
            out.append(f"{key} {gamedata.format_multiplier(tmpl, up.params)}")
    return "; ".join(out)


_LIST_ITEM = re.compile(r"^[\"“]?[A-Z0-9][\w' -]{1,30}[\"”]?:\s+\S")  # "Geo: …", '"Standing Firm": +10%'
# changes to another effect that aren't about its strength
_NOT_STRENGTH = re.compile(r"(duration|\bcd\b|cooldown|energy|range|aoe|heal\w*|shield|stamina|interval|charges?)\b"
                           r"[^.]{0,110}(is |are )?(increased|extended|decreased|reduced)"
                           r"|(increas|extend|decreas|reduc)\w* (the )?(duration|cd|cooldown|energy|range|aoe|charges?)\b"
                           r"|\bnumber of\b|additional charges?|\bcharges?\b|\b(re)?gains? \d+ (elemental )?energy"
                           r"|restores? \d+ (elemental )?energy|\bchance\b|\b(join in|coordinated attack)")


def _list_entries(source, sentences, start, names, values):
    """An intro naming who gets something, ending in ":", then "Name: effect" lines (Xilonen's C2:
    "…all nearby party members will gain effects…:" / "Geo: DMG dealt +50%." / "Pyro: ATK +45%."):
    one entry for the whole list. Returns (entry or None, index after the list)."""
    intro = sentences[start]
    who = _who(_norm(intro), names, ["atk"])  # who the intro names, whatever the buff turns out to be
    end = start + 1
    while end < len(sentences) and _LIST_ITEM.match(sentences[end]):
        end += 1
    items = sentences[start + 1:end]
    if not who or not items:
        return None, start + 1
    types, elements = [], []
    for item in items:
        types += _types(_norm(item), table_values=bool(values))
        elements += _elements(item.split(":", 1)[0].lower())  # "Geo: …" -> geo
    if not types:  # items that are only amounts ('"Crunch": +40%'): the intro says what they raise
        types = _types(_norm(intro), table_values=bool(values))
        elements += _elements(_TRIGGER_CLAUSE.sub("", _norm(intro)))
    if not types:
        return None, start + 1
    # the items in point form under the intro
    text = intro + "".join(f"\n•  {i}" for i in items) + (f" ({values})" if values else "")
    tags = " ".join(dict.fromkeys(types + elements))
    return (source, tags, who, text, _condition("", intro), ""), end


_LEVEL_UP = re.compile(r"Increases the Level of (?:the )?(?:Elemental (?:Skill|Burst) )?(.+?) by 3", re.I)
# a limit or "per point" detail of the line before: added to that entry rather than listed on its own
_CAP = re.compile(r"\b(maximum|max\b|cannot exceed|up to)\b(?:[^.]|\.\d)*\b(this way|this manner)\b"
                  r"|\b(this way|this manner)\b(?:[^.]|\.\d)*\b(maximum|max\b|cannot exceed|up to)\b|^(max|maximum) \d+ stacks?"
                  r"|^(a )?maximum (increase|of|dmg)\b|^the maximum (increase|dmg|bonus|number)\b"
                  r"|^(the |this )?increase in dmg\b|^each stack\b|^every (\d|excess|point)|^for every \d", re.I)


def _append(text, sentence, values):
    """Add a sentence to an entry's text, before the talent-table values in brackets."""
    suffix = f" ({values})" if values and text.endswith(f"({values})") else ""
    base = text[: len(text) - len(suffix)] if suffix else text
    return f"{base} {sentence}{suffix}"


def _mentioned(s, term_info):
    """The longest kit term (lower case) from term_info that the sentence mentions, or None."""
    return next((t for t in sorted(term_info, key=len, reverse=True) if t in s), None)


def _own_skill_dmg(s, own_names, strict=False):
    """The sentence boosts one of the character's own skills. strict: only the unmistakable "DMG dealt by
    <skill>" form, which holds even when party members feed it (Lohen's Will to Win)."""
    for o in own_names:
        o = re.escape(o)
        if re.search(rf"dmg (dealt )?(by|of) (the |that )?{o}", s):
            return True
        if not strict and (re.search(rf"{o}('s?|'|:)?(,? [\w-]+){{0,6}} dmg (is |are )?(increased|by)", s)
                           or re.search(rf"increas\w* (the )?{o}('s?|')? dmg", s)):
            return True
    return False


# limited uses: stacks spent, or "removed after being triggered a certain number of times"
# (not "consume this state" or "charge a shot": those aren't uses of a buff)
_SPENT = re.compile(r"\b(stacks?|usages?|\d+ times|number of times|times? remaining)\b|\b\d+ charges\b|\bexpend\w* \d+"
                    r"|removed(?:[^.]|\.\d){0,40}after (dealing|being|triggering|it)", re.I)  # "removed 0.05s after"


def _scan_text(source, text, names, values="", term_info=None, own_names=(), spent_terms=()):
    """Entries for one talent or constellation. term_info: {kit term: (who, types)} learned from the rest of
    the kit, so a line that only strengthens another effect ("Enhances the effects of Kiongozi…") or names
    its holders by that effect ("characters under the Flying Cloud Flag Formation") is understood.
    spent_terms: kit terms (lower case) used up in limited uses elsewhere in the kit (Lauma's Pale Hymn),
    so a line that strengthens them is still Quills."""
    term_info = term_info or {}
    term_who = {t: w for t, (w, _) in term_info.items()}
    entries = []
    paragraph = ""
    context = None  # who the section's last sentences were about ("…grants all nearby party members X. X: …")
    own_before = None  # the last of the character's own buffs in this section (sentence, types)
    sentences = _sentences(text)
    # Quills are flat DMG used up from a limited number of stacks or uses (Shenhe's Icy Quills, Yun Jin's
    # Flying Cloud Flag Formation): only where this part of the kit counts them out
    spent = bool(_SPENT.search(text))
    i = 0
    while i < len(sentences):
        sentence = sentences[i]
        if sentence.endswith(":") and i + 1 < len(sentences) and _LIST_ITEM.match(sentences[i + 1]):
            entry, after = _list_entries(source, sentences, i, names, values)
            if entry:
                entries.append(entry)
                paragraph = ""
                i = after
                continue
        i += 1
        s = _norm(sentence)
        if _LEVEL_UP.search(sentence) or s.startswith("maximum upgrade level"):
            continue  # talent level-ups get their own level-13 entry (scan_character)
        if "secret rite effect" in s or "become a hexerei character" in s or "becomes a hexerei character" in s:
            continue  # the same Hexerei intro in every Hexerei kit
        if re.search(r"\b(will|do|does|can)( not|n't) stack\b", s):
            continue  # a stacking rule, not a buff
        # a limit on the line before ("You can gain a maximum of 250 Elemental Mastery in this manner."):
        # part of that entry, not a buff of its own
        if entries and _CAP.search(s) and entries[-1][0] == source and not _has(s, TEAM + OTHERS + ACTIVE_NAMED):
            last = entries[-1]
            tags = last[1]
            # the detail can say what kind of increase it is: "Increase in DMG is based on Illuga's Elemental
            # Mastery" makes the line before flat DMG (Quills, when it's used up from stacks)
            if "quills" in _types(s, table_values=bool(values)) and (spent or any(t in last[3].lower() for t in spent_terms)):
                tags = " ".join(dict.fromkeys("quills" if t == "dmg" else t for t in tags.split()))
                if "quills" not in tags.split():
                    tags = "quills " + tags
            entries[-1] = (last[0], tags, last[2], _append(last[3], sentence, values)) + last[4:]
            continue
        # the amount of the line before ("Lunar-Charged: ATK of your current active character increases." /
        # "Increase in ATK is equal to 1% of Columbina's Max HP."): part of that entry
        if (entries and entries[-1][0] == source and re.search(r"\d", s)
                and re.match(r"(the |this |that )?(increase|decrease|bonus|reduction)( in [\w' -]+)? (is|will be) (equal to|based on|\d)", s)):
            last = entries[-1]
            entries[-1] = (last[0], last[1], last[2], _append(last[3], sentence, values)) + last[4:]
            continue
        types = _types(s, table_values=bool(values), enemy_context=context == "enemy")
        if "quills" in types and not spent and not any(t in s for t in spent_terms):
            # flat DMG that isn't used up (Faruzan's Hurricane Guard, every 0.8s) is a plain DMG increase
            types = list(dict.fromkeys("dmg" if t == "quills" else t for t in types))
        own_skill = _own_skill_dmg(s, own_names, strict=True) or (
            _own_skill_dmg(s, own_names) and not _has(s, TEAM + OTHERS + ACTIVE_NAMED))
        if own_skill:
            types = [t for t in types if t not in ("dmg", "quills", "crit")]
        who = _who(s, names, types, term_who) if types else None
        own = _self_subject(s, names) or _self_buff(s, names)
        # a line that only strengthens another effect: same kind of buff, same people
        term = _mentioned(s, term_info)
        if (term and not who and not own and not own_skill and re.search(r"\d", s) and not _NOT_STRENGTH.search(s)
                and re.search(r"\badditional\b|\bfurther\b|increas|enhanc|\bgains?\b", s)
                and not re.search(rf"{re.escape(term)}('s?|’s?)? (\w+ )?dmg|dmg (dealt )?(by|of) (the |that )?{re.escape(term)}", s)):
            who = term_info[term][0]
            types = types or list(term_info[term][1])
        # no one named, but the lines before were about the party / the on-field character / opponents
        if (types and not who and context and not own and (re.search(r"\d", s) or values)
                and not re.search(r"described above|aforementioned dmg", s)
                and (context != "enemy" or set(types) & {"res", "defshred", "taken"} or re.search(r"\breceive", s))):
            who = context
        # the character's own effect, handed to whoever comes on next ("…the incoming active character will take
        # on the Together We Rise effect"): the buff before it, for them
        if not types and own_before and re.search(r"take on|inherit|transferr?ed to|passed to", s):
            handed = _who(s, names, ["atk"])
            if handed:
                before_sentence, before_types = own_before
                tags = " ".join(dict.fromkeys(before_types + _elements(_norm(before_sentence))))
                entries.append((source, tags, handed, f"{before_sentence} {sentence}", _condition(paragraph, before_sentence), ""))
        if types and own and not who:
            own_before = (sentence, types)
        # a follow-up about the people the line before buffed ("If said character is in the Nightsoul's Blessing
        # state, they will deal an additional 9% DMG"): part of that entry
        if (types and not who and not own and entries and entries[-1][0] == source and entries[-1][2] != "enemy"
                and re.search(r"\b(said|such|that|these|those|the) characters?\b|\bthey\b|\btheir\b"
                              r"|characters? affected by the (aforementioned|above)", s)
                and not _has(s, ENEMY)):
            last = entries[-1]
            tags = " ".join(dict.fromkeys(last[1].split() + types + _elements(s)))
            entries[-1] = (last[0], tags, last[2], _append(last[3], sentence, values)) + last[4:]
            continue
        if types and who:
            # elements of the buff itself, not of the reaction that triggers it
            elements = _elements(s if who == "enemy" else _TRIGGER_CLAUSE.sub("", s))
            tags = " ".join(dict.fromkeys(types + elements))
            line = sentence + (f" ({values})" if values else "")
            entries.append((source, tags, who, line, _condition(paragraph, sentence), ""))
        probe = _who(s, names, ["atk"])
        enhanced = term if term and re.search(r"\benhance", s) else None
        # (opponents only named in the "when … hits an opponent," trigger don't make the list theirs)
        if _has(_TRIGGER_CLAUSE.sub("", s), ENEMY) and sentence.endswith(":") and not _has(_TRIGGER_CLAUSE.sub("", s) if probe else s, TEAM + ACTIVE_NAMED):
            context = "enemy"
        elif enhanced:  # "Enhances the effects of the Ascension Talent "Kiongozi":" -> the lines after are for its people
            context = term_info[enhanced][0]
        elif probe:
            context = probe
        elif sentence.endswith(":") and _has(s, TEAM):
            # "When any of your own party members hits an opponent…, the effects of … are enhanced:" — the
            # party triggers it and the party gets what's listed
            context = "team"
        paragraph = sentence if sentence.endswith(":") else paragraph + " " + sentence
    return entries


# ----- kit terms: named effects and talents the entries mention, for hover explanations -----
# the game writes a kit's named effects in this gold, as headings with their explanation underneath
_GOLD_HEADING = re.compile(r"^\s*<color=#FFD780FF>([^<]{3,60})</color>\s*$", re.I)
_GOLD_INLINE = re.compile(r"<color=#FFD780FF>([^<]{3,60})</color>", re.I)
_GENERIC_TERMS = {"press", "hold", "tap", "normal attack", "charged attack", "plunging attack", "arkhe: ousia",
                  "arkhe: pneuma", "hexerei: secret rite"}
MAX_TERM_TEXT = 420


_ITALIC = re.compile(r"<i>.*?</i>", re.S)
# words that show a line describes what the ability does (the first line is often just flavor)
_MECHANICAL = re.compile(r"\b(dmg|deal|party|character|summon|enter|creat|grant|increas|decreas|heal|shield|"
                         r"attack|opponent|state|effect|consum|gain|apply|applies|mode|stack)", re.I)


def _paragraph(text):
    """A short plain explanation: the first non-flavor paragraph(s) of some kit text."""
    out = []
    plain = gamedata.clean(_ITALIC.sub("", gamedata.resolve_layout(text or "").replace("\\n", "\n")))
    lines = [l for l in plain.split("\n")]
    while len(lines) > 1 and lines[0].strip() and not _MECHANICAL.search(lines[0]):
        lines.pop(0)  # flavor line
    for para in re.split(r"\n\s*\n", "\n".join(lines)):
        para = para.strip()
        if not para or para.startswith(("\"", "“")):
            continue
        out.append(para)
        if sum(map(len, out)) > 160:
            break
    text = "\n".join(out)
    return text if len(text) <= MAX_TERM_TEXT else text[:MAX_TERM_TEXT].rsplit(" ", 1)[0] + "…"


def _headings(raw):
    """{term: explanation} for the gold headings in a talent's text ("Blood Blossom" + the lines after it)."""
    lines = gamedata.resolve_layout(raw).replace("\\n", "\n").split("\n")
    found = {}
    for i, line in enumerate(lines):
        m = _GOLD_HEADING.match(line)
        if not m or m.group(1).strip().lower() in _GENERIC_TERMS or m.group(1).startswith(("Moonsign", "Radiance")):
            continue  # state labels like "Moonsign: Ascendant Gleam" read better as conditions
        body = []
        for following in lines[i + 1:]:
            if not following.strip() or _GOLD_HEADING.match(following):
                break
            body.append(following)
        text = _paragraph("\n".join(body))
        if text:
            found.setdefault(m.group(1).strip(), text)
    return found


def _kit_terms(char_id, name, talents, labels, constellations, texts, buffed):
    """{term: (explanation, where it's from)} for a character's kit."""
    terms = {}
    places = []  # (source label, raw text) in kit order, to say where a glossary term comes from
    for talent, label in zip(talents, labels):
        tname = gamedata.clean(talent.name)
        raw = buffed.get(tname) or texts.get(tname) or talent.description or ""
        where = f"{name}'s {label} ({tname})" if label != tname else f"{name}'s passive ({tname})"
        places.append((where, raw))
        for term, text in _headings(raw).items():
            terms.setdefault(term, (text, where))
        if label not in ("Normal Attack", "Alternate Sprint", "Special Jump"):
            terms.setdefault(tname, (_paragraph(raw), where))
    for n, con in enumerate(constellations, 1):
        cname = gamedata.clean(con.name)
        raw = buffed.get(cname) or texts.get(cname) or con.description or ""
        where = f"{name}'s Constellation {n} ({cname})"
        places.append((where, raw))
        terms.setdefault(cname, (_paragraph(raw), where))
    # the game's own glossary (newer characters) is the real explanation of a linked name, so it goes before
    # the sentences that merely use it; say which part of the kit mentions it first
    for term, description in gamedata.CHAR_GLOSSARY.get(char_id, []):
        where = next((w for w, raw in places if term in gamedata.clean(raw)), f"{name}'s kit")
        terms.setdefault(term, (_paragraph(gamedata._GLOSSARY_LINK.sub(r"\1", description)), where))
    # other gold-highlighted names ("Prayerful Wind's Benefit"): explained by the sentences that use them
    for where, raw in places:
        for term in dict.fromkeys(m.strip() for m in _GOLD_INLINE.findall(gamedata.resolve_layout(raw))):
            if term in terms or term.lower() in _GENERIC_TERMS or term.startswith(("Moonsign", "Radiance")):
                continue
            uses = [s for s in _sentences(raw) if term in s]
            if uses:
                text = " ".join(uses[:2])
                terms[term] = (text if len(text) <= MAX_TERM_TEXT else text[:MAX_TERM_TEXT].rsplit(" ", 1)[0] + "…", where)
    return {t: v for t, v in terms.items() if v[0] and t.lower() not in _GENERIC_TERMS}


def scan_character(char_id, name):
    """Buffs-page data for a character, read from their kit (the updated text where reworked):
    {"entries": [(source, tags, who, text, condition, "")], "terms": {term: [explanation, source]}}
    where terms only holds the kit terms the entries mention."""
    detail = gamedata.fetch_character_detail(char_id)
    try:
        texts, buffed = gamedata.fetch_character_markup(char_id)
    except Exception:
        texts, buffed = {}, {}
    names = {name.lower(), name.split()[0].lower(), name.split()[-1].lower()}
    talents = gamedata.real_talents(detail.talents)
    labels = gamedata.talent_labels(talents)
    # (source, talent or constellation name, raw text, level-10 values, talent) for each part of the kit
    sections = []
    for talent, label in zip(talents, labels):
        if label in ("Normal Attack", "Alternate Sprint", "Special Jump", "Utility Passive"):
            continue
        tname = gamedata.clean(talent.name)
        raw = buffed.get(tname) or texts.get(tname) or talent.description
        name_label = label if label not in ("Passive Talent",) else tname
        values = _values(talent) if label in ("Elemental Skill", "Elemental Burst") else ""
        source = _source(name_label, 10)
        if source == "Passive" and re.search(r"Radiance|Polestar Field", gamedata.clean(raw)):
            source = "Stellar"  # the Stellar passives aren't named by category, but they're about Radiance states
        sections.append((source, tname, raw, values, talent))
    for n, con in enumerate(detail.constellations, 1):
        cname = gamedata.clean(con.name)
        sections.append((f"C{n}", cname, buffed.get(cname) or texts.get(cname) or con.description, "", None))
    all_terms = _kit_terms(char_id, name, talents, labels, detail.constellations, texts, buffed)

    # pass 1: what each part says on its own; then learn which effects reach whom
    own_names = [sec[1].lower() for sec in sections]
    first = {sec[1]: _scan_text(sec[0], sec[2], names, sec[3], own_names=own_names) for sec in sections}
    term_info = {}
    for source, sname, raw, _values_, _talent in sections:
        found = first[sname]
        if not found:
            continue
        # who it reaches: the party side if it does both (Faruzan's Burst shreds *and* buffs)
        helps = [e for e in found if e[2] != "enemy"] or found
        info = (helps[0][2], tuple(dict.fromkeys(t for e in helps for t in e[1].split() if t in _TYPE_KEYS)))
        term_info.setdefault(sname.lower(), info)  # the talent itself ("Kiongozi", "Fantastic Voyage")
        # effects it hands out ("…gain the Lightkeeper's Oath effect", "grants … a Flying Cloud Flag Formation"),
        # not ones only mentioned as the trigger ("defeating an enemy affected by a Blood Blossom")
        given = _norm(" ".join(e[3] for e in found if e[2] != "enemy"))
        for term in all_terms:
            t = re.escape(term.lower())
            if re.search(rf"(gains?|grants?|granting|bestow\w*|confers?|apply|applies)\b[^.]{{0,60}}\b{t}"
                         rf"|(under|with|affected by|by) (the )?(effects? of (the )?)?{t}", given):
                term_info.setdefault(term.lower(), info)
    # named effects used up in limited uses (their own section or explanation counts them out)
    spent_texts = [gamedata.clean(raw) for _, _, raw, *_ in sections if _SPENT.search(gamedata.clean(raw))]
    spent_terms = {sname.lower() for _, sname, raw, *_ in sections if _SPENT.search(gamedata.clean(raw))}
    spent_terms |= {t.lower() for t, (explanation, _w) in all_terms.items() if _SPENT.search(explanation)}
    # and the effects such a section describes ("Flying Cloud Flag Formation", a heading in Yun Jin's Burst)
    spent_terms |= {t.lower() for t in all_terms if any(t in text for text in spent_texts)}
    spent_terms = tuple(t for t in spent_terms if len(t) > 3)
    # pass 2: read everything again knowing that
    entries = []
    by_talent = {}
    for source, sname, raw, values, talent in sections:
        found = _scan_text(source, raw, names, values, term_info, own_names, spent_terms)
        if not found and values:
            # the buff is only in the description of an effect the talent creates (Columbina's Burst:
            # "transforms the surrounding terrain into Lunar Domain"): read that effect's description
            plain = gamedata.clean(raw).lower()
            for term, (explanation, _where) in all_terms.items():
                if term.lower() != sname.lower() and re.search(rf"(?<![\w-]){re.escape(term.lower())}(?![\w-])", plain):
                    found = [(e[0], e[1], e[2], f"{term}: {e[3]}", *e[4:])
                             for e in _scan_text(source, explanation, names, values, term_info, own_names, spent_terms)]
                    if found:
                        break
        if not found:
            # the buff is only in the game glossary entry the text links to (Odette's A1: "she also obtains 4
            # stacks of Marvelous Splendor"; the entry says what a stack does and who else gets them)
            plain = gamedata.clean(raw)
            for term, description in gamedata.CHAR_GLOSSARY.get(char_id, []):
                t = re.escape(term.lower())
                # only where this part of the kit gives the effect, not where it merely mentions it
                giving = [x for x in _sentences(plain) if re.search(
                    rf"(obtain|gain|grant|bestow|confer|appl)\w*[^.]{{0,50}}{t}", _norm(x))]
                if term.lower() == sname.lower() or not giving:
                    continue
                text = gamedata.clean(gamedata._GLOSSARY_LINK.sub(r"\1", description).replace("\\n", "\n"))
                found = _scan_text(source, text, names, values, term_info, own_names, spent_terms)
                if not found:
                    continue
                # who has it, from the whole entry: "…while other nearby party members gain the corresponding
                # number of Marvelous Splendor stacks"; with the character holding it too, that's the team
                holders = {_who(_norm(x), names, ["atk"]) for x in _sentences(text) + giving} - {None}
                own_too = any(_self_subject(_norm(x), names) for x in giving)
                who = "team" if holders & {"others", "team"} and own_too else next(iter(holders), None)
                # this part's own sentence ("…she also obtains 4 stacks of Marvelous Splendor"), then what it does
                found = [(e[0], e[1], who or e[2], f"{' '.join(giving)}\n{term}: {e[3]}", *e[4:]) for e in found]
                break
        own_bonus = any(re.search(rf"(dmg|reaction)[^.]{{0,60}}\b{re.escape(n)} deals|dealt by {re.escape(n)}\b", x)
                        for x in [_norm(y) for y in _sentences(gamedata.clean(raw))] for n in names)
        if not found and not own_bonus and re.search(r"(lunar|reaction)[^;]*dmg bonus", values, re.I):
            # (not when the text says it's the character's own: Odette's "…increases the Stellar Glimmer
            # reaction DMG Odette deals")
            # nothing in the text but the table names a party reaction bonus (Columbina's Lunar Domain:
            # "Lunar Reaction DMG Bonus 40.0%"): reaction DMG always counts for the whole party
            sentences = _sentences(gamedata.clean(raw))
            intro = next((x for x in sentences if any(
                t.lower() != sname.lower() and t in x for t in all_terms)), sentences[-1] if sentences else sname)
            found = [(source, "reaction", "team", f"{intro} ({values})", "", "")]
        entries += found
        if talent is not None:
            by_talent[sname.lower()] = (talent, found)
    # C3/C5 raising a Skill/Burst that buffs the team: the same buff at talent level 13
    for source, sname, raw, _values_, talent in sections:
        if talent is not None or not (m := _LEVEL_UP.search(gamedata.clean(raw))):
            continue
        wanted = re.sub(r"\s+", " ", m.group(1)).strip().lower()  # "The Wind's Secret Ways" lost its "The"
        raised = by_talent.get(wanted) or by_talent.get("the " + wanted)
        if not raised or not raised[1]:
            continue
        talent_obj, base = raised
        at13 = _values(talent_obj, 13)
        if not at13 or at13 == _values(talent_obj, 10):
            continue  # the buff doesn't grow past level 10 (Ayato's Burst: Normal Attack DMG stays 20%)
        tags = " ".join(dict.fromkeys(t for e in base for t in e[1].split()))
        kind = "Q" if base[0][0].startswith("Q") else "E"
        lead = next((e for e in base if e[2] != "enemy"), base[0])
        entries.append((source, tags, lead[2], f"{kind}(13): {gamedata.clean(talent_obj.name)} at talent level 13 ({at13})",
                        lead[4], ""))
    # effects a constellation lets stack (Alyosha's C6: "The Hunter's Precision effect … can now stack, max 2
    # stacks"): the Buff/Shred List's totals count them that many times
    stacks = []
    for source, sname, raw, _values_, talent in sections:
        if talent is not None:
            continue
        for m in re.finditer(r"(?:the\s+)?([A-Z][\w'’ -]{2,40}?) effect\b[^.]{0,80}?\bcan (?:now )?stack,?\s*(?:up to\s*)?"
                             r"max(?:imum)?\.?\s*(?:of\s*)?(\d+)\s*stacks", gamedata.clean(raw)):
            stacks.append([source, re.sub(r"^(?:the|an?)\s+", "", m.group(1).strip(), flags=re.I), int(m.group(2))])
    # utility only counts for the party's stamina, cooldowns and infusions, not the character's own skills
    own_skills = [sname.lower() for _, sname, *_ in sections]
    def own_cooldown(text):  # "Lightning Blade's CD is decreased", "the CD of Inuzaka All-Round Defense"
        t = _norm(text)
        return bool(re.search(r"(that|this) skill's (cd|cooldown)|\bits (cd|cooldown)", t)) or any(
            re.search(rf"(cd|cooldown) of (the |his |her )?(\w+'s )?{re.escape(o)}|{re.escape(o)}('s)? (cd|cooldown)", t)
            for o in own_skills)

    entries = [e for e in entries if not own_cooldown(e[3]) and (
        e[1].split()[0] != "utility" or len(e[1].split()) > 1 and e[1].split()[1] in _TYPE_KEYS
        or re.search(r"stamina|infus|\bcd\b|cooldown", e[3], re.I))]
    # buffs the character only gives themself, which the kit's wording doesn't make clear
    skipped = SELF_ONLY.get(name.replace("Lumine (", "Aether ("), ())
    entries = [e for e in entries if not any(e[0] == source and e[3].startswith(start) for source, start in skipped)]
    terms = {}
    if entries:
        used = " ".join(e[3] for e in entries)
        terms = {t: list(v) for t, v in all_terms.items() if re.search(rf"(?<![\w-]){re.escape(t)}(?![\w-])", used)}
    return {"entries": [list(e) for e in entries], "terms": terms, "stacks": stacks}
