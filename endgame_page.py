"""End Game page: Spiral Abyss, Stygian Onslaught and Imaginarium Theater, one at a time.

Each opens on what's live now (highlighted in green, with a LIVE tag). "View all" lists every past one,
and the upcoming ones (dates To Be Decided, line-ups from the test server) when unreleased content is
shown in Settings. Dates are in the chosen server's time.
"""

from datetime import timedelta

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import endgame
import gamedata
import servers
import theme
from dialogs import Popup
from widgets import ColumnGrid, RemoteIcon, card_pixmap, clear_layout, filter_button, section_header

MODES = [("abyss", "Spiral Abyss"), ("stygian", "Stygian Onslaught"), ("theater", "Imaginarium Theater")]
FLOORS = [9, 10, 11, 12]
CARD_MIN_WIDTH = 300  # a chamber / act / opponent card: two side by side when there's room
MONSTER_ICON = 40
THEATER_MONSTER_ICON = 80  # the Theater's opponents, bigger
STYGIAN_ART = 260  # a Stygian opponent's picture height
PORTRAIT = 64


def date_text(day):
    return f"{day:%b} {day.day}, {day.year}"


def entry_title(mode, entry):
    if mode == "theater":
        return f"Season {entry['season']}"
    if mode == "stygian":
        return f"{entry['name']}  ·  {entry['version']}" if not entry["name"].startswith("Version") else entry["name"]
    return entry["name"]


def dates(entry, server):
    """'Oct 16, 2026 – Nov 16, 2026', or TBD for one that hasn't started (its dates are placeholders)."""
    if entry.get("status") == "upcoming":
        return "TBD"
    return f"{date_text(entry['start'])} – {date_text(entry['end'] + timedelta(seconds=1))}"


def tag(text, kind):
    """A small LIVE (green) or TESTING (amber) tag."""
    label = QLabel(text)
    label.setObjectName("LiveTag" if kind == "live" else "TestTag")
    label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    return label


def _rich(text):
    label = QLabel(gamedata.rich_html(text or ""))
    label.setWordWrap(True)
    label.setTextFormat(Qt.RichText)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    label.setObjectName("EndGameText")
    return label


def _muted(text):
    label = QLabel(text)
    label.setObjectName("EndGameMuted")
    label.setWordWrap(True)
    return label


def _box(name="EndGameCard"):
    box = QFrame()
    box.setObjectName(name)
    v = QVBoxLayout(box)
    v.setContentsMargins(16, 14, 16, 14)
    v.setSpacing(8)
    return box, v


def _heading(text):
    label = QLabel(text)
    label.setObjectName("EndGameHeading")
    return label


class AllEntriesDialog(Popup):
    """Every Abyss / Stygian / Theater entry, newest first: click one to open it."""

    def __init__(self, mode, entries, server, current, parent=None):
        super().__init__(parent, f"All {dict(MODES)[mode]}", 520, 640)
        self.chosen = None
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        rows = QVBoxLayout(host)
        rows.setContentsMargins(0, 0, 6, 0)
        rows.setSpacing(4)
        for entry in reversed(entries):
            row = QPushButton()
            row.setObjectName("EntryRow")
            row.setProperty("live", "true" if entry["status"] == "live" else "false")
            row.setProperty("current", "true" if entry is current else "false")
            row.setCursor(Qt.PointingHandCursor)
            h = QHBoxLayout(row)
            h.setContentsMargins(12, 6, 12, 6)
            name = QLabel(entry_title(mode, entry))
            name.setStyleSheet("font-weight: 700;")
            h.addWidget(name)
            for element in entry.get("elements") or []:  # a Theater season's three elements
                icon = RemoteIcon(20)
                icon.set_url(gamedata.element_icon_url(element))
                icon.setToolTip(gamedata.pretty(element))
                h.addWidget(icon)
            if entry["status"] == "live":
                h.addWidget(tag("LIVE", "live"))
            elif entry["status"] == "upcoming":
                h.addWidget(tag("TESTING", "test"))
            h.addStretch()
            h.addWidget(_muted(dates(entry, server)))
            for w in row.findChildren(QWidget):
                w.setAttribute(Qt.WA_TransparentForMouseEvents)
            row.setMinimumHeight(40)
            row.clicked.connect(lambda _=False, e=entry: self._pick(e))
            rows.addWidget(row)
        rows.addStretch()
        scroll.setWidget(host)
        self.body.addWidget(scroll, 1)
        if current is not None:
            QTimer.singleShot(0, lambda: scroll.ensureWidgetVisible(
                next((r for r in host.findChildren(QPushButton) if r.property("current") == "true"), host)))

    def _pick(self, entry):
        self.chosen = entry
        self.accept()


