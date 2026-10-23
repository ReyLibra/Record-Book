"""Home: the top logged DPS of each element (rotating, over the character's splash art), the three supports
used most in your teams, the current banners, the top of the To Do List and the End Game timers: rounded
cards with small coloured tags."""

import random
import time
from datetime import datetime, timezone

from PySide6.QtCore import QEasingCurve, QEvent, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import gamedata
import servers
import theme
from widgets import CORNER, FlowLayout, RemoteIcon, card_pixmap, clear_layout, corner_path

ELEMENT_ORDER = ["PYRO", "HYDRO", "DENDRO", "ELECTRO", "ANEMO", "CRYO", "GEO"]
ROTATE_MS = 7000  # each element's top DPS stays this long
FADE_MS = 650
SUPPORTS_MAX = 20  # Support Character Usage lists as many as fit, up to this
SUPPORT_ROW = 44  # a support's row
SUPPORT_GAP = 5
TODO_ROW = 50  # a goal's row on Home's To-Do card
TODO_GAP = 6
SHOWCASE_MIN_HEIGHT = 210
BANNER_MIN_HEIGHT = 140
ART_SCALE = 1.45  # the splash art, against the showcase's height
ART_FEATHER = 0.2  # how much of each edge of the art fades out
ART_SHIFT = 0.30  # the art sits this much of the card's width further right (clear of the text)
MODE_NAMES = {"abyss": "Spiral Abyss", "fearless": "Stygian Fearless", "dire": "Stygian Dire"}
MODE_ICONS = {  # Lunaris's pictures for each End Game mode
    "abyss": "https://api.lunaris.moe/data/assets/icons/tower-card.png",
    "stygian": "https://api.lunaris.moe/data/assets/icons/leyline-card.png",
    "theater": "https://api.lunaris.moe/data/assets/icons/roleplay-card.png",
}


def _label(text, name):
    label = QLabel(text)
    label.setObjectName(name)
    return label


def _squeezable(label):
    """A label that may be cut short by a narrow window instead of widening its card (whole text on hover)."""
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    label.setMinimumWidth(20)
    label.setToolTip(label.text())
    return label


def pill(text, kind="accent", color=None):
    """A small rounded tag: 'accent' (blue), 'solid' (filled), 'green', 'muted', or an element's colour."""
    label = QLabel(text)
    label.setObjectName("Pill")
    label.setProperty("kind", kind)
    if color:
        c = QColor(color)
        label.setStyleSheet(f"color: {color}; background: rgba({c.red()},{c.green()},{c.blue()},0.16);")
    label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    return label


def _card(title, glyph):
    """A rounded card with a small icon and a title. Returns (card, layout, heading row)."""
    box = QFrame()
    box.setObjectName("HomeCard")
    v = QVBoxLayout(box)
    v.setContentsMargins(14, 10, 14, 10)
    v.setSpacing(7)
    head = QHBoxLayout()
    head.setSpacing(8)
    icon = _label(glyph, "HomeGlyph")
    head.addWidget(icon)
    head.addWidget(_label(title, "HomeTitle"))
    head.addStretch()
    v.addLayout(head)
    return box, v, head


def _portrait(info, size):
    pic = QLabel()
    pic.setFixedSize(size, size)
    pic.setToolTip(info.name)

    def with_element(element_pm):
        def with_icon(pm):
            card = card_pixmap(pm, element_pm, info.rarity, size)
            card.setDevicePixelRatio(2)
            pic.setPixmap(card)

        gamedata.load_pixmap(info.icon, with_icon)

    gamedata.load_pixmap(gamedata.element_icon_url(info.element), with_element)
    return pic


