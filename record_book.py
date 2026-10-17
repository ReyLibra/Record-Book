"""Record Book: log your Genshin Impact characters, builds and DPS.

Run with:  python record_book.py   (or "Record Book.exe", built with build.py)
Data is stored in record_book.db next to the program. Game data comes from
Project Amber (gi.yatta.moe) through ambr-py.
"""

import os
import sys

from PySide6.QtCore import QEvent, QMimeData, QObject, QSize, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import gamedata
from app_info import APP_DIR, APP_NAME, VERSION
from character_page import CharacterPage
from database_pages import BrowsePage
from home_page import HomePage
from log_page import LogPage
from store import Store
from widgets import ACCENT, BAR_BORDER, ICON_SIZE, STYLESHEET, SmoothScroller, shape_icon

PIN_MIME = "application/x-recordbook-pin"
MAX_RECENT_SHOWN = 3


def _discard(widget):
    """Remove a widget from its layout right away (deleteLater alone leaves it visible until idle).

    It must stay parented until Qt deletes it: un-parenting hands it to Python, which frees it the
    moment nothing references it - even when it's the chip whose click is still being handled,
    which crashed the app (access violation).
    """
    from PySide6.QtWidgets import QToolTip

    QToolTip.hideText()
    widget.hide()
    parent = widget.parentWidget()
    if parent is not None and parent.layout() is not None:
        parent.layout().removeWidget(widget)
    widget.deleteLater()


# ---------- left navigation ----------
class NavPanel(QFrame):
    navigate = Signal(int)
    update_requested = Signal()

    COLLAPSED_WIDTH = 60

    def __init__(self):
        super().__init__()
        self.setObjectName("NavPanel")
        self.collapsed = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 14, 0, 14)
        layout.setSpacing(2)

        self.group = QButtonGroup(self)
        self.buttons = []
        self.section = QLabel("DATABASE")
        self.section.setObjectName("NavSection")
        self.rule = QFrame()
        self.rule.setFrameShape(QFrame.HLine)
        self.rule.setStyleSheet(f"color: {BAR_BORDER};")

        entries = [(0, "house", "Home"), None, (1, "circle", "Characters"), (2, "square", "Weapons"), (3, "triangle", "Artifacts")]
        for entry in entries:
            if entry is None:
                layout.addWidget(self.rule)
                layout.addWidget(self.section)
                continue
            index, shape, text = entry
            btn = QPushButton(shape_icon(shape, "#d8d9db"), text)
            btn.setIconSize(ICON_SIZE)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(text)
            btn.setProperty("label", text)
            btn.setProperty("shape", shape)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.toggled.connect(lambda on, b=btn: self._recolor(b, on))
            self.group.addButton(btn, index)
            self.buttons.append(btn)
            layout.addWidget(btn)
        layout.addStretch()
        # fetch new characters / weapons / artifacts (not part of the page group)
        self.update_button = QPushButton(shape_icon("refresh", "#d8d9db"), "Update data")
        self.update_button.setIconSize(ICON_SIZE)
        self.update_button.setCursor(Qt.PointingHandCursor)
        self.update_button.setToolTip("Fetch the latest characters, weapons and artifacts")
        self.update_button.setProperty("label", "Update data")
        self.update_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.update_button.clicked.connect(self.update_requested)
        layout.addWidget(self.update_button)
        self.group.idClicked.connect(self.navigate)
        self.buttons[0].setChecked(True)

    def set_updating(self, busy):
        self.update_button.setEnabled(not busy)
        label = "Updating…" if busy else "Update data"
        self.update_button.setProperty("label", label)
        if not self.collapsed:
            self.update_button.setText(label)

    @staticmethod
    def _recolor(btn, active):
        """The current page's icon turns blue with its label, like Prydwen's sidebar."""
        btn.setIcon(shape_icon(btn.property("shape"), ACCENT if active else "#d8d9db"))

    def set_current(self, index):
        self.group.button(index).setChecked(True)

    def set_collapsed(self, collapsed):
        self.collapsed = collapsed
        for btn in self.buttons + [self.update_button]:
            btn.setText("" if collapsed else btn.property("label"))
        self.section.setVisible(not collapsed)


