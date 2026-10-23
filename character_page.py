"""Characters page, laid out like a Prydwen character guide.

Centre: a hero banner (art, badges, info grid) and tabs split into titled sections.
Right: a searchable, element-filterable list of every character to scroll between.
"""

import html
import re

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QIcon, QLinearGradient, QPainter, QRadialGradient
from PySide6.QtWidgets import (
    QApplication,
    QAbstractButton,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import gamedata
import theme
from search import matches
from gamedata import pretty, rich_html
from widgets import ColumnGrid, EvenGrid, FilterGroup, ImageTile, clear_layout, filter_button, glossary_tooltips, section_header, RemoteIcon, card_pixmap, shape_icon
from widgets import CORNER, SMALL_CORNER, corner_path, corners

TABS = ["PROFILE", "SKILLS", "CONSTELLATIONS", "MY BUILD"]
SORTS = [("Newest first", "newest"), ("Oldest first", "oldest"), ("Name (A–Z)", "name"), ("Rarity", "rarity")]
GRID_CELL = QSize(124, 146)  # landing grid: card + name
RAIL_CELL = QSize(68, 68)  # compact rail: card only

# Prydwen's character-page palette (prydwen.gg/genshin-impact/characters/...): square corners, charcoal
# cards with #373a43 borders, and an accent color that follows the character's element.
PRYDWEN_ELEMENTS = {
    "PYRO": (239, 106, 79),
    "HYDRO": (78, 178, 255),
    "ELECTRO": (173, 125, 255),
    "CRYO": (158, 232, 255),
    "ANEMO": (81, 217, 189),
    "GEO": (215, 168, 79),
    "DENDRO": (126, 217, 87),
}
CONSTELLATION_GOLD = (244, 195, 95)
BORDER = "#373a43"
SECTION_BG = (41, 42, 48)  # kit sections
CARD_BG = (31, 33, 39)  # cards inside them
HEADER_BG = (17, 18, 22)  # card headers
INSET_BG = (14, 15, 18)  # info/stat tiles


def _rgba(rgb, alpha):
    return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {alpha})"


def _blend(base, accent, amount):
    """base with `amount` of accent mixed in, as #rrggbb (QSS gradients can't layer over a color)."""
    return "#" + "".join(f"{round(b + (a - b) * amount):02x}" for b, a in zip(base, accent))


def page_css(accent):
    a = accent
    gold = CONSTELLATION_GOLD
    return f"""
#Hero {{ background: #111318; border: 1px solid #333741; border-radius: 0; }}
#Kicker {{ color: #8c909b; font-size: 9pt; font-weight: 800; }}
#HeroName {{ font-size: 30pt; font-weight: 700; color: #ffffff; }}
#HeroTitle {{ color: #e5e7ec; font-size: 13pt; }}
#Badge {{ background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.12); border-radius: 0;
          padding: 4px 12px; font-size: 10.5pt; font-weight: 800; }}
#ElementBadge {{ background: {_rgba(a, 0.19)}; border: 1px solid {_rgba(a, 0.42)}; border-radius: 0; }}
#InfoTile {{ background: {_rgba(INSET_BG, 0.62)}; border: 1px solid rgba(255,255,255,0.11); border-radius: 0; }}
#InfoKey {{ color: #8c909b; font-size: 7.5pt; font-weight: 900; }}
#InfoValue {{ font-size: 9pt; font-weight: 700; color: #ffffff; }}
#Freshness {{ color: #bfc4cc; font-size: 9pt; font-weight: 800; }}
#TabBar {{ background: rgba(22,23,27,0.9); border-top: 2px solid rgb{a}; border-left: 1px solid #333741; }}
#TabBtn {{ background: transparent; border: none; border-bottom: 1px solid #333741; border-right: 1px solid #333741;
           border-radius: 0; padding: 15px 20px; font-size: 9pt; font-weight: 800; color: #dfe2e8; }}
#TabBtn:hover {{ background: rgba(255,255,255,0.03); }}
#TabBtn:checked {{ background: {_rgba(a, 0.08)}; color: rgb{a}; }}
#SectionTitle {{ font-size: 16.5pt; font-weight: 700; color: #ffffff; border-bottom: 2px solid rgb{a}; padding-bottom: 8px; }}
#KitSection {{ background: {_rgba(SECTION_BG, 0.92)}; border: 1px solid {BORDER}; border-radius: 0; }}
#KitSectionHeader {{ border: none; border-bottom: 1px solid {BORDER};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {_blend((20, 21, 25), a, 0.12)}, stop:0.48 #141519, stop:1 #141519); }}
QPushButton#CollapseHeader {{ text-align: left; padding: 14px 18px; border: none; border-radius: 0;
                              background: transparent; font-size: 13.5pt; font-weight: 700; color: #ffffff; }}
QPushButton#CollapseHeader:hover {{ color: rgb{a}; }}
#KitSectionTitle {{ font-size: 13.5pt; font-weight: 700; color: #ffffff; }}
#KitSectionNote {{ color: #8c909b; font-size: 8.5pt; }}
#Card {{ background: {_rgba(CARD_BG, 0.92)}; border: 1px solid {BORDER}; border-radius: 0; }}
#AccentCard {{ background: {_rgba(CARD_BG, 0.92)}; border: 1px solid {BORDER}; border-left: 2px solid rgb{a}; border-radius: 0; }}
#ConsCard {{ background: {_rgba(CARD_BG, 0.92)}; border: 1px solid {BORDER}; border-left: 2px solid {_rgba(gold, 0.78)}; border-radius: 0; }}
#CardHeader {{ border: none; border-bottom: 1px solid {BORDER}; }}
#Panel {{ background: {_rgba(CARD_BG, 0.92)}; border: 1px solid {BORDER}; border-radius: 0; }}
#AccentPanel {{ border: 1px solid {BORDER}; border-left: 2px solid rgb{a}; border-radius: 0;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {_blend(SECTION_BG, a, 0.11)}, stop:0.42 #292a30, stop:1 #292a30); }}
#PanelKicker {{ color: #8c909b; font-size: 8pt; font-weight: 900; }}
#PanelTitle {{ font-size: 15.5pt; font-weight: 700; color: #ffffff; }}
#MiniLabel {{ background: {_rgba(gold, 0.12)}; border: 1px solid {_rgba(gold, 0.46)}; color: rgb{gold};
              font-size: 12pt; font-weight: 900; padding: 3px 9px; border-radius: 0; }}
#StatTile {{ background: {_rgba(INSET_BG, 0.62)}; border: 1px solid rgba(255,255,255,0.11); border-radius: 0; }}
#StatTile[ascension="true"] {{ border: 1px solid rgb{a}; background: rgba({a[0]},{a[1]},{a[2]},0.10); }}
#StatKey {{ color: #8c909b; font-size: 7.5pt; font-weight: 900; }}
#StatValue {{ font-size: 15pt; font-weight: 700; color: #ffffff; }}
#MultiplierBox {{ background: rgba(12,13,16,0.52); border: 1px solid {BORDER}; border-radius: 0; }}
#LevelBadge {{ background: rgba(12,13,16,0.6); border: 1px solid {_rgba(a, 0.5)}; border-radius: 0; padding: 5px 10px;
               font-weight: 800; font-size: 8.5pt; color: #ffffff; }}
#Body {{ color: #d6d9df; font-size: 11pt; }}
QSlider::groove:horizontal {{ height: 4px; background: #3a3d46; border: none; }}
QSlider::sub-page:horizontal {{ background: rgb{a}; }}
QSlider::handle:horizontal {{ background: rgb{a}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
#ListPanel {{ background: #1c1d21; border-left: 1px solid #33343a; }}
#ElementFilter {{ border: 1px solid transparent; border-radius: 0; }}
#ElementFilter[expanded="true"] {{ background: #1c1d22; border-color: {BORDER}; }}
#FilterBtn {{ background: #2c2d33; border: 1px solid #33343a; border-radius: 3px; padding: 3px; font-size: 8.5pt; font-weight: 600; }}
#FilterBtn:hover {{ border-color: #009eec; }}
#FilterBtn:checked {{ border-color: #009eec; background: #009eec; color: #ffffff; }}
""" + corners(["#Hero", "#KitSection", "#Card", "#AccentCard", "#ConsCard", "#Panel", "#AccentPanel"]) + corners(
        ["#InfoTile", "#StatTile", "#MultiplierBox"], SMALL_CORNER) + (
        # a section's header sits in its top-right corner: rounded the same, so it doesn't square it off
        f"#KitSectionHeader {{ border-top-right-radius: {CORNER - 1}px; }}\n")