def _short(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 10_000:
        return f"{n / 1000:.1f}K"
    return f"{n:,.0f}"


def _date(timestamp):
    day = datetime.fromtimestamp(timestamp)
    return f"{day:%b} {day.day}"


# ---------- the top DPS of each element ----------
class Showcase(QFrame):
    """One element at a time, every few seconds: the logged character with its highest DPS over their splash
    art: their rank, name and title, the DPS, the run's damage and length, their build and a link to their
    log. An element with nobody logged shows a random character of it, asking you to log one."""

    open_log = Signal(str)
    add_requested = Signal(str)  # element

    def __init__(self):
        super().__init__()
        self.setObjectName("Showcase")
        self.slides = []
        self.current = 0
        self._art = None  # (pixmap, element) shown
        self._old = None  # the one fading out
        self._fade = 1.0
        self._feather_cache = {}  # (art, size) -> its scaled, feathered copy
        self._titles = {}

        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 16)
        v.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.rank = pill("#01", "solid")
        self.kicker = _label("", "ShowKicker")
        self.kicker.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        top.addWidget(self.rank)
        top.addWidget(self.kicker, 1)  # (it takes the row's room: it may be cut short, never widen the card)
        v.addLayout(top)
        v.addSpacing(6)
        self.name = _label("", "ShowName")
        v.addWidget(self.name)
        self.subtitle = _label("", "ShowSub")
        self.subtitle.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        v.addWidget(self.subtitle)
        v.addSpacing(6)
        dps_row = QHBoxLayout()
        dps_row.setSpacing(6)
        self.dps = _label("", "ShowDps")
        self.dps_unit = _label("DPS", "ShowDpsUnit")
        dps_row.addWidget(self.dps, 0, Qt.AlignBottom)
        dps_row.addWidget(self.dps_unit, 0, Qt.AlignBottom)
        dps_row.addStretch()
        v.addLayout(dps_row)
        self.detail = _label("", "ShowSub")
        self.detail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        v.addWidget(self.detail)
        v.addSpacing(6)
        tags = QWidget()
        tags.setMaximumWidth(560)
        tags.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.tags = FlowLayout(tags, spacing=6)  # (they wrap instead of widening the page)
        v.addWidget(tags)
        v.addStretch()
        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.talents = _label("", "ShowSub")
        bottom.addWidget(self.talents)
        self.view = QPushButton("View entry ↗")
        self.view.setObjectName("ShowLink")
        self.view.setCursor(Qt.PointingHandCursor)
        self.view.clicked.connect(self._open)
        bottom.addWidget(self.view)
        bottom.addStretch()
        v.addLayout(bottom)
        v.addSpacing(4)
        # the elements: click one to show its top DPS
        dots = QHBoxLayout()
        dots.setSpacing(4)
        self.dots = []
        for n, element in enumerate(ELEMENT_ORDER):
            dot = QToolButton()
            dot.setObjectName("ShowDot")
            dot.setCursor(Qt.PointingHandCursor)
            dot.setToolTip(gamedata.pretty(element))
            dot.setFixedSize(22, 22)
            dot.setIconSize(QSize(15, 15))
            gamedata.load_pixmap(gamedata.element_icon_url(element), lambda pm, d=dot: pm and d.setIcon(QIcon(pm)))
            dot.clicked.connect(lambda _=False, n=n: self.show_slide(n, restart=True))
            dots.addWidget(dot)
            self.dots.append(dot)
        dots.addStretch()
        v.addLayout(dots)

        self.timer = QTimer(self, interval=ROTATE_MS)
        self.timer.timeout.connect(lambda: self.slides and self.show_slide((self.current + 1) % len(self.slides)))
        self.anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=FADE_MS)
        self.anim.setEasingCurve(QEasingCurve.InOutSine)
        self.anim.valueChanged.connect(self._faded)

    def set_slides(self, slides):
        """slides: one per element (see HomePage.refresh)."""
        keep = self.slides[self.current]["element"] if self.slides else None
        self.slides = slides
        start = next((n for n, s in enumerate(slides) if s["element"] == keep), None)
        if start is None:  # first time: start on an element with someone logged
            start = next((n for n, s in enumerate(slides) if s["record"]), 0)
        self.show_slide(start, animate=keep is None)
        self.timer.start()

    def show_slide(self, n, restart=False, animate=True):
        if not self.slides:
            return
        if restart:
            self.timer.start()
        self.current = n
        slide = self.slides[n]
        element, info, record = slide["element"], slide["info"], slide["record"]
        color = gamedata.ELEMENT_COLORS[element]
        self.kicker.setText(f"TOP {gamedata.pretty(element).upper()} DPS  ·  {slide['mode'].upper()}")
        self.kicker.setStyleSheet(f"color: {color};")
        for i, dot in enumerate(self.dots):
            dot.setProperty("active", "true" if ELEMENT_ORDER[i] == element else "false")
            dot.style().unpolish(dot)
            dot.style().polish(dot)
        clear_layout(self.tags)
        if record:
            self.rank.setText(f"#{slide['rank']:02d}")
            self.rank.setToolTip(f"Rank {slide['rank']} of your logged characters by {slide['mode']} DPS")
            self.rank.show()
            self.name.setText(record["name"])
            self._show_subtitle(info, record)
            self.dps.setText(f"{slide['dps']:,.0f}" if slide["dps"] else "—")
            self.dps_unit.setVisible(bool(slide["dps"]))
            run = slide.get("run") or {}
            parts = []
            if run.get("damage"):
                parts.append(f"{_short(run['damage'])} total damage")
                if slide["dps"]:
                    parts.append(f"{run['damage'] / slide['dps']:.0f}s rotation")
            self.detail.setText("  ·  ".join(parts) if parts else
                                (f"No {slide['mode']} runs logged yet" if not slide["dps"] else ""))
            for text in slide["tags"]:
                self.tags.addWidget(pill(text, "muted"))
            talents = [record.get(f"talent{i}") for i in (1, 2, 3)]
            self.talents.setText("Talents " + "/".join(f"{t:02d}" if t else "–" for t in talents))
            self.talents.show()
            self.view.setText("View entry ↗")
            self.view.setToolTip("Open their character log")
        else:
            self.rank.hide()
            self.name.setText(f"No {gamedata.pretty(element)} DPS yet")
            self.subtitle.setText(f"Showing {info.name}" if info else "")
            self.dps.setText("")
            self.dps_unit.hide()
            self.detail.setText(f"Log a {gamedata.pretty(element)} character to see their DPS here")
            self.talents.hide()
            self.view.setText("Log a character ↗")
            self.view.setToolTip(f"Add a {gamedata.pretty(element)} character on the DPS Log")
        if info is not None:
            gamedata.load_pixmap(info.splash, lambda pm, n=n: self._art_loaded(n, pm, element, animate), fallback=info.icon)

    def _show_subtitle(self, info, record):
        """'Driving Thunder  /  C2 · Electro' (the title is read from the game data, once)."""
        char_id = record["char_id"]
        rest = f"C{record.get('constellation') or 0}  ·  {gamedata.pretty(record['element'])}"
        title = self._titles.get(char_id)
        self.subtitle.setText(f"{title}  /  {rest}" if title else rest)
        if title is None:
            self._titles[char_id] = ""

            def done(found, _error, char_id=char_id):
                self._titles[char_id] = found or ""
                slide = self.slides[self.current] if self.slides else None
                if found and slide and slide["record"] and slide["record"]["char_id"] == char_id:
                    self._show_subtitle(slide["info"], slide["record"])

            gamedata.run_async(lambda: gamedata.clean(gamedata.fetch_character_detail(char_id).info.title), done)

    def _art_loaded(self, n, pm, element, animate):
        if n != self.current or pm is None:
            return
        self._old = self._art if animate else None
        self._art = (pm, element)
        self._fade = 0.0 if animate and self._old else 1.0
        if self._fade < 1:
            self.anim.stop()
            self.anim.start()
        self.update()

    def _faded(self, value):
        self._fade = value
        if value >= 1:
            self._old = None
        self.update()

    def _open(self):
        if not self.slides:
            return
        slide = self.slides[self.current]
        if slide["record"]:
            self.open_log.emit(slide["record"]["char_id"])
        else:
            self.add_requested.emit(slide["element"])

    def _feathered(self, pm):
        """The art scaled for the card (ART_SCALE of its height), every edge fading out to nothing; cached."""
        key = (pm.cacheKey(), self.width(), self.height())
        cached = self._feather_cache.get(key)
        if cached is None:
            ratio = self.devicePixelRatioF()
            target = pm.size().scaled(int(self.width() * 1.2 * ratio), int(self.height() * ART_SCALE * ratio),
                                      Qt.KeepAspectRatio)
            image = pm.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation).toImage().convertToFormat(
                QImage.Format_ARGB32_Premultiplied)
            w, h = image.width(), image.height()
            fx, fy = w * ART_FEATHER, h * ART_FEATHER
            painter = QPainter(image)
            painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            for start, end, area in (((0, 0), (fx, 0), QRectF(0, 0, fx, h)), ((w, 0), (w - fx, 0), QRectF(w - fx, 0, fx, h)),
                                     ((0, 0), (0, fy), QRectF(0, 0, w, fy)), ((0, h), (0, h - fy), QRectF(0, h - fy, w, fy))):
                fade = QLinearGradient(*start, *end)
                fade.setColorAt(0, QColor(0, 0, 0, 0))
                fade.setColorAt(1, QColor(0, 0, 0, 255))
                painter.fillRect(area, fade)
            painter.end()
            cached = QPixmap.fromImage(image)
            cached.setDevicePixelRatio(ratio)
            if len(self._feather_cache) > 16:
                self._feather_cache.clear()
            self._feather_cache[key] = cached
        return cached

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        shape = corner_path(rect, CORNER)  # (the top-right and bottom-left corners rounded, like every container)
        p.setClipPath(shape)
        bg = QLinearGradient(rect.topLeft(), rect.bottomRight())  # (darker than the other cards: the art stands out)
        bg.setColorAt(0, theme.qcolor(0x16, 0x17, 0x1c))
        bg.setColorAt(1, theme.qcolor(0x0e, 0x0f, 0x13))
        p.fillRect(rect, bg)
        for art, opacity, shift in ((self._old, 1 - self._fade, self._fade * 30), (self._art, self._fade, (1 - self._fade) * -30)):
            if art is None or opacity <= 0:
                continue
            pm, element = art
            # the art, bigger than the card is tall, towards the right, its edges fading out; the element's
            # colour glows behind it
            art_pm = self._feathered(pm)
            size = art_pm.deviceIndependentSize()
            x = self.width() - size.width() * 0.88 + shift + self.width() * ART_SHIFT
            y = (self.height() - size.height()) / 2 + self.height() * 0.08
            glow = QColor(gamedata.ELEMENT_COLORS.get(element, "#ffffff"))
            glow.setAlpha(int(55 * opacity))
            halo = QLinearGradient(x, 0, self.width(), 0)
            halo.setColorAt(0, QColor(0, 0, 0, 0))
            halo.setColorAt(0.5, glow)
            halo.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(rect, halo)
            p.setOpacity(opacity)
            p.drawPixmap(QRectF(x, y, size.width(), size.height()), art_pm, QRectF(art_pm.rect()))
            p.setOpacity(1)
        # the text side stays readable
        shade = QLinearGradient(0, 0, self.width() * 0.62, 0)
        shade.setColorAt(0, theme.qcolor(14, 15, 19, 245))
        shade.setColorAt(0.6, theme.qcolor(14, 15, 19, 175))
        shade.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(rect, shade)
        p.setClipping(False)
        # a highlight around the border: the theme's colour, a soft glow inside a bright line
        accent = QColor(theme.accent_hex())
        for width, alpha in ((7, 28), (4, 55), (1.5, 200)):
            accent.setAlpha(alpha)
            p.setPen(QPen(accent, width))
            p.drawPath(corner_path(rect.adjusted(width / 2, width / 2, -width / 2, -width / 2), CORNER))
        p.end()


