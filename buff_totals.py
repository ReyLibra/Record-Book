"""What a character's buffs add up to (the Buff/Shred List cards' TOTAL), e.g. "+21.2% ATK", "+100 EM".

From the buff lines shown (so it follows the Cons toggles), each amount is read with the stat it raises, from
the words around it in its sentence. Then:
- a C3/C5 "talent level 13" line replaces the same stats from that Skill/Burst's level-10 line;
- within one source the highest of its alternatives counts (Sucrose's small or large Wind Spirit);
- "additional" / "further" amounts add on to the same stat from another source (Bennett's C1 on his Burst);
- an effect a constellation lets stack (Alyosha's C6: Hunter's Precision, max 2) counts that many times;
  "per point / per stack, max N" and "… Max N stacks" amounts count N times; amounts that grow to a stated
  maximum use it;
- conversions ("0.04% … for every point of Elemental Mastery", per Fanfare) stay "per …", with their cap;
- a Lunar / Stellar passive's Base DMG reads the same for everyone: "+14% … Base DMG (max; 0.7% per 100 ATK)".
Every line starts with its source ("A4: …"), in kit order; a source that gives a choice of damage bonuses
(Vodyanitsa's A4: Hydro and Cryo DMG or Stellar Swirl DMG; Xilonen's C2 by element) joins them with "or".
Damage added by spending stacks or uses (the "Quills" tag) is marked as such, and flat amounts say "Flat".
What a kit's wording can't tell (a stack count it leaves out, a party buff with a bigger one for the character
themself) is in OVERRIDES.
It reads text, so it's a summary: each line still says exactly what it does.
"""

import re

ELEMENTS = ("Pyro", "Hydro", "Electro", "Cryo", "Anemo", "Geo", "Dendro", "Physical")
REACTIONS = ("Lunar-Charged", "Lunar-Bloom", "Lunar-Crystallize", "Stellar-Conduct", "Stellar Glimmer", "Stellar Swirl",
             "Electro-Charged", "Hyperbloom", "Burgeon", "Overloaded", "Superconduct", "Burning", "Bloom", "Spread",
             "Aggravate", "Vaporize", "Melt", "Swirl", "Crystallize", "Shatter")
BLOOM_RELATED = {"Bloom", "Hyperbloom", "Burgeon"}

_EL = "|".join(ELEMENTS)
_RX = "|".join(re.escape(r) for r in REACTIONS)
_JOIN = r"(?:\s*,\s*(?:and |or )?|\s+and\s+|\s+or\s+|\s*/\s*)"

# stat names as they appear in kit text -> how they're totalled (earlier patterns win where they overlap)
_KEYWORDS = [
    (r"normal(?: attack)?, charged(?: attack)?,? (?:and |or )?plunging attack[^.]{0,60}?dmg", "DMG Bonus"),
    (rf"\b((?:{_RX})(?:{_JOIN}(?:{_RX}))+)(?: reaction)?(?: dmg| damage)", "{0} DMG"),
    (rf"\b({_RX})(?:'s| reaction's)? base dmg", "{0} Base DMG"),
    (r"base dmg of lunar reactions|lunar reactions?'s? base dmg", "Lunar Reaction Base DMG"),
    (r"\blunar reactions? dmg", "Lunar Reaction DMG"),
    (r"elemental dmg with (?:their |his |her )?normal attacks", "Elemental Normal Attack DMG"),
    (r"atk spd|attack speed", "ATK SPD"),
    (r"dendro core burst dmg(?: bonus)?", "Dendro Core Burst DMG Bonus"),
    (r"bountiful cores?(?:'s)? dmg|dmg dealt by bountiful cores", "Bountiful Core DMG"),
    (rf"\b({_RX})\b(?: reaction)?(?: dmg| damage)", "{0} DMG"),
    (r"(normal attack|charged attack|plunging attack|elemental skill|elemental burst)(?:'s)? crit rate", "{0} CRIT Rate"),
    (r"(normal attack|charged attack|plunging attack|elemental skill|elemental burst)(?:'s)? crit dmg", "{0} CRIT DMG"),
    (r"crit rate", "CRIT Rate"),
    (r"crit dmg", "CRIT DMG"),
    (r"elemental mastery", "EM"),
    (r"energy recharge", "Energy Recharge"),
    (r"(?:incoming )?healing bonus", "Healing Bonus"),
    (r"shield strength", "Shield Strength"),
    (rf"\b((?:{_EL})(?:\s+res)?(?:{_JOIN}(?:{_EL})(?:\s+res)?)*)\s+res\b", "{0} RES shred"),
    (r"elemental res|\bres\b", "RES shred"),
    (r"def bonus|\bdef\b", "DEF"),
    (r"(normal attack|charged attack|plunging attack|elemental skill|elemental burst) dmg", "{0} DMG"),
    (rf"\b((?:{_EL})(?: dmg)?(?:{_JOIN}(?:{_EL}))+) dmg(?: bonus)?", "{0} DMG Bonus"),
    (rf"\b({_EL}) dmg(?: bonus)?", "{0} DMG Bonus"),
    (r"elemental dmg(?: bonus)?", "Elemental DMG Bonus"),
    (r"\batk\b", "ATK"),
    (r"max(?:imum)? hp|\bhp\b", "Max HP"),
    (r"\bdmg\b", "DMG Bonus"),
]
_KEYWORDS = [(re.compile(p, re.I), name) for p, name in _KEYWORDS]

