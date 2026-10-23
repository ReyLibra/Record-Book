"""Popups: pickers, editors and confirmations.

Every popup is a Popup: no window frame, a black see-through box centred over the app, which is
dimmed behind it. Clicking outside the box (or pressing Esc) closes it.
"""

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

import gamedata
from search import matches
from widgets import ImageTile, card_pixmap

DIM = QColor(0, 0, 0, 150)  # how dark the app gets behind a popup
MARGIN = 24  # smallest gap between the box and the window edge
NAME_ROLE = Qt.UserRole + 1


class Popup(QDialog):
    """A frameless popup over the dimmed main window. Put content in self.body.

    width/height size the box (height None: as tall as its content); it shrinks to fit small windows.
    """

    def __init__(self, parent=None, title="", width=440, height=None):
        super().__init__(parent)
        self.setObjectName("Popup")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self._box_size = (width, height)
        self._host = parent.window() if parent else None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        self.panel = QFrame()
        self.panel.setObjectName("PopupPanel")
        outer.addWidget(self.panel, 0, Qt.AlignCenter)
        self.body = QVBoxLayout(self.panel)
        self.body.setContentsMargins(20, 16, 20, 20)
        self.body.setSpacing(10)
        if title:
            head = QHBoxLayout()
            label = QLabel(title)
            label.setObjectName("PopupTitle")
            close = QPushButton("✕")
            close.setObjectName("PopupClose")
            close.setCursor(Qt.PointingHandCursor)
            close.setAutoDefault(False)
            close.setToolTip("Close (Esc)")
            close.clicked.connect(self.reject)
            head.addWidget(label, 1)
            head.addWidget(close)
            self.body.addLayout(head)

    # ----- cover the main window -----
    def _cover(self):
        if not self._host:
            return
        self.setGeometry(self._host.geometry())
        width, height = self._box_size
        self.panel.setFixedWidth(min(width, self.width() - 2 * MARGIN))
        if height:
            self.panel.setFixedHeight(min(height, self.height() - 2 * MARGIN))
        else:
            self.panel.setMaximumHeight(self.height() - 2 * MARGIN)

    def showEvent(self, event):
        self._cover()
        if self._host:
            self._host.installEventFilter(self)
        super().showEvent(event)

    def done(self, result):
        if self._host:
            self._host.removeEventFilter(self)
        super().done(result)

    def eventFilter(self, obj, event):
        # follow the main window if it's moved, resized or maximized while the popup is open
        if obj is self._host and event.type() in (QEvent.Move, QEvent.Resize, QEvent.WindowStateChange):
            self._cover()
        return False

    def paintEvent(self, event):
        QPainter(self).fillRect(self.rect(), DIM)

    def mousePressEvent(self, event):
        if not self.panel.geometry().contains(event.position().toPoint()):
            self.reject()  # clicked outside the box
            return
        super().mousePressEvent(event)


def _buttons(dialog, ok_text="OK", cancel_text="Cancel"):
    """OK / Cancel row (OK in blue) wired to the dialog's accept / reject."""
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    ok = buttons.button(QDialogButtonBox.Ok)
    ok.setText(ok_text)
    ok.setObjectName("Primary")
    buttons.button(QDialogButtonBox.Cancel).setText(cancel_text)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    return buttons


def confirm(parent, title, text, yes="Yes", no="Cancel"):
    """Ask a yes/no question in a popup; True if confirmed."""
    dialog = Popup(parent, title, width=420)
    label = QLabel(text)
    label.setWordWrap(True)
    label.setMinimumHeight(label.sizeHint().height())
    dialog.body.addWidget(label)
    dialog.body.addSpacing(6)
    dialog.body.addWidget(_buttons(dialog, yes, no))
    return dialog.exec() == QDialog.Accepted


