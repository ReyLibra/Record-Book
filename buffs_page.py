"""Buffs page: every damage buff and RES/DEF shred characters give their team, filterable by buff
type and by the element it affects (data in buffs_data.py)."""

import html
import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import buff_totals
import gamedata
import buff_scan
from buffs_data import ELEMENT_TAGS, FLAGS, LEGEND, TYPES, WHO, source_kind
from search import matches
from widgets import ACCENT, MUTED, FilterGroup, card_pixmap, clear_layout, filter_button, glossary_tooltips, section_header

# settings: what buff_scan read from each character's kit, and which scanner version read it
AUTO_KEY = "auto_buffs"  # {char_id: {"name": str, "entries": [[...]], "terms": {term: [explanation, source]}}}
KNOWN_KEY = "buff_known_chars"  # [char_id]: characters whose kits have been read
SCAN_KEY = "buff_scan_version"  # buff_scan.VERSION the saved results came from

PORTRAIT = 60
LEFT_WIDTH = 250
KICKER_WIDTH = 64  # the "TYPE" / "ELEMENT" labels in front of the filter rows
SORTS = [("Element", "element"), ("Name A–Z", "name"), ("Rarity", "rarity"), ("Most buffs shown", "count")]

# source chips: talents blue, constellations purple, special passives (Lunar/Stellar/Hexerei) gold
CHIP_COLORS = {
    "talent": ("rgba(0,158,236,0.16)", "rgba(0,158,236,0.7)"),
    "constellation": ("rgba(138,95,204,0.2)", "rgba(160,120,230,0.75)"),
    "special": ("rgba(201,163,106,0.18)", "rgba(214,178,118,0.8)"),
}

# who-gets-it badges: team green, enemies red, active blue…
WHO_COLORS = {
    "team": (96, 200, 128),
    "others": (70, 190, 175),
    "active": (0, 158, 236),
    "self_active": (125, 150, 255),
    "enemy": (235, 96, 96),
    "self": (150, 154, 165),
}
CONDITION_COLOR = "#e0b45a"
FLAG_COLORS = {}

# every card's labels are styled by one sheet on the page: a style sheet set on each of ~2,000 labels is
# parsed for each one, which made the page take seconds to build
CARD_STYLE = "\n".join(
    [
        f"QLabel#BuffDot {{ color: {MUTED}; font-size: 10pt; }}",
        "QLabel#BuffText { color: #d6d9df; font-size: 10pt; }",
        "QLabel#BuffMeta { font-size: 8.5pt; }",
        "QLabel#BuffName { font-size: 12pt; font-weight: 700; }",
        f"QLabel#BuffSub {{ color: {MUTED}; font-size: 9pt; }}",
        "QLabel#BuffKinds { font-size: 8pt; font-weight: 700; }",
        "QFrame#BuffDivider { background: #373a43; border: none; }",
        "QLabel#BuffTotal { color: #d6d9df; font-size: 9pt; }",
        f"QLabel#BuffNote {{ color: {MUTED}; font-size: 8.5pt; font-style: italic; }}",
        "QLabel#BuffChip { padding: 2px 0; font-size: 8.5pt; font-weight: 800; }",
        "QLabel#BuffWho { padding: 2px 0; font-size: 8pt; font-weight: 800; }",
    ]
    + [f'QLabel#BuffChip[kind="{kind}"] {{ background: {bg}; border: 1px solid {border}; }}'
       for kind, (bg, border) in CHIP_COLORS.items()]
    + [f'QLabel#BuffWho[who="{who}"] {{ color: rgb{c}; background: rgba{c + (0.12,)}; border: 1px solid rgba{c + (0.55,)}; }}'
       for who, c in WHO_COLORS.items()]
)

_TALENT_NAMES = {"N": "Normal Attack", "E": "Elemental Skill", "Q": "Elemental Burst"}


def _source_tip(source):
    kind = source_kind(source)
    if kind == "constellation":
        return f"Constellation {source[1:]}"
    if kind == "special":
        return "Passive talent" if source == "Passive" else f"{source} passive"
    if re.fullmatch(r"A\d", source):
        return f"Ascension passive ({source})"
    parts = []
    for piece in source.split("+"):
        m = re.fullmatch(r"([NEQ])(?:\((\d+)\))?", piece)
        if m:
            parts.append(_TALENT_NAMES[m[1]] + (f" at talent level {m[2]}" if m[2] else ""))
    return " + ".join(parts) or source