_NUMBER = re.compile(r"(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(%?)")
_NOT_AMOUNT = re.compile(r"^\s*((?!of\b)\w+\s+)?(s\b|sec|second|m\b|stacks?|times|hits?|energy|elemental energy|charges?"
                         r"|targets?|opponents?|enemies|members?|characters?|levels?|such points|points?\b|buffs?"
                         r"|(?:lower|higher|slower|faster) rate)", re.I)
_SEQUENCE = re.compile(r"\d[\d,.]*%?(?:\s*/\s*\d[\d,.]*%?)+")  # "60/90/120/200", "5%/10%/15%/55%": the last one counts
_STAT_WORDS = {"atk": "ATK", "def": "DEF", "max hp": "Max HP", "hp": "Max HP", "elemental mastery": "EM",
               "energy recharge": "Energy Recharge"}
# a Lunar / Stellar passive: "the Base DMG … increased by 0.7% for every 100 points of Odette's ATK. A maximum
# increase of 14%…" (or "every 100 ATK … increasing Lunar-Charged's Base DMG by 0.7%, up to a maximum of 14%")
_STATS = r"(atk|def|max hp|elemental mastery)"
_BASE_RATE = re.compile(rf"(\d+(?:\.\d+)?)%\s*(?:for every|per)\s*(\d[\d,]*)\s*(?:points of\s*)?(?:(?:the\s+)?[\w']+\s+)?{_STATS}\b"
                        rf"|every\s*(\d[\d,]*)?\s*(?:points? of\s*)?{_STATS}\b[^.]{{0,90}}?\bby\s*(\d+(?:\.\d+)?)%", re.I)
_BASE_TOP = re.compile(r"(?:maximum|max\.?|up to)[^.%]{0,60}?(\d+(?:\.\d+)?)%", re.I)
_BEFORE_NOT = re.compile(r"(every|within|for|lasts?|after|once|cd of|cooldown of|level|lv\.?|count reaches|excess of"
                         r"|in excess of|above|below|exceeds?)\s*$", re.I)
_PER_HP = re.compile(r"every 1,?000 (?:points of )?(?:[\w']+ )?max hp", re.I)
_CAP = re.compile(r"(maximum|max\.?(?! hp)|up to|cap)\b[^.]{0,80}$", re.I)
_SHRED_WORDS = re.compile(r"decreas|reduc|lower|shred", re.I)


def _title(name):
    return name if not name.islower() else name.title()


def _names(group):
    """'Hydro/Cryo', 'Hydro DMG and Cryo' -> ["Hydro", "Cryo"]."""
    return [n.strip() for n in re.split(rf"{_JOIN}|\s+dmg\b|\s+res\b", group, flags=re.I)
            if n and n.strip() and n.strip().lower() not in ("dmg", "res")]


def _join_names(names):
    names = [_title(n) for n in names]
    if BLOOM_RELATED <= set(names):  # "Bloom, Hyperbloom & Burgeon" in any order
        names = ["Bloom-related reactions"] + [n for n in names if n not in BLOOM_RELATED]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " & " + names[-1]


def _clauses(text):
    """Sentences (and list items) with where each starts."""
    out, start = [], 0
    for m in re.finditer(r"(?<=[.!?])\s+(?=[A-Z\"•(])|\n+|\s*•\s*", text):
        out.append((start, text[start:m.start()]))
        start = m.end()
    out.append((start, text[start:]))
    return [(s, c) for s, c in out if c.strip()]


def _keywords(clause):
    """[(start, end, stat)] for each stat named in a clause."""
    found = []
    for pattern, name in _KEYWORDS:
        for m in pattern.finditer(clause):
            if any(s <= m.start() < e or s < m.end() <= e for s, e, _ in found):
                continue
            if name == "Max HP" and re.search(r"(every 1,?000 (points of )?|based on (the )?|of )([\w']+ )?$",
                                              clause[max(0, m.start() - 40):m.start()], re.I):
                found.append((m.start(), m.end(), "(basis)"))  # "based on Dahlia's Max HP", "every 1,000 Max HP"
                continue
            stat = name
            if "{0}" in name:
                stat = name.format(_join_names(_names(m.group(1))))
                if stat == "Bloom-related reactions DMG":
                    stat = "Bloom-related reaction DMG"
            if stat.endswith("RES shred") and not _SHRED_WORDS.search(clause):
                stat = stat.replace("RES shred", "RES")
            if stat == "DEF" and _SHRED_WORDS.search(clause[m.end():m.end() + 30] + clause[max(0, m.start() - 30):m.start()]):
                stat = "DEF shred"
            found.append((m.start(), m.end(), stat))
    return sorted(f for f in found if f[2] != "(basis)")


def _nearest(keywords, at, end):
    """The stat named nearest to a number: just after it ("15% Pyro DMG Bonus") or before it ("ATK by 20%")."""
    best, best_d = None, 10 ** 6
    for s, e, stat in keywords:
        d = (s - end) * 0.6 if s >= end else at - e
        if 0 <= d < best_d:
            best, best_d = stat, d
    return best