# ---------- header: title, pinned and recent characters ----------
class Chip(QFrame):
    """A character name with a pin button. Pinned chips can be dragged to reorder."""

    clicked = Signal(str)
    pin_toggled = Signal(str)

    def __init__(self, char_id, name, pinned):
        super().__init__()
        self.char_id = char_id
        self.pinned = pinned
        self._press = None
        self.setObjectName("Chip")
        self.setProperty("pinned", "true" if pinned else "false")
        self.setCursor(Qt.OpenHandCursor if pinned else Qt.PointingHandCursor)
        self.setToolTip("Drag to reorder · click to open" if pinned else "Click to open")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 3, 4, 3)
        layout.setSpacing(2)
        label = QLabel(name)
        label.setAttribute(Qt.WA_TransparentForMouseEvents)
        pin = QToolButton()
        pin.setObjectName("ChipPin")
        pin.setIcon(shape_icon("pin", ACCENT if pinned else "#8c909b"))
        pin.setIconSize(QSize(14, 14))
        pin.setCursor(Qt.PointingHandCursor)
        pin.setToolTip("Unpin" if pinned else "Pin to the left")
        pin.clicked.connect(lambda: self.pin_toggled.emit(self.char_id))
        layout.addWidget(label)
        layout.addWidget(pin)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press = event.position().toPoint()

    def mouseMoveEvent(self, event):
        if not (self.pinned and self._press and event.buttons() & Qt.LeftButton):
            return
        if (event.position().toPoint() - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        self._press = None
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(PIN_MIME, self.char_id.encode())
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.setHotSpot(event.position().toPoint())
        drag.exec(Qt.MoveAction)

    def mouseReleaseEvent(self, event):
        if self._press is not None and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.char_id)
        self._press = None


class PinBar(QWidget):
    """Holds the pinned chips and accepts drops to reorder them."""

    reordered = Signal(list)  # new order of char_ids

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.layout_ = QHBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(6)
        self.chips = []

    def set_chips(self, chips):
        for chip in self.chips:
            _discard(chip)
        self.chips = chips
        for chip in chips:
            self.layout_.addWidget(chip)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(PIN_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(PIN_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event):
        dragged = bytes(event.mimeData().data(PIN_MIME)).decode()
        x = event.position().x()
        order = [c.char_id for c in self.chips if c.char_id != dragged]
        others = [c for c in self.chips if c.char_id != dragged]
        insert_at = sum(1 for c in others if c.geometry().center().x() < x)
        order.insert(insert_at, dragged)
        event.acceptProposedAction()
        self.reordered.emit(order)


class Header(QFrame):
    toggle_nav = Signal()
    open_character = Signal(str)

    def __init__(self, store):
        super().__init__()
        self.setObjectName("Header")
        self.store = store
        self.pins = store.get_setting("pins", [])  # [{"id", "name"}], in display order
        self.recent = store.get_setting("recent", [])  # [{"id", "name"}], newest first

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 16, 8)
        layout.setSpacing(6)

        top = QHBoxLayout()
        toggle = QToolButton()
        toggle.setObjectName("NavToggle")
        toggle.setText("☰")
        toggle.setCursor(Qt.PointingHandCursor)
        toggle.setToolTip("Show or hide the navigation panel")
        toggle.clicked.connect(self.toggle_nav)
        title = QLabel("Record Book")
        title.setObjectName("Title")
        top.addWidget(toggle)
        top.addWidget(title)
        top.addStretch()

        bottom = QHBoxLayout()
        bottom.setContentsMargins(6, 0, 0, 0)
        self.pin_bar = PinBar()
        self.pin_bar.reordered.connect(self._reordered)
        self.recent_row = QHBoxLayout()
        self.recent_row.setSpacing(6)
        self.hint = QLabel()
        self.hint.setObjectName("HeaderHint")
        bottom.addWidget(self.pin_bar)
        bottom.addStretch()
        bottom.addWidget(self.hint)
        bottom.addLayout(self.recent_row)

        layout.addLayout(top)
        layout.addLayout(bottom)
        self._recent_chips = []
        self.rebuild()

    def visit(self, char_id, name):
        self.recent = [{"id": char_id, "name": name}] + [r for r in self.recent if r["id"] != char_id]
        self.recent = self.recent[:10]
        self.store.set_setting("recent", self.recent)
        self.rebuild()

    def forget(self, char_id):
        """Drop a character from pins and recents (e.g. after it is removed)."""
        self.pins = [p for p in self.pins if p["id"] != char_id]
        self.recent = [r for r in self.recent if r["id"] != char_id]
        self._save()
        self.rebuild()

    def _toggle_pin(self, char_id):
        if any(p["id"] == char_id for p in self.pins):
            self.pins = [p for p in self.pins if p["id"] != char_id]
        else:
            name = next((r["name"] for r in self.recent if r["id"] == char_id), char_id)
            self.pins.append({"id": char_id, "name": name})
        self._save()
        self.rebuild()

    def _reordered(self, order):
        by_id = {p["id"]: p for p in self.pins}
        self.pins = [by_id[i] for i in order if i in by_id]
        self._save()
        self.rebuild()

    def _save(self):
        self.store.set_setting("pins", self.pins)
        self.store.set_setting("recent", self.recent)

    def _chip(self, entry, pinned):
        chip = Chip(entry["id"], entry["name"], pinned)
        chip.clicked.connect(self.open_character)
        chip.pin_toggled.connect(self._toggle_pin)
        return chip

    def rebuild(self):
        self.pin_bar.set_chips([self._chip(p, True) for p in self.pins])
        for chip in self._recent_chips:
            _discard(chip)
        pinned_ids = {p["id"] for p in self.pins}
        recent = [r for r in self.recent if r["id"] not in pinned_ids][:MAX_RECENT_SHOWN]
        self._recent_chips = [self._chip(r, False) for r in recent]
        for chip in self._recent_chips:
            self.recent_row.addWidget(chip)
        self.hint.setText("Recently visited:" if recent else "Characters you visit will show up here")