# ----- coloring the buff text: numbers bright, element names in their colors -----
_ELEMENT_WORDS = {"Pyro": "PYRO", "Hydro": "HYDRO", "Electro": "ELECTRO", "Cryo": "CRYO",
                  "Anemo": "ANEMO", "Geo": "GEO", "Dendro": "DENDRO"}
_PATTERN = re.compile(
    # numbers, but not the digits of labels like C1, A4 or Q(13)
    r"(?P<num>(?<![A-Za-z\d])(?<![QE]\()\d[\d.,]*(?:/\d[\d.,]*)*%?(?:K\b)?)|(?P<el>\b(?:" + "|".join(_ELEMENT_WORDS) + r")\b)"
    r"|(?P<shred>\b(?:Res|Def) Shred\b)"
)


def buff_html(text, terms=None):
    """The buff text as HTML: numbers bright, element names in color, and kit terms ({term: glossary
    key}, plus the game mechanics Record Book explains) as links that explain themselves on hover."""
    terms = dict(terms or {})
    for term, key in gamedata._MECHANIC_KEYS.items():
        terms.setdefault(term, key)
    pattern = _PATTERN
    if terms:
        names = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
        pattern = re.compile(rf"(?P<term>(?<![\w-])(?:{names})(?![\w-]))|" + _PATTERN.pattern)
    out, pos = [], 0
    for m in pattern.finditer(text):
        out.append(html.escape(text[pos:m.start()]))
        word = html.escape(m.group())
        if m.groupdict().get("term"):
            out.append(f"<a href='term:{terms[m['term']]}' style='color:{gamedata.LINK_COLOR}; "
                       f"text-decoration:underline'>{word}</a>")
        elif m["num"]:
            out.append(f"<b style='color:#ffffff'>{word}</b>")
        elif m["el"]:
            out.append(f"<span style='color:{gamedata.ELEMENT_COLORS[_ELEMENT_WORDS[m['el']]]}'>{word}</span>")
        else:
            out.append(f"<b style='color:{ACCENT}'>{word}</b>")
        pos = m.end()
    out.append(html.escape(text[pos:]))
    return "".join(out).replace("\n", "<br>")


class _Buff:
    """One line of the list, with its tags split into types and elements."""

    def __init__(self, source, tags, who, text, condition="", flag=""):
        self.source = source
        self.text = text
        self.tags = tags
        self.who = who
        self.condition = condition
        self.flag = flag if flag in FLAGS else ""
        assert who in WHO, f"unknown target {who!r} in {text!r}"
        words = tags.split()
        self.types = {w for w in words if w in TYPES}
        self.elements = {w for w in words if w in ELEMENT_TAGS or w == "any"}
        self.constellation = source_kind(source) == "constellation"
        unknown = set(words) - set(TYPES) - set(ELEMENT_TAGS) - {"any"}
        assert not unknown, f"unknown buff tags {unknown} in {text!r}"

    def affects(self, element):
        # "any": the swirled / absorbed / active character's element, so any element but physical
        return element in self.elements or (element != "phys" and "any" in self.elements)


def source_order(source):
    """Where a source sits in the kit: Skill, Burst, passives, then constellations."""
    if source.startswith("N"):
        return (0, 0)
    if source.startswith("E"):
        return (1, 0)
    if source.startswith("Q"):
        return (2, 0)
    if re.fullmatch(r"A\d", source):
        return (3, int(source[1]))
    if m := re.fullmatch(r"C(\d)", source):
        return (5, int(m[1]))
    return (4, 0)  # Lunar / Stellar / Hexerei / other passives


def _set_shown(widget, shown):
    """setVisible only when it changes: each call re-applies the style sheet, and with ~2,000 widgets on
    the page that alone took seconds. The wanted state is kept on the widget: Qt counts a widget that was
    never shown as hidden, so isHidden() can't tell "hide this" apart from "not on screen yet".
    A widget that was never shown or hidden on purpose already appears with its parent, so showing it needs
    no call at all (that skipped call was most of the time building the page)."""
    if _is_shown(widget) != shown or not hasattr(widget, "_wanted_shown"):
        if shown and not widget.testAttribute(Qt.WA_WState_ExplicitShowHide):
            widget._wanted_shown = True
            return
        widget.setHidden(not shown)
        widget._wanted_shown = shown