def _value(text):
    return float(text.replace(",", ""))


_TAG_OF = {"DEF": "def", "ATK": "atk", "EM": "em", "Max HP": "hp"}


def _base_dmg_passive(text):
    """A Lunar / Stellar passive's Base DMG increase, worded the same for every character: its maximum, then
    the rate it grows at ("+14% Lunar-Charged Base DMG (max; 0.7% per 100 ATK)"), or None."""
    if not re.search(r"base dmg|base [\w -]+ dmg", text, re.I):
        return None
    rate, top = _BASE_RATE.search(text), None
    if rate:
        top = _BASE_TOP.search(text, rate.end()) or _BASE_TOP.search(text)
    if not (rate and top):
        return None
    if rate.group(1):
        value, every, stat = rate.group(1), rate.group(2), rate.group(3)
    else:
        every, stat, value = rate.group(4), rate.group(5), rate.group(6)
    reactions = [r for r in REACTIONS if r.startswith(("Lunar", "Stellar")) and re.search(rf"\b{re.escape(r)}\b", text)]
    if not reactions and re.search(r"\blunar reactions?\b", text, re.I):
        reactions = ["Lunar Reaction"]  # Columbina: every Lunar reaction
    if not reactions:
        return None
    reactions.sort(key=lambda r: text.find(r))
    per = f"{every} {_STAT_WORDS[stat.lower()]}" if every else _STAT_WORDS[stat.lower()]  # "per 100 ATK", "per EM"
    scaling = f"(max; {value}% per {per})"
    return (f"{_join_names(reactions)} Base DMG", _value(top.group(1)), "%", scaling, False, False)