PAGE_CSS = page_css(PRYDWEN_ELEMENTS["GEO"])


def _label(text, name, wrap=False):
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(wrap)
    if wrap:
        label.setTextFormat(Qt.RichText)
        glossary_tooltips(label)
    return label


def _wrapping_title(text):
    """A card title that wraps, so long names (some constellations are a whole sentence) never
    make a card wider than its column."""
    title = QLabel(text)
    title.setObjectName("PanelTitle")
    title.setWordWrap(True)
    return title


def _section_title(text, accent=PRYDWEN_ELEMENTS["GEO"]):
    title = QLabel(f"<span style='color:rgb{accent}'>■</span>&nbsp; {text.upper()}")
    title.setObjectName("SectionTitle")
    return title


class KitSection(QFrame):
    """Prydwen's section box: a header bar (title, optional note on the right) over padded content."""

    def __init__(self, title, note=""):
        super().__init__()
        self.setObjectName("KitSection")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)
        header = QFrame()
        header.setObjectName("KitSectionHeader")
        h = QHBoxLayout(header)
        h.setContentsMargins(18, 14, 18, 14)
        h.addWidget(_label(title.upper(), "KitSectionTitle"))
        h.addStretch()
        if note:
            h.addWidget(_label(note, "KitSectionNote"))
        outer.addWidget(header)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(14, 14, 14, 14)
        self.body.setSpacing(14)
        outer.addLayout(self.body)


class CollapsibleSection(QFrame):
    """A section box whose header opens and closes it (starts closed)."""

    toggled = Signal(bool)

    def __init__(self, title, note="", opened=False):
        super().__init__()
        self.setObjectName("KitSection")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)
        self.header = QPushButton()
        self.header.setObjectName("CollapseHeader")
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.clicked.connect(lambda: self.set_open(not self.body_widget.isVisible()))
        self._title, self._note = title.upper(), note
        outer.addWidget(self.header)
        self.body_widget = QWidget()
        self.body = QVBoxLayout(self.body_widget)
        self.body.setContentsMargins(14, 14, 14, 14)
        self.body.setSpacing(10)
        outer.addWidget(self.body_widget)
        self.set_open(opened, notify=False)

    def set_open(self, opened, notify=True):
        self.body_widget.setVisible(opened)
        arrow = "\u25be" if opened else "\u25b8"
        self.header.setText(f"{arrow}  {self._title}" + (f"     {self._note}" if self._note else ""))
        if notify:
            self.toggled.emit(opened)


class CardHeader(QFrame):
    """Card header: dark strip with a soft accent glow behind the 64px icon, kicker and name."""

    def __init__(self, icon_url, kicker, name, accent, mini_label=None):
        super().__init__()
        self.setObjectName("CardHeader")
        self.accent = accent
        h = QHBoxLayout(self)
        h.setContentsMargins(16, 16, 16, 16)
        h.setSpacing(16)
        icon = RemoteIcon(64)
        icon.set_url(icon_url)
        h.addWidget(icon, 0, Qt.AlignVCenter)
        names = QVBoxLayout()
        names.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(10)
        if mini_label:
            top.addWidget(_label(mini_label, "MiniLabel"), 0, Qt.AlignVCenter)
        names.addWidget(_label(kicker.upper(), "PanelKicker"))
        top.addWidget(_wrapping_title(name), 1)
        names.addLayout(top)
        h.addLayout(names, 1)
        self.extras = QHBoxLayout()  # badges on the right (cooldown, energy)
        self.extras.setSpacing(6)
        h.addLayout(self.extras)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # the header is the top of its card: round its top-right corner the same as the card's
        p.setClipPath(corner_path(QRectF(self.rect()), CORNER - 1, top_right=True, bottom_left=False))
        p.fillRect(self.rect(), theme.qcolor(*HEADER_BG, 184))
        glow = QRadialGradient(QPointF(48, self.height() / 2), 74)
        glow.setColorAt(0, QColor(*self.accent, 41))
        glow.setColorAt(1, QColor(*self.accent, 0))
        p.fillRect(self.rect(), QBrush(glow))
        p.end()
        super().paintEvent(event)


class KitCard(QFrame):
    """Prydwen's talent/constellation card: header strip, then the description and anything below it."""

    def __init__(self, icon_url, kicker, name, accent, style="Card", mini_label=None):
        super().__init__()
        self.setObjectName(style)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1 if style == "Card" else 2, 1, 1, 1)
        outer.setSpacing(0)
        self.header = CardHeader(icon_url, kicker, name, accent, mini_label)
        outer.addWidget(self.header)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(16, 16, 16, 16)
        self.body.setSpacing(14)
        outer.addLayout(self.body)


# Skill/constellation cards use two columns only when each can be at least this wide, so every
# character switches at the same window width (one column at the smallest window size).
CARD_MIN_WIDTH = 470


def _two_columns(cards):
    """Cards in two columns when there's room, one when the window is narrow."""
    cards = list(cards)
    for card in cards:
        card.body.addStretch()  # keep each card's content at the top when its row is taller
    return ColumnGrid(cards, spacing=14, min_column_width=CARD_MIN_WIDTH)


def _clear(layout):
    clear_layout(layout)


def _make_selectable(root):
    """Let the page's text be highlighted and copied (Ctrl+C or right-click > Copy).
    Glossary links keep working; labels on buttons are left alone so clicking them still clicks."""
    for label in root.findChildren(QLabel):
        flags = label.textInteractionFlags()
        if flags & Qt.TextSelectableByMouse or not label.text():
            continue
        parent = label.parentWidget()
        while parent is not None and parent is not root and not isinstance(parent, QAbstractButton):
            parent = parent.parentWidget()
        if isinstance(parent, QAbstractButton):
            continue
        label.setTextInteractionFlags(flags | Qt.TextSelectableByMouse)


