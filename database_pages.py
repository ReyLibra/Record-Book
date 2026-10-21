"""Weapons / Artifacts pages: browse the game database, newest releases first."""

from pydantic import ValidationError
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidgetItem,
    QSlider,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

import gamedata
import weapon_sources
from gamedata import html_text, rich_html
from search import matches
from widgets import (
    EvenGrid,
    FilterGroup,
    ImageTile,
    RemoteIcon,
    card_pixmap,
    clear_layout,
    filter_button,
    glossary_tooltips,
    section_header,
)

GRID_CELL = QSize(124, 146)  # the Characters page's card + name cell

TITLES = {"weapon": "Weapons", "artifact": "Artifacts"}
SEARCH_WIDTH = 300
NEW = "new"  # source filter: weapons the wiki doesn't list yet

# Artifact piece slots, in the game's order
PIECE_ICON = 56  # the artifact set's pieces, in a row
PIECE_SLOTS = {
    "EQUIP_BRACER": "Flower of Life",
    "EQUIP_NECKLACE": "Plume of Death",
    "EQUIP_SHOES": "Sands of Eon",
    "EQUIP_RING": "Goblet of Eonothem",
    "EQUIP_DRESS": "Circlet of Logos",
}

DETAIL_CSS = """
<style>
h3 { color: #ffffff; font-size: 12pt; font-weight: 700; margin-top: 16px; margin-bottom: 4px; }
p { margin: 4px 0; color: #d6d9df; }
.dim { color: rgba(255,255,255,0.55); }
</style>
"""


def _weapon_extras(weapon_id):
    """Refinement texts with the game's colors and the stat curve; each optional (plain text / no
    level slider without them)."""
    try:
        markup = gamedata.fetch_weapon_markup(weapon_id)
    except Exception:
        markup = []
    try:
        curve = gamedata.fetch_weapon_curve()
    except Exception:
        curve = None
    return markup, curve


def _stars(n):
    return "★" * n


def _kicker(text):
    label = QLabel(text)
    label.setObjectName("FieldLabel")
    return label


class _SliderRow(QWidget):
    """A labelled slider with a value badge on the right, Prydwen's level-slider style."""

    def __init__(self, title, minimum, maximum, value, badge, on_change):
        super().__init__()
        self._badge_text = badge
        self._on_change = on_change
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(_kicker(title), 1)
        self.badge = QLabel()
        self.badge.setObjectName("LevelBadge")
        head.addWidget(self.badge)
        v.addLayout(head)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setPageStep(1)
        self.slider.setCursor(Qt.PointingHandCursor)
        self.slider.valueChanged.connect(self._changed)
        v.addWidget(self.slider)
        self.slider.setValue(value)
        self._changed(value)

    def _changed(self, value):
        self.badge.setText(self._badge_text(value))
        self._on_change(value)


DETAIL_MIN, DETAIL_MAX = 340, 480  # the detail panel's width range