def amounts(text, name="", tags=""):
    """[(stat, value, unit, scaling, cap, additional)] read from one buff line."""
    out = []
    owner = [n for n in {name, name.split()[0] if name else "", name.split()[-1] if name else ""} if n]
    tag_set = set(tags.split())
    passive = _base_dmg_passive(text)
    if passive:
        return [passive]
    table = re.search(r"\(([^()]*\d[^()]*)\)\s*$", text)
    if table:  # values the scanner added from the talent's table: "(Hunter's Precision ATK Bonus 21.2%)"
        for part in table.group(1).split(";"):
            part = part.strip()
            per = re.search(r"(\d+(?:\.\d+)?)%\s*per\s*(\d[\d,]*)\s*points?$", part, re.I)
            if per:  # "Elemental Mastery-Based Swirl DMG Increase 45.00% per 100 Points"
                key = part[:per.start()].strip()
                target = _nearest(_keywords(key), len(key), len(key)) or "DMG Bonus"
                basis = "EM" if "elemental mastery" in key.lower() else "points"
                out.append((target, float(per.group(1)), "%", f"per {per.group(2)} {basis}", False, False))
                continue
            m = re.search(r"(\d+(?:\.\d+)?)(%?)\s*([A-Za-z][A-Za-z ]*)?$", part)
            if not m:
                continue
            key, low = part[:m.start()].strip(), part[:m.start()].strip().lower()
            of = {"Elemental Mastery": "EM", "HP": "Max HP"}.get((m.group(3) or "").strip(), (m.group(3) or "").strip())
            table_scaling = ""
            if of.lower().startswith("per "):  # "DEF Bonus 30% Per Stack", "Burst DMG Bonus 0.3% Per Energy"
                table_scaling, of = of[:1].lower() + of[1:], ""
            target = _nearest(_keywords(key), len(key), len(key))
            if target in ("DEF", "ATK", "EM", "Max HP") and tag_set and _TAG_OF.get(target) not in tag_set:
                continue  # the table's other values (Eula's own DEF on her RES shred line)
            if of and m.group(2) and "ratio" not in low:  # "Lunar-Bloom DMG Increase 400.0% Elemental Mastery"
                out.append((f"{of} as {target or 'DMG'}", float(m.group(1)), "%", "", False, False))
            elif "ratio" in low and of:  # "ATK Bonus Ratio 15.00% ATK": a share of the character's ATK
                out.append((f"{of} as {target or of}", float(m.group(1)), "%", "", False, False))
            elif "ratio" in low and "atk" in low:
                out.append(("Base ATK as ATK", float(m.group(1)), "%", "", False, False))
            elif "ratio" in low or "conversion" in low:  # "Fanfare to DMG Increase Conversion Ratio 0.25%"
                per = re.match(r"(.+?) to ", key)
                stat = _nearest(_keywords(key[per.end():] if per else key), len(key), len(key)) or "DMG Bonus"
                out.append((stat, float(m.group(1)), m.group(2), f"per {per.group(1)}" if per else "per point", False, False))
            elif re.search(r"\bmax(imum)?\b", low) and not m.group(2):  # "Max ATK Bonus 600": its cap
                if target:
                    out.append((target, float(m.group(1)), "", "", True, False))
            elif target:
                if target == "DMG Bonus":  # "Characters deal increased Elemental DMG with their Normal Attacks."
                    named = [k[2] for k in _keywords(text[:table.start()]) if "DMG" in k[2] and not k[2].startswith("CRIT")]
                    if not named and tag_set and not tag_set & {"dmg", "quills", "reaction"}:
                        continue  # the talent's table on a line about something else (Candace's Hydro Infusion)
                    target = named[0] if named else target
                out.append((target, float(m.group(1)), m.group(2), table_scaling, False, False))
        text = text[:table.start()]

    previous = None  # the stat of the amount before (a cap after it, "up to 50%", is that stat's)
    for _start, clause in _clauses(text):
        low = clause.lower()
        own = re.compile("|".join(rf"\b{re.escape(n.lower())}\b deals|dealt by {re.escape(n.lower())}\b|"
                                  rf"the dmg {re.escape(n.lower())}\b|{re.escape(n.lower())} gains" for n in owner) or "$^")
        # the character's own CRIT ("increases her CRIT Rate by…", "Mizuki's CRIT Rate … can be increased by…")
        own_crit = re.compile("|".join([r"\b(?:her|his) crit (?:rate|dmg)\b"]
                                       + [rf"\b{re.escape(n.lower())}'s crit (?:rate|dmg)\b" for n in owner]))
        keys = _keywords(clause)
        whole = _keywords(text)
        reaction = [k[2][:-4] for k in keys if k[2].endswith(" DMG") and k[2][:-4] in REACTIONS]
        numbers = list(_NUMBER.finditer(clause))
        inside, last_of = set(), {}  # numbers in "a/b/c" lists: only the last (highest) one counts
        for seq in _SEQUENCE.finditer(clause):
            listed = [n for n in numbers if seq.start() <= n.start() < seq.end()]
            inside |= {n.start() for n in listed[:-1]}
            if listed:
                last_of[listed[-1].start()] = seq.start()
        if "respectively" in low and own_crit.search(low):
            continue  # the character's own CRIT Rate and CRIT DMG
        if "respectively" in low:  # "CRIT Rate and CRIT DMG … increased by 10% and 20% respectively"
            pcts = [m for m in numbers if m.group(2)]
            named = [k for k in keys if not (k[2].endswith(" DMG") and k[2][:-4] in REACTIONS)]
            if len(pcts) == len(named) >= 2:
                for k, m in zip(named, pcts):
                    stat = f"{reaction[0]} {k[2]}" if reaction and k[2].startswith("CRIT") else k[2]
                    out.append((stat, _value(m.group(1)), "%", "", False, False))
                continue
        for m in numbers:
            at, end = m.start(), m.end()
            after, before = clause[end:], clause[max(0, at - 40):at]
            if at in inside:
                continue
            listed = at in last_of  # "by 60/90/120/200 points": the words before the list say what it is
            lead = last_of.get(at, at)
            if (_NOT_AMOUNT.match(after) and not (listed and re.match(r"^\s*points?\b", after, re.I))) \
                    or own.search(low[max(0, at - 45):at]) or own_crit.search(low[max(0, at - 70):at]):
                continue  # a count, a duration…, or the character's own bonus
            if re.match(r"^%?\s*of\s+its\s+original", after, re.I) or re.search(r"(dmg|damage) equal to\s*$", before, re.I):
                continue  # the character's own hit ("deals 135% of its original DMG", "Cryo DMG equal to 500% of…")
            if re.search(r"(higher|lower|above|below|more|less|at least|exceeds?) than\s*$", clause[max(0, at - 16):at], re.I):
                continue  # a condition ("health is higher than 70%")
            if re.search(r"(gain|duration|\bcd\b|cooldown|interval)\b[^.]{0,90}(is |are )?(increased|extended|decreased|reduced)"
                         r"[^.]{0,6}$", clause[max(0, at - 110):at], re.I):
                continue  # Fanfare gain, durations, cooldowns: not a stat
            cap = bool(_CAP.search(clause[max(0, at - 100):at]))
            if _BEFORE_NOT.search(clause[max(0, at - 16):at]) and not re.search(r"maximum of\s*$", before, re.I):
                continue
            if not m.group(2) and not re.search(r"(by|\+|gains?|of|is|to|additional)\s*$", clause[max(0, lead - 12):lead], re.I):
                continue  # a plain number counts as an amount only after "by" / "+" ("by 100", "gain 250")
            if re.match(r"^%?\s*of\s+[^.]{0,50}?\bas\b[^.]{0,50}(to (nearby )?(opponents|enemies)|aoe)", after, re.I):
                continue  # a hit's damage ("500% of ATK as … AoE Pyro DMG to nearby opponents")
            additional = bool(re.search(r"(additional(ly)?|further)[^.]{0,40}$", clause[max(0, at - 50):at], re.I))
            elevated = bool(re.search(r"elevat\w*\s+by\s*$", clause[max(0, at - 20):at], re.I))
            if re.search(r"ignores?\s*$", clause[max(0, at - 12):at], re.I) and re.match(r"^%?\s*of\s+[^.]{0,30}\bdef\b", after, re.I):
                out.append(("DEF ignored", _value(m.group(1)), "%", "", False, False))
                continue
            share = re.match(r"^\s*of\s+(?:the\s+)?(?:(?:his|her|their|[\w' ]{0,30}?'s)\s+)?(base atk|atk|max hp|def|elemental mastery)\b",
                             after, re.I)
            if share:  # "20% of Bennett's Base ATK", "0.8% of her Max HP", "400% of Lauma's Elemental Mastery"
                what = {"base atk": "Base ATK", "atk": "ATK", "max hp": "Max HP", "def": "DEF",
                        "elemental mastery": "EM"}[share.group(1).lower()]
                said = re.search(r"increase in ([\w' -]+?) is (?:equal to|based on)", clause, re.I)  # "Increase in DEF is…"
                raised = [k[2] for k in _keywords(said.group(1))] if said else []
                into = ("ATK" if "atk" in tag_set and what in ("Base ATK", "Max HP", "ATK") and "quills" not in tag_set
                        else "EM" if what == "EM" and "em" in tag_set else "DMG")
                # the stat just before it: "increases … Elemental Mastery by 6% of Ineffa's ATK"
                just_before = [k for k in keys if k[1] <= at and re.fullmatch(
                    r"\s*(?:is |are )?(?:also )?(?:increased )?by\s*", clause[k[1]:at], re.I)]
                if just_before and just_before[-1][2] in ("ATK", "EM", "DEF", "Max HP"):
                    into = just_before[-1][2]
                if raised and raised[0] in ("ATK", "EM", "DEF", "Max HP"):
                    into = raised[0]
                if into == "DMG":  # the DMG named before it ("…their Lunar-Bloom DMG is further increased by…")
                    named = [stat for s_, e_, stat in keys if e_ <= at and stat.endswith("DMG")]
                    into = named[-1] if named else "DMG"
                out.append((f"{what} as {into}", _value(m.group(1)), "%", "", False, additional))
                continue
            before_keys = [k for k in keys if k[1] <= at]
            # a stat after the number only counts if it's in the same part of the sentence ("…by 25% while
            # Hydro DMG… by 60%": the 25% isn't Hydro DMG)
            near_keys = [k for k in keys if k[1] <= at or not re.search(r"\bwhile\b|,|;|\band\b(?! \w+ dmg)", clause[end:k[0]], re.I)]
            follows = re.match(r"^[^.;,]*", after).group(0)
            if cap and previous and not _keywords(follows):
                stat = previous  # "…by 2.5% for every 100 ATK, up to a maximum of 50%": the 2.5%'s stat
            elif (re.search(r"\+\s*$", clause[max(0, at - 2):at]) or re.search(r"maximum of\s*$", before, re.I)) and before_keys:
                stat = before_keys[-1][2]  # "CRIT Rate +10%", "…DMG … by a maximum of 6500": the stat before it
            else:
                stat = _nearest(near_keys, at, end) or (whole[0][2] if whole else None)
            if not stat:
                continue
            if stat == "DMG Bonus":
                specific = [k[2] for k in keys if k[2].endswith(("DMG", "DMG Bonus")) and k[2] != "DMG Bonus"
                            and not k[2].startswith("CRIT")]
                stat = specific[0] if specific else stat
            if elevated:  # "Lunar Reaction DMG is elevated by 1.5%": Elevation, which adds up across the kit
                out.append((f"{stat} Elevation", _value(m.group(1)), m.group(2), "", False, True))
                continue
            if stat in ("Elemental DMG Bonus", "DMG Bonus") and any(k[2] == "CRIT DMG" for k in before_keys):
                stat = "CRIT DMG"  # "the CRIT DMG of the corresponding Elemental DMG … is increased by 80%"
            if stat.startswith("CRIT") and reaction:  # "Lunar-Bloom DMG CRIT Rate +10%": that reaction's CRIT
                stat = f"{reaction[0]} {stat}"
            elif stat.startswith("CRIT") and re.search(r"\blunar reactions?\b", clause, re.I):
                stat = f"Lunar-related {stat}"  # Columbina's C6: the CRIT DMG of the Lunar reaction's elements
            elif stat.startswith("CRIT") and _crit_element(clause):
                stat = f"{_crit_element(clause)} {stat}"  # "The Electro DMG of … has its CRIT DMG increased by 60%"
            elif stat.endswith(" DMG") and stat[:-4] in REACTIONS:
                crit = [k[2] for k in before_keys if k[2] in ("CRIT DMG", "CRIT Rate")]
                if crit:  # "increases the CRIT DMG from Stellar Swirl reaction DMG … by 60%"
                    stat = f"{stat[:-4]} {crit[-1]}"
            scaling = ""
            s = re.match(r"^[^.;]{0,90}?\b(for every|per|each)\b\s*(\d+(?:\.\d+)?%?\s*)?(point|stack)?\s*([\w' ]{0,30})", after, re.I)
            every = re.match(rf"^%?\s*(?:for every|per)\s*(\d[\d,]*)\s*(?:points of\s*)?(?:(?:the\s+)?[\w']+\s+)?{_STATS}\b",
                             after, re.I)
            if every and not _PER_HP.search(after[:60]):  # "by 2.5% for every 100 ATK that Ineffa has"
                scaling = f"per {every.group(1)} {_STAT_WORDS[every.group(2).lower()]}"
            elif _PER_HP.search(after[:120]) or _PER_HP.search(clause[:at]):
                scaling = "per 1,000 Max HP"
            elif s or re.search(r"\b(every|each) (elemental mastery )?(point|stack)[^.]{0,140}$", clause[:at], re.I):
                rest = (s.group(0) if s else clause[:at]).lower()
                scaling = ("per EM" if "elemental mastery" in rest else "per 1% Energy Recharge" if "energy recharge" in rest
                           else "per point" if "point" in rest else "per stack" if "stack" in rest
                           else "per 1,000 Max HP" if _PER_HP.search(rest + " " + clause[:at].lower()) else "")
            elif _PER_HP.search(clause[:at].lower()):
                scaling = "per 1,000 Max HP"
            out.append((stat, _value(m.group(1)), m.group(2), scaling, cap, additional))
            previous = stat
    return out


