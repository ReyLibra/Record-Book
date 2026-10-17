"""Home page: character art behind a build card (left) and the element selector (right)."""

import time

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import gamedata
from dialogs import ArtifactDialog, CharacterSearchDialog, WeaponDialog, confirm
from widgets import ACCENT, ImageTile, RemoteIcon, card_pixmap, clear_layout, filter_button

HOVER_CLEAR_DELAY_MS = 90  # avoids flicker when the mouse moves between rows
DPS_MODES = [("abyss", "Spiral Abyss"), ("fearless", "Stygian Fearless"), ("dire", "Stygian Dire")]


def _field_label(text):
    label = QLabel(text)
    label.setObjectName("FieldLabel")
    return label


# ---------- right side: element selector ----------
class CharRow(QFrame):
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
        layout.setContentsMargins(6, 4, 10, 4)
        icon = RemoteIcon(36)
        icon.set_url(icon_url)
        name = QLabel(record["name"])
        name.setStyleSheet("font-size: 11pt;")
        dps = QLabel(f"{record['best_dps']:,.0f} DPS" if record["best_dps"] else "No Data")
        dps.setStyleSheet("color: rgba(255,255,255,0.55); font-size: 9pt; font-weight: 600;")
        for w in (icon, name, dps):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(icon)
        layout.addWidget(name, 1)
        layout.addWidget(dps)
        self._icon, self._name = icon, name
        self.setToolTip("Click the name or portrait to open the character log")

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