# ---------- hero banner ----------
class Hero(QFrame):
    """Art on the right fading into the name, badges and info grid on the left."""

    def __init__(self, compact=False, kicker="GENSHIN IMPACT CHARACTER GUIDE"):
        super().__init__()
        self.setObjectName("Hero")
        # compact: the character page and the log, whose banner holds fewer facts (the rest are in the
        # Profile tab) - the same height for every character, whatever their art or text
        if compact:
            self.setFixedHeight(HERO_COMPACT_HEIGHT)
        else:
            self.setMinimumHeight(430)
        self.corner = None
        self._art = None
        self._art_url = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(*((40, 28, 40, 24) if compact else (46, 40, 46, 36)))
        left = QVBoxLayout()
        left.setSpacing(10)
        left.addWidget(_label(kicker, "Kicker"))
        self.name = _label("", "HeroName")
        self.title = _label("", "HeroTitle")
        left.addWidget(self.name)
        left.addWidget(self.title)
        self.badges = QHBoxLayout()
        self.badges.setSpacing(6)
        left.addLayout(self.badges)
        self.grid = QGridLayout()
        self.grid.setSpacing(6)
        left.addLayout(self.grid)
        self.actions = QHBoxLayout()
        left.addSpacing(4)
        left.addLayout(self.actions)
        left.addStretch()
        holder = QWidget()
        holder.setLayout(left)
        holder.setMaximumWidth(470)
        layout.addWidget(holder)
        layout.addStretch()

    def set_corner(self, widget):
        """A small button in the bottom-right corner (the log page's favourite star)."""
        self.corner = widget
        widget.setParent(self)
        self._place_corner()

    def _place_corner(self):
        if self.corner is not None:
            size = self.corner.sizeHint()
            self.corner.setGeometry(self.width() - size.width() - 14, self.height() - size.height() - 12,
                                    size.width(), size.height())
            self.corner.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_corner()

    def set_art(self, url, fallback):
        if url == self._art_url:
            return
        self._art_url = url
        self._art = None
        self.update()
        gamedata.load_pixmap(url, lambda pm, url=url: self._loaded(url, pm), fallback=fallback)

    def _loaded(self, url, pm):
        if url == self._art_url:
            self._art = pm
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._art is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setClipPath(corner_path(rect, CORNER - 1))  # (inside the banner's rounded corners)
        scaled = self._art.scaled(int(rect.width() * 0.85), int(rect.height() * 1.15), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = rect.right() - scaled.width() + scaled.width() * 0.12
        y = rect.center().y() - scaled.height() / 2
        p.drawPixmap(int(x), int(y), scaled)
        fade = QLinearGradient(rect.topLeft(), rect.topRight())
        fade.setColorAt(0.0, theme.qcolor(17, 19, 24, 255))
        fade.setColorAt(0.38, theme.qcolor(17, 19, 24, 235))
        fade.setColorAt(0.62, theme.qcolor(17, 19, 24, 40))
        fade.setColorAt(1.0, theme.qcolor(17, 19, 24, 0))
        p.fillRect(rect, QBrush(fade))
        p.end()


def profile_facts(detail):
    """Title, constellation, birthday and affiliation (the character page shows these under About)."""
    return [
        ("Title", gamedata.clean(detail.info.title)),
        ("Constellation", gamedata.clean(detail.info.constellation)),
        ("Birthday", f"{detail.birthday.month:02d}-{detail.birthday.day:02d}"),
        ("Affiliation", gamedata.clean(detail.info.native)),
    ]


def fill_hero(hero, info, detail, color, with_profile=True):
    """Fill the character banner: art, name, title, rarity/element/weapon badges and the info grid.
    Shared by the character page and the character log; each adds its own buttons.
    with_profile=False leaves the profile facts out (the character page has them in its Profile tab)."""
    hero.set_art(info.splash, info.icon)
    hero.name.setText(info.name)
    hero.title.setText(gamedata.clean(detail.info.title))
    _clear(hero.badges)
    star = _label(f"<span style='color:#f4c35f'>{'★' * info.rarity}&nbsp; {info.rarity}-star</span>", "Badge")
    element = QFrame()
    element.setObjectName("ElementBadge")
    el = QHBoxLayout(element)
    el.setContentsMargins(10, 0, 12, 0)
    el.setSpacing(6)
    icon = RemoteIcon(18)
    icon.set_url(gamedata.element_icon_url(info.element))
    el.addWidget(icon)
    name = QLabel(f"<span style='color:rgb{color}'>{pretty(info.element)}</span>")
    name.setStyleSheet("font-size: 10.5pt; font-weight: 800;")
    el.addWidget(name)
    weapon = _label(gamedata.weapon_type_name(info.weapon_type), "Badge")
    for b in (star, element, weapon):
        hero.badges.addWidget(b)
    hero.badges.addStretch()

    _clear(hero.grid)
    facts = (profile_facts(detail) if with_profile else []) + [
        ("Region", pretty(detail.region) if detail.region else "—"),
        ("Release", "Unreleased" if getattr(detail, "unreleased", False)
         else detail.release.strftime("%Y-%m-%d") if detail.release else "—"),
    ]
    for n, (key, value) in enumerate(facts):
        hero.grid.addWidget(InfoTile(key, value or "—"), n // 2, n % 2)


class InfoTile(QFrame):
    def __init__(self, key, value):
        super().__init__()
        self.setObjectName("InfoTile")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.addWidget(_label(key.upper(), "InfoKey"))
        layout.addStretch()
        value_label = _label(value, "InfoValue")
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value_label.setWordWrap(True)
        layout.addWidget(value_label)


# ---------- reusable section pieces ----------
class Panel(QFrame):
    def __init__(self, accent=False):
        super().__init__()
        self.setObjectName("AccentPanel" if accent else "Panel")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 16)
        self.body.setSpacing(10)


class TalentCard(KitCard):
    """Icon, category, name and description; active talents get a level slider for their multipliers.
    Passive cards get the accent stripe on the left, like Prydwen's."""

    def __init__(self, talent, label, accent, start_level=1, description=None):
        active = label in gamedata.ACTIVE_LABELS
        super().__init__(talent.icon, label, gamedata.clean(talent.name), accent, "Card" if active else "AccentCard")
        if talent.cooldown:
            self.header.extras.addWidget(_label(f"CD {talent.cooldown:g}s", "LevelBadge"), 0, Qt.AlignTop)
        if talent.cost:
            self.header.extras.addWidget(_label(f"Energy {talent.cost}", "LevelBadge"), 0, Qt.AlignTop)
        self.body.addWidget(_label(rich_html(description or talent.description), "Body", wrap=True))
        if talent.upgrades:
            self._add_multipliers(talent.upgrades, start_level)

    def _add_multipliers(self, upgrades, start_level):
        """A slider over the talent levels; the tiles show every multiplier at the chosen level."""
        rows = [d for d in upgrades[0].description if d and "|" in d]
        if not rows:
            return
        box = QFrame()
        box.setObjectName("MultiplierBox")
        v = QVBoxLayout(box)
        v.setContentsMargins(14, 12, 14, 14)
        v.setSpacing(8)

        head = QHBoxLayout()
        head.addWidget(_label("▸ SKILL MULTIPLIERS", "StatKey"), 1)
        level_badge = _label("", "LevelBadge")
        head.addWidget(level_badge)
        v.addLayout(head)

        slider = QSlider(Qt.Horizontal)
        slider.setRange(1, len(upgrades))
        slider.setPageStep(1)
        slider.setTickPosition(QSlider.TicksBelow)
        slider.setTickInterval(1)
        slider.setCursor(Qt.PointingHandCursor)
        v.addWidget(slider)

        pairs = []
        values = []
        for row in rows:
            pair = QWidget()
            h = QHBoxLayout(pair)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(10)
            name = _label(gamedata.clean(row.split("|", 1)[0]), "Body")
            name.setStyleSheet("color: #8a91a0;")
            name.setWordWrap(True)  # long names wrap instead of widening the card
            value = _label("", "InfoValue")
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            h.addWidget(name, 1)
            h.addWidget(value)
            pairs.append(pair)
            values.append((row.split("|", 1)[1], value))
        # two columns of name/value pairs when the card is wide enough, else one
        v.addWidget(ColumnGrid(pairs, spacing=6, min_column_width=190))

        def show(level):
            up = upgrades[level - 1]
            level_badge.setText(f"LEVEL  {up.level}/{upgrades[-1].level}")
            for template, value in values:
                value.setText(gamedata.format_multiplier(template, up.params))

        slider.valueChanged.connect(show)
        slider.setValue(max(1, min(start_level, len(upgrades))))
        show(slider.value())
        self.body.addWidget(box)


HERO_COMPACT_HEIGHT = 330  # the character page's and the log's banner
LOADING_CARD = 120  # the portrait in the middle while a character loads
LOADING_MIN_MS = 300  # the loading view stays up at least this long when switching characters
IMAGE_WAIT_MS = 8000  # longest the loading view waits on the page's images before showing it anyway

MAX_LEVEL = 100  # the stat curves go to 100
START_LEVEL = 90


class LevelStats(Panel):
    """Prydwen-style level slider with base stats and the ascension stat."""

    def __init__(self, detail, curve):
        super().__init__(accent=True)
        self.detail = detail
        self.curve = curve
        self.body.setContentsMargins(18, 14, 18, 12)
        row = QHBoxLayout()
        row.setSpacing(18)
        left = QVBoxLayout()
        left.setSpacing(10)
        head = QHBoxLayout()
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(_label("CHARACTER STATS", "PanelKicker"))
        names.addWidget(_label("Level Stats", "PanelTitle"))
        head.addLayout(names, 1)
        self.level_badge = _label("", "LevelBadge")
        head.addWidget(self.level_badge, 0, Qt.AlignBottom)
        left.addLayout(head)

        # up to level 100 (the game's levels past 90), starting at the usual 90
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(1, MAX_LEVEL)
        self.slider.setValue(START_LEVEL)
        self.slider.setTickPosition(QSlider.TicksBelow)
        self.slider.setTickInterval(10)
        self.slider.setCursor(Qt.PointingHandCursor)
        self.slider.valueChanged.connect(self.refresh)
        left.addWidget(self.slider)
        left.addStretch()
        row.addLayout(left, 1)

        grid = QGridLayout()
        grid.setSpacing(6)
        row.addLayout(grid, 1)
        self.body.addLayout(row)
        self.values = {}
        props = list(gamedata.character_stats(detail, curve, START_LEVEL))
        for n, prop in enumerate(props):
            tile = QFrame()
            tile.setObjectName("StatTile")
            if gamedata.stat_name(prop).upper() not in ("BASE HP", "BASE ATK", "BASE DEF"):
                tile.setProperty("ascension", "true")
            v = QVBoxLayout(tile)
            v.setContentsMargins(10, 8, 10, 8)
            v.setSpacing(2)
            v.addWidget(_label(gamedata.stat_name(prop).upper(), "StatKey"))
            value = _label("", "StatValue")
            v.addWidget(value)
            self.values[prop] = value
            grid.addWidget(tile, n // 2, n % 2)
        self.refresh(START_LEVEL)

    def refresh(self, level):
        self.level_badge.setText(f"LEVEL  {level}/{MAX_LEVEL}")
        for prop, value in gamedata.character_stats(self.detail, self.curve, level).items():
            if prop in self.values:
                self.values[prop].setText(gamedata.format_stat(prop, value))


def _sorted_characters(characters, sort):
    """Order for the grid and the rail. Same-day releases fall back to rarity, then name."""
    by_name = sorted(characters, key=lambda c: c.name)
    if sort == "name":
        return by_name
    if sort == "rarity":
        return sorted(by_name, key=lambda c: -c.rarity)
    by_rarity = sorted(by_name, key=lambda c: -c.rarity)
    # characters without a date sort as the oldest
    return sorted(by_rarity, key=lambda c: c.release.timestamp() if c.release else 0, reverse=(sort == "newest"))


def _filter_button(element, size):
    """A checkable element-filter button; element None means "All"."""
    btn = QToolButton()
    btn.setObjectName("FilterBtn")
    btn.setCheckable(True)
    btn.setChecked(element is None)
    btn.setFixedSize(size, size)
    btn.setCursor(Qt.PointingHandCursor)
    if element is None:
        btn.setText("All")
        btn.setToolTip("All elements")
    else:
        btn.setIconSize(QSize(size - 10, size - 10))
        btn.setToolTip(pretty(element))
        gamedata.load_pixmap(gamedata.element_icon_url(element), lambda pm: pm and btn.setIcon(QIcon(pm)))
    return btn


class _HoverFrame(QFrame):
    """A frame that reports when the mouse leaves it."""

    left = Signal()

    def leaveEvent(self, event):
        self.left.emit()


class ElementFilter(_HoverFrame):
    """Shows only the chosen element; hovering slides every option out to the left.

    The options live in a strip parented to `overlay_parent` (the page), so they float over
    the guide instead of pushing the rail's list around.
    """

    changed = Signal(object)  # element name, or None for all

    SIZE = 44

    def __init__(self, overlay_parent):
        super().__init__()
        self.setObjectName("ElementFilter")
        self.value = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.current = _filter_button(None, self.SIZE)
        self.current.setCheckable(False)
        self.current.setToolTip("Hover to filter by element")
        layout.addWidget(self.current)

        self.strip = _HoverFrame(overlay_parent)
        self.strip.setObjectName("ElementFilter")
        self.strip.setProperty("expanded", "true")
        row = QHBoxLayout(self.strip)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(4)
        self.buttons = {}
        # elements read left to right, with "All" on the right next to the rail
        for key in gamedata.ELEMENTS + [None]:
            btn = _filter_button(key, self.SIZE)
            btn.clicked.connect(lambda _=False, k=key: self._choose(k))
            self.buttons[key] = btn
            row.addWidget(btn)
        self.strip.hide()

        self._close_timer = QTimer(self, singleShot=True, interval=120)
        self._close_timer.timeout.connect(self._close_if_away)
        self.left.connect(self._close_timer.start)
        self.strip.left.connect(self._close_timer.start)
        self._sync()

    @property
    def expanded(self):
        return self.strip.isVisible()

    def enterEvent(self, event):
        self._open()

    def _open(self):
        self._close_timer.stop()
        self.strip.adjustSize()
        parent = self.strip.parentWidget()
        top_right = self.mapTo(parent, self.rect().topRight())
        self.strip.move(top_right.x() - self.strip.width() + 1, top_right.y())
        self.strip.show()
        self.strip.raise_()

    def _close_if_away(self):
        cursor = QCursor.pos()
        for widget in (self, self.strip):
            if widget.isVisible() and widget.rect().contains(widget.mapFromGlobal(cursor)):
                return
        self.strip.hide()

    def _choose(self, key):
        self.value = key
        self._sync()
        self.strip.hide()  # picking an option closes the strip; hover again to change it
        self.changed.emit(key)

    def set_value(self, key):
        self.value = key
        self._sync()

    def _sync(self):
        for key, btn in self.buttons.items():
            btn.setChecked(key == self.value)
        # the collapsed button mirrors the chosen option
        chosen = self.buttons[self.value]
        self.current.setText(chosen.text())
        self.current.setIcon(chosen.icon())
        self.current.setIconSize(chosen.iconSize())
        if self.value is not None and chosen.icon().isNull():  # icon may still be downloading
            gamedata.load_pixmap(gamedata.element_icon_url(self.value), lambda pm: self._sync() if pm else None)


# ---------- the page ----------
class CharacterPage(QWidget):
    visited = Signal(str)
    add_requested = Signal(str)
    open_home = Signal(str)
    open_log = Signal(str)  # a logged character's character log
    message = Signal(str)

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.index = None
        self.current_id = None
        self.element_filter = None  # shared by the grid's buttons and the rail's hover filter
        self._card_parts = {}  # char_id -> (portrait, element icon, rarity, logged) for redrawing rail icons
        self._request = 0
        self._pending = None  # the request still loading, if any
        self._markup = {}
        self._buffed = {}  # updated kit text (Buff toggle), by talent / constellation name
        self._detail = None
        self._accent = PRYDWEN_ELEMENTS["GEO"]
        self._name = ""
        self.setStyleSheet(PAGE_CSS)

        # Two modes: 0 = grid of every character (landing), 1 = one character's guide.
        self.mode = QStackedWidget()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.mode)
        self.mode.addWidget(self._build_grid_view())
        detail = QWidget()
        layout = QHBoxLayout(detail)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.mode.addWidget(detail)

        # guide: scrollable sections
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(28, 22, 28, 28)
        self.content_layout.setSpacing(0)
        self.placeholder = _label("Pick a character from the list on the right.", "Body")
        self.placeholder.setStyleSheet("color: #8a91a0; font-size: 12pt; padding: 40px;")
        self.content_layout.addWidget(self.placeholder)

        self.hero = Hero(compact=True, kicker="GENSHIN IMPACT CHARACTER DETAILS")
        self.content_layout.addWidget(self.hero)
        self.content_layout.addSpacing(26)
        tab_bar = QFrame()
        tab_bar.setObjectName("TabBar")
        tabs = QHBoxLayout(tab_bar)
        tabs.setContentsMargins(0, 0, 0, 0)
        tabs.setSpacing(0)
        self.tab_group = QButtonGroup(self)
        for i, name in enumerate(TABS):
            btn = QPushButton(name)
            btn.setObjectName("TabBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.tab_group.addButton(btn, i)
            tabs.addWidget(btn)
        self.tab_group.button(0).setChecked(True)
        self.tab_group.idClicked.connect(self._tab_changed)
        self.content_layout.addWidget(tab_bar)
        self.content_layout.addSpacing(22)

        # One widget per tab; only the active one is shown, so each tab is only as tall as its content.
        self.tab_pages = []
        self.tab_layouts = []
        for _ in TABS:
            page = QWidget()
            v = QVBoxLayout(page)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(14)
            self.tab_pages.append(page)
            self.tab_layouts.append(v)
            self.content_layout.addWidget(page)
        self.content_layout.addStretch()
        self.scroll.setWidget(content)
        # while a character's page is fetched and built: their portrait and "Loading …" in the middle, in place
        # of the guide, which then appears complete (rather than the old character being swapped out piece by piece)
        self.detail_stack = QStackedWidget()
        self.detail_stack.addWidget(self._build_loading_view())
        self.detail_stack.addWidget(self.scroll)
        self.detail_stack.setCurrentWidget(self.scroll)
        layout.addWidget(self.detail_stack, 1)
        layout.addWidget(self._build_rail())  # character selection rail on the right
        self._detail_widgets = [self.hero, tab_bar]
        for w in self._detail_widgets + self.tab_pages:
            w.hide()

    def _build_loading_view(self):
        view = QWidget()
        v = QVBoxLayout(view)
        v.setSpacing(14)
        v.addStretch()
        self.loading_card = QLabel()
        self.loading_card.setFixedSize(LOADING_CARD, LOADING_CARD)
        v.addWidget(self.loading_card, 0, Qt.AlignHCenter)
        self.loading_text = _label("", "Body")
        self.loading_text.setAlignment(Qt.AlignCenter)
        self.loading_text.setWordWrap(True)
        self.loading_text.setStyleSheet("color: #8a91a0; font-size: 13pt;")
        v.addWidget(self.loading_text)
        v.addStretch()
        return view

    def _show_loading(self, info, request, text=None):
        """Show the loading view for a character (or an error message), if that load is still the current one."""
        if request != self._request:
            return
        self.loading_text.setText(text or f"Loading {info.name}…")
        self.loading_card.clear()

        def portrait(pm):
            if request == self._request and pm is not None:
                card = card_pixmap(pm, None, info.rarity, LOADING_CARD)
                card.setDevicePixelRatio(2)
                self.loading_card.setPixmap(card)

        gamedata.load_pixmap(info.icon, portrait)
        self.detail_stack.setCurrentIndex(0)

    # ----- landing grid: every character at once -----
    def _build_grid_view(self):
        view = QWidget()
        v = QVBoxLayout(view)
        v.setContentsMargins(28, 22, 28, 20)
        v.setSpacing(12)
        head, self.count_label = section_header("All characters")
        v.addWidget(head)

        # Prydwen-style filters, stacked: search (and sort) / [All] [5★] [4★] [elements] / weapon types
        top = QHBoxLayout()
        top.setSpacing(4)
        self.search = QLineEdit(placeholderText="Search characters…")
        self.search.setFixedWidth(300)
        self.search.textChanged.connect(self.apply_filter)
        top.addWidget(self.search)
        top.addStretch()
        top.addWidget(_label("SORT", "PanelKicker"))
        self.sort_box = QComboBox()
        for label, key in SORTS:
            self.sort_box.addItem(label, key)
        self.sort_box.setMinimumWidth(150)
        self.sort_box.currentIndexChanged.connect(lambda _: self.index and self.populate())
        top.addWidget(self.sort_box)
        v.addLayout(top)

        controls = QHBoxLayout()
        controls.setSpacing(4)
        self.all_button = filter_button("All", tooltip="Clear all filters")
        self.all_button.setChecked(True)
        self.all_button.clicked.connect(self.clear_filters)
        controls.addWidget(self.all_button)
        self.rarity_group = FilterGroup([(r, f"{r}★", None, f"{r}-star characters") for r in (5, 4)])
        self.rarity_group.changed.connect(lambda _: self.apply_filter())
        controls.addWidget(self.rarity_group)
        controls.addSpacing(8)
        self.element_group = FilterGroup(
            [(e, "", gamedata.element_icon_url(e), pretty(e)) for e in gamedata.ELEMENTS]
        )
        self.element_group.changed.connect(self.set_element_filter)
        controls.addWidget(self.element_group)
        controls.addStretch()
        v.addLayout(controls)

        weapons = QHBoxLayout()
        weapons.setSpacing(4)
        self.weapon_group = FilterGroup(
            [(t, "", gamedata.weapon_type_icon_url(t), gamedata.weapon_type_name(t)) for t in gamedata.WEAPON_TYPES]
        )
        self.weapon_group.changed.connect(lambda _: self.apply_filter())
        weapons.addWidget(self.weapon_group)
        weapons.addStretch()
        v.addLayout(weapons)

        self.grid = EvenGrid(GRID_CELL + QSize(8, 8))
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setIconSize(QSize(104, 104))
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setWordWrap(True)
        self.grid.setSpacing(4)
        self.grid.setCursor(Qt.PointingHandCursor)
        self.grid.setStyleSheet("QListWidget { background: transparent; border: none; outline: 0; }")
        self.grid.itemClicked.connect(lambda item: self.show_item(item.data(Qt.UserRole)))
        v.addWidget(self.grid, 1)
        return view

    # ----- guide mode: compact icon rail on the left -----
    def _build_rail(self):
        panel = QFrame()
        panel.setObjectName("ListPanel")
        panel.setFixedWidth(92)
        v = QVBoxLayout(panel)
        v.setContentsMargins(8, 14, 8, 10)
        v.setSpacing(8)
        back = QToolButton()
        back.setIcon(shape_icon("grid", theme.accent_hex()))
        back.setIconSize(QSize(24, 24))
        back.setFixedSize(QSize(76, 40))
        back.setObjectName("FilterBtn")
        back.setToolTip("All characters")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self.show_grid)
        self.rail_filter = ElementFilter(overlay_parent=self)
        self.rail_filter.changed.connect(self.set_element_filter)
        self.rail = QListWidget()
        self.rail.setViewMode(QListView.IconMode)
        self.rail.setFlow(QListView.TopToBottom)
        self.rail.setWrapping(False)
        self.rail.setMovement(QListView.Static)
        self.rail.setIconSize(QSize(58, 58))
        self.rail.setGridSize(RAIL_CELL)
        self.rail.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.rail.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # scroll with the wheel; keeps the rail slim
        self.rail.setCursor(Qt.PointingHandCursor)
        # No row highlight or focus outline: the selected character gets an element-coloured
        # border drawn into its icon instead (see _set_rail_icon).
        self.rail.setFocusPolicy(Qt.NoFocus)
        self.rail.setStyleSheet(
            "QListWidget { background: transparent; border: none; outline: 0; }"
            "QListWidget::item { border: none; padding: 1px; }"
            "QListWidget::item:selected, QListWidget::item:hover { background: transparent; border: none; }"
        )
        self.rail.currentItemChanged.connect(lambda item, _prev: item and self.show_item(item.data(Qt.UserRole)))
        v.addWidget(back, 0, Qt.AlignHCenter)
        v.addWidget(self.rail_filter, 0, Qt.AlignHCenter)
        v.addWidget(self.rail, 1)
        return panel

    def show_grid(self):
        self.rail_filter.strip.hide()
        self.mode.setCurrentIndex(0)

    def set_element_filter(self, element):
        self.element_filter = element
        self.element_group.set_value(element)
        self.rail_filter.set_value(element)
        self.apply_filter()

    def clear_filters(self):
        self.rarity_group.set_value(None)
        self.weapon_group.set_value(None)
        self.set_element_filter(None)

    # ----- data -----
    def set_index(self, index):
        self.index = index
        self.populate()

    def populate(self):
        logged = {r["char_id"] for r in self.store.characters()}
        for view in (self.grid, self.rail):
            view.blockSignals(True)
            view.clear()
        for char in _sorted_characters(self.index.characters.values(), self.sort_box.currentData()):
            tip = f"{char.name}\n{'★' * char.rarity}  {pretty(char.element)} · {gamedata.weapon_type_name(char.weapon_type)}"
            if char.id in logged:
                tip += "\n✔ In your Record Book"
            grid_item = QListWidgetItem(char.name)
            rail_item = QListWidgetItem()
            for item in (grid_item, rail_item):
                item.setData(Qt.UserRole, char.id)
                item.setToolTip(tip)
            grid_item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            # fixed sizes: otherwise the view measures items before their pictures arrive and crops them
            grid_item.setSizeHint(GRID_CELL)
            rail_item.setSizeHint(RAIL_CELL)
            self.grid.addItem(grid_item)
            self.rail.addItem(rail_item)
            if char.id == self.current_id:
                self.rail.setCurrentItem(rail_item)
            self._load_card(char, char.id in logged, (grid_item, rail_item))
        for view in (self.grid, self.rail):
            view.blockSignals(False)
        self.apply_filter()

    def _load_card(self, char, logged, items):
        grid_item, rail_item = items

        def with_element(element_pm):
            def with_portrait(portrait):
                self._card_parts[char.id] = (portrait, element_pm, char.rarity, logged)
                grid_item.setIcon(QIcon(card_pixmap(portrait, element_pm, char.rarity, logged=logged)))
                self._set_rail_icon(rail_item)

            gamedata.load_pixmap(char.icon, with_portrait, bulk=True)

        gamedata.load_pixmap(gamedata.element_icon_url(char.element), with_element)

    def _set_rail_icon(self, item):
        """Rail icon, with a border in the character's element colour when it's the one shown."""
        char_id = item.data(Qt.UserRole)
        parts = self._card_parts.get(char_id)
        if parts is None:
            return  # pictures still loading; _load_card calls back here when they arrive
        border = gamedata.ELEMENT_COLORS[self.index.characters[char_id].element] if char_id == self.current_id else None
        portrait, element_pm, rarity, logged = parts
        item.setIcon(QIcon(card_pixmap(portrait, element_pm, rarity, logged=logged, border=border)))

    def apply_filter(self):
        if not self.index:
            return
        text = self.search.text()
        element = self.element_filter
        rarity = self.rarity_group.value
        weapon = self.weapon_group.value
        self.all_button.setChecked(element is None and rarity is None and weapon is None)
        shown = 0
        for i in range(self.grid.count()):
            char = self.index.characters[self.grid.item(i).data(Qt.UserRole)]
            wrong_element = bool(element and char.element != element)
            hidden = (
                wrong_element
                or not matches(text, char.name)
                or bool(rarity and char.rarity != rarity)
                or bool(weapon and char.weapon_type != weapon)
            )
            self.grid.item(i).setHidden(hidden)
            self.rail.item(i).setHidden(wrong_element)  # the rail only filters by element
            shown += not hidden
        self.count_label.setText(f"Showing {shown} characters")

    # ----- showing a character -----
    def show_item(self, char_id, visit=True):
        if not self.index or char_id not in self.index.characters:
            return
        self.mode.setCurrentIndex(1)
        previous_id = self.current_id
        first_time = char_id != previous_id
        self.current_id = char_id
        for i in range(self.rail.count()):
            item = self.rail.item(i)
            if item.data(Qt.UserRole) == char_id:
                self.rail.blockSignals(True)
                self.rail.setCurrentRow(i)
                self.rail.blockSignals(False)
                self.rail.scrollToItem(item)
            if item.data(Qt.UserRole) in (char_id, previous_id):
                self._set_rail_icon(item)  # move the element border to the new character
        if visit:
            self.visited.emit(char_id)

        info = self.index.characters[char_id]
        self._request += 1
        request = self._request
        # a newly picked character always gets the loading view, for at least LOADING_MIN_MS, so switching
        # never shows one character's page being swapped over to the next
        # (a refresh of the same character keeps its page up while it updates)
        waiting = {"min time", "images"} if first_time else set()
        if first_time:
            self._show_loading(info, request)
            QTimer.singleShot(LOADING_MIN_MS, lambda: ready("min time"))
        self._pending = request

        def fetch():
            try:  # colors and glossary links; the page still works with the plain text without them
                markup = gamedata.fetch_character_markup(char_id)
            except Exception:
                markup = ({}, {})
            return gamedata.fetch_character_detail(char_id), gamedata.fetch_avatar_curve(), markup

        def done(result, error):
            if request != self._request:
                return
            self._pending = None
            if error:
                self._show_loading(info, request, f"Couldn't load {info.name}: {error}")
                return
            if not first_time:  # a refresh of the page already up: update it in place
                self._render(info, *result)
                return
            # built behind the loading view, which stays up until its images (art, icons) are in too,
            # so the page appears whole instead of filling in piece by piece
            self._pending = request
            images = gamedata.track_images()
            try:
                self._render(info, *result)
            finally:
                gamedata.stop_tracking()
            QTimer.singleShot(IMAGE_WAIT_MS, lambda: ready("images"))  # don't wait forever on a slow image
            gamedata.when_loaded(images, lambda: ready("images"))

        def ready(what):
            waiting.discard(what)
            if not waiting:
                reveal()

        def reveal():
            if request != self._request or self._pending != request:
                return  # another character was picked meanwhile, or it's already shown
            self._pending = None
            self.detail_stack.setCurrentWidget(self.scroll)
            # arrange it before the first paint: built while hidden, its sections' layouts are only queued, and
            # it would show a frame of them piled on each other; run every queued layout update now
            QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
            self.scroll.verticalScrollBar().setValue(0)

        gamedata.run_async(fetch, done)

    def refresh_detail(self):
        if self.index:
            self.populate()
            if self.current_id and self.mode.currentIndex() == 1:
                self.show_item(self.current_id, visit=False)

    def _tab_changed(self, index):
        for i, page in enumerate(self.tab_pages):
            page.setVisible(i == index)
        _make_selectable(self.scroll.widget())

    def _render(self, info, detail, curve, markup):
        self._markup, self._buffed = markup
        self._detail = detail
        self.placeholder.hide()
        for w in self._detail_widgets:
            w.show()
        accent = PRYDWEN_ELEMENTS[info.element]
        if accent != self._accent:  # Prydwen tints the whole page with the character's element
            self._accent = accent
            self.setStyleSheet(page_css(accent))
        self._name = info.name
        self._render_hero(info, detail, accent)
        self._render_profile(info, detail, curve)
        self._render_skills(detail, accent)
        self._render_constellations(detail, accent)
        self._render_build(info)
        self._tab_changed(self.tab_group.checkedId())

    def _render_hero(self, info, detail, color):
        hero = self.hero
        fill_hero(hero, info, detail, color, with_profile=False)

        _clear(hero.actions)
        char_id = info.id
        if self.store.character(char_id):
            log = QPushButton("Open character log")
            log.setObjectName("Primary")
            log.clicked.connect(lambda: self.open_log.emit(str(char_id)))
            hero.actions.addWidget(log)
            hero.actions.addWidget(_label("✔ In your Record Book", "PanelKicker"))
        else:
            add = QPushButton("+  Add to Record Book")
            add.setObjectName("Primary")
            add.clicked.connect(lambda: self.add_requested.emit(char_id))
            hero.actions.addWidget(add)
        if self._buffed:
            # like Project Amber's Buff toggle: the updated text of a reworked kit
            buff = filter_button("Buff", tooltip="Show the updated kit text for this character's rework\n(the Buff toggle on Project Amber)")
            buff.setFixedHeight(hero.actions.itemAt(0).widget().sizeHint().height())
            buff.setMinimumWidth(64)
            buff.setChecked(self._show_buffed())
            buff.toggled.connect(self._buff_toggled)
            hero.actions.addSpacing(6)
            hero.actions.addWidget(buff)
        hero.actions.addStretch()

    def _show_buffed(self):
        return bool(self._buffed) and self.store.get_setting("kit_buff", True)

    def _buff_toggled(self, on):
        self.store.set_setting("kit_buff", on)
        position = self.scroll.verticalScrollBar().value()
        self._render_skills(self._detail, self._accent)
        self._render_constellations(self._detail, self._accent)
        self._tab_changed(self.tab_group.checkedId())
        self.scroll.verticalScrollBar().setValue(position)

    def _render_profile(self, info, detail, curve):
        v = self.tab_layouts[0]
        _clear(v)
        v.addWidget(_section_title(f"{info.name} profile", self._accent))
        v.addWidget(LevelStats(detail, curve))
        about = KitSection("About")
        about.body.addWidget(_label(rich_html(detail.info.detail), "Body", wrap=True))
        grid = QGridLayout()
        grid.setSpacing(6)
        for n, (key, value) in enumerate(profile_facts(detail)):
            grid.addWidget(InfoTile(key, value or "—"), n // 2, n % 2)
        about.body.addLayout(grid)
        v.addWidget(about)
        if detail.info.cv:
            voices = KitSection("Voice actors")
            grid = QGridLayout()
            grid.setSpacing(6)
            for n, cv in enumerate(detail.info.cv):
                grid.addWidget(InfoTile(cv.lang, cv.va), n // 2, n % 2)
            voices.body.addLayout(grid)
            v.addWidget(voices)

    def _render_skills(self, detail, accent):
        v = self.tab_layouts[1]
        _clear(v)
        talents = gamedata.real_talents(detail.talents)
        labels = gamedata.talent_labels(talents)
        record = self.store.character(self.current_id)
        logged = {}
        if record:  # start each slider at the level you've logged for that talent
            logged = {"Normal Attack": record["talent1"], "Elemental Skill": record["talent2"], "Elemental Burst": record["talent3"]}
        v.addWidget(_section_title(f"{self._name} skills", accent))
        skills = KitSection("Skills", "Talent text and per-level multipliers, straight from the character data.")
        skills.body.addWidget(_two_columns(
            TalentCard(talent, label, accent, logged.get(label, 1), self._text(talent))
            for talent, label in zip(talents, labels)
            if label in gamedata.ACTIVE_LABELS
        ))
        v.addWidget(skills)
        passives = KitSection("Passive talents")
        passives.body.addWidget(_two_columns(
            TalentCard(talent, label, accent, description=self._text(talent))
            for talent, label in zip(talents, labels)
            if label not in gamedata.ACTIVE_LABELS
        ))
        v.addWidget(passives)
        self._render_glossary(v, talents, detail)

    def _edit_my_build(self, info):
        from dialogs import BuildDialog

        dialog = BuildDialog(self.index, info, self.store.my_build(str(info.id)) or {}, self)
        if dialog.exec():
            self.store.set_my_build(str(info.id), dialog.values)
            self._render_build(info)
            _make_selectable(self.scroll.widget())
            if self.store.character(str(info.id)):
                self.message.emit(f"Saved {info.name}'s build")
            else:
                self.message.emit(f"Saved {info.name}'s build: used when you pick them as a teammate")

    def _render_glossary(self, v, talents, detail):
        """The terms this character's kit uses, with what they mean (collapsed to start with)."""
        keys = []
        for entry in list(talents) + list(detail.constellations):
            for key in re.findall(r"term:([\w-]+)", self._text(entry) or ""):
                if key not in keys:
                    keys.append(key)
        names = {gamedata.GLOSSARY[k][0] for k in keys if k in gamedata.GLOSSARY}
        for name, _description in gamedata.CHAR_GLOSSARY.get(self.current_id, []):
            key = next((k for k, (n, _d, src) in gamedata.GLOSSARY.items() if n == name and src == "Game glossary"), None)
            if key and name not in names:
                keys.append(key)
                names.add(name)
        terms = sorted({gamedata.GLOSSARY[k][0]: k for k in keys if k in gamedata.GLOSSARY}.items(), key=lambda t: t[0].lower())
        if not terms:
            return
        section = CollapsibleSection("Glossary", f"{len(terms)} term{'s' if len(terms) != 1 else ''} used in this kit",
                                     opened=getattr(self, "_glossary_open", False))
        section.toggled.connect(lambda on: setattr(self, "_glossary_open", on))
        for name, key in terms:
            _name, description, source = gamedata.GLOSSARY[key]
            body = gamedata._GLOSSARY_LINK.sub(r"\1", description) if source == "Game glossary" else description
            text = rich_html(body) if source == "Game glossary" else html.escape(body).replace("\n", "<br>")
            label = _label(f"<b style='color:rgb{self._accent}'>{html.escape(name)}</b><br>{text}"
                           f"<br><span style='color:#8a91a0; font-size:8pt'>{html.escape(source)}</span>", "Body", wrap=True)
            label.setTextFormat(Qt.RichText)
            section.body.addWidget(label)
        v.addWidget(section)

    def _text(self, entry):
        """A talent's or constellation's description with the game's colors and links, when available
        (the updated text when the Buff toggle is on)."""
        name = gamedata.clean(entry.name)
        if self._show_buffed() and name in self._buffed:
            return self._buffed[name]
        return self._markup.get(name, entry.description)

    def _render_constellations(self, detail, accent):
        v = self.tab_layouts[2]
        _clear(v)
        v.addWidget(_section_title(f"{self._name} constellations", accent))
        section = KitSection("Constellations", gamedata.clean(detail.info.constellation))
        cards = []
        for n, con in enumerate(detail.constellations, 1):
            card = KitCard(con.icon, f"Constellation {n}", gamedata.clean(con.name), accent, "ConsCard", f"C{n}")
            card.body.addWidget(_label(rich_html(self._text(con)), "Body", wrap=True))
            cards.append(card)
        section.body.addWidget(_two_columns(cards))
        v.addWidget(section)

    def _render_build(self, info):
        """My Build: weapon, artifacts, talents and constellation, for any character. A logged character's is
        their Record Book build; it's also the build they start with when picked as a teammate on the log."""
        v = self.tab_layouts[3]
        _clear(v)
        v.addWidget(_section_title(f"{info.name} build", self._accent))
        char_id = str(info.id)
        record = self.store.character(char_id)
        build = self.store.my_build(char_id) or {}

        idx = self.index
        gear = Panel(accent=True)
        head = QHBoxLayout()
        head.addWidget(_label("MY BUILD", "PanelKicker"), 1)
        edit = QPushButton("Edit build" if build.get("weapon_id") else "+  Fill out build")
        edit.setObjectName("Primary")
        edit.setCursor(Qt.PointingHandCursor)
        edit.setToolTip("Weapon, artifacts, talent levels and constellation")
        edit.clicked.connect(lambda: self._edit_my_build(info))
        head.addWidget(edit)
        gear.body.addLayout(head)
        gear.body.addWidget(_label(
            "Your build for this character: used when you pick them as a teammate on a character log"
            + (" (and it's their Record Book build)." if record else "."), "Body", wrap=True))
        if build.get("weapon_id"):
            row = QHBoxLayout()
            row.setSpacing(16)
            weapon = idx.weapons.get(build.get("weapon_id"))
            ref = build.get("refinement") or 1
            wtile = ImageTile(88)
            wtile.show_plus = False
            wtile.setCursor(Qt.PointingHandCursor)
            wtile.clicked.connect(lambda: self._edit_my_build(info))
            if weapon:
                wtile.set_content([weapon.icon], weapon.rarity, f"R{ref}")
            row.addWidget(wtile)
            row.addWidget(_label(f"<b>{weapon.name if weapon else '—'}</b><br>Refinement {ref}", "Body", wrap=True), 1)
            sets = [idx.artifacts[a] for a in (build.get("artifact1"), build.get("artifact2")) if a in idx.artifacts]
            atile = ImageTile(88)
            atile.show_plus = False
            atile.setCursor(Qt.PointingHandCursor)
            atile.clicked.connect(lambda: self._edit_my_build(info))
            if sets:
                atile.set_content([s.icon for s in sets], max(s.rarity for s in sets), "4p" if len(sets) == 1 else "2p2p")
            row.addWidget(atile)
            if len(sets) == 1:
                bonus = "<br>".join(f"<span style='color:#8a91a0'>{n}p:</span> {rich_html(b)}" for n, b in zip((2, 4), sets[0].bonuses))
                text = f"<b>{sets[0].name}</b><br>{bonus}"
            else:
                text = "<br>".join(f"<b>{s.name}</b> <span style='color:#8a91a0'>2p:</span> {rich_html(s.bonuses[0])}" for s in sets)
            row.addWidget(_label(text or "—", "Body", wrap=True), 2)
            gear.body.addLayout(row)
            gear.body.addWidget(_label(
                f"Talents&nbsp;&nbsp;<b>{build.get('talent1') or 1} / {build.get('talent2') or 1} / {build.get('talent3') or 1}</b>"
                f"&nbsp;&nbsp;&nbsp;&nbsp;Constellation&nbsp;&nbsp;<b>C{build.get('constellation') or 0}</b>", "Body", wrap=True))
        v.addWidget(gear)

        if not record:
            empty = Panel()
            empty.body.addWidget(_label(f"{info.name} isn't in your Record Book yet.", "Body"))
            add = QPushButton("+  Add to Record Book")
            add.clicked.connect(lambda: self.add_requested.emit(info.id))
            row = QHBoxLayout()
            row.addWidget(add)
            row.addStretch()
            empty.body.addLayout(row)
            v.addWidget(empty)
            return

        # runs (with their notes) live on the character log; this is the summary
        dps = Panel()
        runs = self.store.runs(str(info.id))
        head = QHBoxLayout()
        head.addWidget(_label("RUNS", "PanelKicker"), 1)
        open_log = QPushButton("Open character log")
        open_log.setObjectName("Primary")
        open_log.clicked.connect(lambda: self.open_log.emit(str(info.id)))
        head.addWidget(open_log)
        dps.body.addLayout(head)
        best = self.store.best_dps(str(info.id))
        dps.body.addWidget(_label(
            f"<span style='font-size:18pt; color:rgb{self._accent}; font-weight:700'>{best:,.0f} DPS</span>"
            f"&nbsp; highest · {len(runs)} run{'s' if len(runs) != 1 else ''} logged", "Body", wrap=True))
        if not runs:
            dps.body.addWidget(_label("No runs yet. Add one on the character log.", "Body"))
        v.addWidget(dps)
