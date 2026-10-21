"""Home page: character art behind a character card (top left), the current banners (top right)
and a column per element along the bottom."""

import time

from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, QSequentialAnimationGroup, QVariantAnimation, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QImage, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import math
import random

import gamedata
import theme
from dialogs import BuildDialog, CharacterSearchDialog, confirm
from widgets import ACCENT, RemoteIcon, card_pixmap, clear_layout, filter_button

HOVER_CLEAR_DELAY_MS = 90  # avoids flicker when the mouse moves between rows
ADD_FULL_WIDTH = 150  # narrower element columns say just '+ Add'
BOARD_ORDER = ["PYRO", "HYDRO", "DENDRO", "ELECTRO", "ANEMO", "CRYO", "GEO"]
PAGE_SCROLL_MS = 380
# the art: in from the left (a page width away) to the middle, then a slow drift right; out to the right
ART_ENTER_FROM = 1.1  # page widths
ART_ENTER_MS = 520
ART_DRIFT = 0.10  # page widths past the middle: 20% of the way from the left edge to the middle
ART_DRIFT_MS = 20000
ART_LEAVE_TO = 1.1
ART_LEAVE_MS = 420
GLOW_STRENGTH = 0.35  # the element glow behind the art once it's in the middle (0-1)
GLOW_MS = 900
GLOW_BREATH_MS = 4200  # one slow breath: dimmer and back
GLOW_BREATH_DEPTH = 0.55  # how far it dims at the bottom of a breath (0-1)
BLUR_RADIUS = 60  # the banners page's (Gaussian) blur, in pixels of the art at the page's size  # scrolling between the two pages
TEAM_CARD = 100  # teammate portraits on the card: three of them fill its width
TEAM_AREA = TEAM_CARD + (TEAM_CARD - 4) // 2 + 30  # portrait, weapon/artifact icons and name
DPS_MODES = [("abyss", "Spiral Abyss"), ("fearless", "Stygian Fearless"), ("dire", "Stygian Dire")]


def _field_label(text):
    label = QLabel(text)
    label.setObjectName("FieldLabel")
    return label


# ---------- bottom: the element board ----------
class CharRow(QFrame):
    """A logged character in an element column: portrait, name and DPS."""

    hovered = Signal(object)  # char_id, or None when the mouse leaves
    picked = Signal(str)
    open_log = Signal(str)  # clicked the name or portrait
    remove_requested = Signal(str)

    def __init__(self, record, icon_url, selected):
        super().__init__()
        self.char_id = record["char_id"]
        self.setObjectName("CharRow")
        self.setProperty("selected", "true" if selected else "false")
        self.setCursor(Qt.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 6, 3)
        layout.setSpacing(6)
        icon = RemoteIcon(32)
        icon.set_url(icon_url)
        text = QVBoxLayout()
        text.setSpacing(0)
        self._full_name = record["name"]
        name = QLabel(self._full_name)
        name.setObjectName("RowName")
        name.setMinimumWidth(10)
        name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)  # elided to the column's width
        dps = QLabel(f"{record['best_dps']:,.0f} DPS" if record["best_dps"] else "No Data")
        dps.setObjectName("RowDps")
        for w in (icon, name, dps):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        text.addWidget(name)
        text.addWidget(dps)
        layout.addWidget(icon)
        layout.addLayout(text, 1)
        self._icon, self._name = icon, name
        self.setToolTip(f"{self._full_name}\nClick the name or portrait to open the character log")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        metrics = self._name.fontMetrics()
        self._name.setText(metrics.elidedText(self._full_name, Qt.ElideRight, max(10, self._name.width())))

    def _on_name_or_portrait(self, pos):
        text = self._name.geometry()
        text.setWidth(self._name.fontMetrics().horizontalAdvance(self._name.text()) + 6)
        return self._icon.geometry().contains(pos) or text.contains(pos)

    def enterEvent(self, event):
        self.hovered.emit(self.char_id)

    def leaveEvent(self, event):
        self.hovered.emit(None)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.picked.emit(self.char_id)
            if self._on_name_or_portrait(event.position().toPoint()):
                self.open_log.emit(self.char_id)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction("Remove from Record Book", lambda: self.remove_requested.emit(self.char_id))
        menu.exec(event.globalPos())