class Footer(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("Footer")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 5, 16, 5)
        self.status = QLabel("")
        self.count = QLabel("")
        source = QLabel(f"Game data: Project Amber (gi.yatta.moe)  ·  v{VERSION}")
        layout.addWidget(self.status)
        layout.addStretch()
        layout.addWidget(self.count)
        layout.addSpacing(20)
        layout.addWidget(source)


# ---------- main window ----------
class MainWindow(QMainWindow):
    def __init__(self, store):
        super().__init__()
        self.store = store
        self.setWindowTitle(f"{APP_NAME} {VERSION}")
        self.setWindowIcon(shape_icon("book", ACCENT, 64))
        self.resize(1440, 860)
        self.setMinimumSize(1100, 700)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.nav = NavPanel()
        self.header = Header(store)
        self.footer = Footer()
        self.home = HomePage(store)
        self.pages = [
            self.home,
            CharacterPage(store),
            BrowsePage("weapon", store),
            BrowsePage("artifact", store),
            LogPage(store),  # not in the nav: opened from a character's name on Home
        ]
        self.log_page = self.pages[4]
        self.stack = QStackedWidget()
        for page in self.pages:
            self.stack.addWidget(page)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self.header)
        right.addWidget(self.stack, 1)
        right.addWidget(self.footer)
        outer.addWidget(self.nav)
        outer.addLayout(right, 1)

        self.nav.navigate.connect(self.go)
        self.nav.update_requested.connect(self.update_data)
        self.header.toggle_nav.connect(self.toggle_nav)
        self.header.open_character.connect(self.open_character)
        self.home.visited.connect(self.visit)
        self.home.message.connect(self.footer.status.setText)
        self.home.roster_changed.connect(self.roster_changed)
        self.home.removed.connect(self.header.forget)
        self.home.open_log.connect(self.open_log)
        self.log_page.back_home.connect(lambda: self.go(0))
        self.log_page.open_guide.connect(self.open_guide)
        self.log_page.changed.connect(self._log_changed)
        self.home.banners.open_character.connect(self.open_guide)
        self.home.banners.open_weapon.connect(self.open_weapon)
        characters_page = self.pages[1]
        characters_page.visited.connect(self.visit)
        characters_page.add_requested.connect(self.add_from_database)
        characters_page.open_home.connect(self.open_character)
        characters_page.open_log.connect(self.open_log)
        for page in self.pages[1:]:
            page.message.connect(self.footer.status.setText)

        self.roster_changed()
        self.footer.status.setText("Loading game data…")
        gamedata.run_async(gamedata.fetch_index, self.index_loaded)

    def index_loaded(self, index, error):
        if error:
            self.footer.status.setText(f"Couldn't load game data (check your internet connection): {error}")
            return
        self.index = index
        for page in self.pages:
            page.set_index(index)
        self.footer.status.setText(
            f"Loaded {len(index.characters)} characters, {len(index.weapons)} weapons, {len(index.artifacts)} artifact sets"
        )

    def update_data(self):
        """Nav 'Update data': re-download the game lists, then tell every page; reports what's new."""
        old = getattr(self, "index", None)
        self.nav.set_updating(True)
        self.footer.status.setText("Updating game data…")

        def done(index, error):
            self.nav.set_updating(False)
            if error:
                self.footer.status.setText(f"Couldn't update game data (check your internet connection): {error}")
                return
            self.index_loaded(index, None)
            if old:
                new = [
                    f"{len(set(getattr(index, k)) - set(getattr(old, k)))} {label}"
                    for k, label in (("characters", "characters"), ("weapons", "weapons"), ("artifacts", "artifact sets"))
                ]
                self.footer.status.setText(f"Game data updated · new: {', '.join(new)}")

        gamedata.run_async(gamedata.refresh_index, done)

    def go(self, index):
        if index == 1:  # entering Characters always starts at the all-characters grid
            self.pages[1].show_grid()
        self.stack.setCurrentIndex(index)
        self.nav.set_current(index if index < 4 else 0)  # the character log belongs to Home
        crumbs = getattr(QApplication.instance(), "breadcrumbs", None)
        if crumbs:
            crumbs.note(f"page   {type(self.pages[index]).__name__}")

    def open_log(self, char_id):
        self.log_page.show_character(char_id)
        self.go(4)

    def _log_changed(self):
        self.home.reload_roster()
        self.home.refresh_card()
        self.roster_changed()

    def toggle_nav(self):
        self.nav.set_collapsed(not self.nav.collapsed)
        self._size_nav()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._size_nav()

    def _size_nav(self):
        if self.nav.collapsed:
            width = NavPanel.COLLAPSED_WIDTH
        else:  # 10% of the window, but never clipping "Update data"
            width = max(130, round(self.width() * 0.10), self.nav.update_button.sizeHint().width())
        self.nav.setFixedWidth(width)

    def visit(self, char_id):
        record = self.store.character(char_id)
        info = getattr(self, "index", None) and self.index.characters.get(char_id)
        name = (record and record["name"]) or (info and info.name) or char_id
        self.header.visit(char_id, name)

    def open_guide(self, char_id):
        """A character's page on the Characters tab (from the Home banners)."""
        self.go(1)
        self.pages[1].show_item(char_id)

    def open_weapon(self, weapon_id):
        self.go(2)
        self.pages[2].show_item(weapon_id)

    def open_character(self, char_id):
        if self.store.character(char_id):
            self.go(0)
            self.home.select(char_id)
        else:
            self.go(1)
            self.pages[1].show_item(char_id)

    def add_from_database(self, char_id):
        self.go(0)
        self.home.start_add(char_id)

    def roster_changed(self):
        n = len(self.store.characters())
        self.footer.count.setText(f"{n} character{'s' if n != 1 else ''} logged")
        self.pages[1].refresh_detail()


