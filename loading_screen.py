"""The loading screen shown while Record Book starts: the window is built, the game data loaded, every
picture the pages use decoded, the Buff/Shred List's cards built and each page laid out once, all before
the window appears, so nothing pops in or stutters the first time a page is opened."""

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QProgressBar, QVBoxLayout, QWidget

import gamedata
import theme
from app_info import APP_NAME, VERSION
from widgets import shape_icon

PICTURES_TIMEOUT_S = 25  # past this, the window opens anyway (pictures still loading come in as they arrive)
BUFFS_TIMEOUT_S = 20
SKIPPED_PAGES = {4}  # the character log needs a character; it's laid out when one is opened


class LoadingScreen(QWidget):
    """A small window with the app's name, what's being done and a progress bar."""

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(440, 230)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QFrame()
        panel.setObjectName("LoadingPanel")
        outer.addWidget(panel)
        v = QVBoxLayout(panel)
        v.setContentsMargins(32, 26, 32, 26)
        v.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(shape_icon("book", theme.accent_hex(), 96).pixmap(48, 48))
        v.addWidget(icon, 0, Qt.AlignHCenter)
        title = QLabel(APP_NAME)
        title.setObjectName("LoadingTitle")
        v.addWidget(title, 0, Qt.AlignHCenter)
        version = QLabel(f"v{VERSION}")
        version.setObjectName("LoadingNote")
        v.addWidget(version, 0, Qt.AlignHCenter)
        v.addStretch()
        self.status = QLabel("Starting…")
        self.status.setObjectName("LoadingNote")
        v.addWidget(self.status, 0, Qt.AlignHCenter)
        self.bar = QProgressBar()
        self.bar.setObjectName("LoadingBar")
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setRange(0, 100)
        v.addWidget(self.bar)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center() - self.rect().center())

    def step(self, text, percent):
        self.status.setText(text)
        self.bar.setValue(int(percent))
        QApplication.processEvents()


class Preloader(QObject):
    """Runs the start: build the window, wait for the game data, then preload; finished when it's shown."""

    finished = Signal()

    def __init__(self, make_window):
        super().__init__()
        self.make_window = make_window
        self.screen = LoadingScreen()
        self.window = None

    def start(self):
        self.screen.show()
        self.screen.step("Building pages…", 5)
        self.window = self.make_window()  # (blocks for a moment: the pages are built)
        self.screen.step("Loading game data…", 25)
        if getattr(self.window, "full_index", None):
            self._data_ready(True)
        else:
            self.window.index_ready.connect(self._data_ready)

    # ----- 1: game data -----
    def _data_ready(self, ok):
        try:  # only the first time (Update data loads it again later)
            self.window.index_ready.disconnect(self._data_ready)
        except (RuntimeError, TypeError):
            pass
        if not ok:  # offline: open the window, which says what went wrong
            self._reveal()
            return
        self._load_pictures()

    # ----- 2: pictures -----
    def _picture_urls(self):
        index = self.window.full_index
        urls = {gamedata.element_icon_url(e) for e in gamedata.ELEMENTS}
        urls |= {c.icon for c in index.characters.values()}
        urls |= {w.icon for w in index.weapons.values()}
        urls |= {a.icon for a in index.artifacts.values()}
        for record in self.window.store.characters():  # the DPS Log's and Home's splash art
            info = index.characters.get(record["char_id"])
            if info:
                urls.add(info.splash)
        return [u for u in urls if u]

    def _load_pictures(self):
        urls = self._picture_urls()
        self._left = len(urls)
        self._total = max(1, len(urls))
        if not urls:
            self._build_buffs()
            return
        self.screen.step(f"Loading pictures (0 / {self._total})…", 30)
        for url in urls:
            gamedata.load_pixmap(url, self._picture_done)
        QTimer.singleShot(PICTURES_TIMEOUT_S * 1000, self._pictures_timed_out)

    def _picture_done(self, _pm):
        if self._left <= 0:
            return
        self._left -= 1
        done = self._total - self._left
        if done % 10 == 0 or not self._left:
            self.screen.step(f"Loading pictures ({done} / {self._total})…", 30 + 40 * done / self._total)
        if not self._left:
            QTimer.singleShot(0, self._build_buffs)

    def _pictures_timed_out(self):
        if self._left > 0:
            self._left = 0
            self._build_buffs()

    # ----- 3: the Buff/Shred List's cards -----
    def _build_buffs(self):
        self.screen.step("Building the Buff/Shred List…", 72)
        # the window goes up first, fully see-through behind the loading screen: the cards are then built at
        # the size they'll be shown at (built any smaller, they'd all be laid out again when first shown)
        buffs = self.window.pages[5]
        buffs.start_preload()
        self.window.setWindowOpacity(0.0)
        self.window.setUpdatesEnabled(False)  # nothing to paint while it's unseen (the cards are laid out, not drawn)
        self.window.show()
        self.window.stack.setCurrentIndex(5)  # (only the page on top of the stack gets its real size)
        QApplication.processEvents()
        self.window.stack.setCurrentIndex(0)  # then it's built hidden, at that size
        QApplication.processEvents()
        self._buffs_done = False
        buffs.built.connect(self._buffs_built)
        QTimer.singleShot(BUFFS_TIMEOUT_S * 1000, self._buffs_built)
        buffs.preload()

    def _buffs_built(self):
        if self._buffs_done:
            return
        self._buffs_done = True
        QTimer.singleShot(0, self._lay_out_pages)

    # ----- 4: every page laid out once, unseen -----
    def _lay_out_pages(self):
        """Show the window fully see-through behind the loading screen and open each page once, so the first
        real visit to any of them is instant (Qt styles and lays a page out the first time it's shown)."""
        window = self.window
        pages = [i for i in range(len(window.pages)) if i not in SKIPPED_PAGES]
        for n, index in enumerate(pages):
            self.screen.step("Preparing pages…", 80 + 18 * n / len(pages))
            window.stack.setCurrentIndex(index)
            QApplication.processEvents()
        window.go(0)
        QApplication.processEvents()
        self._reveal()

    def _reveal(self):
        self.screen.step("Ready", 100)
        window = self.window
        window.setUpdatesEnabled(True)
        window.setWindowOpacity(1.0)
        window.show()
        window.raise_()
        window.activateWindow()
        self.screen.close()
        self.finished.emit()