def _is_shown(widget):
    """Whether the filters show this widget (whether or not the page is on screen yet)."""
    return getattr(widget, "_wanted_shown", True)


class BuffLine(QWidget):
    """One buff: its text (a bullet point when its source gives several) and who gets it."""

    def __init__(self, buff, terms=None, bullet=False):
        """terms: {kit term: glossary key} to explain on hover."""
        super().__init__()
        self.buff = buff
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.dot = QLabel("•")  # shown only while its source has more than one point on screen
        self.dot.setObjectName("BuffDot")
        row.addWidget(self.dot, 0, Qt.AlignTop)
        _set_shown(self.dot, bullet)  # after it has a parent: shown parentless, it'd open as its own window
        text = QLabel(buff_html(buff.text, terms))
        text.setTextFormat(Qt.RichText)
        text.setWordWrap(True)
        text.setObjectName("BuffText")
        glossary_tooltips(text)  # underlined kit terms explain themselves on hover
        self.text = text
        self.meta = None
        body = QVBoxLayout()
        body.setSpacing(2)
        body.addWidget(text)
        # under the text: its special condition and whether it was added / couldn't be verified
        meta = []
        if buff.condition:
            meta.append(f"<span style='color:{CONDITION_COLOR}'>⚑ {html.escape(buff.condition)}</span>")
        if buff.flag:
            label, _tip = FLAGS[buff.flag]
            meta.append(f"<span style='color:{FLAG_COLORS[buff.flag]}; font-weight:700'>{label.upper()}</span>")
        if meta:
            line = QLabel("&nbsp;&nbsp;·&nbsp;&nbsp;".join(meta))
            line.setTextFormat(Qt.RichText)
            line.setWordWrap(True)
            line.setObjectName("BuffMeta")
            if buff.flag:
                line.setToolTip(FLAGS[buff.flag][1])
            body.addWidget(line)
            self.meta = line

        who_label, who_tip = WHO[buff.who]
        who = QLabel(who_label.upper())
        who.setAlignment(Qt.AlignCenter)
        who.setFixedWidth(118)
        who.setToolTip(who_tip)
        who.setObjectName("BuffWho")
        who.setProperty("who", buff.who)  # colored by CARD_STYLE
        policy = who.sizePolicy()
        policy.setRetainSizeWhenHidden(True)  # a repeated badge is hidden, but its column stays
        who.setSizePolicy(policy)
        self.who = who
        self._body = body
        row.addLayout(body, 1)
        row.addWidget(who, 0, Qt.AlignTop)

    def height_for(self, width):
        """The height this line needs at a width, worked out from its labels (layouts cache theirs, and a
        line a filter just hid or showed can leave them stale)."""
        row = self.layout()
        text_width = width - self.who.width() - row.spacing()
        if _is_shown(self.dot):
            text_width -= self.dot.sizeHint().width() + row.spacing()
        height = self.text.heightForWidth(text_width)
        if self.meta is not None:
            height += self._body.spacing() + self.meta.heightForWidth(text_width)
        return max(height, self.who.sizeHint().height(), self.dot.sizeHint().height() if _is_shown(self.dot) else 0)


class BuffRow(QWidget):
    """A source chip (E, A1, C2…) with every buff it gives listed beside it."""

    def __init__(self, source, buffs, terms=None):
        super().__init__()
        self.source = source
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 3, 0, 3)
        row.setSpacing(10)
        chip = QLabel(source)
        chip.setAlignment(Qt.AlignCenter)
        chip.setFixedWidth(68)
        chip.setToolTip(_source_tip(source))
        chip.setObjectName("BuffChip")
        chip.setProperty("kind", source_kind(source))  # colored by CARD_STYLE
        points = QVBoxLayout()
        self.points = points
        points.setContentsMargins(0, 0, 0, 0)
        points.setSpacing(4)
        self.lines = [BuffLine(b, terms, bullet=len(buffs) > 1) for b in buffs]
        for line in self.lines:
            points.addWidget(line)
        points.addStretch()  # the points stay at the top of the row
        self.chip = chip
        row.addWidget(chip, 0, Qt.AlignTop)
        row.addLayout(points, 1)
        self.update_badges()

    def height_for(self, width):
        """The height the shown points need beside the chip at a width."""
        row = self.layout()
        margins = row.contentsMargins()
        points_width = width - margins.left() - margins.right() - self.chip.width() - row.spacing()
        shown = [line.height_for(points_width) for line in self.lines if _is_shown(line)]
        return (margins.top() + margins.bottom() + sum(shown) + self.points.spacing() * max(len(shown) - 1, 0))

    def update_badges(self):
        """Show who gets it once per run of points that go to the same people, and bullets only when
        more than one point is shown (a filter can leave just one)."""
        shown = [line for line in self.lines if _is_shown(line)]
        previous = None
        for line in shown:
            _set_shown(line.who, line.buff.who != previous)
            _set_shown(line.dot, len(shown) > 1)
            previous = line.buff.who