class _IconList(QListWidget):
    """A list of game items with icons that load in the background."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIconSize(QSize(48, 48))
        self.setUniformItemSizes(True)

    def add(self, text, icon_url, data, tooltip="", rarity=0, name=None):
        """rarity puts the icon on Prydwen's rarity-colored card background; name is what the
        search box matches (default: the first line of text)."""
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, data)
        item.setData(NAME_ROLE, name or text.split("\n")[0])
        if tooltip:
            item.setToolTip(tooltip)
        self.addItem(item)

        def loaded(pm, item=item):
            if pm:
                item.setIcon(QIcon(card_pixmap(pm, None, rarity, 48) if rarity else pm))

        gamedata.load_pixmap(icon_url, loaded)
        return item

    def filter(self, text):
        """Show items matching the search, shorthand included ("VV", "TotM", "Childe")."""
        first = None
        for i in range(self.count()):
            item = self.item(i)
            hidden = not matches(text, item.data(NAME_ROLE))
            item.setHidden(hidden)
            if not hidden and first is None:
                first = item
        current = self.currentItem()
        if text.strip() and first and (current is None or current.isHidden()):
            self.setCurrentItem(first)  # so Enter picks the top match


def _stars(n):
    return "★" * n


def _search_box(placeholder, popup):
    box = QLineEdit(placeholderText=placeholder)
    box.setClearButtonEnabled(True)  # Enter picks the top match through the default (OK) button
    return box


class CharacterSearchDialog(Popup):
    """Type to search, then pick one character to add."""

    def __init__(self, characters, element, parent=None, title=None):
        super().__init__(parent, title or f"Add {gamedata.pretty(element)} character", 440, 560)
        self.chosen = None

        self.search = _search_box("Search characters…  (e.g. Childe, HT, Kazu)", self)
        self.list = _IconList()
        for c in sorted(characters, key=lambda c: c.name):
            self.list.add(f"{c.name}\n{_stars(c.rarity)}  {gamedata.weapon_type_name(c.weapon_type)}", c.icon, c.id, rarity=c.rarity)
        self.search.textChanged.connect(self.list.filter)
        self.list.itemDoubleClicked.connect(lambda _: self.accept())

        self.body.addWidget(self.search)
        if not characters:
            self.body.addWidget(QLabel("Every character of this element is already logged."))
        self.body.addWidget(self.list, 1)
        self.body.addWidget(_buttons(self, "Choose"))
        self.search.setFocus()

    def accept(self):
        item = self.list.currentItem()
        if item is None or item.isHidden():
            return
        self.chosen = item.data(Qt.UserRole)
        super().accept()


class WeaponDialog(Popup):
    """Pick a weapon of the character's type and a refinement R1–R5."""

    def __init__(self, weapons, current_id=None, refinement=1, parent=None):
        super().__init__(parent, "Choose weapon", 460, 600)
        self.weapon_id = None
        self.refinement = refinement

        self.search = _search_box("Search weapons…  (e.g. Homa, PJWS, EL)", self)
        self.list = _IconList()
        for w in sorted(weapons, key=lambda w: (-w.rarity, w.name)):
            item = self.list.add(f"{w.name}\n{_stars(w.rarity)}", w.icon, w.id, rarity=w.rarity)
            if w.id == current_id:
                self.list.setCurrentItem(item)
        self.search.textChanged.connect(self.list.filter)
        self.list.itemDoubleClicked.connect(lambda _: self.accept())

        row = QHBoxLayout()
        row.addWidget(QLabel("Refinement"))
        self.refine = QComboBox()
        self.refine.addItems([f"R{i}" for i in range(1, 6)])
        self.refine.setCurrentIndex(refinement - 1)
        row.addWidget(self.refine)
        row.addStretch()

        self.body.addWidget(self.search)
        self.body.addWidget(self.list, 1)
        self.body.addLayout(row)
        self.body.addWidget(_buttons(self))
        if self.list.currentItem():
            self.list.scrollToItem(self.list.currentItem())
        self.search.setFocus()

    def accept(self):
        item = self.list.currentItem()
        if item is None or item.isHidden():
            return  # nothing picked yet
        self.weapon_id = item.data(Qt.UserRole)
        self.refinement = self.refine.currentIndex() + 1
        super().accept()