def _crit_element(clause):
    """The element a CRIT buff is for, if the sentence names one: "Physical CRIT DMG", "Cryo DMG CRIT DMG", "the
    Electro DMG of … has its CRIT DMG", "CRIT DMG when they deal Anemo DMG", "Hydro and Geo party members' CRIT"."""
    m = (re.search(rf"\b({_EL})(?: dmg)? crit\b", clause, re.I)
         or re.search(rf"crit (?:rate|dmg)[^.]{{0,40}}\bdeal\w* ({_EL}) dmg", clause, re.I)
         or re.search(rf"\b((?:{_EL})(?:{_JOIN}(?:{_EL}))*) (?:party members|characters)\b[^.]{{0,40}}\bcrit", clause, re.I))
    if m:
        return _join_names(_names(m.group(1)))
    named = {k[2][:-len(" DMG Bonus")] for k in _keywords(clause)
             if k[2].endswith(" DMG Bonus") and k[2][:-len(" DMG Bonus")] in ELEMENTS}
    return named.pop() if len(named) == 1 else None


def _max_count(text, unit):
    m = re.search(rf"max(?:imum)?(?: of)?\s*(\d+)\s*(?:such\s+)?{unit}s?|up to (\d+) {unit}s?|stack(?:s)? up to (\d+) times",
                  text, re.I)
    return int(next(g for g in m.groups() if g)) if m else None


