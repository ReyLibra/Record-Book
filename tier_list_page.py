"""Tier List Maker: your saved tier lists, and the editor for one.

A list has a title, a character icon (to tell lists apart), tiers (S, A, B, C, D to start: each with a name,
a colour and the pictures dragged into it) and the grid of pictures not placed yet. Pictures are
characters, weapons and artifact sets, all the same size, keyed "c:<id>", "w:<id>" or "a:<id>".
Lists are kept in the settings table ("tier_lists"); Save writes a picture of the list to
"Saved Tier Lists" next to the program, Copy puts one on the clipboard.
"""

import pathlib
import re
import time

from PySide6.QtCore import QMimeData, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QDrag, QFont, QFontMetrics, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import gamedata
import theme
from app_info import APP_DIR
from dialogs import CharacterSearchDialog, Popup, confirm
from search import matches
from widgets import card_pixmap, filter_button, section_header

CAPTURE_COLUMNS = 10  # pictures a row in a copied / saved picture of the list
TILE = 128  # every picture, in the tiers and the grid below (2x the database cards' 64)
LABEL_WIDTH = 138  # the tier's name square
MIME = "application/x-recordbook-tier-item"
# dragging near the top or bottom of the page scrolls it
EDGE_SCROLL_ZONE = 80  # px from the edge
EDGE_SCROLL_MAX = 40  # px per step, at the very edge (or past it)
EDGE_SCROLL_MS = 16
SAVE_DIR = APP_DIR / "Saved Tier Lists"
KINDS = (("c", "Characters"), ("w", "Weapons"), ("a", "Artifacts"))
DEFAULT_TIERS = [("S", "#ff7f7f"), ("A", "#ffbf7f"), ("B", "#ffdf7f"), ("C", "#ffff7f"), ("D", "#bfff7f")]
SWATCHES = ["#ff7f7f", "#ffbf7f", "#ffdf7f", "#ffff7f", "#bfff7f", "#7fff7f", "#7fffff", "#7fbfff",
            "#7f7fff", "#ff7fff", "#bf7fbf", "#cfcfcf"]


def _ink(hex_color):
    """Dark or light text, whichever reads on that background."""
    c = QColor(hex_color)
    return QColor("#15171c") if 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue() > 140 else QColor("#ffffff")