# ---------- the supports used most ----------
class SupportsPanel(QFrame):
    """The supports in the most logged teams: rank, name, how many of your teams use them, element. As many as
    fit the panel: the list grows and shrinks with the window."""

    open_character = Signal(str)

    def __init__(self):
        super().__init__()
        box, self.v, _ = _card("Support Character Usage", "\u2726")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(box)
        self.sub = _label("Most used in your logged teams", "HomeSub")
        self.v.addWidget(self.sub)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(SUPPORT_GAP)
        self.v.addLayout(self.rows)
        self.v.addStretch()
        self.note = _label("\u2022  A team with the same members and gear counts once", "HomeNote")
        self.v.addWidget(self.note)
        self._counts, self._total, self._character = [], 0, None
        self._shown = None
        # it never asks for room of its own (the row would grow to fit more, and it'd show more…): it fills what the
        # row gives it
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)

    def set_counts(self, counts, total, character):
        """counts: [(char_id, teams)] most first; total: how many different teams are logged."""
        self._counts, self._total, self._character = counts, total, character
        self._shown = None
        self._render()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.size().height() != event.oldSize().height():
            self._render()

    def _fits(self):
        """How many rows fit (at least 1)."""
        margins = self.v.contentsMargins()
        used = margins.top() + margins.bottom() + 4 * self.v.spacing()
        used += 22 + self.sub.sizeHint().height() + self.note.sizeHint().height()  # (title, subtitle, note)
        return max(1, (self.height() - used + SUPPORT_GAP) // (SUPPORT_ROW + SUPPORT_GAP))

    def _render(self):
        if self._character is None:
            return
        listed = [(c, n) for c, n in self._counts if self._character(c)][:min(SUPPORTS_MAX, self._fits())]
        if listed == self._shown:
            return
        self._shown = listed
        clear_layout(self.rows)
        total = self._total
        for rank, (char_id, teams) in enumerate(listed, 1):
            info = self._character(char_id)
            row = QPushButton()
            row.setObjectName("HomeItem")
            row.setCursor(Qt.PointingHandCursor)
            row.setToolTip(f"{info.name}: in {teams} of your {total} logged teams\nClick to open their page")
            h = QHBoxLayout(row)
            h.setContentsMargins(10, 4, 10, 4)
            h.setSpacing(10)
            number = _label(str(rank), "RankCircle")
            number.setFixedSize(22, 22)
            number.setAlignment(Qt.AlignCenter)
            h.addWidget(number)
            h.addWidget(_portrait(info, 30))
            text = QVBoxLayout()
            text.setSpacing(0)
            text.addWidget(_squeezable(_label(info.name, "HomeItemTitle")))
            text.addWidget(_squeezable(_label(f"{teams} of {total} teams  ·  {round(100 * teams / max(1, total))}% usage",
                                              "HomeItemSub")))
            h.addLayout(text, 1)
            element = gamedata.ELEMENT_COLORS.get(info.element, "#9aa0ab")
            h.addWidget(pill(gamedata.pretty(info.element), color=element))
            for w in row.findChildren(QWidget):
                w.setAttribute(Qt.WA_TransparentForMouseEvents)
            row.setFixedHeight(SUPPORT_ROW)
            row.clicked.connect(lambda _=False, c=info.id: self.open_character.emit(c))
            self.rows.addWidget(row)
        if not listed:
            empty = _label("Log runs with teammates to see who you lean on most.", "HomeSub")
            empty.setWordWrap(True)
            self.rows.addWidget(empty)


def support_counts(runs):
    """How many different teams each support is in, and how many different teams there are: runs of the
    same character with the same three teammates on the same weapons and artifacts count once."""
    teams = set()
    for run in runs:
        members = (run.get("team") or [])[1:]
        key = frozenset((str(m.get("char_id")), m.get("weapon_id"), m.get("artifact1"), m.get("artifact2"))
                        for m in members if m.get("char_id"))
        if key:
            teams.add((str(run["char_id"]), key))
    counts = {}
    for _main, members in teams:
        for char_id, *_ in members:
            counts[char_id] = counts.get(char_id, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])), len(teams)