def _source_label(source, text=""):
    """E(10) -> E, Q(10) -> Q; a C3/C5 level-13 line -> its talent; A1, C4, Hexerei… as they are."""
    if re.match(r"[EQ]\(13\):", text):
        return text[0]
    return source[0] if re.match(r"[EQ]\(", source) else source


def _span(labels):
    """The label of a line several constellations add up to ("C1–C6", Columbina's Elevation); a line others add
    on to keeps its own source's label (Lauma's Burst, with her C2's "further" increase)."""
    labels = list(dict.fromkeys(labels))
    cons = [int(x[1]) for x in labels if re.fullmatch(r"C\d", x)]
    if len(labels) > 1 and len(cons) == len(labels):
        return f"C{min(cons)}–C{max(cons)}" if cons == list(range(min(cons), max(cons) + 1)) else ", ".join(labels)
    return labels[0]


def _source_order(label):
    """Kit order: Skill, Burst, passives, then constellations."""
    if label in ("N", "E", "Q"):
        return (0, "NEQ".index(label))
    if re.fullmatch(r"A\d", label):
        return (1, int(label[1]))
    if re.match(r"C\d", label):
        return (3, int(label[1]))
    return (2, 0)


def _format(stat, unit, scaling, value):
    number = f"{value:,.4f}" if value < 0.1 else f"{value:,.2f}"  # (small rates like 0.0175% keep their digits)
    number = number.rstrip("0").rstrip(".")
    if " as " in stat:  # "+32% of Base ATK as DMG", "+400% of EM as Lunar-Bloom DMG"
        what, into = stat.split(" as ")
        label = f"+{number}% of {what} as {into}"
    elif not unit and stat.endswith(("DMG", "DMG Bonus")):  # a flat amount of damage
        label = f"+{number} Flat {stat.replace(' Bonus', '')}"
    elif not unit and stat in ("ATK", "DEF", "Max HP"):  # "+350 Flat ATK" (not a %)
        label = f"+{number} Flat {stat}"
    else:
        label = f"+{number}{unit} {stat}"
    return f"{label} {scaling}".strip()


def _bare(stat):
    return stat[:-len(" Bonus")] if stat.endswith(" Bonus") else stat