class ArtifactDialog(Popup):
    """Pick one artifact set (4-piece) or two sets (2-piece + 2-piece)."""

    def __init__(self, artifacts, current_ids=(), parent=None):
        super().__init__(parent, "Choose artifact sets", 500, 640)
        self.chosen = []
        self._order = [i for i in current_ids if i]  # selection order: first chosen is the base picture

        hint = QLabel("Tick 1 set for 4-piece, or 2 sets for 2-piece + 2-piece.")
        hint.setStyleSheet("color: rgba(255,255,255,0.6);")
        self.search = QLineEdit(placeholderText="Search artifact sets…  (e.g. VV, TotM, EoSF)")
        self.search.setClearButtonEnabled(True)
        self.list = _IconList()
        for a in sorted(artifacts, key=lambda a: (-a.rarity, a.name)):
            tip = "\n".join(f"{n}-piece: {b}" for n, b in zip((2, 4), a.bonuses))
            item = self.list.add(a.name, a.icon, a.id, tooltip=tip, rarity=a.rarity)
            # Not ItemIsUserCheckable: clicks anywhere on the row toggle it via _clicked instead.
            item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if a.id in self._order else Qt.Unchecked)
        self.search.textChanged.connect(self.list.filter)
        self.list.itemChanged.connect(self._changed)
        self.list.itemClicked.connect(self._clicked)
        self.summary = QLabel()

        buttons = _buttons(self)
        self.ok = buttons.button(QDialogButtonBox.Ok)

        self.body.addWidget(hint)
        self.body.addWidget(self.search)
        self.body.addWidget(self.list, 1)
        self.body.addWidget(self.summary)
        self.body.addWidget(buttons)
        self._refresh()
        self.search.setFocus()

    def keyPressEvent(self, event):
        # Enter in the search box ticks the top match instead of closing
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.search.hasFocus():
            item = self.list.currentItem()
            if item and not item.isHidden():
                self._clicked(item)
            return
        super().keyPressEvent(event)

    def _clicked(self, item):
        item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)

    def _changed(self, item):
        set_id = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked and set_id not in self._order:
            self._order.append(set_id)
            if len(self._order) > 2:  # keep the two most recent picks
                dropped = self._order.pop(0)
                for i in range(self.list.count()):
                    if self.list.item(i).data(Qt.UserRole) == dropped:
                        self.list.blockSignals(True)
                        self.list.item(i).setCheckState(Qt.Unchecked)
                        self.list.blockSignals(False)
        elif item.checkState() == Qt.Unchecked and set_id in self._order:
            self._order.remove(set_id)
        self._refresh()

    def _refresh(self):
        names = {self.list.item(i).data(Qt.UserRole): self.list.item(i).text() for i in range(self.list.count())}
        if not self._order:
            self.summary.setText("Nothing selected")
        elif len(self._order) == 1:
            self.summary.setText(f"4p  {names[self._order[0]]}")
        else:
            self.summary.setText(f"2p2p  {names[self._order[0]]} + {names[self._order[1]]}")
        self.ok.setEnabled(bool(self._order))

    def accept(self):
        if not self._order:
            return
        self.chosen = list(self._order)
        super().accept()


def _field_label(text):
    label = QLabel(text)
    label.setObjectName("FieldLabel")
    return label


def _level_box(items, index, tooltip):
    box = QComboBox()
    box.setObjectName("TalentBox")
    box.setCursor(Qt.PointingHandCursor)
    box.addItems(items)
    box.setMaxVisibleItems(len(items))  # the whole list without scrolling
    box.view().setMinimumWidth(56)
    box.setCurrentIndex(index)
    box.setToolTip(tooltip)
    return box