class BrowsePage(QWidget):
    message = Signal(str)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # the detail panel takes ~40% of the page (within its range), the list the rest
        self.detail.setFixedWidth(max(DETAIL_MIN, min(DETAIL_MAX, round(self.width() * 0.4))))
        if self.type_group is None:
            return
        margins = self.layout().contentsMargins()
        room = self.width() - self.detail.width() - self.layout().spacing() - margins.left() - margins.right()
        one_row = (self.all_button.sizeHint().width() + self.rarity_group.sizeHint().width()
                   + self.type_group.sizeHint().width() + 30) <= room
        in_first = self.controls.indexOf(self.type_group) >= 0
        if one_row and not in_first:
            self.type_row.removeWidget(self.type_group)
            self.controls.insertWidget(self.controls.count() - 1, self.type_group)
        elif not one_row and in_first:
            self.controls.removeWidget(self.type_group)
            self.type_row.addWidget(self.type_group)
            self.type_row.addStretch()
        if one_row:  # (drop the second row's leftover stretch)
            while self.type_row.count():
                self.type_row.takeAt(0)

    def __init__(self, kind, store):
        super().__init__()
        self.kind = kind
        self.store = store
        self.index = None
        self.current_id = None
        self._request = 0
        self._loaded = None  # what the detail panel is showing, for re-rendering on slider moves

        layout = QHBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 20)  # the same as the Characters and Buffs pages
        layout.setSpacing(20)

        # ----- left: header, Prydwen-style filter buttons, grid -----
        left = QVBoxLayout()
        left.setSpacing(10)
        title, self.count_label = section_header(f"All {TITLES[kind]}")
        left.addWidget(title)

        # row 1: search, and (weapons) the source dropdown beside it; row 2: [All] + rarities, then the weapon types
        top = QHBoxLayout()
        top.setSpacing(8)
        self.search = QLineEdit(placeholderText=f"Search {TITLES[kind].lower()}…")
        self.search.setMaximumWidth(SEARCH_WIDTH * 2)
        self.search.textChanged.connect(self.apply_filter)
        top.addWidget(self.search, 1)
        # where a weapon comes from (event, wish, crafting…), from the wiki (weapon_sources.py)
        # (a dropdown: ten sources don't fit as a row of buttons)
        self.source_box = None
        if kind == "weapon":
            weapon_sources.load_cache()
            top.addSpacing(4)
            kicker = QLabel("SOURCE")
            kicker.setObjectName("FieldLabel")
            top.addWidget(kicker)
            self.source_box = QComboBox()
            self.source_box.setMinimumWidth(150)
            self.source_box.setMaximumWidth(260)
            self.source_box.setToolTip("Where the weapon comes from (from the Genshin Impact wiki)")
            self.source_box.currentIndexChanged.connect(lambda _: self.apply_filter())
            top.addWidget(self.source_box, 1)
        # the spare width goes after the row, so the label stays beside its dropdown in a wide window
        top.addStretch()
        left.addLayout(top)

        controls = QHBoxLayout()
        controls.setSpacing(4)
        self.all_button = filter_button("All", tooltip="Clear all filters")
        self.all_button.setChecked(True)
        self.all_button.clicked.connect(self.clear_filters)
        controls.addWidget(self.all_button)
        rarities = (5, 4, 3, 2, 1) if kind == "weapon" else (5, 4, 3)
        tip = "{}-star weapons" if kind == "weapon" else "Sets that go up to {}-star"
        self.rarity_group = FilterGroup([(r, f"{r}★", None, tip.format(r)) for r in rarities])
        self.rarity_group.changed.connect(lambda _: self.apply_filter())
        controls.addWidget(self.rarity_group)
        self.type_group = None
        if kind == "weapon":
            controls.addSpacing(8)
            self.type_group = FilterGroup(
                [(t, "", gamedata.weapon_type_icon_url(t), gamedata.weapon_type_name(t)) for t in gamedata.WEAPON_TYPES]
            )
            self.type_group.changed.connect(lambda _: self.apply_filter())
            controls.addWidget(self.type_group)
        controls.addStretch()
        left.addLayout(controls)
        # (weapons) the weapon types move to their own row when the list side is too narrow for one row
        self.controls = controls
        self.type_row = QHBoxLayout()
        self.type_row.setSpacing(4)
        left.addLayout(self.type_row)
        if self.source_box:
            self._fill_sources()

        # same cards as the Characters grid
        self.grid = EvenGrid(GRID_CELL + QSize(8, 8))
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setIconSize(QSize(104, 104))
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setWordWrap(True)
        self.grid.setSpacing(4)
        self.grid.setStyleSheet("QListWidget { background: transparent; border: none; outline: 0; }")
        self.grid.currentItemChanged.connect(lambda item, _prev: item and self.show_item(item.data(Qt.UserRole)))
        self.loading = QLabel("Loading game data…")
        self.loading.setStyleSheet("color: rgba(255,255,255,0.55);")
        left.addWidget(self.loading)
        left.addWidget(self.grid, 1)
        layout.addLayout(left, 1)

        # ----- right: detail panel -----
        self.detail = QFrame()
        self.detail.setObjectName("Card")
        # between DETAIL_MIN and DETAIL_MAX wide, so the page always fits the window (see resizeEvent)
        self.detail.setMinimumWidth(DETAIL_MIN)
        self.detail.setMaximumWidth(DETAIL_MAX)
        d = QVBoxLayout(self.detail)
        d.setContentsMargins(20, 20, 20, 20)
        d.setSpacing(12)
        head = QHBoxLayout()
        self.tile = ImageTile(96)
        self.tile.show_plus = False
        self.tile.setCursor(Qt.ArrowCursor)
        names = QVBoxLayout()
        self.name_label = QLabel("Select an item")
        self.name_label.setObjectName("CharName")
        self.name_label.setWordWrap(True)
        self.sub_label = QLabel("")
        self.sub_label.setObjectName("CharTitle")
        self.sub_label.setWordWrap(True)
        names.addStretch()
        names.addWidget(self.name_label)
        names.addWidget(self.sub_label)
        names.addStretch()
        head.addWidget(self.tile)
        head.addLayout(names, 1)
        d.addLayout(head)

        # weapon sliders go here (level stats, refinement)
        self.extras = QVBoxLayout()
        self.extras.setSpacing(12)
        d.addLayout(self.extras)

        self.text = QTextBrowser()
        self.text.setOpenExternalLinks(False)
        glossary_tooltips(self.text)
        self.text.setStyleSheet("border: none; background: transparent;")
        d.addWidget(self.text, 1)

        # artifact pieces, pinned to the bottom of the panel
        self.pieces = QFrame()
        self.pieces.setObjectName("PiecesBox")
        self.pieces_layout = QGridLayout(self.pieces)
        self.pieces_layout.setContentsMargins(0, 10, 0, 0)
        self.pieces_layout.setHorizontalSpacing(10)
        self.pieces_layout.setVerticalSpacing(6)
        self.pieces.hide()
        d.addWidget(self.pieces)
        layout.addWidget(self.detail)

    # ----- data -----
    def set_index(self, index):
        self.index = index
        self.loading.hide()
        self.grid.clear()
        # newest releases first; same release: higher rarity, then name
        entries = sorted(self._entries().values(), key=lambda e: e.name)
        entries.sort(key=lambda e: e.rarity, reverse=True)
        entries.sort(key=lambda e: e.release, reverse=True)
        for entry in entries:
            item = QListWidgetItem(entry.name)
            item.setData(Qt.UserRole, entry.id)
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            item.setSizeHint(GRID_CELL)
            self.grid.addItem(item)
            gamedata.load_pixmap(
                entry.icon,
                lambda pm, item=item, r=entry.rarity: pm and item.setIcon(QIcon(card_pixmap(pm, None, r))),
                bulk=True,
            )
        self._fill_sources()  # the counts follow the listed weapons (Unreleased on / off)
        self.apply_filter()
        # never an empty detail panel: keep the item being shown, else open the first one in the grid
        current = getattr(self, "current_id", None)
        if current not in self._entries():
            current = next((self.grid.item(i).data(Qt.UserRole) for i in range(self.grid.count())
                            if not self.grid.item(i).isHidden()), None)
        if current is not None:
            self.show_item(current, visit=False)

    def _entries(self):
        return self.index.weapons if self.kind == "weapon" else self.index.artifacts

    def clear_filters(self):
        self.rarity_group.set_value(None)
        if self.type_group:
            self.type_group.set_value(None)
        if self.source_box:
            self.source_box.blockSignals(True)
            self.source_box.setCurrentIndex(0)
            self.source_box.blockSignals(False)
        self.apply_filter()

    def _fill_sources(self):
        """The source dropdown, with how many of the listed weapons come from each."""
        if not self.source_box:
            return
        weapons = list(self.index.weapons.values()) if self.index else []
        counts = {}
        for w in weapons:
            key = weapon_sources.source_of(w) or NEW
            counts[key] = counts.get(key, 0) + 1
        current = self.source_box.currentData()
        self.source_box.blockSignals(True)
        self.source_box.clear()
        self.source_box.addItem("All sources", None)
        for key, label, tip, _cat in weapon_sources.SOURCES:
            self.source_box.addItem(f"{label}  ({counts.get(key, 0)})", key)
            self.source_box.setItemData(self.source_box.count() - 1, tip, Qt.ToolTipRole)
        if counts.get(NEW):  # new / upcoming / unreleased weapons the wiki hasn't filed yet
            self.source_box.addItem(f"{weapon_sources.UNKNOWN}  ({counts[NEW]})", NEW)
        found = self.source_box.findData(current)
        self.source_box.setCurrentIndex(found if found >= 0 else 0)
        self.source_box.blockSignals(False)

    def sources_updated(self):
        """The wiki's weapon sources were read again: refilter, and refresh the source in the detail panel."""
        if self.kind != "weapon" or not self.index:
            return
        self._fill_sources()
        self.apply_filter()
        if self._loaded:
            info, w, _markup = self._loaded
            self.sub_label.setText(self._weapon_subtitle(info, w))

    def apply_filter(self):
        if not self.index:
            return
        text = self.search.text()
        rarity = self.rarity_group.value
        wtype = self.type_group.value if self.type_group else None
        source = self.source_box.currentData() if self.source_box else None
        self.all_button.setChecked(rarity is None and wtype is None and source is None)
        entries = self._entries()
        shown = 0
        for i in range(self.grid.count()):
            item = self.grid.item(i)
            entry = entries[item.data(Qt.UserRole)]
            hidden = (
                not matches(text, entry.name)
                or bool(rarity and entry.rarity != rarity)
                or bool(wtype and entry.type != wtype)
                or bool(source and (weapon_sources.source_of(entry) or NEW) != source)
            )
            item.setHidden(hidden)
            shown += not hidden
        self.count_label.setText(f"Showing {shown} {TITLES[self.kind].lower()}")

    # ----- detail panel -----
    def show_item(self, item_id, visit=True):
        if not self.index or item_id not in self._entries():
            return
        self.current_id = item_id
        for i in range(self.grid.count()):
            if self.grid.item(i).data(Qt.UserRole) == item_id:
                self.grid.blockSignals(True)
                self.grid.setCurrentRow(i)
                self.grid.blockSignals(False)
                self.grid.scrollToItem(self.grid.item(i))
                break
        entry = self._entries()[item_id]
        self.tile.set_content([entry.icon], entry.rarity)
        self.name_label.setText(entry.name)
        self.sub_label.setText("")
        self._clear_extras()
        self.pieces.hide()
        self._loaded = None
        self.text.setHtml(DETAIL_CSS + "<p class='dim'>Loading…</p>")

        self._request += 1
        request = self._request
        if self.kind == "weapon":
            def fetch():
                return (gamedata.fetch_weapon_detail(item_id),) + _weapon_extras(item_id)
        else:
            def fetch():
                return gamedata.fetch_artifact_detail(item_id)

        def done(detail, error):
            if request != self._request:
                return
            if isinstance(error, ValidationError):  # brand-new items often have incomplete data upstream
                self.text.setHtml(
                    DETAIL_CSS + "<p class='dim'>Project Amber doesn't have complete details for this item yet.</p>"
                )
                return
            if error:
                self.text.setHtml(DETAIL_CSS + f"<p>Couldn't load details (check your connection): {error}</p>")
                return
            if self.kind == "weapon":
                self._show_weapon(entry, *detail)
            else:
                self._show_artifact(entry, detail)
            self.text.verticalScrollBar().setValue(0)

        gamedata.run_async(fetch, done)

    def _clear_extras(self):
        clear_layout(self.extras)

    # ----- weapons: level slider for the stats, refinement slider for the passive -----
    @staticmethod
    def _weapon_subtitle(info, w):
        return f"{_stars(w.rarity)}  {gamedata.weapon_type_name(info.type)}  ·  {weapon_sources.label_of(info)}"

    def _show_weapon(self, info, w, markup, curve):
        self.sub_label.setText(self._weapon_subtitle(info, w))
        self._loaded = (info, w, markup)

        if curve:
            box = QFrame()
            box.setObjectName("StatTile")
            v = QVBoxLayout(box)
            v.setContentsMargins(12, 10, 12, 12)
            v.setSpacing(8)
            tiles = QHBoxLayout()
            tiles.setSpacing(6)
            values = {}
            max_level = gamedata.weapon_max_level(w)
            for prop in gamedata.weapon_stats(w, curve, max_level):
                tile = QFrame()
                tile.setObjectName("InsetTile")
                t = QVBoxLayout(tile)
                t.setContentsMargins(10, 6, 10, 6)
                t.setSpacing(0)
                key = QLabel(gamedata.stat_name(prop).upper())
                key.setObjectName("FieldLabel")
                value = QLabel()
                value.setObjectName("StatNumber")
                t.addWidget(key)
                t.addWidget(value)
                values[prop] = value
                tiles.addWidget(tile, 1)

            def show_level(level):
                for prop, value in gamedata.weapon_stats(w, curve, level).items():
                    if prop in values:
                        values[prop].setText(gamedata.format_stat(prop, value))

            v.addWidget(_SliderRow("WEAPON STATS", 1, max_level, max_level, lambda n: f"LEVEL  {n}/{max_level}", show_level))
            v.addLayout(tiles)
            self.extras.addWidget(box)

        if w.affix and len(w.affix.upgrades) > 1:
            count = len(w.affix.upgrades)
            self.extras.addWidget(
                _SliderRow("REFINEMENT", 1, count, 1, lambda n: f"R{n}", lambda n: self._render_weapon_text(n))
            )
        else:
            self._render_weapon_text(1)

    def _render_weapon_text(self, refinement):
        if not self._loaded:
            return
        info, w, markup = self._loaded
        parts = []
        if w.affix:
            n = refinement - 1
            up = w.affix.upgrades[min(n, len(w.affix.upgrades) - 1)]
            text = markup[n] if n < len(markup) else up.description
            parts.append(f"<h3>{html_text(w.affix.name)} <span class='dim'>· R{refinement}</span></h3>")
            parts.append(f"<p>{rich_html(text)}</p>")
        if w.description:  # the lore goes last
            parts.append(f"<h3>Description</h3><p class='dim'>{html_text(w.description)}</p>")
        position = self.text.verticalScrollBar().value()
        self.text.setHtml(DETAIL_CSS + "".join(parts))
        self.text.verticalScrollBar().setValue(position)

    # ----- artifacts: set bonuses, pieces pinned at the bottom -----
    def _show_artifact(self, info, a):
        rarities = sorted(a.rarity_list)
        self.sub_label.setText(f"Artifact set  ·  {rarities[0]}★ – {rarities[-1]}★")
        parts = []
        for n, bonus in zip((2, 4), info.bonuses):
            parts.append(f"<h3>{n}-piece bonus</h3><p>{rich_html(bonus)}</p>")
        self.text.setHtml(DETAIL_CSS + "".join(parts))

        # the pieces in one row (flower, plume, sands, goblet, circlet); hover one for its name and slot
        clear_layout(self.pieces_layout)
        order = list(PIECE_SLOTS)
        pieces = sorted(a.artifacts, key=lambda p: order.index(p.pos) if p.pos in order else len(order))
        self.pieces_layout.addWidget(_kicker("PIECES"), 0, 0, 1, max(1, len(pieces)))
        for col, piece in enumerate(pieces):
            icon = RemoteIcon(PIECE_ICON)
            icon.set_url(piece.icon)
            icon.setStyleSheet("background: rgba(0,0,0,0.28); border: 1px solid #33343a;")
            icon.setToolTip(f"<b>{html_text(piece.name)}</b><br>"
                            f"<span style='color: rgba(255,255,255,0.55)'>{PIECE_SLOTS.get(piece.pos, piece.pos)}</span>")
            self.pieces_layout.addWidget(icon, 1, col)
        for col in range(self.pieces_layout.columnCount()):
            self.pieces_layout.setColumnStretch(col, 0)
        self.pieces_layout.setColumnStretch(len(pieces), 1)  # keep the row on the left
        self.pieces.show()