def totals(buffs, stacking=(), name=""):
    """Summary lines for buffs (objects with .source, .text and .tags), e.g. ["+21.2% ATK", "+100 EM"], or
    by source ("A4: … or …") for a kit with a choice of damage bonuses. stacking: [(source, effect, n)] from the
    scanner: an effect a constellation lets stack n times."""
    shown_sources = {b.source for b in buffs}
    parts = []  # [label, stat, value, unit, scaling, additional, text, quill, source]
    for b in buffs:
        tags = getattr(b, "tags", "")
        found = amounts(b.text, name, tags)
        caps = {(st, u) for st, v, u, sc, cap, add in found if cap}
        share_targets = {_bare(st.split(" as ")[1]) for st, *_ in found if " as " in st}
        notes = {}
        for st, v, u, sc, cap, add in found:
            if cap and not u and _bare(st) in share_targets:  # "Max ATK Bonus 600" for "15% of ATK as ATK"
                notes[_bare(st)] = f"(up to {v:,.0f} {_bare(st)})"
        # "…increased by 16%. Max 5 stacks.": an amount that stacks counts that many times
        stacks = re.search(r"\bmax(?:imum)?\.?\s*(?:of\s*)?(\d+)\s*stacks\b", b.text, re.I)
        plain = [f for f in found if not f[3] and not f[4] and " as " not in f[0]]
        stack_count = int(stacks.group(1)) if stacks and len(plain) == 1 and "can now stack" not in b.text else 0
        for stat, value, unit, scaling, cap, additional in found:
            if cap and not unit and _bare(stat) in share_targets:
                continue  # (shown with the share it caps)
            if stack_count > 1 and (stat, value, unit, scaling, cap, additional) == plain[0]:
                value, scaling = value * stack_count, f"({stack_count} stacks)"
            if cap and not unit:
                scaling = ""  # flat damage up to a maximum: the maximum
            if (stat, unit) in caps and not cap:
                if scaling:  # "0.5% per 1,000 Max HP, up to 20%", "80 per 1,000 Max HP, up to 2,800": the rate and cap
                    top = max(v for st, v, u, sc, c, a in found if c and st == stat and u == unit)
                    scaling = f"{scaling} (up to {top:,g}{unit})"
                else:
                    continue  # it grows to a stated maximum: that's the amount
            elif cap and any(st == stat and u == unit and sc for st, v, u, sc, c, a in found if not c):
                continue  # (shown with the rate it caps)
            if scaling in ("per point", "per stack"):
                n = _max_count(b.text, scaling.split()[1])
                if n:
                    value, scaling = value * n, ""
            if " as " in stat and _bare(stat.split(" as ")[1]) in notes:
                scaling = f"{scaling} {notes[_bare(stat.split(' as ')[1])]}".strip()
            option = (re.match(rf"^\s*(?:{_RX}|{_EL})\s*:", b.text, re.I)
                      or len(re.findall(rf"•\s*(?:{_RX}|{_EL})\s*:", b.text, re.I)) > 1)  # Xilonen's C2, by element
            parts.append([_source_label(b.source, b.text), stat, value, unit, scaling, additional, b.text,
                          "quills" in tags.split(), b.source, "•" in b.text, bool(option)])

    # C3/C5 level-13 lines replace the level-10 values of the talent they raise
    for p in [p for p in parts if re.match(r"[EQ]\(13\):", p[6])]:
        for q in parts:
            if q is not p and q[8].startswith(p[6][0]) and q[1] == p[1] and not re.match(r"[EQ]\(13\):", q[6]):
                q[2] = None
    parts = [p for p in parts if p[2] is not None]

    # an effect a (shown) constellation lets stack: every amount that comes from it, n times
    for source, effect, n in stacking:
        if source in shown_sources and n > 1:
            for p in parts:
                if p[8] != source and effect.lower() in p[6].lower():
                    p[2] *= n

    # within a source: the highest alternative (plus "additional" amounts)
    by_source = {}
    choice = {p[0] for p in parts if p[7] or p[9]}  # sources whose damage bonuses are a choice: spent stacks, a list
    # sources with options that depend on the reaction or element ("Lunar-Charged: ATK…", "Lunar-Bloom: EM…")
    option_stats = {}
    for p in parts:
        if p[10]:
            option_stats.setdefault(p[0], set()).add(p[1])
    options = {label for label, stats in option_stats.items() if len(stats) > 1}
    for label, stat, value, unit, scaling, additional, _text, quill, _src, _listed, _option in parts:
        slot = by_source.setdefault((label, stat, unit, scaling), [0, 0, False, False])
        if additional:
            slot[1] += value
            slot[2] = slot[2] or slot[0] == 0
        else:
            slot[0] = max(slot[0], value)
        slot[3] = slot[3] or quill
    # across sources: "additional" amounts add on to the same stat elsewhere; the rest keep their own line
    groups = {}  # (stat, unit, scaling) -> [[value, label, quill], …]
    for (label, stat, unit, scaling), (best, extra, adds_on, quill) in sorted(by_source.items(), key=lambda kv: kv[1][2]):
        same = groups.setdefault((stat, unit, scaling), [])
        if adds_on and same:
            same[0][0] += best + extra
            same[0][3].append(label)
        else:
            same.append([best + extra, label, quill, [label]])

    # a source that gives a choice of damage bonuses: show everything by source, alternatives joined by "or"
    damage_kinds = {}
    for entries in groups.values():
        for entry in entries:  # "C1–C6" for an Elevation every constellation adds to
            entry[1] = _span(entry[3])
    for (stat, unit, scaling), entries in groups.items():
        if stat.endswith(("DMG", "DMG Bonus")) and not stat.startswith(("CRIT", "DEF")):
            for value, label, quill, _labels in entries:
                damage_kinds.setdefault(label, set()).add(stat.split(" as ")[-1])
    option_of = {(p[0], p[1]) for p in parts if p[10] and p[0] in options}
    option_of |= {(p[0], p[1]) for p in parts if p[10] and p[9]}  # (a bulleted list: its own items)
    options |= {p[0] for p in parts if p[10] and p[9]}
    # every line names its source first ("A1: …"), in kit order; a source that gives a choice of damage bonuses
    # has its alternatives joined by "or"
    per_label = {}
    for (stat, unit, scaling), entries in groups.items():
        for value, label, quill, _labels in entries:
            per_label.setdefault(label, []).append((_format(stat, unit, scaling, value), stat, quill))
    texts = {}
    for label, items in per_label.items():
        picks = [text for text, stat, _q in items if (label, stat) in option_of]  # one applies, by reaction
        damage = [text for text, stat, _q in items
                  if stat.endswith(("DMG", "DMG Bonus")) and " CRIT " not in f" {stat} " and text not in picks]
        other = [text for text, stat, _q in items if text not in damage and text not in picks]
        joined = (" or " if label in choice else ", ").join(damage)
        text = ", ".join(([" or ".join(picks)] if picks else []) + other + ([joined] if damage else []))
        quill = " (Quills)" if any(q for *_x, q in items) else ""
        texts[label] = f"{text}{quill}"
    # what a kit's wording doesn't spell out (OVERRIDES): replaces, adds or drops a source's line
    fixes = OVERRIDES.get(re.sub(r"^Lumine \(", "Aether (", name), {})
    shown_labels = {_source_label(b.source, b.text) for b in buffs}
    constellations = any(re.fullmatch(r"C\d", b.source) for b in buffs)
    for label, fix in fixes.items():
        if label not in shown_labels:
            continue
        text = fix(constellations) if callable(fix) else fix
        if text is None:
            texts.pop(label, None)
        else:
            texts[label] = text
    return [f"{label}: {text}" for label, text in sorted(texts.items(), key=lambda kv: _source_order(kv[0])) if text]