class ElementBoard(QFrame):
    """One column per element along the bottom of the page: its symbol, the characters you've logged
    (highest DPS first) and "+ Add Character"."""

    MIN_ROWS, MAX_ROWS = 1, 5  # characters a column shows before it scrolls (with the window's height)

    hovered = Signal(object)
    picked = Signal(str)
    open_log = Signal(str)
    add_requested = Signal(str)  # element
    remove_requested = Signal(str)
    mode_changed = Signal(str)  # 'abyss' / 'fearless' / 'dire'
    fitted = Signal()  # its size limits changed (the page re-checks what fits)

    def __init__(self, mode="abyss"):
        super().__init__()
        self.setObjectName("ElementBoard")
        self.records = []
        self.index = None
        self.selected_id = None
        self.mode = mode

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        columns = QHBoxLayout()
        columns.setSpacing(0)
        self.lists = {}
        self.scrolls = {}
        for n, element in enumerate(BOARD_ORDER):
            column = QFrame()
            column.setObjectName("ElementColumn")
            column.setProperty("alt", "true" if n % 2 else "false")
            col = QVBoxLayout(column)
            col.setContentsMargins(6, 10, 6, 8)
            col.setSpacing(8)
            symbol = RemoteIcon(40)
            symbol.set_url(gamedata.element_icon_url(element))
            symbol.setToolTip(gamedata.pretty(element))
            col.addWidget(symbol, 0, Qt.AlignHCenter)
            name = QLabel(gamedata.pretty(element))
            name.setObjectName("ColumnName")
            name.setAlignment(Qt.AlignHCenter)
            name.setStyleSheet(f"color: {gamedata.ELEMENT_COLORS[element]};")
            col.addWidget(name)
            host = QWidget()
            rows = QVBoxLayout(host)
            rows.setContentsMargins(0, 0, 0, 0)
            rows.setSpacing(3)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # no bar shown; the mouse wheel still scrolls
            scroll.setWidget(host)
            col.addWidget(scroll, 1)
            self._column = column
            self.lists[element] = rows
            self.scrolls[element] = scroll
            columns.addWidget(column, 1)
        layout.addLayout(columns)

    def _add_text(self):
        """'+ Add Character', or just '+ Add' when the columns are narrow (the smallest window)."""
        column = self._column.width() if hasattr(self, "_column") else 0
        return "+  Add" if 0 < column < ADD_FULL_WIDTH else "+  Add Character"

    def resizeEvent(self, event):
        super().resizeEvent(event)
        text = self._add_text()
        for add in self.findChildren(QPushButton, "AddRow"):
            add.setText(text)

    def set_mode(self, mode):
        self.mode = mode
        self.mode_changed.emit(mode)

    def mark_selected(self, char_id):
        for row in self.findChildren(CharRow):
            row.setProperty("selected", "true" if row.char_id == char_id else "false")
            row.style().unpolish(row)
            row.style().polish(row)

    def set_roster(self, records, selected_id):
        self.records = records
        self.selected_id = selected_id
        self.rebuild()

    def open_element(self, element):
        """Highlight the selected character and scroll their column to them."""
        self.mark_selected(self.selected_id)
        for row in self.findChildren(CharRow):
            if row.char_id == self.selected_id and element in self.scrolls:
                self.scrolls[element].ensureWidgetVisible(row, 0, 0)

    def rebuild(self):
        self.hovered.emit(None)  # rows being replaced won't send their own leave event
        row_height = add_height = 0
        for element, rows in self.lists.items():
            clear_layout(rows)
            # highest DPS (in the chosen mode) first; characters with no data after them, by name
            mine = sorted((r for r in self.records if r["element"] == element), key=lambda r: r["name"])
            mine.sort(key=lambda r: r["best_dps"] or 0, reverse=True)
            for record in mine:
                info = self.index.characters.get(record["char_id"]) if self.index else None
                row = CharRow(record, info.icon if info else None, record["char_id"] == self.selected_id)
                row.hovered.connect(self.hovered)
                row.picked.connect(self.picked)
                row.open_log.connect(self.open_log)
                row.remove_requested.connect(self.remove_requested)
                rows.addWidget(row)
                row_height = row.sizeHint().height()
            add = QPushButton(self._add_text())
            add.setObjectName("AddRow")
            add.setCursor(Qt.PointingHandCursor)
            add.setMinimumHeight(30)
            add.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)  # the column sets its width, not the label
            add.setToolTip(f"Add a {gamedata.pretty(element)} character to your Record Book")
            add.clicked.connect(lambda _=False, e=element: self.add_requested.emit(e))
            rows.addWidget(add)
            rows.addStretch()
            add_height = add.sizeHint().height()
        QTimer.singleShot(0, self._fit)  # measured once the new rows have their styles

    def showEvent(self, event):
        super().showEvent(event)
        self._fit()

    def _fit(self):
        """Every column the same height, room for MIN_ROWS to MAX_ROWS characters and the add button,
        and the board no taller than that, so the art shows above it in a tall window."""
        rows = self.findChildren(CharRow)
        adds = self.findChildren(QPushButton, "AddRow")
        if not adds:
            return
        row_height = max((r.sizeHint().height() for r in rows), default=44)
        add_height = adds[0].sizeHint().height()
        spacing = 3
        rows_high = lambda n: row_height * n + (add_height + spacing * n)
        for scroll in self.scrolls.values():
            scroll.setMinimumHeight(rows_high(self.MIN_ROWS))
            scroll.setMaximumHeight(rows_high(self.MAX_ROWS))
        column = self._column.layout()
        margins = column.contentsMargins()
        column_chrome = margins.top() + margins.bottom() + sum(
            column.itemAt(i).sizeHint().height() + column.spacing() for i in range(2))  # symbol and name
        outer = self.layout()
        self.setMaximumHeight(outer.contentsMargins().top() + outer.contentsMargins().bottom()
                              + column_chrome + rows_high(self.MAX_ROWS) + 2)
        self.fitted.emit()


# ---------- current wishes ----------
def _time_left(end):
    left = max(0, int(end - time.time()))
    days, rest = divmod(left, 86400)
    hours, rest = divmod(rest, 3600)
    if days:
        return f"{days}d {hours}h left"
    return f"{hours}h {rest // 60}m left"