# ---------- pictures ----------
class Tile(QLabel):
    """One draggable picture (a character, weapon or artifact set)."""

    def __init__(self, key, name, page):
        super().__init__()
        self.key = key
        self.page = page
        self.setFixedSize(TILE, TILE)
        self.setToolTip(name)
        self.setCursor(Qt.OpenHandCursor)
        self._press = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press = event.position().toPoint()

    def mouseMoveEvent(self, event):
        if self._press is None or (event.position().toPoint() - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        self._press = None
        drag = QDrag(self)
        data = QMimeData()
        data.setData(MIME, self.key.encode())
        drag.setMimeData(data)
        if self.pixmap() and not self.pixmap().isNull():
            drag.setPixmap(self.pixmap())
            drag.setHotSpot(QPoint(TILE // 2, TILE // 2))
        self.page.drag_started(self)
        dropped = drag.exec(Qt.MoveAction) != Qt.IgnoreAction
        self.page.drag_ended(self, dropped)

    def mouseReleaseEvent(self, event):
        self._press = None


class DragCatcher(QWidget):
    """The tier list editor's page: a picture dragged over it (not over a tier or the grid) scrolls the page
    near its top and bottom edges, and can't be dropped there; let go, it goes back to the grid."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            event.accept()

    def dragMoveEvent(self, event):
        self.page._edge_scroll()
        event.ignore()  # not a place to drop it


class Flow(QWidget):
    """Pictures in rows that wrap, edge to edge (they snap together). Accepts drops: where the picture lands
    between the others is where it goes."""

    def __init__(self, page, owner, empty_height=TILE):
        super().__init__()
        self.page = page
        self.owner = owner  # the tier dict, or "pool"
        self.keys = []
        self.empty_height = empty_height
        self.setAcceptDrops(True)
        self._drop_at = None
        self.setMinimumHeight(empty_height)

    def columns(self):
        return max(1, self.width() // TILE)

    def set_keys(self, keys):
        self.keys = keys
        self._place()

    def _place(self):
        cols = self.columns()
        for n, key in enumerate(self.keys):
            tile = self.page.tile(key)
            if tile is None:
                continue
            if tile.parent() is not self:
                tile.setParent(self)
            tile.move((n % cols) * TILE, (n // cols) * TILE)
            tile.show()
        rows = (len(self.keys) + cols - 1) // cols
        height = max(self.empty_height, rows * TILE)
        if self.minimumHeight() != height:
            self.setMinimumHeight(height)
            self.setMaximumHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place()

    def _index_at(self, pos):
        cols = self.columns()
        col = max(0, min(cols, round(pos.x() / TILE)))
        row = max(0, pos.y() // TILE)
        return max(0, min(len(self.keys), row * cols + col))

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            self._drop_at = self._index_at(event.position().toPoint())
            self.update()
            event.acceptProposedAction()
            self.page._edge_scroll()

    def dragLeaveEvent(self, event):
        self._drop_at = None
        self.update()

    def dropEvent(self, event):
        key = bytes(event.mimeData().data(MIME)).decode()
        index = self._index_at(event.position().toPoint())
        self._drop_at = None
        self.update()
        event.acceptProposedAction()
        QTimer.singleShot(0, lambda: self.page.move_item(key, self.owner, index, self.keys))

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._drop_at is None:
            return
        cols = self.columns()
        n = self._drop_at
        x, y = (n % cols) * TILE, (n // cols) * TILE
        if n and n % cols == 0 and n == len(self.keys):  # after the last picture of a full row
            x, y = cols * TILE, (n // cols - 1) * TILE
        p = QPainter(self)
        p.setPen(QPen(QColor(theme.accent_hex()), 3))
        p.drawLine(max(1, x), y + 2, max(1, x), y + TILE - 2)
        p.end()


# ---------- a tier row ----------
class TierLabel(QLabel):
    """The tier's coloured name square: double-click to rename it or change its colour."""

    def __init__(self, tier, on_edit):
        super().__init__()
        self.tier = tier
        self.on_edit = on_edit
        self.setObjectName("TierLabel")
        self.setFixedWidth(LABEL_WIDTH)
        self.setMinimumHeight(TILE)
        self.setWordWrap(True)  # a long name wraps and the row grows
        self.setAlignment(Qt.AlignCenter)
        self.setMargin(6)
        self.setToolTip("Double-click to rename it or change its colour")
        self.refresh()

    def refresh(self):
        self.setText(self.tier["name"])
        # drawn with its own font (the app's stylesheet would override setFont)
        self._font = QFont("Segoe UI", 19 if len(self.tier["name"]) <= 3 else 12, QFont.Bold)
        # (sizes the wrapped text; by object name, so the tooltip doesn't take this font size too)
        self.setStyleSheet(f"#TierLabel {{ font-size: {self._font.pointSize()}pt; font-weight: 700; }}")
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(self.tier["color"]))  # (as chosen: not changed by the app's look)
        p.setPen(_ink(self.tier["color"]))
        p.setFont(self._font)
        p.drawText(self.rect().adjusted(6, 6, -6, -6), Qt.AlignCenter | Qt.TextWordWrap, self.tier["name"])
        p.end()

    def mouseDoubleClickEvent(self, event):
        self.on_edit(self.tier)


class TierDialog(Popup):
    """Rename a tier, pick its colour, or delete it."""

    def __init__(self, tier, parent=None):
        super().__init__(parent, "Edit tier", 420)
        self.color = tier["color"]
        self.deleted = False
        self.name = QLineEdit(tier["name"])
        self.name.setPlaceholderText("Tier name")
        self.body.addWidget(self.name)
        swatches = QHBoxLayout()
        swatches.setSpacing(4)
        self.swatch_buttons = []
        for color in SWATCHES:
            btn = QToolButton()
            btn.setFixedSize(26, 26)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("swatch", color)
            btn.clicked.connect(lambda _=False, c=color: self._pick(c))
            self.swatch_buttons.append(btn)
            swatches.addWidget(btn)
        swatches.addStretch()
        self.body.addLayout(swatches)
        row = QHBoxLayout()
        custom = QPushButton("Custom colour…")
        custom.clicked.connect(self._custom)
        row.addWidget(custom)
        row.addStretch()
        delete = QPushButton("Delete tier")
        delete.setObjectName("DeleteRun")
        delete.clicked.connect(self._delete)
        row.addWidget(delete)
        self.body.addLayout(row)
        from dialogs import _buttons

        self.body.addWidget(_buttons(self, "Save"))
        self._pick(self.color)
        self.name.setFocus()
        self.name.selectAll()

    def _pick(self, color):
        self.color = color
        for btn in self.swatch_buttons:
            c = btn.property("swatch")
            border = "#ffffff" if c == color else "transparent"
            btn.setStyleSheet(f"QToolButton {{ background: {c}; border: 2px solid {border}; }}")

    def _custom(self):
        color = QColorDialog.getColor(QColor(self.color), self, "Tier colour")
        if color.isValid():
            self._pick(color.name())

    def _delete(self):
        self.deleted = True
        self.accept()


class ListRow(QFrame):
    """A saved list in the overview: click to open; Delete on the far right (asks first)."""

    def __init__(self, title, details, on_open, on_delete):
        super().__init__()
        self.setObjectName("TierListRow")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Click to open · right-click to change its icon")
        self.on_open = on_open
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 6, 10, 6)
        h.setSpacing(12)
        self.icon = QLabel()
        self.icon.setFixedSize(48, 48)
        h.addWidget(self.icon)
        text = QLabel(f"<span style='font-size:12pt; font-weight:700'>{title}</span><br>"
                      f"<span style='color: rgba(255,255,255,0.55)'>{details}</span>")
        text.setAttribute(Qt.WA_TransparentForMouseEvents)
        h.addWidget(text, 1)
        delete = QPushButton("Delete")
        delete.setObjectName("DeleteRun")
        delete.setCursor(Qt.PointingHandCursor)
        delete.setToolTip("Delete this tier list (asks first)")
        delete.clicked.connect(on_delete)
        h.addWidget(delete)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.on_open()


# ---------- the page ----------
class TierListPage(QWidget):
    message = Signal(str)

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.index = None
        self.full_index = None  # (with both Traveler twins: set by the window)
        self.traveler = "Aether"
        self.lists = store.get_setting("tier_lists", []) or []
        self.current = None
        self._tiles = {}
        self._save_timer = QTimer(self, singleShot=True, interval=400)
        self._save_timer.timeout.connect(lambda: self.store.set_setting("tier_lists", self.lists))

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_overview())
        self.stack.addWidget(self._build_editor())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

    def set_index(self, index):
        self.index = index
        self._tiles.clear()  # pictures are made again from the new data when needed
        self._fill_overview()
        if self.current is not None and self.stack.currentIndex() == 1:
            self._open(self.current)

    def _changed(self):
        self._save_timer.start()

    # ----- the overview: every saved list -----
    def _build_overview(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(28, 22, 28, 20)
        v.setSpacing(10)
        head, self.count_label = section_header("All Tier Lists")
        v.addWidget(head)
        top = QHBoxLayout()
        self.search = QLineEdit(placeholderText="Search tier lists…")
        self.search.setMaximumWidth(360)
        self.search.textChanged.connect(lambda _: self._fill_overview())
        top.addWidget(self.search)
        top.addStretch()
        v.addLayout(top)
        self.list_view = QListWidget()
        self.list_view.setObjectName("TierLists")
        self.list_view.setIconSize(QSize(48, 48))
        self.list_view.setSpacing(2)
        self.list_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_view.customContextMenuRequested.connect(self._list_menu)
        self.list_view.itemClicked.connect(self._list_clicked)
        self.list_view.setStyleSheet("QListWidget { background: transparent; border: none; }"
                                     "QListWidget::item { padding: 0; margin: 2px 0; font-size: 12pt; }"
                                     "QListWidget::item:selected { background: transparent; border: none; }")
        v.addWidget(self.list_view, 1)
        return page

    def _fill_overview(self):
        self.list_view.clear()
        add = QListWidgetItem("+  Add Tier List")
        add.setData(Qt.UserRole, None)
        add.setForeground(QColor(theme.accent_hex()))
        add.setToolTip("Start a new tier list")
        self.list_view.addItem(add)
        text = self.search.text().strip()
        shown = [t for t in self.lists if not text or matches(text, t["title"])]
        for tier_list in shown:
            placed = sum(len(self._shown(t)) for t in tier_list["tiers"]) if self.index else 0
            item = QListWidgetItem()
            item.setData(Qt.UserRole, tier_list["id"])
            row = ListRow(tier_list["title"], f"{len(tier_list['tiers'])} tiers · {placed} placed",
                          lambda t=tier_list: self._open(t), lambda _=False, t=tier_list: self._delete_list(t))
            item.setSizeHint(QSize(0, row.sizeHint().height() + 4))
            self.list_view.addItem(item)
            self.list_view.setItemWidget(item, row)
            self._set_list_icon(row.icon, tier_list.get("icon"))
        self.count_label.setText(f"{len(self.lists)} tier list{'s' if len(self.lists) != 1 else ''}")

    def _set_list_icon(self, label, char_id):
        info = self.index.characters.get(char_id) if (self.index and char_id) else None
        if info is None:  # no icon chosen yet: an empty square, so the names line up
            empty = QPixmap(96, 96)
            empty.fill(Qt.transparent)
            p = QPainter(empty)
            p.setPen(QPen(theme.qcolor(0x4a, 0x4d, 0x57), 3, Qt.DashLine))
            p.drawRect(QRectF(2, 2, 92, 92))
            p.end()
            empty.setDevicePixelRatio(2)
            label.setPixmap(empty)
            return

        def with_element(element_pm):
            def show(pm):
                card = card_pixmap(pm, element_pm, info.rarity, 48)
                card.setDevicePixelRatio(2)
                label.setPixmap(card)
            gamedata.load_pixmap(info.icon, show)
        gamedata.load_pixmap(gamedata.element_icon_url(info.element), with_element)

    def _find(self, list_id):
        return next((t for t in self.lists if t["id"] == list_id), None)

    def _list_clicked(self, item):
        list_id = item.data(Qt.UserRole)
        if list_id is None:
            self._new_list()
        else:
            self._open(self._find(list_id))

    def _list_menu(self, pos):
        item = self.list_view.itemAt(pos)
        tier_list = self._find(item.data(Qt.UserRole)) if item else None
        if tier_list is None:
            return
        menu = QMenu(self)
        menu.addAction("Open", lambda: self._open(tier_list))
        menu.addAction("Change icon…", lambda: self._pick_icon(tier_list))
        menu.exec(self.list_view.mapToGlobal(pos))

    def _unique_title(self, title, ignore=None):
        taken = {t["title"].lower() for t in self.lists if t is not ignore}
        title = title.strip() or "Tier List"
        if title.lower() not in taken:
            return title
        base = re.sub(r"\s+\d+$", "", title)
        n = 2
        while f"{base} {n}".lower() in taken:
            n += 1
        return f"{base} {n}"

    def _new_list(self):
        n = 1
        taken = {t["title"].lower() for t in self.lists}
        while f"tier list {n}" in taken:
            n += 1
        tier_list = {
            "id": f"{int(time.time() * 1000)}",
            "title": f"Tier List {n}",
            "icon": None,
            "tiers": [{"name": name, "color": color, "items": []} for name, color in DEFAULT_TIERS],
            "pool": [],
            "kinds": ["c"],
            "tags": True,
        }
        self.lists.append(tier_list)
        self._changed()
        self._fill_overview()
        self._open(tier_list)

    def _delete_list(self, tier_list):
        if not confirm(self, "Delete tier list", f"Delete “{tier_list['title']}”? This can't be undone.", "Delete"):
            return
        self.lists.remove(tier_list)
        self._changed()
        if self.current is tier_list:
            self.current = None
            self.stack.setCurrentIndex(0)
        self._fill_overview()

    def _pick_icon(self, tier_list):
        if not self.index:
            return
        dialog = CharacterSearchDialog(list(self.index.characters.values()), None, self, title="Tier list icon")
        if dialog.exec() and dialog.chosen:
            tier_list["icon"] = dialog.chosen
            self._changed()
            self._fill_overview()
            if self.current is tier_list:
                self._show_icon()

    # ----- the editor -----
    def _build_editor(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        self.editor_scroll = scroll
        content = DragCatcher(self)
        v = QVBoxLayout(content)
        v.setContentsMargins(28, 22, 28, 28)
        v.setSpacing(12)
        scroll.setWidget(content)

        # ← All Tier Lists · [icon] editable title ............ Copy  Save
        top = QHBoxLayout()
        top.setSpacing(10)
        back = QPushButton("←  All Tier Lists")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self._close_editor)
        top.addWidget(back)
        self.icon_button = QToolButton()
        self.icon_button.setFixedSize(44, 44)
        self.icon_button.setIconSize(QSize(40, 40))
        self.icon_button.setCursor(Qt.PointingHandCursor)
        self.icon_button.setToolTip("Change this list's icon")
        self.icon_button.setStyleSheet("QToolButton { border: 1px dashed #4a4d57; background: transparent; }")
        self.icon_button.clicked.connect(lambda: self.current and self._pick_icon(self.current))
        top.addWidget(self.icon_button)
        self.title_edit = QLineEdit()
        self.title_edit.setObjectName("TierTitle")
        self.title_edit.setPlaceholderText("Tier list title")
        self.title_edit.editingFinished.connect(self._title_done)
        top.addWidget(self.title_edit, 1)
        copy = QPushButton("Copy")
        copy.setCursor(Qt.PointingHandCursor)
        copy.setToolTip("Copy a picture of the tier list to the clipboard")
        copy.clicked.connect(self._copy)
        top.addWidget(copy)
        save = QPushButton("Save PNG")
        save.setObjectName("Primary")
        save.setCursor(Qt.PointingHandCursor)
        save.setToolTip("Save a picture of the tier list (10 pictures a row) as a PNG: you choose where")
        save.clicked.connect(self._save_image)
        top.addWidget(save)
        v.addLayout(top)

        # the tiers (what Copy / Save capture), then "+ Add tier"
        self.tiers_box = QFrame()
        self.tiers_box.setObjectName("TiersBox")
        self.tiers_layout = QVBoxLayout(self.tiers_box)
        self.tiers_layout.setContentsMargins(0, 0, 0, 0)
        self.tiers_layout.setSpacing(2)
        v.addWidget(self.tiers_box)
        add_tier = QPushButton("+  Add tier")
        add_tier.setObjectName("PageHint")
        add_tier.setCursor(Qt.PointingHandCursor)
        add_tier.clicked.connect(self._add_tier)
        v.addWidget(add_tier, 0, Qt.AlignLeft)

        # the pictures not placed yet: which kinds; then Reorder Below, Add / Remove Twin, Remove / Add Tag
        controls = QHBoxLayout()
        controls.setSpacing(4)
        self.kind_buttons = {}
        for kind, label in KINDS:
            btn = filter_button(label, tooltip=f"Show {label.lower()} in the grid below")
            btn.clicked.connect(lambda _=False, k=kind: self._toggle_kind(k))
            self.kind_buttons[kind] = btn
            controls.addWidget(btn)
        controls.addStretch()
        reorder = QPushButton("Reorder Below")
        reorder.setCursor(Qt.PointingHandCursor)
        reorder.setToolTip("Put the pictures left in the grid back in order: characters, weapons, artifacts, "
                           "each alphabetically")
        reorder.clicked.connect(self._reorder_pool)
        controls.addWidget(reorder)
        # the other Traveler twin's pictures (the app shows only the one chosen in Settings)
        self.twin_button = QPushButton("Add Twin")
        self.twin_button.setCursor(Qt.PointingHandCursor)
        self.twin_button.clicked.connect(self._toggle_twin)
        controls.addWidget(self.twin_button)
        # the element (characters) and weapon-type (weapons) symbols on the pictures
        self.tag_button = QPushButton("Remove Tag")
        self.tag_button.setCursor(Qt.PointingHandCursor)
        self.tag_button.setToolTip("Show or hide the element and weapon symbols on the pictures")
        self.tag_button.clicked.connect(self._toggle_tags)
        controls.addWidget(self.tag_button)
        v.addLayout(controls)
        self.pool = Flow(self, "pool", empty_height=TILE * 2)
        self.pool.setObjectName("TierPool")
        self.pool.setAttribute(Qt.WA_StyledBackground, True)
        v.addWidget(self.pool)
        v.addStretch()
        return page

    def _close_editor(self):
        self._title_done()
        self.stack.setCurrentIndex(0)
        self._fill_overview()

    def _open(self, tier_list):
        if tier_list is None or not self.index:
            return
        self.current = tier_list
        self.title_edit.setText(tier_list["title"])
        self._show_icon()
        for kind, btn in self.kind_buttons.items():
            btn.setChecked(kind in tier_list["kinds"])
        self._show_tag_button()
        self._show_twin_button()
        self._sync_pool()
        self._render_tiers()
        self.stack.setCurrentIndex(1)
        self.editor_scroll.verticalScrollBar().setValue(0)

    def _show_icon(self):
        info = self.index.characters.get(self.current.get("icon")) if self.current.get("icon") else None
        self.icon_button.setIcon(QIcon())
        self.icon_button.setText("" if info else "+")
        if info:
            def with_element(element_pm):
                gamedata.load_pixmap(info.icon, lambda pm: self.icon_button.setIcon(
                    QIcon(card_pixmap(pm, element_pm, info.rarity, 40))))
            gamedata.load_pixmap(gamedata.element_icon_url(info.element), with_element)

    def _title_done(self):
        if self.current is None:
            return
        title = self._unique_title(self.title_edit.text() or "Tier List", ignore=self.current)
        if title != self.title_edit.text():
            self.title_edit.setText(title)
        if title != self.current["title"]:
            self.current["title"] = title
            self._changed()

    # ----- the pictures -----
    def _other_twin(self):
        """The Traveler twin not chosen in Settings (whose pictures "Add Twin" brings in)."""
        return "Lumine" if self.traveler == "Aether" else "Aether"

    def _twin_keys(self):
        prefix = f"{self._other_twin()} ("
        return {f"c:{c.id}" for c in (self.full_index or self.index).characters.values() if c.name.startswith(prefix)}

    def _items(self):
        """Every picture there is: {key: (kind order, name, info)} (the other twin's too, which the grid
        only shows with "Add Twin")."""
        idx = self.index
        out = {}
        for c in idx.characters.values():
            out[f"c:{c.id}"] = (0, c.name, c)
        if self.full_index is not None:
            for key in self._twin_keys():
                c = self.full_index.characters[key[2:]]
                out[key] = (0, c.name, c)
        for w in idx.weapons.values():
            out[f"w:{w.id}"] = (1, w.name, w)
        for a in idx.artifacts.values():
            out[f"a:{a.id}"] = (2, a.name, a)
        return out

    def _sort_key(self, key, items):
        kind, name, _ = items.get(key, (9, key, None))
        return kind, name.lower()

    def _sync_pool(self):
        """Every picture not in a tier is in the pool, once (new ones join at the end, in order)."""
        items = self._items()
        placed = {k for t in self.current["tiers"] for k in t["items"]}
        pool = [k for k in dict.fromkeys(self.current["pool"]) if k in items and k not in placed]
        missing = sorted((k for k in items if k not in placed and k not in set(pool)), key=lambda k: self._sort_key(k, items))
        self.current["pool"] = pool + missing

    def tile(self, key):
        tile = self._tiles.get(key)
        if tile is None:
            items = self._items_cache if getattr(self, "_items_cache", None) else self._items()
            if key not in items:
                return None
            kind, name, info = items[key]
            tile = Tile(key, name, self)
            tile.info = info
            tile.tagged = None
            self._tiles[key] = tile
        if tile.tagged != self._tags():  # made, or the tags were switched since
            tile.tagged = self._tags()
            self._load_picture(tile, key[0], tile.info, tile.tagged)
        return tile

    def _load_picture(self, tile, kind, info, tagged=True):
        """The picture on its rarity background, with (tagged) the character's element or the weapon's
        type in the corner."""
        def show(pm, symbol=None):
            if pm is None or tile.tagged != tagged:
                return
            card = card_pixmap(pm, symbol, info.rarity, TILE)
            card.setDevicePixelRatio(2)
            tile.setPixmap(card)

        symbol_url = None
        if tagged and kind == "c":
            symbol_url = gamedata.element_icon_url(info.element)
        elif tagged and kind == "w":
            symbol_url = gamedata.weapon_type_icon_url(info.type)
        if symbol_url:
            gamedata.load_pixmap(symbol_url, lambda spm: gamedata.load_pixmap(info.icon, lambda pm: show(pm, spm), bulk=True))
        else:
            gamedata.load_pixmap(info.icon, show, bulk=True)

    def _shown(self, tier):
        """A tier's pictures that exist right now (unreleased ones are left out while they're hidden in
        Settings; they come back in their places when shown)."""
        items = self._items_cache if getattr(self, "_items_cache", None) else self._items()
        return [k for k in tier["items"] if k in items]

    def _pool_keys(self):
        twins = set() if self.current.get("twin") else self._twin_keys()
        return [k for k in self.current["pool"] if k[0] in self.current["kinds"] and k not in twins]

    def _relayout(self):
        """Put every picture where the list says (the ones filtered out of the grid hidden)."""
        self._items_cache = self._items()
        shown = set(self._pool_keys()) | {k for t in self.current["tiers"] for k in t["items"]}
        for key, tile in self._tiles.items():
            if key not in shown:
                tile.hide()
        for row in self._tier_rows:
            row.flow.set_keys(self._shown(row.tier))
        self.pool.set_keys(self._pool_keys())
        self._items_cache = None

    def _toggle_kind(self, kind):
        kinds = self.current["kinds"]
        if kind in kinds:
            kinds.remove(kind)
        else:
            kinds.append(kind)
        self.kind_buttons[kind].setChecked(kind in kinds)
        self._changed()
        self._relayout()

    def _tags(self):
        return self.current is None or self.current.get("tags", True)

    def _show_tag_button(self):
        self.tag_button.setText("Remove Tag" if self._tags() else "Add Tag")

    def _toggle_tags(self):
        self.current["tags"] = not self._tags()
        self._show_tag_button()
        self._changed()
        self._relayout()

    def _show_twin_button(self):
        twin = self._other_twin()
        on = bool(self.current and self.current.get("twin"))
        self.twin_button.setText("Remove Twin" if on else "Add Twin")
        self.twin_button.setToolTip(f"{'Hide' if on else 'Show'} {twin}'s pictures in the grid below "
                                    f"(the Traveler in Settings is {self.traveler})")

    def _toggle_twin(self):
        self.current["twin"] = not self.current.get("twin")
        self._show_twin_button()
        self._changed()
        self._relayout()

    def _reorder_pool(self):
        items = self._items()
        self.current["pool"].sort(key=lambda k: self._sort_key(k, items))
        self._changed()
        self._relayout()

    # ----- dragging -----
    def drag_started(self, tile):
        if not hasattr(self, "_edge_timer"):
            self._edge_timer = QTimer(self, interval=EDGE_SCROLL_MS)
            self._edge_timer.timeout.connect(self._edge_scroll)
        self._edge_timer.start()

    def drag_ended(self, tile, dropped=True):
        self._edge_timer.stop()
        if not dropped:  # let go off the chart: back to the grid below
            self._return_to_pool(tile.key)

    def _edge_scroll(self):
        """While a picture is dragged near (or past) the top or bottom of the page, the page scrolls that way,
        faster the further in, so it can be carried to a tier or the grid that's off screen."""
        viewport = self.editor_scroll.viewport()
        y = viewport.mapFromGlobal(QCursor.pos()).y()
        height = viewport.height()
        if y < EDGE_SCROLL_ZONE:
            step = -min(EDGE_SCROLL_MAX, (EDGE_SCROLL_ZONE - y) // 3 + 4)
        elif y > height - EDGE_SCROLL_ZONE:
            step = min(EDGE_SCROLL_MAX, (y - height + EDGE_SCROLL_ZONE) // 3 + 4)
        else:
            return
        bar = self.editor_scroll.verticalScrollBar()
        bar.setValue(bar.value() + step)

    def _return_to_pool(self, key):
        """A picture taken off a tier goes back into the grid, first in it (easy to find again)."""
        if self.current is None or not any(key in tier["items"] for tier in self.current["tiers"]):
            return
        for tier in self.current["tiers"]:
            if key in tier["items"]:
                tier["items"].remove(key)
        self.current["pool"].insert(0, key)
        if key[0] not in self.current["kinds"]:
            self.current["kinds"].append(key[0])
            self.kind_buttons[key[0]].setChecked(True)
        self._changed()
        self._relayout()

    def move_item(self, key, owner, index, shown_keys):
        """A picture dropped at a place (index among what that flow shows) in a tier or the grid."""
        if self.current is None:
            return
        # where it was (in the same flow, an index after it moves up by one once it's taken out)
        if owner == "pool":
            before = shown_keys[:index]
        else:
            before = self._shown(owner)[:index]
        for tier in self.current["tiers"]:
            if key in tier["items"]:
                tier["items"].remove(key)
        if key in self.current["pool"]:
            self.current["pool"].remove(key)
        before = [k for k in before if k != key]
        if owner == "pool":
            pool = self.current["pool"]
            if before:  # right after the shown picture it landed after (hidden ones keep their places)
                pool.insert(pool.index(before[-1]) + 1, key)
            else:
                first = next((k for k in pool if k[0] in self.current["kinds"]), None)
                pool.insert(pool.index(first) if first else 0, key)
            if key[0] not in self.current["kinds"]:  # dropped a picture of a kind that's filtered out: show it
                self.current["kinds"].append(key[0])
                self.kind_buttons[key[0]].setChecked(True)
        else:
            items = owner["items"]  # right after the shown picture it landed after (hidden ones keep their places)
            items.insert(items.index(before[-1]) + 1 if before else 0, key)
        self._changed()
        self._relayout()

    # ----- tiers -----
    def _render_tiers(self):
        layout = self.tiers_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # the pictures inside belong to the page, not to this row: keep them
                for tile in widget.findChildren(Tile):
                    tile.hide()
                    tile.setParent(None)
                widget.hide()
                widget.deleteLater()
        self._tier_rows = []
        tiers = self.current["tiers"]
        for n, tier in enumerate(tiers):
            row = QFrame()
            row.setObjectName("TierRow")
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(0)
            label = TierLabel(tier, self._edit_tier)
            h.addWidget(label)
            flow = Flow(self, tier)
            flow.setObjectName("TierCell")
            flow.setAttribute(Qt.WA_StyledBackground, True)
            h.addWidget(flow, 1)
            arrows = QWidget()
            arrows.setObjectName("TierArrows")
            a = QVBoxLayout(arrows)
            a.setContentsMargins(6, 0, 6, 0)
            a.setSpacing(2)
            for text, step, tip in (("▲", -1, "Move this tier up"), ("▼", 1, "Move this tier down")):
                btn = QToolButton()
                btn.setText(text)
                btn.setObjectName("TierArrow")
                btn.setCursor(Qt.PointingHandCursor)
                btn.setToolTip(tip)
                btn.setEnabled(0 <= n + step < len(tiers))
                btn.clicked.connect(lambda _=False, t=tier, s=step: self._move_tier(t, s))
                a.addWidget(btn)
            h.addWidget(arrows)
            row.tier, row.flow, row.label, row.arrows = tier, flow, label, arrows
            self._tier_rows.append(row)
            layout.addWidget(row)
        self._relayout()

    def _move_tier(self, tier, step):
        tiers = self.current["tiers"]
        n = tiers.index(tier)
        if 0 <= n + step < len(tiers):
            tiers[n], tiers[n + step] = tiers[n + step], tiers[n]
            self._changed()
            self._render_tiers()

    def _edit_tier(self, tier):
        dialog = TierDialog(tier, self)
        if not dialog.exec():
            return
        if dialog.deleted:
            if len(self.current["tiers"]) == 1:
                self.message.emit("A tier list needs at least one tier.")
                return
            self.current["tiers"].remove(tier)
            self.current["pool"] = tier["items"] + self.current["pool"]  # its pictures go back to the grid
        else:
            tier["name"] = dialog.name.text().strip() or tier["name"]
            tier["color"] = dialog.color
        self._changed()
        self._render_tiers()

    def _add_tier(self):
        if self.current is None:
            return
        used = {t["name"] for t in self.current["tiers"]}
        name = next((n for n in ("S", "A", "B", "C", "D", "E", "F") if n not in used), f"Tier {len(used) + 1}")
        self.current["tiers"].append({"name": name, "color": SWATCHES[len(self.current["tiers"]) % len(SWATCHES)],
                                      "items": []})
        self._changed()
        self._render_tiers()

    # ----- a picture of the list -----
    def _capture(self):
        """The title over the tiers, drawn at CAPTURE_COLUMNS pictures a row (whatever the window's width)."""
        self._title_done()
        pad, title_h, gap = 16, 56, 2
        width = LABEL_WIDTH + CAPTURE_COLUMNS * TILE
        name_fonts = {}
        rows = []
        for tier in self.current["tiers"]:
            font = QFont("Segoe UI", 19 if len(tier["name"]) <= 3 else 12, QFont.Bold)
            name_fonts[id(tier)] = font
            text_h = QFontMetrics(font).boundingRect(QRect(0, 0, LABEL_WIDTH - 12, 10000),
                                                     Qt.AlignCenter | Qt.TextWordWrap, tier["name"]).height() + 12
            lines = max(1, -(-len(self._shown(tier)) // CAPTURE_COLUMNS))
            rows.append((tier, max(lines * TILE, text_h)))
        height = sum(h for _, h in rows) + gap * (len(rows) - 1)
        ratio = 2
        image = QImage((width + 2 * pad) * ratio, (height + title_h + pad) * ratio, QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(ratio)
        image.fill(theme.qcolor(0x1c, 0x1d, 0x21))
        p = QPainter(image)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setPen(theme.qcolor(255, 255, 255))
        p.setFont(QFont("Segoe UI", 18, QFont.Bold))
        p.drawText(QRect(pad, 0, width, title_h), Qt.AlignVCenter | Qt.AlignLeft, self.current["title"])
        y = title_h
        for tier, h in rows:
            p.fillRect(QRect(pad, y, LABEL_WIDTH, h), QColor(tier["color"]))
            p.setPen(_ink(tier["color"]))
            p.setFont(name_fonts[id(tier)])
            p.drawText(QRect(pad + 6, y + 6, LABEL_WIDTH - 12, h - 12), Qt.AlignCenter | Qt.TextWordWrap, tier["name"])
            p.fillRect(QRect(pad + LABEL_WIDTH, y, CAPTURE_COLUMNS * TILE, h), theme.qcolor(0x28, 0x29, 0x2f))
            for n, key in enumerate(self._shown(tier)):
                tile = self.tile(key)
                pm = tile.pixmap() if tile is not None else None
                if pm is None or pm.isNull():
                    continue
                x = pad + LABEL_WIDTH + (n % CAPTURE_COLUMNS) * TILE
                p.drawPixmap(QRect(x, y + (n // CAPTURE_COLUMNS) * TILE, TILE, TILE), pm)
            y += h + gap
        p.end()
        return image

    def _copy(self):
        if self.current is None:
            return
        QApplication.clipboard().setImage(self._capture())
        self.message.emit(f"Copied a picture of “{self.current['title']}” to the clipboard")

    def _save_image(self):
        if self.current is None:
            return
        SAVE_DIR.mkdir(exist_ok=True)
        name = re.sub(r'[<>:"/\\|?*]+', "_", self.current["title"]).strip(" .") or "Tier List"
        path = SAVE_DIR / f"{name}.png"
        n = 2
        while path.exists():  # (the suggested name: one that's free in the folder)
            path = SAVE_DIR / f"{name} ({n}).png"
            n += 1
        # ask where (starting in "Saved Tier Lists", or wherever the last one was saved)
        start = pathlib.Path(self.store.get_setting("tier_save_dir", str(SAVE_DIR)))
        if not start.is_dir():
            start = SAVE_DIR
        chosen, _ = QFileDialog.getSaveFileName(self, "Save tier list as PNG", str(start / path.name), "PNG image (*.png)")
        if not chosen:
            return  # cancelled
        if not chosen.lower().endswith(".png"):
            chosen += ".png"
        path = pathlib.Path(chosen)
        self.store.set_setting("tier_save_dir", str(path.parent))
        if self._capture().save(str(path)):
            self.message.emit(f"Saved {path}")
        else:
            self.message.emit(f"Couldn't save {path}")