# Per character, {source: its TOTAL line} where the kit's text can't be read right: a stack count or cap it doesn't
# state, a buff for the party with a different one for the character, an element "corresponding to the
# reaction"… A function gets whether constellations are shown (C6) and returns the line; None drops it.
OVERRIDES = {
    "Chevreuse": {"C6": "+60% Pyro & Electro DMG Bonus (20% per stack, max 3 stacks)"},
    "Dehya": {"C2": "+50% coordinated attack DMG (Fiery Sanctum's, not the party's DMG Bonus)"},
    "Durin": {"A1": "+20% Pyro & corresponding Elemental RES shred",
              "Hexerei": "A1's effects +75% (+35% Pyro & corresponding Elemental RES shred)",
              "C2": "+50% Pyro & corresponding Elemental DMG Bonus"},
    "Klee": {"C6": "+10% Pyro DMG Bonus (Klee herself: +50%)"},
    "Yoimiya": {"A4": "+10% ATK, +1% ATK per stack (max +10%)"},
    "Furina": {"Q": lambda c6: ("+0.31% DMG Bonus per Fanfare (max +124% at 400 Fanfare)" if c6
                                else "+0.25% DMG Bonus per Fanfare (max +75% at 300 Fanfare)"),
               "C2": "+250% Fanfare gain"},
    "Mona": {"C1": "+24% Hydro-related reaction DMG Bonus (Electro-Charged, Lunar-Charged, Vaporize, Hydro Swirl, "
                   "Lunar-Crystallize)"},
    "Fischl": {"Hexerei": "+22.5% ATK and/or +90 EM (by the reaction triggered)",
               "C6": "Hexerei effects +100% (+45% ATK and/or +180 EM)"},
    "Yae Miko": {"C1": "+50% Electro & Stellar-Conduct DMG Bonus"},
    "Ganyu": {"C4": "up to +25% DMG taken (5% more every 3s)"},
    "Mika": {"A1": lambda c6: ("+40% Physical DMG Bonus (10% per Detector stack, max 4 with C6)" if c6
                               else "+30% Physical DMG Bonus (10% per Detector stack, max 3)")},
    "Odette": {"A1": "+60% Stellar Glimmer DMG (15% per Marvelous Splendor stack, 4 stacks)",
               "C1": "+2 stacks: +90% Stellar Glimmer DMG in all (6 stacks)",
               "C2": "+42% ATK (7% per stack, 6 stacks), +20% RES shred"},
    "Ifa": {"A1": "+1.5% Swirl & Electro-Charged DMG, +0.2% Lunar-Charged & Stellar Swirl DMG per Rescue Essentials point",
            "C2": "+4 Rescue Essentials points per Nightsoul point above 60"},
    "Sucrose": {"Hexerei": "+5.71428% DMG Bonus, plus +7.14285% DMG Bonus for Hexerei characters",
                "C6": "+20% Elemental DMG Bonus, plus +8.57142% for Hexerei characters"},
    "Varka": {"C4": "+20% Anemo & corresponding Elemental DMG Bonus"},
    "Yun Jin": {"Q": lambda c6: f"+{68 if c6 else 58}% of DEF as Normal Attack DMG (Quills)",
                "A4": "+11.5% of DEF as Normal Attack DMG Bonus (with 4 Elemental Types)"},
    "Baizhu": {"A4": "+100% Bloom-related reactions & Burning DMG, +40% Aggravate & Spread DMG Bonus (additive DMG), "
                     "+35% Lunar-Bloom DMG (at 50,000 Max HP)"},
    "Aether (Dendro)": {"A1": "+60 EM (6 per second, max 10 levels)",
                        "C6": "+12% Dendro DMG Bonus, +12% corresponding Elemental DMG Bonus"},
}