class EndGamePage(QWidget):
    message = Signal(str)
    server_changed = Signal(str)
    loaded = Signal()  # the schedules are in (or their live entries changed): Home's timers follow

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.index = None
        self.full_index = None
        self.server = store.get_setting("server", servers.DEFAULT)
        self.show_upcoming = bool(store.get_setting("show_unreleased", False))
        self.mode = store.get_setting("endgame_mode", "abyss")
        self.data = None  # {"abyss": [...], ...} once loaded
        self.selected = {}  # mode -> entry shown
        self.floor = 12
        self.level = {"stygian": "Dire", "theater": None}  # Theater: its hardest by default
        self._details = {}  # (mode, id) -> detail
        self._loading = False
        self.moe = {}  # stygian.moe's current bosses: {name: {"url", "tldr"}}
        self._stygian_level = None

        v = QVBoxLayout(self)
        v.setContentsMargins(28, 22, 28, 20)
        v.setSpacing(14)
        head, self.note = section_header("End Game")
        v.addWidget(head)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.mode_group = QButtonGroup(self)
        for key, text in MODES:
            btn = filter_button(text)
            btn.setChecked(key == self.mode)
            self.mode_group.addButton(btn)
            btn.clicked.connect(lambda _=False, k=key: self.set_mode(k))
            bar.addWidget(btn)
        bar.addStretch()
        self.all_button = QPushButton("View all")
        self.all_button.setCursor(Qt.PointingHandCursor)
        self.all_button.setToolTip("Every past one (and the upcoming ones when unreleased content is shown)")
        self.all_button.clicked.connect(self._view_all)
        bar.addWidget(self.all_button)
        bar.addSpacing(8)
        bar.addWidget(_muted("Server"))
        self.server_box = QComboBox()
        self.server_box.addItems([name for name, _ in servers.SERVERS])
        self.server_box.setCurrentText(self.server)
        self.server_box.setToolTip("Dates and timers follow this server's clock")
        self.server_box.currentTextChanged.connect(self._server_picked)
        bar.addWidget(self.server_box)
        v.addLayout(bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.content = QWidget()
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(0, 0, 8, 0)
        self.body.setSpacing(14)
        self.scroll.setWidget(self.content)
        v.addWidget(self.scroll, 1)
        self.body.addWidget(_muted("Loading…"))

    # ----- outside -----
    def set_index(self, index):
        self.index = index
        if self.data is None and not self._loading:
            self._load()

    def set_full_index(self, index):
        self.full_index = index

    def set_unreleased(self, show):
        self.show_upcoming = show
        if self.data is not None:
            if not show:  # an upcoming one on screen goes back to the live one
                for mode, entry in list(self.selected.items()):
                    if entry and entry["status"] == "upcoming":
                        self.selected.pop(mode)
            self._render()

    def set_server(self, server):
        if server == self.server:
            return
        self.server = server
        self.server_box.blockSignals(True)
        self.server_box.setCurrentText(server)
        self.server_box.blockSignals(False)
        if self.data is not None:
            self._mark()
            self._render()

    def _server_picked(self, server):
        self.server = server
        self.store.set_setting("server", server)
        self.server_changed.emit(server)
        if self.data is not None:
            self._mark()
            self._render()

    def _load(self):
        self._loading = True
        gamedata.run_async(endgame.fetch_all, self._loaded)

        def moe(bosses, error):
            self.moe = bosses or {}
            if self.data is not None and self.mode == "stygian":
                self._render()

        gamedata.run_async(endgame.fetch_stygian_moe, moe)

    def _loaded(self, data, error):
        self._loading = False
        if error or not data:
            clear_layout(self.body)
            self.body.addWidget(_muted(f"Couldn't load the End Game schedules from Lunaris: {error}"))
            return
        self.data = data
        self._mark()
        self._render()

    def _mark(self):
        now = servers.now(self.server).replace(tzinfo=None)
        for entries in self.data.values():
            endgame.mark(entries, now)
        self.loaded.emit()

    # ----- choosing what's shown -----
    def set_mode(self, mode):
        self.mode = mode
        self.store.set_setting("endgame_mode", mode)
        for btn, (key, _) in zip(self.mode_group.buttons(), MODES):
            btn.setChecked(key == mode)
        self._render()

    def _entries(self, mode=None):
        entries = (self.data or {}).get(mode or self.mode) or []
        return [e for e in entries if self.show_upcoming or e["status"] != "upcoming"]

    def current(self, mode=None):
        """The entry shown for a mode: the one picked in View all, else the live one (else the newest)."""
        mode = mode or self.mode
        entries = self._entries(mode)
        picked = self.selected.get(mode)
        if picked in entries:
            return picked
        return next((e for e in entries if e["status"] == "live"), entries[-1] if entries else None)

    def _view_all(self):
        if not self.data:
            return
        dialog = AllEntriesDialog(self.mode, self._entries(), self.server, self.current(), self)
        if dialog.exec() and dialog.chosen:
            self.selected[self.mode] = dialog.chosen
            self._render()

    # ----- drawing -----
    def _render(self):
        clear_layout(self.body)
        entry = self.current()
        self.note.setText(f"Times in {self.server} server time")
        if entry is None:
            self.body.addWidget(_muted("Nothing to show yet."))
            self.body.addStretch()
            return
        key = (self.mode, entry["id"])
        if self.mode == "stygian":
            self._show_stygian(entry)
        elif key in self._details:
            self._show_detail(entry, self._details[key])
        else:
            self.body.addWidget(self._header(entry))
            self.body.addWidget(_muted("Loading the line-up…"))
            self.body.addStretch()
            fetch = endgame.fetch_abyss if self.mode == "abyss" else endgame.fetch_theater
            mode = self.mode

            def done(detail, error, key=key, mode=mode):
                self._details[key] = detail or {"error": str(error)}
                if self.mode == mode and self.current() is entry:
                    self._render()

            gamedata.run_async(lambda: fetch(entry["id"]), done)

    def _show_detail(self, entry, detail):
        if detail.get("error"):
            self.body.addWidget(self._header(entry))
            self.body.addWidget(_muted("Couldn't load this line-up from Lunaris."))
            self.body.addStretch()
            return
        if self.mode == "abyss":
            self._show_abyss(entry, detail)
        else:
            self._show_theater(entry, detail)

    def _header(self, entry, image_url=None, description=None, extra=None, beside=None):
        """The entry's name, dates, LIVE / TESTING tag and time left, with its picture on the left."""
        box = QFrame()
        box.setObjectName("EndGameHeader")
        box.setProperty("live", "true" if entry["status"] == "live" else "false")
        row = QHBoxLayout(box)
        row.setContentsMargins(16, 14, 16, 14)
        row.setSpacing(16)
        if image_url:
            pic = QLabel()
            pic.setFixedSize(240, 120)
            pic.setObjectName("EndGameArt")

            def loaded(pm, pic=pic):
                if pm is not None:
                    pic.setPixmap(pm.scaled(pic.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                                  .copy(0, 0, pic.width(), pic.height()))

            gamedata.load_pixmap(image_url, loaded)
            row.addWidget(pic, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title = QLabel(entry_title(self.mode, entry))
        title.setObjectName("EndGameTitle")
        title_row.addWidget(title)
        if beside is not None:  # (the Theater season's elements)
            title_row.addWidget(beside, 0, Qt.AlignVCenter)
        if entry["status"] == "live":
            title_row.addWidget(tag("LIVE", "live"), 0, Qt.AlignVCenter)
        elif entry["status"] == "upcoming":
            title_row.addWidget(tag("TESTING", "test"), 0, Qt.AlignVCenter)
        title_row.addStretch()
        text.addLayout(title_row)
        when = dates(entry, self.server)
        if entry["status"] == "live":
            end = endgame.to_utc(entry["end"], servers.offset(self.server))
            when += f"   ·   ends in {servers.countdown(end)}"
        text.addWidget(_muted(when))
        if extra is not None:
            text.addWidget(extra)
        if description:
            text.addWidget(_rich(description))
        text.addStretch()
        row.addLayout(text, 1)
        return box

    def _choice_row(self, label, options, current, on_pick):
        """A row of exclusive filter buttons (floors, difficulties)."""
        row = QHBoxLayout()
        row.setSpacing(4)
        if label:
            row.addWidget(_muted(label))
            row.addSpacing(4)
        group = QButtonGroup(self.content)
        for value, text in options:
            btn = filter_button(text)
            btn.setChecked(value == current)
            group.addButton(btn)
            btn.clicked.connect(lambda _=False, v=value: on_pick(v))
            row.addWidget(btn)
        row.addStretch()
        return row

    def _monster(self, icon_url, name, note, size=MONSTER_ICON):
        row = QHBoxLayout()
        row.setSpacing(8)
        pic = RemoteIcon(size)
        pic.set_url(icon_url)
        pic.setObjectName("MonsterIcon")
        row.addWidget(pic, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(0)
        label = QLabel(name)
        label.setWordWrap(True)
        label.setStyleSheet("font-weight: 600;")
        text.addWidget(label)
        if note:
            text.addWidget(_muted(note))
        row.addLayout(text, 1)
        holder = QWidget()  # its own height: rows don't spread out when a column is taller
        holder.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        holder.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        wrap = QVBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.addWidget(holder)
        return wrap

    def _cards(self, cards):
        """Cards two to a row when there's room (one when the window is narrow)."""
        if len(cards) == 1:
            return cards[0]
        return ColumnGrid(cards, spacing=12, min_column_width=CARD_MIN_WIDTH)

    @staticmethod
    def _columns(cards):
        """Cards side by side in equal columns (the Abyss's three chambers, Stygian's three opponents)."""
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        for card in cards:
            card.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
            row.addWidget(card, 1, Qt.AlignTop)  # each as tall as its content
        return holder

    def _character_info(self, char_id):
        for index in (self.full_index, self.index):
            if index is None:
                continue
            info = index.characters.get(char_id) or index.characters.get(str(char_id))
            if info is None and str(char_id).isdigit():
                info = index.characters.get(int(char_id))
            if info:
                return info
        return None

    def _portraits(self, char_ids, size=PORTRAIT):
        row = QHBoxLayout()
        row.setSpacing(6)
        for char_id in char_ids:
            info = self._character_info(char_id)
            if info is None:
                continue
            pic = QLabel()
            pic.setFixedSize(size, size)
            pic.setToolTip(info.name)

            def with_element(element_pm, pic=pic, info=info):
                def with_icon(pm):
                    card = card_pixmap(pm, element_pm, info.rarity, size)
                    card.setDevicePixelRatio(2)
                    pic.setPixmap(card)

                gamedata.load_pixmap(info.icon, with_icon)

            gamedata.load_pixmap(gamedata.element_icon_url(info.element), with_element)
            row.addWidget(pic)
        row.addStretch()
        return row

    # ----- Spiral Abyss -----
    def _show_abyss(self, entry, detail):
        blessing = (detail.get("monthlyBuff") or {}).get("description")
        self.body.addWidget(self._header(entry, endgame.blessing_icon(detail.get("icon") or entry.get("icon")),
                                         blessing))
        floors = {f["floorIndex"]: f for f in detail.get("floors") or []}
        options = [(n, f"Floor {n}") for n in FLOORS if n in floors]
        if not options:
            self.body.addWidget(_muted("No floor line-ups for this one yet."))
            self.body.addStretch()
            return
        if self.floor not in floors:
            self.floor = options[-1][0]
        self.body.addLayout(self._choice_row("", options, self.floor, self._pick_floor))
        floor = floors[self.floor]
        disorders = [(label, (floor.get(key) or {}).get("description"))
                     for label, key in (("Ley Line Disorder", "floorLevelConfig"), ("First Half", "firstHalfBuff"),
                                        ("Second Half", "secondHalfBuff"))]
        disorders = [(label, text) for label, text in disorders if text]
        if disorders:
            box, v = _box()
            for label, text in disorders:
                v.addWidget(_heading(label.upper()))
                v.addWidget(_rich(text))
            self.body.addWidget(box)
        cards = []
        for n, chamber in enumerate(floor.get("chambers") or [], 1):
            box, v = _box()
            v.addWidget(_heading(f"CHAMBER {n}  ·  LV. {chamber.get('monsterLevel', '?')}"))
            stars = [c.get("value") for c in chamber.get("conditions") or [] if c.get("completionCondition") == "timeRemaining"]
            if stars:
                v.addWidget(_muted("   ".join(f"{'★' * (i + 1)} {s // 60}:{s % 60:02d} left" for i, s in enumerate(stars))))
            for half, key in (("First Half", "firstHalfMonsters"), ("Second Half", "secondHalfMonsters")):
                monsters = chamber.get(key) or []
                if not monsters:
                    continue
                if key == "secondHalfMonsters":  # a line between the two halves
                    rule = QFrame()
                    rule.setObjectName("HalfDivider")
                    rule.setFixedHeight(1)
                    v.addSpacing(4)
                    v.addWidget(rule)
                v.addSpacing(4)
                v.addWidget(_muted(half))
                for m in monsters:
                    v.addLayout(self._monster(endgame.monster_icon(m.get("icon")), m.get("name", "?"),
                                              f"HP {m['hp']:,.0f}" if m.get("hp") else ""))
            v.addStretch()
            cards.append(box)
        if cards:
            self.body.addWidget(self._columns(cards))
        self.body.addStretch()

    def _pick_floor(self, floor):
        self.floor = floor
        self._render()

    # ----- Imaginarium Theater -----
    def _show_theater(self, entry, detail):
        config = detail.get("avatarConfig") or {}
        elements = QHBoxLayout()
        elements.setSpacing(6)
        for element in entry.get("elements") or []:
            icon = RemoteIcon(26)
            icon.set_url(gamedata.element_icon_url(element))
            icon.setToolTip(gamedata.pretty(element))
            elements.addWidget(icon)
        elements.setContentsMargins(0, 0, 0, 0)
        holder = QWidget()
        holder.setLayout(elements)
        self.body.addWidget(self._header(entry, beside=holder))

        people, v = _box()
        if config.get("featuredAvatars"):
            v.addWidget(_heading("OPENING CHARACTERS"))
            v.addLayout(self._portraits(config["featuredAvatars"]))
        guests = config.get("bonusAvatars") or []
        if guests:
            v.addSpacing(6)
            v.addWidget(_heading("SPECIAL GUEST STARS"))
            v.addLayout(self._portraits([g["avatarId"] for g in guests]))
            v.addWidget(_rich(guests[0].get("description", "")))
        self.body.addWidget(people)

        levels = detail.get("difficultyConfig") or {}
        options = [(k, endgame.THEATER_LEVELS.get(str(k), f"Difficulty {k}")) for k in sorted(levels, key=int)]
        if not options:
            self.body.addStretch()
            return
        if self.level["theater"] not in levels:
            self.level["theater"] = options[-1][0]
        self.body.addLayout(self._choice_row("", options, self.level["theater"], self._pick_theater_level))
        level = levels[self.level["theater"]]
        self.body.addWidget(_muted(
            f"{level.get('roomCount', '?')} acts  ·  characters Lv. {level.get('minAvatarLevel', '?')}+  ·  "
            f"{level.get('invitePoolSize', '?')} trial characters"))
        rooms = level.get("rooms") or {}
        hard = level.get("hardRooms") or {}
        cards, lunar = [], []  # (the Lunar Stages go first)
        stage = 0
        for act in sorted(set(rooms) | set(hard), key=int):
            for room, hard_room in ((rooms.get(act), False), (hard.get(act), True)):
                if not room or not room.get("bossName"):
                    continue  # an act of regular opponents
                if hard_room:  # the hardest difficulty's extra stages, in the order they come
                    stage += 1
                    label = f"LUNAR STAGE {stage}"
                else:
                    label = f"ACT {act}"
                box, v = _box()
                v.addWidget(_heading(f"{label}  ·  LV. {room.get('monsterLevel', '?')}"))
                title = QLabel(room["bossName"])
                title.setStyleSheet("font-weight: 700; font-size: 11pt;")
                title.setWordWrap(True)
                v.addWidget(title)
                for m in room.get("monsters") or []:
                    v.addLayout(self._monster(endgame.monster_icon(m.get("icon")), m.get("name", "?"), "",
                                              THEATER_MONSTER_ICON))
                if room.get("bossDescription"):
                    v.addWidget(_rich(room["bossDescription"]))
                v.addStretch()
                (lunar if hard_room else cards).append(box)
        cards = lunar + cards
        if cards:
            self.body.addWidget(self._cards(cards))
        self.body.addStretch()

    def _pick_theater_level(self, level):
        self.level["theater"] = level
        self._render()

    # ----- Stygian Onslaught -----
    def _show_stygian(self, entry):
        levels = endgame.stygian_levels(entry)
        self.body.addWidget(self._header(entry))  # (no picture: like the Theater's, the opponents show theirs below)
        if not levels:
            self.body.addWidget(_muted("No line-up for this one yet."))
            self.body.addStretch()
            return
        names = [name for name, _ in levels]
        if self.level["stygian"] not in names:
            self.level["stygian"] = names[-1]
        self.body.addLayout(self._choice_row("", [(n, n) for n in names], self.level["stygian"], self._pick_stygian_level))
        level = dict(levels)[self.level["stygian"]]
        self._stygian_level = level.get("monsterLevel")
        cards = []
        for boss in level.get("levelConfigs") or []:
            column = QWidget()
            stack = QVBoxLayout(column)
            stack.setContentsMargins(0, 0, 0, 0)
            stack.setSpacing(12)
            stack.addWidget(self._stygian_boss(boss))
            stack.addWidget(self._tldr(boss.get("enLevelName") or ""))
            stack.addStretch()
            cards.append(column)
        if cards:
            self.body.addWidget(self._columns(cards))
        self.body.addStretch()

    def _stygian_boss(self, boss):
        box, v = _box()
        pic = QLabel()
        pic.setObjectName("EndGameArt")
        pic.setFixedHeight(STYGIAN_ART)
        pic.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        url = endgame.stygian_image(boss.get("specialMonsterIcon"))

        def loaded(pm, pic=pic):
            if pm is not None:
                pic.setPixmap(pm.scaledToHeight(STYGIAN_ART, Qt.SmoothTransformation))

        gamedata.load_pixmap(url, loaded)
        pic.setAlignment(Qt.AlignCenter)
        v.addWidget(pic)
        title = QLabel(boss.get("enLevelName") or "")
        title.setObjectName("StygianName")
        title.setWordWrap(True)
        title.setAlignment(Qt.AlignCenter)
        title.ensurePolished()
        title.setFixedHeight(title.fontMetrics().lineSpacing() * 3)  # room for 3 lines: the boxes below line up
        v.addWidget(title)
        # its level (grey) over its HP (big and white), in one box
        stats = boss.get("monsterStats") or {}
        level = stats.get("level") or self._stygian_level
        tile = QFrame()
        tile.setObjectName("StygianStats")
        stack = QVBoxLayout(tile)
        stack.setContentsMargins(12, 8, 12, 10)
        stack.setSpacing(0)
        level_label = QLabel(f"LV. {level}" if level else "LV. ?")
        level_label.setObjectName("StygianLevel")
        level_label.setAlignment(Qt.AlignCenter)
        stack.addWidget(level_label)
        hp = QLabel(f"HP {stats['hp']:,.0f}" if stats.get("hp") else "HP ?")
        hp.setObjectName("StygianStat")
        hp.setAlignment(Qt.AlignCenter)
        stack.addWidget(hp)
        v.addWidget(tile)
        names = [n for n in boss.get("enMonsterSpecialMechanicName") or [] if n]
        texts = boss.get("enLevelMaxDescription") or []
        for i, name in enumerate(names):
            v.addSpacing(2)
            v.addWidget(_heading(name.upper()))
            if i < len(texts) and texts[i]:
                v.addWidget(_rich(texts[i]))
        if boss.get("enMonsterSpecialDesc"):
            pic.setToolTip(gamedata.clean(boss["enMonsterSpecialDesc"]))
        v.addStretch()
        return box

    def _tldr(self, name):
        """stygian.moe's "Insider's TLDR" of the fight (the current bosses only), with a link to the boss's page
        there for its resistances."""
        box, v = _box("EndGameCard")
        v.addWidget(_heading("INSIDER'S TLDR  ·  STYGIAN.MOE"))
        entry = endgame.stygian_moe_entry(self.moe, name) if name else None
        if entry and entry.get("tldr"):
            for point in entry["tldr"]:
                line = QLabel(f"\u2022 {point}")
                line.setObjectName("EndGameText")
                line.setTextFormat(Qt.RichText)
                line.setWordWrap(True)
                v.addWidget(line)
        else:
            v.addWidget(_muted("stygian.moe only has notes on the current Stygian Onslaught's opponents."))
        link = entry["url"] if entry else endgame.STYGIAN_MOE
        more = QLabel(f"<a href='{link}' style='color:{theme.accent_hex()}'>Boss resistances are on stygian.moe \u2197</a>")
        more.setOpenExternalLinks(True)
        more.setToolTip(link)
        v.addSpacing(4)
        v.addWidget(more)
        return box

    def _pick_stygian_level(self, level):
        self.level["stygian"] = level
        self._render()

    # ----- for Home -----
    def timers(self):
        """[(mode name, entry title, ends at (aware datetime) or None)] for what's live in each mode."""
        out = []
        for key, text in MODES:
            entries = (self.data or {}).get(key) or []
            live = next((e for e in entries if e.get("status") == "live"), None)
            end = endgame.to_utc(live["end"], servers.offset(self.server)) if live else None
            out.append((key, text, entry_title(key, live) if live else "Not running", end))
        return out