def _log_crashes():
    """Write native crashes and uncaught errors to crash.log next to the app, so a silent exit leaves
    a trace (without this a crash inside Qt just closes the window)."""
    import faulthandler
    import traceback
    from datetime import datetime
    from pathlib import Path

    path = APP_DIR / "crash.log"
    try:  # keep the file small: only the most recent lines
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > 3000:
            path.write_text("\n".join(lines[-1500:]) + "\n", encoding="utf-8")
    except OSError:
        pass
    log = open(path, "a", encoding="utf-8")
    log.write(f"\n--- started {datetime.now():%Y-%m-%d %H:%M:%S} ---\n")
    log.flush()
    faulthandler.enable(file=log, all_threads=True)

    def excepthook(kind, value, tb):
        log.write(f"{datetime.now():%H:%M:%S} uncaught error:\n{''.join(traceback.format_exception(kind, value, tb))}")
        log.flush()
        sys.__excepthook__(kind, value, tb)

    sys.excepthook = excepthook
    return log


class _Breadcrumbs(QObject):
    """Writes a short line to crash.log for every click and opened popup, so if the app ever crashes
    inside Qt (where there's no Python traceback) the log still shows what was done just before."""

    def __init__(self, log, parent=None):
        super().__init__(parent)
        self.log = log

    def note(self, text):
        from datetime import datetime

        self.log.write(f"{datetime.now():%H:%M:%S}  {text}\n")
        self.log.flush()

    @staticmethod
    def describe(obj):
        name = type(obj).__name__
        label = obj.objectName() or ""
        text = obj.text() if hasattr(obj, "text") and callable(obj.text) else ""
        if isinstance(text, str) and text:
            label = f"{label} '{text[:40]}'".strip()
        parent = obj.parent()
        owner = type(parent).__name__ if parent is not None else ""
        return f"{name} {label} (in {owner})".replace("  ", " ")

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.Type.MouseButtonRelease and isinstance(obj, QWidget):
            # a click is passed up to each parent that ignores it; note only the widget clicked
            if event.timestamp() != getattr(self, "_last_click", None):
                self._last_click = event.timestamp()
                self.note(f"click  {self.describe(obj)}")
        elif kind == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow() and obj.windowType() in (Qt.Popup, Qt.Dialog):
            self.note(f"popup  {self.describe(obj)}")
        return False


def main():
    # ambr-py keeps a small cache in "./.cache"; make "." the app's folder however it was started
    os.chdir(APP_DIR)
    _crash_log = _log_crashes()  # keep the file open for the app's lifetime
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setStyleSheet(STYLESHEET)
    scroller = SmoothScroller(app)
    app.installEventFilter(scroller)
    breadcrumbs = _Breadcrumbs(_crash_log, app)
    app.installEventFilter(breadcrumbs)
    app.breadcrumbs = breadcrumbs  # MainWindow.go() notes page changes through this
    window = MainWindow(Store())
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