class BuildDialog(Popup):
    """A character's build: weapon (with refinement), artifact sets, constellation and talent levels.
    adding=True for a character being added (they need a weapon and artifacts first).
    After exec(), `values` holds the fields to save."""

    def __init__(self, index, info, record, parent=None, adding=False):
        super().__init__(parent, f"Add {info.name}" if adding else f"{info.name}  ·  Build", 520)
        self.index, self.info, self.adding = index, info, adding
        self.values = {
            "weapon_id": record.get("weapon_id"),
            "refinement": record.get("refinement") or 1,
            "artifact1": record.get("artifact1"),
            "artifact2": record.get("artifact2"),
            "constellation": record.get("constellation") or 0,
            "talent1": record.get("talent1") or 1,
            "talent2": record.get("talent2") or 1,
            "talent3": record.get("talent3") or 1,
        }

        gear = QHBoxLayout()
        gear.setSpacing(18)
        self.weapon_tile = ImageTile(104)
        self.weapon_tile.clicked.connect(self._pick_weapon)
        self.weapon_name = QLabel()
        self.artifact_tile = ImageTile(104)
        self.artifact_tile.clicked.connect(self._pick_artifacts)
        self.artifact_name = QLabel()
        for label, tile, name in (("WEAPON", self.weapon_tile, self.weapon_name),
                                  ("ARTIFACTS", self.artifact_tile, self.artifact_name)):
            col = QVBoxLayout()
            col.setSpacing(4)
            col.addWidget(_field_label(label))
            col.addWidget(tile)
            name.setWordWrap(True)
            name.setFixedWidth(200)
            name.setStyleSheet("font-size: 9pt; color: #d6d9df;")
            col.addWidget(name)
            col.addStretch()
            gear.addLayout(col)
        gear.addStretch()
        self.body.addLayout(gear)

        levels = QHBoxLayout()
        levels.setSpacing(24)
        cons_col = QVBoxLayout()
        cons_col.setSpacing(4)
        cons_col.addWidget(_field_label("CONSTELLATION"))
        self.cons_box = _level_box([f"C{n}" for n in range(7)], self.values["constellation"], "Constellation level")
        cons_col.addWidget(self.cons_box)
        levels.addLayout(cons_col)
        talent_col = QVBoxLayout()
        talent_col.setSpacing(4)
        talent_col.addWidget(_field_label("TALENT LEVEL"))
        talents = QHBoxLayout()
        talents.setSpacing(4)
        self.talent_boxes = []
        for i, name in enumerate(("Normal Attack", "Elemental Skill", "Elemental Burst")):
            if i:
                slash = QLabel("/")
                slash.setStyleSheet("font-size: 14pt; color: rgba(255,255,255,0.55);")
                talents.addWidget(slash)
            box = _level_box([str(n) for n in range(1, 16)], self.values[f"talent{i + 1}"] - 1, name)
            self.talent_boxes.append(box)
            talents.addWidget(box)
        talents.addStretch()
        talent_col.addLayout(talents)
        levels.addLayout(talent_col, 1)
        self.body.addSpacing(6)
        self.body.addLayout(levels)

        self.missing = QLabel(f"Choose a weapon and artifacts to add {info.name}.")
        self.missing.setStyleSheet("color: rgba(255,255,255,0.55);")
        self.body.addSpacing(4)
        self.body.addWidget(self.missing)
        buttons = _buttons(self, "Add" if adding else "Save")
        self.ok = buttons.button(QDialogButtonBox.Ok)
        self.body.addWidget(buttons)
        self._refresh()

    def _refresh(self):
        dim = "<span style='color:rgba(255,255,255,0.55)'>{}</span>"
        weapon = self.index.weapons.get(self.values["weapon_id"]) if self.values["weapon_id"] else None
        if weapon:
            ref = self.values["refinement"]
            self.weapon_tile.set_content([weapon.icon], weapon.rarity, f"R{ref}")
            self.weapon_name.setText(f"{weapon.name}<br>{dim.format(f'Refinement {ref}')}")
        else:
            self.weapon_tile.clear()
            self.weapon_name.setText(dim.format("Click to choose a weapon"))
        sets = [self.index.artifacts.get(self.values[k]) for k in ("artifact1", "artifact2") if self.values[k]]
        sets = [s for s in sets if s]
        if sets:
            self.artifact_tile.set_content([s.icon for s in sets], max(s.rarity for s in sets), "4p" if len(sets) == 1 else "2p2p")
            self.artifact_name.setText("<br>".join(s.name for s in sets))
        else:
            self.artifact_tile.clear()
            self.artifact_name.setText(dim.format("Click to choose artifact sets"))
        ready = bool(self.values["weapon_id"] and self.values["artifact1"])
        self.ok.setEnabled(ready)
        self.missing.setVisible(not ready)

    def _pick_weapon(self):
        weapons = [w for w in self.index.weapons.values() if w.type == self.info.weapon_type]
        dialog = WeaponDialog(weapons, self.values["weapon_id"], self.values["refinement"], self)
        if dialog.exec() and dialog.weapon_id:
            self.values.update(weapon_id=dialog.weapon_id, refinement=dialog.refinement)
            self._refresh()

    def _pick_artifacts(self):
        current = (self.values["artifact1"], self.values["artifact2"])
        dialog = ArtifactDialog(self.index.artifacts.values(), current, self)
        if dialog.exec() and dialog.chosen:
            chosen = dialog.chosen + [None]
            self.values.update(artifact1=chosen[0], artifact2=chosen[1])
            self._refresh()

    def accept(self):
        if not (self.values["weapon_id"] and self.values["artifact1"]):
            return
        self.values["constellation"] = self.cons_box.currentIndex()
        for i, box in enumerate(self.talent_boxes):
            self.values[f"talent{i + 1}"] = box.currentIndex() + 1
        super().accept()