class CharacterBuffs(QFrame):
    """A character's card: portrait and name on the left, their buffs on the right."""

    open_character = Signal(str)

    def __init__(self, info, note, buffs, terms=None, stacking=()):
        super().__init__()
        self.info = info
        self.stacking = stacking
        self.setObjectName("Card")
        self._portrait_pm = None
        self._logged = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 16, 12)
        layout.setSpacing(18)

        # portrait with the name, element and weapon beside it
        side = QHBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(12)
        left = QVBoxLayout()
        left.setSpacing(3)
        self.portrait = QLabel()
        self.portrait.setFixedSize(PORTRAIT, PORTRAIT)
        self.portrait.setCursor(Qt.PointingHandCursor)
        self.portrait.setToolTip(f"Open {info.name} on the Characters page")
        self.portrait.mousePressEvent = lambda e: e.button() == Qt.LeftButton and self.open_character.emit(info.id)
        name = QLabel(f"<a href='#' style='color:#ffffff; text-decoration:none'>{html.escape(info.name)}</a>")
        name.setObjectName("BuffName")
        name.setWordWrap(True)
        name.linkActivated.connect(lambda _: self.open_character.emit(info.id))
        color = gamedata.ELEMENT_COLORS.get(info.element, "#ffffff")
        sub = QLabel(
            f"<span style='color:{color}'>{gamedata.pretty(info.element)}</span>"
            f" · {gamedata.weapon_type_name(info.weapon_type)} · {'★' * info.rarity}"
        )
        sub.setObjectName("BuffSub")
        # the kinds of buff the shown lines give (ATK, EM, Quills, RES Shred…); follows the filters
        kinds_label = QLabel()
        kinds_label.setTextFormat(Qt.RichText)
        kinds_label.setWordWrap(True)
        kinds_label.setObjectName("BuffKinds")
        kinds_label.setToolTip("Kinds of buff shown for this character")
        self._kinds_label = kinds_label
        self._set_kinds(buffs)
        side.addWidget(self.portrait, 0, Qt.AlignTop)
        left.addWidget(name)
        left.addWidget(sub)
        left.addSpacing(4)
        left.addWidget(kinds_label)
        # a divider, then what the shown buffs add up to (at C0, or C6 with the Cons toggle on): under the
        # portrait, across the whole column
        self._divider = QFrame()
        self._divider.setObjectName("BuffDivider")
        self._divider.setFixedHeight(1)
        self._total_label = QLabel()
        self._total_label.setObjectName("BuffTotal")
        self._total_label.setTextFormat(Qt.RichText)
        self._total_label.setWordWrap(True)
        self._total_label.setToolTip("What these buffs add up to (read from their text; each line says exactly what it does)")

        if note:
            note_label = QLabel(note)
            note_label.setWordWrap(True)
            note_label.setObjectName("BuffNote")
            left.addWidget(note_label)
        left.addStretch()
        side.addLayout(left, 1)
        holder = QWidget()
        holder.setFixedWidth(LEFT_WIDTH)
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        column.addLayout(side)
        column.addWidget(self._divider)
        column.addWidget(self._total_label)
        column.addStretch()
        layout.addWidget(holder)
        self._holder = holder

        lines = QVBoxLayout()
        self._lines = lines
        lines.setSpacing(2)
        # one row per source, in kit order (E, Q, passives, C1–C6); a C3/C5 talent level-up sits with its
        # constellation
        groups = {}
        for b in sorted(buffs, key=lambda b: source_order(b.source)):
            groups.setdefault(b.source, []).append(b)
        self.rows = [BuffRow(source, group, terms) for source, group in groups.items()]
        for r in self.rows:
            lines.addWidget(r)
        lines.addStretch()
        layout.addLayout(lines, 1)

        gamedata.load_pixmap(info.icon, self._portrait_loaded)
        # the text can be highlighted and copied (links and tooltips keep working)
        for label in self.findChildren(QLabel):
            if label is not self.portrait:
                label.setTextInteractionFlags(label.textInteractionFlags() | Qt.TextSelectableByMouse)

    def _set_kinds(self, buffs):
        """Tags for the kinds of buff in buffs, in the filter buttons' order."""
        kinds = {t for b in buffs for t in b.types}
        self._kinds_label.setText("&nbsp; ".join(
            f"<span style='background-color: rgba(0,158,236,0.16); color: #cfe6f7'>&nbsp;{html.escape(label)}&nbsp;</span>"
            for key, (label, _tip) in TYPES.items() if key in kinds
        ))

    def _portrait_loaded(self, pm):
        self._portrait_pm = pm
        self._draw_portrait(bool(self._logged))

    def set_logged(self, logged):
        if logged != self._logged:
            self._logged = logged
            self._draw_portrait(logged)

    def _draw_portrait(self, logged):
        pm = card_pixmap(self._portrait_pm, None, self.info.rarity, PORTRAIT, logged=logged)
        pm.setDevicePixelRatio(2)
        self.portrait.setPixmap(pm)

    def _set_total(self, buffs, level):
        lines = buff_totals.totals(buffs, self.stacking, self.info.name)
        _set_shown(self._divider, bool(lines))
        _set_shown(self._total_label, bool(lines))
        if lines:
            self._total_label.setText(
                f"<span style='color:#8c909b; font-size:8pt; font-weight:900'>TOTAL · {level}</span><br>"
                + "<br>".join(re.sub(r"^([^:\s]+):", r"<b>\1:</b>", html.escape(line)) for line in lines))
            self._total_label.setFixedHeight(_text_height(self._total_label, LEFT_WIDTH))

    def apply(self, test, level="C0"):
        """Show only the rows passing test(buff); returns how many are shown. level: "C0" or "C6", for
        the total under the portrait."""
        shown = 0
        for r in self.rows:
            row_shown = 0
            for line in r.lines:
                ok = test(line.buff)
                _set_shown(line, ok)
                row_shown += ok
            _set_shown(r, row_shown > 0)
            r.update_badges()
            shown += row_shown
        shown_buffs = [line.buff for r in self.rows for line in r.lines if _is_shown(line)]
        self._set_kinds(shown_buffs)
        self._set_total(shown_buffs, level)
        _set_shown(self, shown > 0)
        self._fit()
        return shown

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self._fit()

    def _fit(self):
        """Give each shown row, then the card, exactly the height its wrapped text needs at this width.

        Word-wrapped labels report a size hint for a narrow guessed width, and Qt's layouts share space
        out by those hints: left alone, long sentences either leave a gap under the card or get their
        rows squeezed and clipped. So the heights are worked out from the real width and fixed."""
        width = self.contentsRect().width()  # inside the card's border
        if width < 100:
            return
        layout = self.layout()
        margins = layout.contentsMargins()
        lines_width = width - margins.left() - margins.right() - LEFT_WIDTH - layout.spacing()
        rows_height, shown = 0, 0
        for row in self.rows:
            if not _is_shown(row):
                continue
            # worked out from the labels, not the layouts: those cache their height for a width, and after a
            # filter hid a line the row could keep its old height with the text floating in it
            height = row.height_for(lines_width)
            if height > 0 and row.maximumHeight() != height:  # fixed every time, or Qt may squeeze it
                row.setFixedHeight(height)
            rows_height += max(height, 0)
            shown += 1
        rows_height += self._lines.spacing() * max(shown - 1, 0)
        border = self.height() - self.contentsRect().height()
        side_height = self._holder.layout().totalHeightForWidth(LEFT_WIDTH)  # the wrapped buff kinds included
        height = border + margins.top() + margins.bottom() + max(rows_height, side_height)
        if height != self.height():
            self.setFixedHeight(height)
        # place the rows now: a card that was hidden by a filter keeps its old row positions otherwise,
        # and the rows overlap
        layout.invalidate()
        layout.activate()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit()