# ---------- the current banners ----------
class BannerCarousel(QFrame):
    """The current wishes, one at a time (the arrows go through them), with how long they have left."""

    open_character = Signal(str)
    open_weapon = Signal(int)

    def __init__(self):
        super().__init__()
        self.index = None
        self.banners = []
        self.current = 0
        box, v, head = _card("Current Banner Rotation", "★")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(box)
        self.timer_pill = pill("Loading…", "muted")
        head.addWidget(self.timer_pill)
        self.picture = QLabel()
        self.picture.setObjectName("BannerArt")
        self.picture.setAlignment(Qt.AlignCenter)
        self.picture.setMinimumHeight(BANNER_MIN_HEIGHT)
        # its size comes from the card, never from the picture in it (which would stop it shrinking or growing)
        self.picture.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.picture.setCursor(Qt.PointingHandCursor)
        self.picture.mousePressEvent = lambda _e: self._open_featured()
        v.addWidget(self.picture, 1)
        info = QHBoxLayout()
        info.setSpacing(8)
        self.kind_pill = pill("CHARACTER", "accent")
        self.phase = _label("", "HomeItemSub")
        info.addWidget(self.kind_pill)
        info.addWidget(self.phase)
        info.addStretch()
        self.prev = QPushButton("‹")
        self.next = QPushButton("›")
        for btn, step in ((self.prev, -1), (self.next, 1)):
            btn.setObjectName("CarouselArrow")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, s=step: self._step(s))
            info.addWidget(btn)
        v.addLayout(info)
        self.title = _label("Loading…", "HomeItemTitle")
        v.addWidget(self.title)
        self._pixmap = None
        tick = QTimer(self, interval=30_000)
        tick.timeout.connect(self._show_timer)
        tick.start()
        # the banners go round on their own, as often as the DPS showcase (the arrows restart the wait)
        self.rotate = QTimer(self, interval=ROTATE_MS)
        self.rotate.timeout.connect(lambda: self._step(1, by_hand=False))
        # the picture is refitted whenever it changes size, also while Home isn't the page on screen
        self.picture.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.picture and event.type() in (QEvent.Resize, QEvent.Show):
            QTimer.singleShot(0, self._fit)
        return False

    def load(self, index):
        self.index = index

        def work():
            banners = gamedata.fetch_banners()
            try:
                art = gamedata.fetch_wish_art()
            except Exception:
                art = []
            return banners, art

        gamedata.run_async(work, self._loaded)

    def _loaded(self, result, error):
        if error or not result:
            self.title.setText("Couldn't load the current banners")
            self.timer_pill.setText("Offline")
            return
        banners, art = result
        self.banners = [b for b in banners if b["end"] > time.time()]
        # pair each wish with its picture: character wishes in order, the weapon wish with Epitome Invocation
        characters = [a for a in art if a["kind"] == "character"]
        weapons = [a for a in art if a["kind"] == "weapon"]
        for banner in self.banners:
            pool = characters if banner["characters"] else weapons
            banner["art"] = pool.pop(0) if pool else None
        self.current = 0
        self._show()
        if len(self.banners) > 1:
            self.rotate.start()

    def _step(self, step, by_hand=True):
        if self.banners:
            self.current = (self.current + step) % len(self.banners)
            self._show()
            if by_hand and len(self.banners) > 1:
                self.rotate.start()  # (a fresh wait after an arrow)

    def _show(self):
        if not self.banners:
            self.title.setText("No banners running right now")
            self.picture.clear()
            return
        banner = self.banners[self.current]
        art = banner.get("art")
        featured = self._featured(banner)
        name = art["title"] if art else banner["name"]
        who = featured.name if featured else ""
        self.title.setText(f"{name}  ·  {who}" if who else name)
        self.kind_pill.setText("CHARACTER" if banner["characters"] else "WEAPON")
        start = banner.get("start")
        self.phase.setText(f"{_date(start)} – {_date(banner['end'])}  ·  {self.current + 1} / {len(self.banners)}"
                           if start else f"{self.current + 1} / {len(self.banners)}")
        self._pixmap = None
        self.picture.clear()
        self.picture.setToolTip(f"{who}\nClick to open their page" if who else "")
        url = art["image"] if art else (featured.icon if featured else None)
        if url:
            n = self.current
            gamedata.load_pixmap(url, lambda pm, n=n: self._art_loaded(n, pm))
        self._show_timer()
        self.prev.setEnabled(len(self.banners) > 1)
        self.next.setEnabled(len(self.banners) > 1)

    def _featured(self, banner):
        if not self.index:
            return None
        for item_id, rarity in banner["characters"]:
            if rarity == 5:
                return self.index.characters.get(item_id) or self.index.characters.get(str(item_id))
        for item_id, rarity in banner["weapons"]:
            if rarity == 5:
                return self.index.weapons.get(item_id) or self.index.weapons.get(int(item_id))
        return None

    def _open_featured(self):
        if not self.banners:
            return
        banner = self.banners[self.current]
        featured = self._featured(banner)
        if featured is None:
            return
        if banner["characters"]:
            self.open_character.emit(featured.id)
        else:
            self.open_weapon.emit(featured.id)

    def _art_loaded(self, n, pm):
        if n == self.current and pm is not None:
            self._pixmap = pm
            self._fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _fit(self):
        """The banner picture at the card's size, with rounded corners."""
        if self._pixmap is None:
            return
        size = self.picture.size()
        ratio = self.devicePixelRatioF()
        scaled = self._pixmap.scaled(size * ratio, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        rounded = QPixmap(scaled.size())
        rounded.fill(Qt.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setClipPath(corner_path(QRectF(rounded.rect()), 8 * ratio))  # (the same corners as the containers)
        painter.drawPixmap(0, 0, scaled)
        painter.end()
        rounded.setDevicePixelRatio(ratio)
        self.picture.setPixmap(rounded)

    def _show_timer(self):
        if self.banners:
            end = self.banners[self.current]["end"]
            self.timer_pill.setText(f"Ends in {servers.countdown(datetime.fromtimestamp(end, timezone.utc))}")


# ---------- the top of the To Do List ----------
class TodoPanel(QFrame):
    """The goals at the top of the To Do List (Home's order): as many as fit the card."""

    open_todo = Signal()

    def __init__(self):
        super().__init__()
        box, self.v, head = _card("To-Do", "\u2630")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(box)
        more = QPushButton("Open list \u203a")
        more.setObjectName("PillButton")
        more.setCursor(Qt.PointingHandCursor)
        more.setToolTip("Plan levels and talents, and see the materials")
        more.clicked.connect(self.open_todo)
        head.addWidget(more)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(TODO_GAP)
        self.v.addLayout(self.rows)
        self.v.addStretch()
        self._tasks, self._weekday, self._shown = [], 0, None
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)  # (it fills the room it's given)

    def set_tasks(self, tasks, weekday):
        """tasks: [(task, info, goal text, detail)] in Home's order."""
        self._tasks, self._weekday, self._shown = tasks, weekday, None
        self._render()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.size().height() != event.oldSize().height():
            self._render()

    def _fits(self):
        margins = self.v.contentsMargins()
        room = self.height() - margins.top() - margins.bottom() - 30 - self.v.spacing()  # (its heading)
        return max(1, (room + TODO_GAP) // (TODO_ROW + TODO_GAP))

    def _render(self):
        tasks = self._tasks[:self._fits()]
        key = [t[0]["id"] for t in tasks]
        if key == self._shown:
            return
        self._shown = key
        clear_layout(self.rows)
        if not tasks:
            empty = _label("Nothing planned. Add characters or weapons to the To Do List.", "HomeSub")
            empty.setWordWrap(True)
            self.rows.addWidget(empty)
            return
        for task, info, goal, detail in tasks:
            n = self._tasks.index((task, info, goal, detail)) + 1
            row = QFrame()
            row.setObjectName("HomeItem")
            row.setFixedHeight(TODO_ROW)
            h = QHBoxLayout(row)
            h.setContentsMargins(10, 4, 10, 4)
            h.setSpacing(10)
            if getattr(info, "element", None):
                h.addWidget(_portrait(info, 34))
            else:
                pic = QLabel()
                pic.setFixedSize(34, 34)
                if info.icon:  # (a weapon, or a note's picture)
                    gamedata.load_pixmap(info.icon, lambda pm, pic=pic, info=info: pm and pic.setPixmap(
                        _small_card(pm, info.rarity)))
                h.addWidget(pic)
            text = QVBoxLayout()
            text.setSpacing(0)
            text.addWidget(_squeezable(_label(info.name, "HomeItemTitle")))
            text.addWidget(_squeezable(_label(goal, "HomeItemSub")))
            h.addLayout(text, 1)
            days = (detail or {}).get("days") or {}
            if any(self._weekday in d for d in days.values()):
                h.addWidget(pill("Domain open", "green"), 0, Qt.AlignVCenter)
            else:
                h.addWidget(pill(f"#{n}", "accent"), 0, Qt.AlignVCenter)
            self.rows.addWidget(row)


def _small_card(pm, rarity):
    card = card_pixmap(pm, None, rarity, 34)
    card.setDevicePixelRatio(2)
    return card


# ---------- End Game timers ----------
class TimersPanel(QFrame):
    open_mode = Signal(str)
    server_picked = Signal(str)

    def __init__(self, server):
        super().__init__()
        box, v, head = _card("Content Timers", "◷")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(box)
        self.server_box = QComboBox()
        self.server_box.setObjectName("SmallCombo")
        self.server_box.addItems([name for name, _ in servers.SERVERS])
        self.server_box.setCurrentText(server)
        self.server_box.setToolTip("The timers follow this server's resets")
        self.server_box.currentTextChanged.connect(self.server_picked)
        head.addWidget(self.server_box)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(6)
        v.addLayout(self.rows)
        v.addStretch()
        self._timers = []
        tick = QTimer(self, interval=30_000)
        tick.timeout.connect(self._render)
        tick.start()
        self._render()

    def set_server(self, server):
        self.server_box.blockSignals(True)
        self.server_box.setCurrentText(server)
        self.server_box.blockSignals(False)

    def set_timers(self, timers):
        """[(mode key, mode name, what's live, ends at (aware datetime) or None)]."""
        self._timers = timers
        self._render()

    def _render(self):
        clear_layout(self.rows)
        if not self._timers:
            self.rows.addWidget(_label("Loading…", "HomeSub"))
            return
        for key, mode, title, end in self._timers:
            row = QPushButton()
            row.setObjectName("HomeItem")
            row.setCursor(Qt.PointingHandCursor)
            row.setToolTip(f"Open {mode} on the End Game page")
            h = QHBoxLayout(row)
            h.setContentsMargins(10, 6, 10, 6)
            h.setSpacing(10)
            icon = RemoteIcon(30)
            icon.setObjectName("ModeIcon")
            icon.set_url(MODE_ICONS.get(key))
            h.addWidget(icon)
            text = QVBoxLayout()
            text.setSpacing(0)
            text.addWidget(_squeezable(_label(mode, "HomeItemTitle")))
            sub = _label(title, "HomeItemSub")
            sub.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            text.addWidget(sub)
            h.addLayout(text, 1)
            right = QVBoxLayout()
            right.setSpacing(2)
            right.addWidget(_label(servers.countdown(end) if end else "—", "TimerValue"), 0, Qt.AlignRight)
            right.addWidget(pill("LIVE" if end else "OFF", "green" if end else "muted"), 0, Qt.AlignRight)
            h.addLayout(right)
            for w in row.findChildren(QWidget):
                w.setAttribute(Qt.WA_TransparentForMouseEvents)
            row.setMinimumHeight(50)
            row.clicked.connect(lambda _=False, k=key: self.open_mode.emit(k))
            self.rows.addWidget(row)


# ---------- the page ----------
class HomePage(QWidget):
    message = Signal(str)
    open_log = Signal(str)
    open_character = Signal(str)  # its page on Characters
    open_weapon = Signal(int)
    add_requested = Signal(str)  # log a character of this element (on the DPS Log)
    open_todo = Signal()
    open_endgame = Signal(str)  # mode
    server_picked = Signal(str)

    def __init__(self, store, server):
        super().__init__()
        self.store = store
        self.index = None
        self.server = server

        self.showcase = Showcase()
        self.showcase.open_log.connect(self.open_log)
        self.showcase.add_requested.connect(self.add_requested)
        self.supports = SupportsPanel()
        self.supports.open_character.connect(self.open_character)
        self.banners = BannerCarousel()
        self.banners.open_character.connect(self.open_character)
        self.banners.open_weapon.connect(self.open_weapon)
        self.todo = TodoPanel()
        self.todo.open_todo.connect(self.open_todo)
        self.timers = TimersPanel(server)
        self.timers.open_mode.connect(self.open_endgame)
        self.timers.server_picked.connect(self.server_picked)

        # the showcase over two columns with the supports beside it; the banners, To-Do and timers below,
        # three equal columns
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(18, 12, 18, 12)
        grid.setSpacing(12)
        grid.addWidget(self.showcase, 0, 0, 1, 2)
        grid.addWidget(self.supports, 0, 2)
        grid.addWidget(self.banners, 1, 0)
        grid.addWidget(self.todo, 1, 1)
        grid.addWidget(self.timers, 1, 2)
        for c in range(3):
            grid.setColumnStretch(c, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        self.showcase.setMinimumHeight(SHOWCASE_MIN_HEIGHT)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    def set_index(self, index):
        first = self.index is None
        self.index = index
        if first:
            self.banners.load(index)
        else:
            self.banners.index = index
        self.refresh()

    def _character(self, char_id):
        if not self.index:
            return None
        info = self.index.characters.get(char_id) or self.index.characters.get(str(char_id))
        if info is None and str(char_id).isdigit():
            info = self.index.characters.get(int(char_id))
        return info

    def _tags(self, record, run):
        """The showcase's tags: the run's team name, the weapon and refinement, the artifact set(s)."""
        tags = []
        if run and run.get("team_name"):
            tags.append(run["team_name"])
        weapon = self.index.weapons.get(record.get("weapon_id")) if record.get("weapon_id") else None
        if weapon:
            tags.append(f"{weapon.name}  ·  R{record.get('refinement') or 1}")
        sets = [self.index.artifacts.get(record.get(k)) for k in ("artifact1", "artifact2") if record.get(k)]
        sets = [a.name for a in sets if a]
        if sets:
            tags.append(" + ".join(sets) if len(sets) > 1 else f"4p {sets[0]}")
        return tags

    def refresh(self):
        """Re-read the logged characters and runs (after the log changes)."""
        if not self.index:
            return
        mode = self.store.get_setting("home_dps_mode", "abyss")
        records = self.store.characters()
        dps_of = {r["char_id"]: self.store.best_dps(r["char_id"], mode) or 0 for r in records}
        ranking = sorted((cid for cid in dps_of if dps_of[cid]), key=lambda cid: -dps_of[cid])
        slides = []
        for element in ELEMENT_ORDER:
            mine = [r for r in records if r["element"] == element]
            best = max(mine, key=lambda r: dps_of[r["char_id"]], default=None)
            if best is not None:
                run_id = self.store.best_run_id(best["char_id"], mode)
                run = self.store.run(run_id) if run_id else None
                rank = ranking.index(best["char_id"]) + 1 if best["char_id"] in ranking else len(ranking) + 1
                slides.append({"element": element, "info": self._character(best["char_id"]), "record": best,
                               "dps": dps_of[best["char_id"]], "mode": MODE_NAMES.get(mode, mode), "run": run,
                               "rank": rank, "tags": self._tags(best, run)})
            else:
                pool = [c for c in self.index.characters.values()
                        if c.element == element and not c.name.startswith(("Aether", "Lumine"))]
                slides.append({"element": element, "info": random.choice(pool) if pool else None, "record": None,
                               "dps": 0, "mode": MODE_NAMES.get(mode, mode), "run": None, "rank": 0, "tags": []})
        self.showcase.set_slides(slides)
        counts, total = support_counts(self.store.all_runs())
        self.supports.set_counts(counts, total, self._character)

    def set_tasks(self, tasks, weekday):
        self.todo.set_tasks(tasks, weekday)

    def set_timers(self, timers):
        self.timers.set_timers(timers)

    def set_server(self, server):
        self.server = server
        self.timers.set_server(server)