class ElementSelector(QFrame):
    VISIBLE_ROWS = 6  # characters that fit (with "Add Character") before the list scrolls

    hovered = Signal(object)
    picked = Signal(str)
    open_log = Signal(str)
    add_requested = Signal(str)  # element
    remove_requested = Signal(str)
    mode_changed = Signal(str)  # 'abyss' / 'fearless' / 'dire'

    def __init__(self, mode="abyss"):
        super().__init__()
        self.setObjectName("Selector")
        self.setFixedWidth(360)
        self.current = None
        self.records = []
        self.index = None
        self.selected_id = None
        self.mode = mode

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(_field_label("ELEMENTS"))

        icons = QHBoxLayout()
        icons.setSpacing(4)
        self.element_buttons = {}
        for element in gamedata.ELEMENTS:
            btn = QToolButton()
            btn.setObjectName("ElementBtn")
            btn.setCheckable(True)
            btn.setFixedSize(44, 44)
            btn.setIconSize(QSize(30, 30))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(gamedata.pretty(element))
            # Prydwen's active filter button is solid blue
            btn.setStyleSheet(f"#ElementBtn:checked {{ border-color: {ACCENT}; background: {ACCENT}; }}")
            gamedata.load_pixmap(gamedata.element_icon_url(element), lambda pm, b=btn: pm and b.setIcon(QIcon(pm)))
            btn.clicked.connect(lambda _=False, e=element: self._element_clicked(e))
            self.element_buttons[element] = btn
            icons.addWidget(btn)
        layout.addLayout(icons)

        self.element_title = QLabel("Choose an element")
        self.element_title.setStyleSheet("font-size: 14pt; font-weight: 700;")
        layout.addWidget(self.element_title)

        # which DPS the list shows (and sorts by)
        self.mode_row = QWidget()
        modes = QHBoxLayout(self.mode_row)
        modes.setContentsMargins(0, 0, 0, 0)
        modes.setSpacing(4)
        self.mode_group = QButtonGroup(self)
        for n, (key, label) in enumerate(DPS_MODES):
            btn = filter_button(label, tooltip=f"Show each character's highest {label} DPS")
            btn.setChecked(key == self.mode)
            self.mode_group.addButton(btn, n)
            modes.addWidget(btn)
        modes.addStretch()
        self.mode_group.idClicked.connect(self._mode_clicked)
        layout.addWidget(self.mode_row)
        self.mode_row.hide()

        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(4)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidget(self.list_host)
        self.scroll.verticalScrollBar().rangeChanged.connect(self._fit_list)
        layout.addWidget(self.scroll)
        self.scroll.hide()

    def _fit_list(self, _minimum=0, maximum=0):
        """With 6 or fewer characters the list must fit with no scrolling at all: when it's laid out a
        few pixels taller than estimated, grow by exactly that much."""
        if maximum > 0 and self.scroll.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff:
            self.scroll.setFixedHeight(self.scroll.height() + maximum)

    def _mode_clicked(self, n):
        self.mode = DPS_MODES[n][0]
        self.mode_changed.emit(self.mode)

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
        if element == self.current and self.findChildren(CharRow):
            # same list: just move the highlight (rebuilding would delete the row being clicked)
            self.mark_selected(self.selected_id)
            return
        self.current = element
        self.rebuild()

    def _element_clicked(self, element):
        self.current = None if self.current == element else element
        self.rebuild()

    def rebuild(self):
        self.hovered.emit(None)  # rows being replaced won't send their own leave event
        for element, btn in self.element_buttons.items():
            btn.setChecked(element == self.current)
        clear_layout(self.list_layout)
        if self.current is None:
            self.element_title.setText("Choose an element")
            self.scroll.hide()
            self.mode_row.hide()
            return
        self.mode_row.show()
        color = gamedata.ELEMENT_COLORS[self.current]
        # highest DPS (in the chosen mode) first; characters with no data after them, by name
        mine = sorted((r for r in self.records if r["element"] == self.current), key=lambda r: r["name"])
        mine.sort(key=lambda r: r["best_dps"] or 0, reverse=True)
        self.element_title.setText(f"<span style='color:{color}'>{gamedata.pretty(self.current)}</span>  ·  {len(mine)} logged")
        for record in mine:
            info = self.index.characters.get(record["char_id"]) if self.index else None
            row = CharRow(record, info.icon if info else None, record["char_id"] == self.selected_id)
            row.hovered.connect(self.hovered)
            row.picked.connect(self.picked)
            row.open_log.connect(self.open_log)
            row.remove_requested.connect(self.remove_requested)
            self.list_layout.addWidget(row)
        add = QPushButton("+  Add Character")
        add.setObjectName("AddRow")
        add.setCursor(Qt.PointingHandCursor)
        add.setMinimumHeight(40)
        add.clicked.connect(lambda: self.add_requested.emit(self.current))
        self.list_layout.addWidget(add)
        self.list_layout.addStretch()
        # grow with the list: up to 6 characters + "Add Character" (7 items) fit without a scrollbar
        spacing = self.list_layout.spacing()
        rows = [self.list_layout.itemAt(i).widget() for i in range(len(mine))]
        if len(rows) <= self.VISIBLE_ROWS:
            items = rows + [add]
        else:  # 7 items' worth of room, the rest scrolls
            items = rows[: self.VISIBLE_ROWS + 1]
        height = sum(w.sizeHint().height() for w in items) + spacing * (len(items) - 1)
        self.scroll.setFixedHeight(height)
        self.scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded if len(rows) > self.VISIBLE_ROWS else Qt.ScrollBarAlwaysOff
        )
        self.scroll.show()


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
        self.row = QHBoxLayout()
        self.row.setSpacing(22)
        outer.addLayout(self.row)
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
        for banner in banners:
            self.row.addWidget(self._banner(banner))
        self.row.addStretch()

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
        self._hover_timer = QTimer(self, singleShot=True, interval=HOVER_CLEAR_DELAY_MS)
        self._hover_timer.timeout.connect(lambda: self._set_hover(None))

        self.card = self._build_card()
        self.selector = ElementSelector(store.get_setting("home_dps_mode", "abyss"))
        self.selector.mode_changed.connect(self._dps_mode_changed)
        self.selector.hovered.connect(self._on_hover)
        self.selector.picked.connect(self._on_pick)
        self.selector.open_log.connect(self._open_log_for)
        self.selector.add_requested.connect(self._on_add)
        self.selector.remove_requested.connect(self._on_remove)

        self.banners = BannerPanel()

        # The build card in the top-left corner, the element selector on the right and the current
        # banners along the bottom. Scrolls when the window is too short for all of it.
        content = QWidget()
        content.setAttribute(Qt.WA_TranslucentBackground)
        v = QVBoxLayout(content)
        v.setContentsMargins(32, 20, 32, 20)
        v.setSpacing(20)
        row = QHBoxLayout()
        row.setSpacing(32)
        row.addWidget(self.card, 0, Qt.AlignTop)
        row.addStretch()
        row.addWidget(self.selector, 0, Qt.AlignVCenter)
        v.addLayout(row, 1)
        v.addWidget(self.banners)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        scroll.viewport().setAutoFillBackground(False)
        scroll.setWidget(content)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

        self.reload_roster()
        self.refresh_card()

    # ----- card (left side) -----
    def _build_card(self):
        card = QFrame()
        card.setObjectName("Card")
        card.setFixedWidth(380)
        outer = QVBoxLayout(card)
        outer.setContentsMargins(24, 22, 24, 20)

        self.hint = QLabel("Hover over a character in the element selector on the right,\nor pick an element and add your first character.")
        self.hint.setStyleSheet("color: rgba(255,255,255,0.55);")
        self.hint.setWordWrap(True)
        outer.addWidget(self.hint)

        self.content = QWidget()
        v = QVBoxLayout(self.content)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)

        # 1. element symbol, name and title
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

        # 2 + 3. weapon and artifacts
        gear = QHBoxLayout()
        gear.setSpacing(18)
        self.weapon_tile = ImageTile(104)
        self.weapon_tile.clicked.connect(self._edit_weapon)
        self.artifact_tile = ImageTile(104)
        self.artifact_tile.clicked.connect(self._edit_artifacts)
        for label, tile in (("WEAPON", self.weapon_tile), ("ARTIFACTS", self.artifact_tile)):
            col = QVBoxLayout()
            col.setSpacing(4)
            col.addWidget(_field_label(label))
            col.addWidget(tile)
            gear.addLayout(col)
        gear.addStretch()
        v.addLayout(gear)

        # 4. talent levels
        v.addWidget(_field_label("TALENT LEVEL"))
        talent_row = QHBoxLayout()
        self.talent_plus = QPushButton("+")
        self.talent_plus.setFixedSize(44, 32)
        self.talent_plus.setToolTip("Set talent levels")
        self.talent_plus.clicked.connect(self._start_talents)
        talent_row.addWidget(self.talent_plus)
        self.talent_widget = QWidget()
        t = QHBoxLayout(self.talent_widget)
        t.setContentsMargins(0, 0, 0, 0)
        self.talent_boxes = []
        for i in range(3):
            if i:
                slash = QLabel("/")
                slash.setStyleSheet("font-size: 14pt; color: rgba(255,255,255,0.55);")
                t.addWidget(slash)
            box = QComboBox()
            box.setObjectName("TalentBox")
            box.setCursor(Qt.PointingHandCursor)
            box.addItems([str(n) for n in range(1, 16)])
            box.setMaxVisibleItems(15)  # the whole list without scrolling
            box.view().setMinimumWidth(56)
            box.setFixedWidth(48)
            box.setToolTip(["Normal Attack", "Elemental Skill", "Elemental Burst"][i])
            box.currentIndexChanged.connect(lambda idx, i=i: self._talent_changed(i, idx + 1))
            self.talent_boxes.append(box)
            t.addWidget(box)
        talent_row.addWidget(self.talent_widget)
        talent_row.addStretch()
        v.addLayout(talent_row)

        # 5. the team from the highest-DPS run, then 6. that DPS (both from the character log)
        v.addWidget(_field_label("TEAM"))
        self.team_row = QHBoxLayout()
        self.team_row.setSpacing(8)
        self.team_widget = QWidget()
        self.team_widget.setLayout(self.team_row)
        v.addWidget(self.team_widget)
        self.team_empty = QLabel("No runs logged yet")
        self.team_empty.setStyleSheet("color: rgba(255,255,255,0.55);")
        v.addWidget(self.team_empty)
        v.addWidget(_field_label("HIGHEST AVERAGE DPS"))
        self.dps_button = QLabel("0 DPS")
        self.dps_button.setObjectName("Dps")
        v.addWidget(self.dps_button)

        # bottom-right buttons
        actions = QHBoxLayout()
        actions.addStretch()
        self.done_button = QPushButton("Done")
        self.done_button.setObjectName("Primary")
        self.done_button.setToolTip("Choose a weapon and artifacts first")
        self.done_button.clicked.connect(self._finish_add)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self._cancel_add)
        for b in (self.done_button, self.cancel_button):
            actions.addWidget(b)
        v.addSpacing(4)
        v.addLayout(actions)

        outer.addWidget(self.content)
        return card

    def _shown(self):
        """The record the card is showing: the draft, else the hovered, else the selected character."""
        if self.draft:
            return self.draft
        char_id = self.hover_id or self.selected_id
        if not char_id:
            return None
        record = self.store.character(char_id)
        return record

    def _editable(self):
        return self.draft is not None or (self.selected_id and self.hover_id in (None, self.selected_id))

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
        editable = self._editable()

        self.element_icon.set_url(gamedata.element_icon_url(record["element"]))
        self.name_label.setText(record["name"])
        self._show_title(char_id)

        # weapon
        weapon = self.index.weapons.get(record["weapon_id"]) if self.index and record["weapon_id"] else None
        if weapon:
            ref = record["refinement"]
            self.weapon_tile.set_content([weapon.icon], weapon.rarity, f"R{ref}")
            self.weapon_tile.setToolTip(f"{weapon.name}  R{ref}")
        else:
            self.weapon_tile.clear()
            self.weapon_tile.setToolTip("Choose a weapon" if editable else "")
        self.weapon_tile.show_plus = editable

        # artifacts
        sets = [self.index.artifacts.get(a) for a in (record["artifact1"], record["artifact2"]) if a and self.index]
        sets = [s for s in sets if s]
        if sets:
            badge = "4p" if len(sets) == 1 else "2p2p"
            self.artifact_tile.set_content([s.icon for s in sets], max(s.rarity for s in sets), badge)
            self.artifact_tile.setToolTip("  +  ".join(s.name for s in sets))
        else:
            self.artifact_tile.clear()
            self.artifact_tile.setToolTip("Choose artifact sets" if editable else "")
        self.artifact_tile.show_plus = editable
        for tile in (self.weapon_tile, self.artifact_tile):
            tile.setCursor(Qt.PointingHandCursor if editable else Qt.ArrowCursor)
            tile.update()

        # DPS
        # DPS and team follow the right panel's Spiral Abyss / Stygian toggle
        mode = self.selector.mode
        best = 0 if self.draft else self.store.best_dps(char_id, mode)
        self.dps_button.setText(f"~{best:,.0f} DPS" if best else "No runs logged yet")
        self.dps_button.setProperty("empty", "false" if best else "true")
        self.dps_button.style().unpolish(self.dps_button)
        self.dps_button.style().polish(self.dps_button)
        self._show_team(None if self.draft else char_id)

        # talents
        show_talents = not (self.draft and not self.draft.get("talents_set"))
        self.talent_plus.setVisible(not show_talents)
        self.talent_widget.setVisible(show_talents)
        for i, box in enumerate(self.talent_boxes):
            box.blockSignals(True)
            box.setCurrentIndex(record[f"talent{i + 1}"] - 1)
            box.blockSignals(False)
            box.setEnabled(bool(editable))

        # buttons
        adding = self.draft is not None
        self.done_button.setVisible(adding)
        self.cancel_button.setVisible(adding)
        self.done_button.setEnabled(adding and bool(record["weapon_id"]) and bool(record["artifact1"]))

        if info:
            self._set_art(info.splash, info.icon)

    def _show_team(self, char_id):
        """Portraits (with names) of the team from the character's highest-DPS run."""
        clear_layout(self.team_row)
        run_id = self.store.best_run_id(char_id, self.selector.mode) if char_id else None
        run = self.store.run(run_id) if run_id else None
        team = (run or {}).get("team") or []
        for member in team:
            info = self.index.characters.get(member["char_id"]) or self.index.characters.get(str(member["char_id"])) \
                if self.index else None
            if info is None and self.index and str(member["char_id"]).isdigit():
                info = self.index.characters.get(int(member["char_id"]))
            if info is None:
                continue
            cell = QWidget()
            col = QVBoxLayout(cell)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(2)
            pic = QLabel()
            pic.setFixedSize(56, 56)
            pic.setToolTip(f"{info.name}  C{member.get('constellation') or 0}")

            def with_element(element_pm, pic=pic, info=info):
                def with_icon(pm):
                    card = card_pixmap(pm, element_pm, info.rarity, 56)
                    card.setDevicePixelRatio(2)
                    pic.setPixmap(card)

                gamedata.load_pixmap(info.icon, with_icon)

            gamedata.load_pixmap(gamedata.element_icon_url(info.element), with_element)
            name = QLabel()
            name.setFixedWidth(64)
            name.setText(name.fontMetrics().elidedText(info.name, Qt.ElideRight, 64))
            name.setAlignment(Qt.AlignHCenter)
            name.setStyleSheet("font-size: 8pt; color: #d6d9df;")
            col.addWidget(pic, 0, Qt.AlignHCenter)
            col.addWidget(name, 0, Qt.AlignHCenter)
            self.team_row.addWidget(cell)
        self.team_row.addStretch()
        self.team_widget.setVisible(bool(team))
        self.team_empty.setVisible(not team)

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
    def _set_art(self, url, fallback=None):
        if url == self._art_url:
            return
        self._art_url = url
        self._art = None
        self.update()
        if url:
            gamedata.load_pixmap(url, lambda pm, url=url: self._art_loaded(url, pm), fallback=fallback)

    def _art_loaded(self, url, pm):
        if url == self._art_url:
            self._art = pm
            self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        rect = QRectF(self.rect())
        bg = QLinearGradient(rect.topLeft(), rect.bottomRight())
        bg.setColorAt(0, QColor("#26272d"))
        bg.setColorAt(1, QColor("#1c1d21"))
        p.fillRect(rect, bg)
        if self._art is not None:
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            # zoomed out 10% from filling the page, centred
            fill = self._art.size().scaled(self.size(), Qt.KeepAspectRatioByExpanding)
            scaled = self._art.scaled(fill * 0.9, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = (self.width() - scaled.width()) / 2
            y = (self.height() - scaled.height()) / 2
            p.setOpacity(0.95)
            p.drawPixmap(int(x), int(y), scaled)
            p.setOpacity(1)
            shade = QLinearGradient(rect.topLeft(), rect.topRight())
            shade.setColorAt(0.0, QColor(28, 29, 33, 215))
            shade.setColorAt(0.3, QColor(28, 29, 33, 60))
            shade.setColorAt(0.7, QColor(28, 29, 33, 60))
            shade.setColorAt(1.0, QColor(28, 29, 33, 215))
            p.fillRect(rect, shade)
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
        """Begin the add flow for a character (also used by the Characters page)."""
        if not self.index or char_id not in self.index.characters:
            return
        if self.store.character(char_id):
            self.select(char_id)
            return
        info = self.index.characters[char_id]
        self.draft = {
            "char_id": char_id,
            "name": info.name,
            "element": info.element,
            "weapon_id": None,
            "refinement": 1,
            "artifact1": None,
            "artifact2": None,
            "talent1": 1,
            "talent2": 1,
            "talent3": 1,
            "notes": "",
            "talents_set": False,
        }
        self.hover_id = None
        self.selector.open_element(info.element)
        self.message.emit(f"Adding {info.name}: choose a weapon and artifacts, then press Done.")
        self.refresh_card()

    def _finish_add(self):
        draft = self.draft
        if not (draft and draft["weapon_id"] and draft["artifact1"]):
            return
        self.store.save_character(draft)
        self.draft = None
        self.selected_id = draft["char_id"]
        self.selector.selected_id = self.selected_id
        self.reload_roster()
        self.refresh_card()
        self.roster_changed.emit()
        self.visited.emit(draft["char_id"])
        self.message.emit(f"Added {draft['name']} to your Record Book")

    def _cancel_add(self):
        self.draft = None
        self.message.emit("")
        self.refresh_card()

    # ----- editing fields -----
    def _apply(self, **fields):
        if self.draft is not None:
            self.draft.update(fields)
        elif self.selected_id:
            self.store.update_character(self.selected_id, **fields)
        self.refresh_card()

    def _edit_weapon(self):
        if not self._editable() or not self.index:
            return
        record = self._shown()
        info = self.index.characters[record["char_id"]]
        weapons = [w for w in self.index.weapons.values() if w.type == info.weapon_type]
        dialog = WeaponDialog(weapons, record["weapon_id"], record["refinement"], self)
        if dialog.exec():
            self._apply(weapon_id=dialog.weapon_id, refinement=dialog.refinement)

    def _edit_artifacts(self):
        if not self._editable() or not self.index:
            return
        record = self._shown()
        dialog = ArtifactDialog(self.index.artifacts.values(), (record["artifact1"], record["artifact2"]), self)
        if dialog.exec() and dialog.chosen:
            chosen = dialog.chosen + [None]
            self._apply(artifact1=chosen[0], artifact2=chosen[1])

    def _start_talents(self):
        if self.draft:
            self.draft["talents_set"] = True
            self.refresh_card()

    def _talent_changed(self, i, level):
        if self._editable():
            self._apply(**{f"talent{i + 1}": level})

    def _select_on_launch(self):
        """Open on the most recently viewed logged character (else the first one logged)."""
        logged = {r["char_id"] for r in self.store.characters()}
        if not logged:
            return
        recent = [str(r.get("id")) for r in self.store.get_setting("recent", []) or []]
        pinned = [str(p.get("id")) for p in self.store.get_setting("pins", []) or []]
        choice = next((cid for cid in recent + pinned if cid in logged), None) or sorted(logged)[0]
        self.select(choice)

    def _open_log_for(self, char_id):
        """From a name or portrait in the element selector (not while adding a character)."""
        if not self.draft and self.store.character(char_id):
            self.open_log.emit(char_id)