def _text_height(label, width):
    """The height a word-wrapped rich-text label really needs at a width, laid out the way it's drawn (its
    own heightForWidth can come up short with display scaling, and the last lines got cut off)."""
    from PySide6.QtGui import QTextDocument

    label.ensurePolished()  # its font from the page's style sheet
    doc = QTextDocument()
    doc.setDefaultFont(label.font())
    doc.setDocumentMargin(0)
    doc.setHtml(label.text())
    doc.setTextWidth(width)
    return int(doc.size().height()) + label.fontMetrics().descent() + 2


def _kicker(text):
    label = QLabel(text)
    label.setObjectName("FieldLabel")
    label.setFixedWidth(KICKER_WIDTH)
    return label


class BuffsPage(QWidget):
    message = Signal(str)
    open_character = Signal(str)
    built = Signal()  # every card is built

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.index = None
        self.cards = []
        self._shown = {}  # card -> number of buffs shown, for the "most buffs" sort

        self.setStyleSheet(CARD_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 12)
        layout.setSpacing(10)
        head, self.count_label = section_header("Team buffs & shreds")
        layout.addWidget(head)
        legend = QLabel(LEGEND)
        legend.setWordWrap(True)
        legend.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt;")
        layout.addWidget(legend)

        # row 1: search, include toggles (4★ Cons, 5★ Cons, Team Restrictions) ... sort
        top = QHBoxLayout()
        top.setSpacing(4)
        self.search = QLineEdit(placeholderText="Search characters or buffs…  (e.g. Kazu, swirl, Lunar)")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(360)
        self.search.textChanged.connect(self.apply_filter)
        top.addWidget(self.search)
        top.addSpacing(12)
        # what to include: lit = shown (by default everything but 5-star constellations)
        self.four_cons_button = filter_button("4★ Cons", tooltip="Include 4-star characters' constellation buffs")
        self.five_cons_button = filter_button("5★ Cons", tooltip="Include 5-star characters' constellation buffs")
        self.restricted_button = filter_button(
            "Team Restrictions", tooltip="Include buffs with special requirements (team makeup, Moonsign, Hexerei…)"
        )
        for btn, on in ((self.four_cons_button, True), (self.five_cons_button, False), (self.restricted_button, True)):
            btn.setChecked(on)
            btn.toggled.connect(lambda _: self.apply_filter())
            top.addWidget(btn)
        top.addStretch()
        sort_label = QLabel("SORT")
        sort_label.setObjectName("FieldLabel")
        top.addWidget(sort_label)
        top.addSpacing(6)
        self.sort_box = QComboBox()
        for label, key in SORTS:
            self.sort_box.addItem(label, key)
        self.sort_box.setMinimumWidth(170)
        self.sort_box.currentIndexChanged.connect(lambda _: self._sort())
        top.addWidget(self.sort_box)
        layout.addLayout(top)

        # row 2: buff types
        types = QHBoxLayout()
        types.setSpacing(4)
        types.addWidget(_kicker("TYPE"))
        self.type_group = FilterGroup([(key, label, None, tip) for key, (label, tip) in TYPES.items()], size=32)
        self.type_group.changed.connect(lambda _: self.apply_filter())
        types.addWidget(self.type_group)
        types.addStretch()
        layout.addLayout(types)

        # row 3: the element a buff affects (DMG bonus, RES shred, crit…)
        elements = QHBoxLayout()
        elements.setSpacing(4)
        elements.addWidget(_kicker("ELEMENT"))
        options = []
        for key, element in ELEMENT_TAGS.items():
            if element:
                options.append((key, "", gamedata.element_icon_url(element), f"Buffs and shreds for {gamedata.pretty(element)}"))
            else:
                options.append((key, "Phys", None, "Buffs and shreds for Physical damage"))
        self.element_group = FilterGroup(options, size=32)
        self.element_group.changed.connect(lambda _: self.apply_filter())
        elements.addWidget(self.element_group)
        elements.addStretch()
        layout.addLayout(elements)

        # row 4: who receives it
        targets = QHBoxLayout()
        targets.setSpacing(4)
        targets.addWidget(_kicker("TARGET"))
        self.who_group = FilterGroup([(key, label, None, tip) for key, (label, tip) in WHO.items()], size=32)
        self.who_group.changed.connect(lambda _: self.apply_filter())
        targets.addWidget(self.who_group)
        targets.addStretch()
        layout.addLayout(targets)

        # the list and its messages ("Loading buffs…", "No buffs match…") share one area that keeps its size,
        # so the filters above never move while the cards load
        self.messages = QWidget()
        m = QVBoxLayout(self.messages)
        m.setContentsMargins(0, 4, 0, 0)
        self.loading = QLabel("Loading game data…")
        self.loading.setStyleSheet(f"color: {MUTED};")
        m.addWidget(self.loading)
        self.empty = QLabel("No buffs match these filters.")
        self.empty.setStyleSheet(f"color: {MUTED}; padding: 20px 0;")
        self.empty.hide()
        m.addWidget(self.empty)
        m.addStretch()

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        self.list = QVBoxLayout(content)
        self.list.setContentsMargins(0, 4, 12, 12)
        self.list.setSpacing(10)
        self.list.addStretch()
        self.scroll.setWidget(content)
        self.area = QStackedWidget()
        self.area.addWidget(self.messages)
        self.area.addWidget(self.scroll)
        layout.addWidget(self.area, 1)

    def _show_message(self, text=None):
        """The loading text (or, with text None, "No buffs match…") in place of the list."""
        self.loading.setVisible(text is not None)
        if text is not None:
            self.loading.setText(text)
        self.empty.setVisible(text is None)
        self.area.setCurrentWidget(self.messages)

    # ----- data -----
    def set_index(self, index):
        self.index = index
        if not self.cards:
            self.reload()

    def scan_is_current(self):
        """Whether the saved kit readings come from this version of the scanner."""
        return self.store.get_setting(SCAN_KEY) == buff_scan.VERSION

    def reload(self, force=False):
        """Rebuild every card from the saved kit readings. Off screen it only notes that it's due (the cards
        are built when the page is opened), unless force: the loading screen builds them before the app shows."""
        if not self.index:
            return
        if not self.isVisible() and not force:
            self._stale = True
            return
        self._stale = False
        clear_layout(self.list)  # also hides any open tooltip before the cards go
        self.list.addStretch()
        self.cards = []
        self._shown = {}
        saved = self.store.get_setting(AUTO_KEY, {}) if self.scan_is_current() else {}
        # kits are read once per Traveler element (as Aether); show them under whichever twin is chosen
        by_name = {c.name: c for c in self.index.characters.values()}
        pending = []
        for char_id, data in saved.items():
            if not data.get("entries"):
                continue
            info = self.index.characters.get(char_id)
            name = data.get("name") or ""
            if name.startswith("Aether ("):
                info = by_name.get(name) or by_name.get("Lumine" + name[len("Aether"):])
            if info:
                pending.append((info, data["entries"], data.get("terms") or {}, data.get("stacks") or []))
        # build the cards a few at a time, in the order they'll be shown: the first ones appear at once and
        # the window keeps responding while the rest are added (all at once froze it for seconds)
        key = self._sort_key()
        if key:
            pending.sort(key=lambda p: key(p[0]))
        self._pending = pending
        self._generation = getattr(self, "_generation", 0) + 1
        # the list stays hidden until every card is built, so it doesn't grow and jump while loading; behind the
        # loading screen it's up from the start instead, so each card is styled and laid out once, as it's added
        # (revealing ~2,000 widgets at the end took seconds)
        if not getattr(self, "_preloading", False):
            self._show_message("Loading buffs…" if pending else "Reading every character's kit for buffs… (only the first time)")
        self._build_more(self._generation)

    BATCH = 6  # cards built per pass of the event loop
    PRELOAD_BATCH = 20  # (behind the loading screen, where nothing else needs the time)

    def _build_more(self, generation):
        if generation != self._generation:  # a newer reload took over
            return
        logged = {r["char_id"] for r in self.store.characters()}
        size = self.PRELOAD_BATCH if getattr(self, "_preloading", False) else self.BATCH
        batch, self._pending = self._pending[:size], self._pending[size:]
        for info, entries, terms, stacking in batch:
            card = self._add_card(info, entries, terms, stacking)
            card.set_logged(info.id in logged)  # (the filters are applied to every card at the end, once)
        if self._pending:
            self._show_count()
            QTimer.singleShot(0, lambda: self._build_more(generation))
        else:
            self.apply_filter()  # shows the list (or "No buffs match…") now that every card is built
            self._sort()
            self._preloading = False
            self.built.emit()

    def preload(self):
        """Build the cards now, behind the loading screen (which waits for built)."""
        if self.cards and not getattr(self, "_stale", False):
            self._preloading = False
            self.built.emit()
        else:
            self._preloading = True
            self.reload(force=True)

    def start_preload(self):
        """The loading screen is about to put this page on top for a moment (unseen), so the list gets its real
        width: showing it mustn't start a build of its own. The cards are then built hidden at that width
        (built on screen, each one was styled as it appeared, which cost far more)."""
        self._preloading = True
        self.area.setCurrentWidget(self.scroll)

    def _card_width(self):
        """The width the list gives a card (known once the page has been on screen, even if it's hidden now)."""
        margins = self.list.contentsMargins()
        return self.scroll.viewport().width() - margins.left() - margins.right()

    def _add_card(self, info, entries, terms, stacking=()):
        # register the kit terms the entries mention, so hovering them explains what they are
        keys = {}
        for n, (term, (explanation, source)) in enumerate(sorted(terms.items())):
            key = f"kit{info.id}_{n}"
            gamedata.GLOSSARY[key] = (term, explanation, f"From {source}")
            keys[term] = key
        card = CharacterBuffs(info, "", [_Buff(*e) for e in entries], keys, [tuple(x) for x in stacking])
        card.open_character.connect(self.open_character)
        self.cards.append(card)
        self.list.insertWidget(self.list.count() - 1, card)
        if getattr(self, "_preloading", False) and self._card_width() > 100:
            card.resize(self._card_width(), card.height())  # (hidden, the list doesn't size it yet)
        return card

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_stale", False) and not getattr(self, "_preloading", False):
            self.reload()
        self._refresh_logged()

    def _refresh_logged(self):
        logged = {r["char_id"] for r in self.store.characters()}
        for card in self.cards:
            card.set_logged(card.info.id in logged)

    # ----- filters -----
    def _test_for(self, card):
        """test(buff) for one card under the current filters."""
        kind = self.type_group.value
        element = self.element_group.value
        who = self.who_group.value
        plain = not self.restricted_button.isChecked()
        query = self.search.text().strip()
        name_hit = matches(query, card.info.name)
        # constellation buffs only when that rarity's "Cons" toggle is on
        cons_button = self.five_cons_button if card.info.rarity >= 5 else self.four_cons_button
        no_cons = not cons_button.isChecked()

        def test(buff):
            return (
                (kind is None or kind in buff.types)
                and (element is None or buff.affects(element))
                and (who is None or buff.who == who)
                and not (no_cons and buff.constellation)
                and not (plain and buff.condition)
                and (not query or name_hit or query.lower() in (buff.text + " " + buff.condition).lower())
            )

        return test

    def _level_for(self, card):
        """The investment the card's total is at: C6 when that rarity's Cons toggle is on, else C0."""
        button = self.five_cons_button if card.info.rarity >= 5 else self.four_cons_button
        return "C6" if button.isChecked() else "C0"

    def apply_filter(self):
        # the list is laid out once at the end, not again after every card's new height
        self.list.setEnabled(False)
        try:
            for card in self.cards:
                self._shown[card] = card.apply(self._test_for(card), self._level_for(card))
        finally:
            self.list.setEnabled(True)
            self.list.activate()
        self._show_count()
        if self.sort_box.currentData() == "count":
            self._sort()

    def _show_count(self):
        total = sum(self._shown.get(c, 0) for c in self.cards)
        characters = sum(1 for c in self.cards if self._shown.get(c, 0))
        building = bool(getattr(self, "_pending", None))
        if self.cards and not building:  # (while building, the area keeps showing "Loading buffs…")
            if total == 0:
                self._show_message()
            else:
                self.area.setCurrentWidget(self.scroll)
        self.count_label.setText(f"Showing {total} buffs from {characters} characters" + ("…" if building else ""))

    def _sort_key(self):
        """The card order for the sort box (on CharInfo), or None for "most buffs shown"."""
        key = self.sort_box.currentData()
        order = {e: i for i, e in enumerate(gamedata.ELEMENTS)}
        if key == "name":
            return lambda info: info.name
        if key == "rarity":
            return lambda info: (-info.rarity, info.name)
        if key == "count":
            return None
        return lambda info: (order.get(info.element, 99), info.name)

    def _sort(self):
        key = self._sort_key()
        if key is None:
            cards = sorted(self.cards, key=lambda c: (-self._shown.get(c, 0), c.info.name))
        else:
            cards = sorted(self.cards, key=lambda c: key(c.info))
        for i, card in enumerate(cards):
            if self.list.indexOf(card) != i:
                self.list.removeWidget(card)
                self.list.insertWidget(i, card)