class BannerPanel(QFrame):
    """The character and weapon event wishes running right now: featured 5★ large, 4★ small.
    Clicking a character opens their page."""

    open_character = Signal(str)
    open_weapon = Signal(int)

    def __init__(self):
        super().__init__()
        self.setObjectName("Selector")
        self.index = None
        self.banners = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 14)
        outer.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(_field_label("CURRENT BANNERS"))
        head.addStretch()
        self.status = QLabel("Loading…")
        self.status.setStyleSheet("color: rgba(255,255,255,0.55); font-size: 9pt;")
        head.addWidget(self.status)
        outer.addLayout(head)
        # the banners side by side, wrapping onto more lines when the window is too narrow for one
        self.row = QGridLayout()
        self.row.setHorizontalSpacing(22)
        self.row.setVerticalSpacing(10)
        self._boxes = []
        self._columns = 0
        outer.addLayout(self.row)
        outer.addStretch()  # keep the banners under their heading when the panel is taller
        # keep the countdowns current
        self._timer = QTimer(self, interval=60_000)
        self._timer.timeout.connect(self._render)
        self._timer.start()

    def load(self, index):
        self.index = index
        gamedata.run_async(gamedata.fetch_banners, self._loaded)

    def _loaded(self, banners, error):
        if error:
            self.status.setText("Couldn't load the current banners")
            return
        self.banners = banners
        self._render()

    def _render(self):
        if self.banners is None or not self.index:
            return
        banners = [b for b in self.banners if b["end"] > time.time()]
        clear_layout(self.row)
        self.status.setText("" if banners else "No banners running right now")
        self._boxes = [self._banner(banner) for banner in banners]
        widest = max((box.sizeHint().width() for box in self._boxes), default=0)
        margins = self.layout().contentsMargins()
        self.setMinimumWidth(widest + margins.left() + margins.right())  # one banner a line at the narrowest
        self._columns = 0
        self._arrange()

    def _arrange(self):
        if not self._boxes:
            return
        margins = self.layout().contentsMargins()
        room = self.width() - margins.left() - margins.right()
        spacing = self.row.horizontalSpacing()
        columns, used = 0, -spacing
        for box in self._boxes:  # as many on a line as fit
            used += spacing + box.sizeHint().width()
            if used > room and columns:
                break
            columns += 1
        if columns == self._columns:
            return
        self._columns = columns
        for box in self._boxes:
            self.row.removeWidget(box)
        for n, box in enumerate(self._boxes):
            self.row.addWidget(box, n // columns, n % columns, Qt.AlignLeft | Qt.AlignTop)
        for c in range(len(self._boxes) + 1):
            self.row.setColumnStretch(c, 1 if c == columns else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange()

    def _banner(self, banner):
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        title = QLabel(f"<b>{banner['name']}</b>  <span style='color: rgba(255,255,255,0.55)'>· {_time_left(banner['end'])}</span>")
        title.setStyleSheet("font-size: 9.5pt;")
        v.addWidget(title)
        cards = QHBoxLayout()
        cards.setSpacing(4)
        entries = [("c", cid, r) for cid, r in banner["characters"]] + [("w", wid, r) for wid, r in banner["weapons"]]
        entries.sort(key=lambda e: -e[2])  # featured 5★ first
        for kind, item_id, rarity in entries:
            cards.addWidget(self._card(kind, item_id, rarity), 0, Qt.AlignBottom)
        cards.addStretch()
        v.addLayout(cards)
        return box

    def _card(self, kind, item_id, rarity):
        size = 64 if rarity == 5 else 44
        btn = QToolButton()
        btn.setObjectName("BannerCard")
        btn.setFixedSize(size, size)
        btn.setIconSize(QSize(size, size))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("#BannerCard { border: none; background: transparent; padding: 0; }")
        if kind == "c":
            info = self.index.characters.get(item_id) or self.index.characters.get(str(item_id))
            if info is None:
                btn.hide()
                return btn
            btn.setToolTip(f"{info.name}  {'★' * info.rarity}\nClick to open their page")
            btn.clicked.connect(lambda: self.open_character.emit(info.id))

            def with_element(element_pm):
                gamedata.load_pixmap(
                    info.icon, lambda pm: btn.setIcon(QIcon(card_pixmap(pm, element_pm, info.rarity, size)))
                )

            gamedata.load_pixmap(gamedata.element_icon_url(info.element), with_element)
        else:
            info = self.index.weapons.get(item_id) or self.index.weapons.get(str(item_id))
            if info is None:
                btn.hide()
                return btn
            btn.setToolTip(f"{info.name}  {'★' * info.rarity}\nClick to open its page")
            btn.clicked.connect(lambda: self.open_weapon.emit(info.id))
            gamedata.load_pixmap(info.icon, lambda pm: btn.setIcon(QIcon(card_pixmap(pm, None, info.rarity, size))))
        return btn


def _draw_at(painter, x, y, pixmap):
    """Draw a pixmap at a fractional position, filtered smoothly (not snapped to the nearest pixel)."""
    size = pixmap.deviceIndependentSize()
    painter.drawPixmap(QRectF(x, y, size.width(), size.height()), pixmap, QRectF(pixmap.rect()))


def _gaussian_blur(pixmap, radius):
    """A heavy Gaussian blur of a picture (worked out at a quarter size, so it's quick, then scaled back up:
    a blur that wide has no fine detail to lose). Returns (blurred, margin): the blurred picture is bigger
    by margin on every side, where the blur fades out; draw it that far up and to the left."""
    from PySide6.QtWidgets import QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene

    step = 4
    small = pixmap.scaled(max(1, pixmap.width() // step), max(1, pixmap.height() // step),
                          Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    pad = radius // step * 2  # room around it, so the edges fade out instead of being cut
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(small)
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(radius / step)
    effect.setBlurHints(QGraphicsBlurEffect.QualityHint)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    out = QImage(small.width() + 2 * pad, small.height() + 2 * pad, QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    painter = QPainter(out)
    scene.render(painter, QRectF(0, 0, out.width(), out.height()),
                 QRectF(-pad, -pad, out.width(), out.height()))
    painter.end()
    # feather the edges: splash art with a solid background would otherwise show its rectangle
    feather = max(4, min(out.width(), out.height()) // 4)
    painter = QPainter(out)
    painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    w_, h_ = out.width(), out.height()
    for start, end, rect in (((0, 0), (feather, 0), QRectF(0, 0, feather, h_)),
                             ((w_, 0), (w_ - feather, 0), QRectF(w_ - feather, 0, feather, h_)),
                             ((0, 0), (0, feather), QRectF(0, 0, w_, feather)),
                             ((0, h_), (0, h_ - feather), QRectF(0, h_ - feather, w_, feather))):
        fade = QLinearGradient(*start, *end)
        fade.setColorAt(0, QColor(0, 0, 0, 0))
        fade.setColorAt(1, QColor(0, 0, 0, 255))
        painter.fillRect(rect, fade)
    painter.end()
    big = QPixmap.fromImage(out).scaled((small.width() + 2 * pad) * step, (small.height() + 2 * pad) * step,
                                        Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return big, pad * step


# ---------- links to other sites ----------
LINKS = [
    ("Keqing Mains (KQM)", "https://keqingmains.com", "Theorycrafting guides and calcs"),
    ("Project Amber", "https://gi.yatta.moe", "Game data: characters, weapons, artifacts"),
    ("Lunaris", "https://lunaris.moe", "Upcoming and unreleased content"),
    ("stygian.moe", "https://stygian.moe", "Stygian Onslaught"),
]


class LinksPanel(QFrame):
    """Buttons that open other Genshin sites in the browser."""

    def __init__(self):
        super().__init__()
        self.setObjectName("Selector")
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(8)
        v.addWidget(_field_label("LINKS"))
        for name, url, tip in LINKS:
            btn = QPushButton(f"{name}  \u2197")
            btn.setObjectName("LinkBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(f"{tip}\n{url}")
            btn.clicked.connect(lambda _=False, url=url: QDesktopServices.openUrl(QUrl(url)))
            v.addWidget(btn)
        v.addStretch()


# ---------- the page ----------
class HomePage(QWidget):
    visited = Signal(str)
    message = Signal(str)
    roster_changed = Signal()
    removed = Signal(str)
    open_log = Signal(str)  # the character log page for a logged character

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.index = None
        self.selected_id = None
        self.hover_id = None
        self.draft = None  # dict while adding a character, shaped like a stored record
        self._titles = {}
        self._art = None
        self._art_url = None
        self._art_element = None
        self._layers = []  # the art on screen: the current one, and any sliding out
        self._art_cache = {}
        self._hover_timer = QTimer(self, singleShot=True, interval=HOVER_CLEAR_DELAY_MS)
        self._hover_timer.timeout.connect(lambda: self._set_hover(None))

        self.card = self._build_card()
        self.selector = ElementBoard(store.get_setting("home_dps_mode", "abyss"))
        self.selector.fitted.connect(lambda: hasattr(self, "page_scroll") and self._fit_pages())
        self.selector.mode_changed.connect(self._dps_mode_changed)
        self.selector.hovered.connect(self._on_hover)
        self.selector.picked.connect(self._on_pick)
        self.selector.open_log.connect(self._open_log_for)
        self.selector.add_requested.connect(self._on_add)
        self.selector.remove_requested.connect(self._on_remove)

        self.banners = BannerPanel()

        # Two pages, each the height of the window: first the character card (top left) over the art with
        # the element board along the bottom; scrolling down moves to the second, with the current banners
        # and links to other sites. (A page scrolls on its own if the window is too short for it.)
        self.first_page = QWidget()
        v = QVBoxLayout(self.first_page)
        v.setContentsMargins(32, 20, 32, 8)
        v.setSpacing(20)
        row = QHBoxLayout()
        row.setSpacing(32)
        row.addWidget(self.card, 0, Qt.AlignTop)
        row.addStretch()
        # which DPS the card and the columns show: one button that cycles through the modes
        self.mode_button = QPushButton()
        self.mode_button.setObjectName("ModeCycle")
        self.mode_button.setCursor(Qt.PointingHandCursor)
        self.mode_button.setToolTip("toggle DPS numbers to the run")
        self.mode_button.clicked.connect(self._cycle_mode)
        row.addWidget(self.mode_button, 0, Qt.AlignTop)
        self._show_mode()
        v.addLayout(row)
        # the board grows first (up to MAX_ROWS characters a column), what's left shows the art above it
        v.addStretch(1)
        self.selector.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        v.addWidget(self.selector, 20)
        down = QPushButton("Banners && links  \u25be")  # && shows one "&" (a single one marks a shortcut key)
        down.setObjectName("PageHint")
        down.setCursor(Qt.PointingHandCursor)
        down.setToolTip("Scroll down for the current banners and links")
        down.clicked.connect(lambda: self.go_to_page(1))
        v.addWidget(down, 0, Qt.AlignHCenter)
        self.page_hint = down

        self.second_page = QWidget()
        v2 = QVBoxLayout(self.second_page)
        v2.setContentsMargins(32, 8, 32, 20)
        v2.setSpacing(20)
        up = QPushButton("\u25b4  Back")
        up.setObjectName("PageHint")
        up.setCursor(Qt.PointingHandCursor)
        up.setToolTip("Back to your characters")
        up.clicked.connect(lambda: self.go_to_page(0))
        v2.addWidget(up, 0, Qt.AlignHCenter)
        bottom = QHBoxLayout()
        bottom.setSpacing(20)
        self.banners.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)  # wraps instead of widening the page
        bottom.addWidget(self.banners, 1, Qt.AlignTop)
        bottom.addWidget(LinksPanel(), 0, Qt.AlignTop)
        v2.addLayout(bottom)
        v2.addStretch()

        content = QWidget()
        pages = QVBoxLayout(content)
        pages.setContentsMargins(0, 0, 0, 0)
        pages.setSpacing(0)
        for page in (content, self.first_page, self.second_page):
            page.setAttribute(Qt.WA_TranslucentBackground)
        pages.addWidget(self.first_page)
        pages.addWidget(self.second_page)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # pages, not a scrollbar
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        scroll.viewport().setAutoFillBackground(False)
        scroll.setWidget(content)
        scroll.viewport().installEventFilter(self)
        scroll.setProperty("paged", True)
        scroll.verticalScrollBar().valueChanged.connect(lambda _: self.update())  # the art blurs as you scroll down
        self.page_scroll = scroll
        self._page = 0
        self._page_anim = QPropertyAnimation(scroll.verticalScrollBar(), b"value", self)
        self._page_anim.setDuration(PAGE_SCROLL_MS)
        self._page_anim.setEasingCurve(QEasingCurve.OutCubic)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

        self.reload_roster()
        self.refresh_card()

    # ----- the two pages -----
    def _fit_pages(self):
        """Both pages the height of the window. The card drops to just the name when the first page
        would be too cramped for all of it."""
        height = self.page_scroll.viewport().height()
        margins = self.first_page.layout().contentsMargins()
        spacing = self.first_page.layout().spacing()
        hint = self.page_hint.sizeHint().height()
        board = self.selector.minimumSizeHint().height()
        room = height - margins.top() - margins.bottom() - 2 * spacing - hint - board
        self._set_compact(self._card_height(False) > room)
        for page in (self.first_page, self.second_page):
            page.setFixedHeight(height)
        if self._page == 1 and self._page_anim.state() != QPropertyAnimation.Running:
            QTimer.singleShot(0, lambda: self.page_scroll.verticalScrollBar().setValue(self.first_page.height()))

    def go_to_page(self, page):
        self._page = page
        bar = self.page_scroll.verticalScrollBar()
        target = self.first_page.height() if page else 0
        self._page_anim.stop()
        self._page_anim.setStartValue(bar.value())
        self._page_anim.setEndValue(min(target, bar.maximum()))
        self._page_anim.start()

    def eventFilter(self, obj, event):
        if obj is self.page_scroll.viewport():
            if event.type() == QEvent.Resize:
                self._fit_pages()
            elif event.type() == QEvent.Wheel:
                return self._page_wheel(event)
        return super().eventFilter(obj, event)

    def _page_wheel(self, event):
        """The wheel moves a whole page."""
        dy = event.angleDelta().y() or event.pixelDelta().y()
        # a column of the element board scrolls its own list first; at the end of it, the page moves
        widget = QApplication.widgetAt(event.globalPosition().toPoint())
        while widget is not None and widget is not self.page_scroll:
            if isinstance(widget, QScrollArea):
                bar = widget.verticalScrollBar()
                if (dy < 0 and bar.value() < bar.maximum() - 1) or (dy > 0 and bar.value() > bar.minimum() + 1):
                    return True
            widget = widget.parentWidget()
        if dy and self._page_anim.state() != QPropertyAnimation.Running:
            page = 1 if dy < 0 else 0
            if page != self._page or self.page_scroll.verticalScrollBar().value() != (self.first_page.height() if page else 0):
                self.go_to_page(page)
        return True

    # ----- card (left side) -----
    def _build_card(self):
        """Element, name and title; then the best logged team and the average DPS. Always the same size
        (whatever is logged), and just the name part when the window is too small for the rest."""
        card = QFrame()
        card.setObjectName("Card")
        card.setFixedWidth(380)
        outer = QVBoxLayout(card)
        outer.setContentsMargins(24, 22, 24, 20)

        self.hint = QLabel("Hover over a character in the element columns below,\nor add your first character.")
        self.hint.setStyleSheet("color: rgba(255,255,255,0.55);")
        self.hint.setWordWrap(True)
        outer.addWidget(self.hint)

        self.content = QWidget()
        v = QVBoxLayout(self.content)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)

        # element symbol, name and title
        name_row = QHBoxLayout()
        self.element_icon = RemoteIcon(42)
        names = QVBoxLayout()
        names.setSpacing(0)
        self.name_label = QLabel()
        self.name_label.setObjectName("CharName")
        self.title_label = QLabel()
        self.title_label.setObjectName("CharTitle")
        names.addWidget(self.name_label)
        names.addWidget(self.title_label)
        name_row.addWidget(self.element_icon, 0, Qt.AlignVCenter)
        name_row.addLayout(names, 1)
        v.addLayout(name_row)

        # the rest, hidden when the window is cramped
        self.details = QWidget()
        d = QVBoxLayout(self.details)
        d.setContentsMargins(0, 0, 0, 0)
        d.setSpacing(14)
        # the team from the highest-DPS run (the three teammates), then that DPS (both from the character log);
        # the team area keeps its size with fewer (or no) teammates logged
        d.addWidget(_field_label("BEST LOGGED TEAM"))
        team_area = QWidget()
        team_area.setFixedHeight(TEAM_AREA)
        t = QVBoxLayout(team_area)
        t.setContentsMargins(0, 0, 0, 0)
        self.team_row = QHBoxLayout()
        self.team_row.setSpacing(6)
        self.team_widget = QWidget()
        self.team_widget.setLayout(self.team_row)
        t.addWidget(self.team_widget)
        self.team_empty = QLabel("No runs logged yet")
        self.team_empty.setStyleSheet("color: rgba(255,255,255,0.55);")
        t.addWidget(self.team_empty)
        t.addStretch()
        d.addWidget(team_area)
        d.addWidget(_field_label("AVERAGE DPS"))
        self.dps_button = QLabel("0 DPS")
        self.dps_button.setObjectName("Dps")
        self.dps_button.setToolTip("The highest average DPS logged for this character")
        dps_row = QHBoxLayout()
        dps_row.addWidget(self.dps_button, 1)
        self.edit_button = QPushButton("Edit build")
        self.edit_button.setCursor(Qt.PointingHandCursor)
        self.edit_button.setToolTip("Change this character's weapon, artifacts, constellation and talents")
        self.edit_button.clicked.connect(self._open_build)
        dps_row.addWidget(self.edit_button, 0, Qt.AlignBottom)
        d.addLayout(dps_row)
        v.addWidget(self.details)

        outer.addWidget(self.content)
        outer.addStretch()
        return card

    def _set_compact(self, compact):
        """Just the element, name and title (for a window too small for the whole card)."""
        if compact != self.details.isHidden():
            self.details.setVisible(not compact)
        # the card is a fixed size in each mode: the hint or a character, any number of teammates
        self.card.setFixedHeight(self._card_height(compact))

    def _card_height(self, compact):
        margins = self.card.layout().contentsMargins()
        name = self.content.layout().itemAt(0).sizeHint().height()
        full = name if compact else name + self.content.layout().spacing() + self.details.sizeHint().height()
        return margins.top() + margins.bottom() + full

    def _shown(self):
        """The record the card is showing: the hovered, else the selected character."""
        char_id = self.hover_id or self.selected_id
        if not char_id:
            return None
        record = self.store.character(char_id)
        return record

    def _editable(self):
        return self.selected_id and self.hover_id in (None, self.selected_id)

    def refresh_card(self):
        record = self._shown()
        if record is None:
            self.hint.show()
            self.content.hide()
            self._set_art(None)
            return
        self.hint.hide()
        self.content.show()
        char_id = record["char_id"]
        info = self.index.characters.get(char_id) if self.index else None

        self.element_icon.set_url(gamedata.element_icon_url(record["element"]))
        self.name_label.setText(record["name"])
        self._show_title(char_id)

        # DPS and team follow the element board's Spiral Abyss / Stygian toggle
        best = self.store.best_dps(char_id, self.selector.mode)
        self.dps_button.setText(f"~{best:,.0f} DPS" if best else "No runs logged yet")
        self.dps_button.setProperty("empty", "false" if best else "true")
        self.dps_button.style().unpolish(self.dps_button)
        self.dps_button.style().polish(self.dps_button)
        self._show_team(char_id)
        self.edit_button.setVisible(bool(self._editable()))

        if info:
            self._set_art(info.splash, info.icon, info.element)

    def _show_team(self, char_id):
        """The teammates from the character's highest-DPS run: portrait, name, weapon and artifact set."""
        clear_layout(self.team_row)
        run_id = self.store.best_run_id(char_id, self.selector.mode) if char_id else None
        run = self.store.run(run_id) if run_id else None
        team = ((run or {}).get("team") or [])[1:]  # the first member is the character themself
        shown = 0
        for member in team:
            info = self._character(member["char_id"])
            if info is None:
                continue
            self.team_row.addWidget(self._team_cell(member, info), 1)
            shown += 1
        self.team_widget.setVisible(bool(shown))
        self.team_empty.setText("No teammates logged" if run else "No runs logged yet")
        self.team_empty.setVisible(not shown)

    def _character(self, char_id):
        if not self.index:
            return None
        info = self.index.characters.get(char_id) or self.index.characters.get(str(char_id))
        if info is None and str(char_id).isdigit():
            info = self.index.characters.get(int(char_id))
        return info

    def _team_cell(self, member, info):
        size = TEAM_CARD
        cell = QWidget()
        col = QVBoxLayout(cell)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        pic = QLabel()
        pic.setFixedSize(size, size)
        pic.setToolTip(f"{info.name}  C{member.get('constellation') or 0}")

        def with_element(element_pm, pic=pic, info=info):
            def with_icon(pm):
                card = card_pixmap(pm, element_pm, info.rarity, size)
                card.setDevicePixelRatio(2)
                pic.setPixmap(card)

            gamedata.load_pixmap(info.icon, with_icon)

        gamedata.load_pixmap(gamedata.element_icon_url(info.element), with_element)
        col.addWidget(pic, 0, Qt.AlignHCenter)

        # weapon and artifact set side by side under the portrait
        gear = QHBoxLayout()
        gear.setSpacing(4)
        weapon = self.index.weapons.get(member.get("weapon_id")) if member.get("weapon_id") else None
        sets = [self.index.artifacts.get(member.get(k)) for k in ("artifact1", "artifact2") if member.get(k)]
        sets = [a for a in sets if a]
        gear.addWidget(self._gear_icon(weapon.icon if weapon else None, weapon.rarity if weapon else 1,
                                       f"{weapon.name}  R{member.get('refinement') or 1}" if weapon else "No weapon logged",
                                       "Weapon"))
        gear.addWidget(self._gear_icon(sets[0].icon if sets else None, max((a.rarity for a in sets), default=1),
                                       "  +  ".join(a.name for a in sets) if sets else "No artifacts logged",
                                       "Artifact"))
        col.addLayout(gear)

        name = QLabel()
        name.setFixedWidth(size + 6)
        name.setText(name.fontMetrics().elidedText(info.name, Qt.ElideRight, size + 6))
        name.setAlignment(Qt.AlignHCenter)
        name.setStyleSheet("font-size: 8.5pt; color: #d6d9df;")
        col.addWidget(name, 0, Qt.AlignHCenter)
        return cell

    def _gear_icon(self, url, rarity, tooltip, placeholder):
        size = (TEAM_CARD - 4) // 2
        icon = QLabel()
        icon.setObjectName("GearIcon")
        icon.setFixedSize(size, size)
        icon.setAlignment(Qt.AlignCenter)
        icon.setToolTip(tooltip)
        if url:
            def loaded(pm, icon=icon):
                card = card_pixmap(pm, None, rarity, size)
                card.setDevicePixelRatio(2)
                icon.setPixmap(card)

            gamedata.load_pixmap(url, loaded)
        else:
            icon.setText(placeholder[0])
        return icon

    def _show_title(self, char_id):
        if char_id in self._titles:
            self.title_label.setText(self._titles[char_id])
            return
        self.title_label.setText("")

        def done(title, error):
            self._titles[char_id] = title or ""
            shown = self._shown()
            if shown and shown["char_id"] == char_id:
                self.title_label.setText(self._titles[char_id])

        gamedata.run_async(lambda: gamedata.clean(gamedata.fetch_character_detail(char_id).info.title), done)

    # ----- layer 1: character art -----
    # A new character's art slides in from the left to the middle, then keeps drifting right, slowly, for
    # ART_DRIFT more, with a faint glow of their element; the art it replaces slides out to the right. It's
    # shown as it is (no dimming); on the banners page it's blurred.
    def _set_art(self, url, fallback=None, element=None):
        if url == self._art_url:
            return
        self._art_url = url
        self._art_element = element
        if not url:
            self._art_out()
            self._art = None
            return
        gamedata.load_pixmap(url, lambda pm, url=url: self._art_loaded(url, pm), fallback=fallback)

    def _art_loaded(self, url, pm):
        if url != self._art_url or pm is None:
            return
        self._art_out()
        self._art = pm
        layer = {"pm": pm, "x": -ART_ENTER_FROM, "alpha": 0.0, "glow": 0.0, "element": self._art_element}
        self._layers.append(layer)

        def moved(value, layer=layer):
            layer["x"] = value
            layer["alpha"] = min(1.0, max(0.0, (value + ART_ENTER_FROM) / ART_ENTER_FROM))  # fades in on the way
            self.update()

        enter = QVariantAnimation(self, startValue=-ART_ENTER_FROM, endValue=0.0, duration=ART_ENTER_MS)
        enter.setEasingCurve(QEasingCurve.OutCubic)
        enter.valueChanged.connect(moved)
        drift = QVariantAnimation(self, startValue=0.0, endValue=ART_DRIFT, duration=ART_DRIFT_MS)
        drift.setEasingCurve(QEasingCurve.OutSine)
        drift.valueChanged.connect(moved)
        # in the middle: a faint glow of the character's element fades in behind the art
        glow = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=GLOW_MS)

        def glowing(value, layer=layer):
            layer["glow"] = value
            self.update()

        glow.valueChanged.connect(glowing)
        enter.finished.connect(lambda: layer.get("leaving") or glow.start())
        layer["glow_anim"] = glow
        # then it breathes: slowly dimmer and back, for as long as the art is up
        breathe = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=GLOW_BREATH_MS)
        breathe.setLoopCount(-1)
        breathe.valueChanged.connect(
            lambda t, layer=layer: glowing(1 - GLOW_BREATH_DEPTH * (1 - math.cos(2 * math.pi * t)) / 2, layer))
        glow.finished.connect(lambda: layer.get("leaving") or breathe.start())
        layer["breathe_anim"] = breathe
        layer["anim"] = QSequentialAnimationGroup(self)
        layer["anim"].addAnimation(enter)
        layer["anim"].addAnimation(drift)
        layer["anim"].start()

    def _art_out(self):
        """Every art on screen slides out to the right from where it is (and is dropped once gone)."""
        for layer in [l for l in self._layers if not l.get("leaving")]:
            layer["leaving"] = True
            layer["anim"].stop()
            layer["glow_anim"].stop()
            layer["breathe_anim"].stop()

            def moved(value, layer=layer):
                layer["x"] = value
                self.update()

            leave = QVariantAnimation(self, startValue=layer["x"], endValue=ART_LEAVE_TO, duration=ART_LEAVE_MS)
            leave.setEasingCurve(QEasingCurve.InCubic)
            leave.valueChanged.connect(moved)
            leave.finished.connect(lambda layer=layer: self._layers.remove(layer) if layer in self._layers else None)
            layer["anim"] = leave
            leave.start()

    def _art_images(self, pm):
        """The art scaled for the page, and a blurred copy of it (cached for the current size)."""
        key = (pm.cacheKey(), self.width(), self.height())  # -> sharp, blurred, its margin, {element: glow}
        cached = self._art_cache.get(key)
        if cached is None:
            # zoomed out 10% from filling the page
            fill = pm.size().scaled(self.size(), Qt.KeepAspectRatioByExpanding)
            # at the screen's own resolution, so the slow drift between pixels stays crisp
            ratio = self.devicePixelRatioF()
            sharp = pm.scaled(fill * 0.9 * ratio, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            sharp.setDevicePixelRatio(ratio)
            blurred, margin = _gaussian_blur(pm.scaled(fill * 0.9, Qt.KeepAspectRatio, Qt.SmoothTransformation),
                                             BLUR_RADIUS)
            cached = (sharp, blurred, margin, {})
            if len(self._art_cache) > 12:
                self._art_cache.clear()
            self._art_cache[key] = cached
        return cached

    def _glow_image(self, cached, element):
        glows = cached[3]
        if element not in glows:
            glow = QPixmap(cached[1].size())
            glow.fill(Qt.transparent)
            painter = QPainter(glow)
            painter.drawPixmap(0, 0, cached[1])
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(glow.rect(), QColor(gamedata.ELEMENT_COLORS.get(element, "#ffffff")))
            painter.end()
            glows[element] = glow
        return glows[element]

    def _blur_amount(self):
        """0 on the characters page, 1 on the banners page (in between while scrolling)."""
        scroll = getattr(self, "page_scroll", None)
        seam = self.first_page.height() if scroll is not None else 0
        if not seam:
            return 0.0
        return min(1.0, max(0.0, scroll.verticalScrollBar().value() / seam))

    def paintEvent(self, _event):
        p = QPainter(self)
        rect = QRectF(self.rect())
        bg = QLinearGradient(rect.topLeft(), rect.bottomRight())
        bg.setColorAt(0, theme.qcolor(0x26, 0x27, 0x2d))
        bg.setColorAt(1, theme.qcolor(0x1c, 0x1d, 0x21))
        p.fillRect(rect, bg)
        if self._layers:
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            blur = self._blur_amount()
            for layer in self._layers:
                cached = self._art_images(layer["pm"])
                sharp, blurred, margin = cached[:3]
                size = sharp.deviceIndependentSize()
                # fractional positions (drawn smoothly between pixels): whole pixels made the slow drift step
                x = (self.width() - size.width()) / 2 + layer["x"] * self.width()
                y = (self.height() - size.height()) / 2
                strength = layer.get("alpha", 1.0)
                if layer.get("glow") and layer.get("element") and blur < 1:
                    p.setOpacity(GLOW_STRENGTH * layer["glow"] * strength * (1 - blur))
                    _draw_at(p, x - margin, y - margin, self._glow_image(cached, layer["element"]))
                if blur < 1:
                    p.setOpacity(strength * (1 - blur))
                    _draw_at(p, x, y, sharp)
                if blur > 0:
                    p.setOpacity(strength * blur)
                    _draw_at(p, x - margin, y - margin, blurred)
            p.setOpacity(1)
            if blur > 0:  # on the banners page: dimmed a little too, so the banners and links stand out
                p.fillRect(rect, theme.qcolor(28, 29, 33, int(140 * blur)))
        p.end()

    # ----- roster / selection -----
    def set_index(self, index):
        self.index = index
        self.selector.index = index
        self.banners.load(index)
        self.reload_roster()
        self.refresh_card()
        if not self.selected_id and not self.draft:
            self._select_on_launch()
        for record in self.store.characters():  # warm the art cache so hovering is instant
            info = index.characters.get(record["char_id"])
            if info:
                gamedata.load_pixmap(info.splash, lambda pm: None, fallback=info.icon)

    def reload_roster(self):
        records = self.store.characters()
        for r in records:  # the right panel shows (and sorts by) the chosen mode's DPS
            r["best_dps"] = self.store.best_dps(r["char_id"], self.selector.mode)
        self.selector.set_roster(records, self.selected_id)

    def _cycle_mode(self):
        keys = [key for key, _ in DPS_MODES]
        self.selector.set_mode(keys[(keys.index(self.selector.mode) + 1) % len(keys)])
        self._show_mode()

    def _show_mode(self):
        self.mode_button.setText(f"{dict(DPS_MODES)[self.selector.mode]}  \u21bb")

    def _dps_mode_changed(self, mode):
        self.store.set_setting("home_dps_mode", mode)
        self.reload_roster()
        self.refresh_card()

    def select(self, char_id):
        if self.draft:
            self.message.emit("Finish or cancel adding the current character first.")
            return
        record = self.store.character(char_id)
        if not record:
            return
        self.selected_id = char_id
        self.hover_id = None
        self.selector.selected_id = char_id
        self.selector.open_element(record["element"])
        self.visited.emit(char_id)
        self.refresh_card()

    def _on_hover(self, char_id):
        """Hovering a character selects them (quietly: no 'recently visited' entry), and they stay
        on the card after the mouse moves away."""
        if self.draft or char_id is None or char_id == self.selected_id:
            return
        if not self.store.character(char_id):
            return
        self.selected_id = char_id
        self.hover_id = None
        self.selector.selected_id = char_id
        self.selector.mark_selected(char_id)  # restyle the rows in place: rebuilding would end the hover
        self.refresh_card()

    def _set_hover(self, char_id):
        if char_id != self.hover_id:
            self.hover_id = char_id
            self.refresh_card()

    def _on_pick(self, char_id):
        self.select(char_id)

    def _on_remove(self, char_id):
        record = self.store.character(char_id)
        if not record:
            return
        if not confirm(self, "Remove character", f"Remove {record['name']} and their DPS log from your Record Book?", "Remove"):
            return
        self.store.delete_character(char_id)
        if self.selected_id == char_id:
            self.selected_id = None
        self.hover_id = None
        self.reload_roster()
        self.refresh_card()
        self.roster_changed.emit()
        self.removed.emit(char_id)
        self.message.emit(f"Removed {record['name']}")

    # ----- adding a character -----
    def _on_add(self, element):
        if self.draft:
            self.message.emit("Finish or cancel adding the current character first.")
            return
        if not self.index:
            self.message.emit("Game data is still loading…")
            return
        logged = {r["char_id"] for r in self.store.characters()}
        candidates = [c for c in self.index.characters.values() if c.element == element and c.id not in logged]
        dialog = CharacterSearchDialog(candidates, element, self)
        if dialog.exec() and dialog.chosen:
            self.start_add(dialog.chosen)

    def start_add(self, char_id):
        """Add a character: their build in a popup, saved when you press Add (also used by the Characters page)."""
        if not self.index or char_id not in self.index.characters:
            return
        if self.store.character(char_id):
            self.select(char_id)
            return
        info = self.index.characters[char_id]
        dialog = BuildDialog(self.index, info, {}, self, adding=True)
        if not dialog.exec():
            return
        self.store.save_character({"char_id": char_id, "name": info.name, "element": info.element, "notes": "",
                                   **dialog.values})
        self.reload_roster()
        self.roster_changed.emit()
        self.select(char_id)
        self.message.emit(f"Added {info.name} to your Record Book")

    def _open_build(self):
        """Edit the selected character's weapon, artifacts, constellation and talents in a popup."""
        record = self.store.character(self.selected_id) if self.selected_id else None
        info = self.index.characters.get(self.selected_id) if record and self.index else None
        if info is None:
            return
        dialog = BuildDialog(self.index, info, record, self)
        if dialog.exec():
            self.store.update_character(self.selected_id, **dialog.values)
            self.refresh_card()
            self.roster_changed.emit()

    def _select_on_launch(self):
        """Open on a favourite character (Settings), else the most recently viewed one (else the first logged)."""
        logged = {r["char_id"] for r in self.store.characters()}
        if not logged:
            return
        favourites = [c for c in self.store.favourites() if c in logged]
        if favourites and self.store.get_setting("open_favourite", True):
            self.select(random.choice(favourites))  # one of several favourites at random
            return
        recent = [str(r.get("id")) for r in self.store.get_setting("recent", []) or []]
        pinned = [str(p.get("id")) for p in self.store.get_setting("pins", []) or []]
        choice = next((cid for cid in recent + pinned if cid in logged), None) or sorted(logged)[0]
        self.select(choice)

    def _open_log_for(self, char_id):
        """From a name or portrait in the element selector (not while adding a character)."""
        if not self.draft and self.store.character(char_id):
            self.open_log.emit(char_id)

