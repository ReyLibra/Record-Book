"""Character log: a logged character's banner and their runs.

"+ Add run" opens a form with the team (the logged character plus up to three teammates, each with
weapon, artifacts, talents and constellation), notes, the mode and the total damage. Submitting saves
the whole thing as a run; runs are listed newest first with their date and stay editable.
"""

from datetime import date

from PySide6.QtCore import QDate, Qt, QTimer, Signal
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QCompleter,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import gamedata
from character_page import PRYDWEN_ELEMENTS, Hero, KitSection, _label, fill_hero, page_css
from dialogs import ArtifactDialog, CharacterSearchDialog, WeaponDialog, confirm
from store import BUILD_FIELDS
from widgets import CORNER, ImageTile, card_pixmap, clear_layout, corners, filter_button, themed_calendar

# DPS = total damage ÷ the mode's time (seconds)
MODES = [("abyss", "Spiral Abyss", 90), ("fearless", "Stygian Fearless", 120), ("dire", "Stygian Dire", 120)]
MODE_NAMES = {key: name for key, name, _ in MODES}
DIVISORS = {key: seconds for key, _, seconds in MODES}
TEAM_SIZE = 3  # teammates besides the logged character
# the team cards in a run's editor: the portrait, with the weapon over the artifact set beside it (fits the
# narrowest card, at the smallest window; the tiles are big enough that their R# / 4p tag leaves the picture)
CARD_PORTRAIT = 72
CARD_GEAR = 50
ROW_FULL_WIDTH = 1080  # a run's summary row narrower than this uses the dense cells
DENSE_PORTRAIT = 56
PORTRAIT = 64  # team portraits in a run's summary, each with its weapon and artifact set beside it
GEAR_ICON = (PORTRAIT - 3) // 2
SUMMARY_COLUMN = 200  # a run's date / DPS / team name, the same width in every row (so the teams line up)
LEVELS_COLUMN = 54  # a teammate's "C6" and "10/13/13", the same width for each (so the cells are evenly spaced)
NOTES_WIDTH = 300  # the run's notes on the right of the summary
NOTES_CHARS = 140

LOG_CSS = """
#LogCard { background: rgba(28,29,35,0.95); border: 1px solid #30323c; border-radius: 0; }
#LogMainCard { background: rgba(28,29,35,0.95); border: 1px solid #30323c; border-top: 2px solid ACCENT; border-radius: 0; }
#RunItem { background: rgba(28,29,35,0.95); border: 1px solid #30323c; border-radius: 0; }
#RunItem[best="true"] { border-left: 3px solid #f4c35f; }
#RunHead { background: rgba(17,18,22,0.72); border: none; border-radius: 0; }
#RunHead:hover { background: rgba(0,158,236,0.08); }
#AddTeammate { background: rgba(0,0,0,0.18); border: 1px dashed #4a4d57; border-radius: 0; color: #009eec; font-weight: 600; }
#AddTeammate:hover { background: rgba(0,158,236,0.10); border-color: #009eec; }
#RemoveBtn { background: transparent; border: none; color: rgba(255,255,255,0.55); padding: 0 4px; font-weight: 700; }
#RemoveBtn:hover { color: #f75058; }
#RunHeader { color: #8c909b; font-size: 7.5pt; font-weight: 900; }
#RunValue { font-size: 15pt; font-weight: 700; color: #ffffff; }
#MemberCons { font-size: 11pt; font-weight: 800; color: #ffffff; }
#MemberTalents { font-size: 8.5pt; font-weight: 600; color: rgba(255,255,255,0.62); }
#FavStar { background: transparent; border: none; font-size: 20pt; color: rgba(255,255,255,0.45); padding: 0 4px; }
#FavStar:hover { color: #f4c35f; }
#FavStar:checked { color: #f4c35f; }
#LogCard QComboBox#TalentBox, #LogMainCard QComboBox#TalentBox { padding: 2px 3px; font-size: 12pt; }
QPushButton#DeleteRun { color: #f75058; }
QPushButton#DeleteRun:hover { border-color: #f75058; background: rgba(247,80,88,0.12); }
#CardName { font-size: 12.5pt; font-weight: 700; color: #ffffff; }
#RunNotes { color: rgba(255,255,255,0.62); font-size: 9pt; }
#BestBadge { background: rgba(244,195,95,0.12); border: 1px solid rgba(244,195,95,0.46); color: #f4c35f;
             font-size: 8pt; font-weight: 900; padding: 2px 6px; }
""" + corners(["#LogCard", "#LogMainCard", "#RunItem"]) + (
    # a run's header fills its top (and, folded, the whole run): its corners follow the run's
    f"#RunHead {{ border-top-right-radius: {CORNER - 1}px; border-bottom-left-radius: {CORNER - 1}px; }}\n")


def _parse_number(text):
    try:
        return float(text.replace(",", "").strip())
    except ValueError:
        return None


def _millions(value):
    return f"{value / 1_000_000:,.2f}M"


def _portrait(label, info, size):
    """Draw a character card into a QLabel (card_pixmap draws at 2x, so mark it as such)."""
    def with_element(element_pm):
        def with_icon(pm):
            card = card_pixmap(pm, element_pm, info.rarity, size)
            card.setDevicePixelRatio(2)
            label.setPixmap(card)

        gamedata.load_pixmap(info.icon, with_icon)

    gamedata.load_pixmap(gamedata.element_icon_url(info.element), with_element)


def _lookup(index, char_id):
    """CharInfo for an id stored as text (the index may key by str or int)."""
    chars = index.characters
    found = chars.get(char_id) or chars.get(str(char_id))
    if found is None and str(char_id).isdigit():
        found = chars.get(int(char_id))
    return found


def _member(info, build=None, constellation=0):
    """A team member dict for a character, from a saved build when there is one."""
    build = build or {}
    member = {"char_id": str(info.id), "name": info.name, "constellation": build.get("constellation", constellation) or 0}
    member.update({f: build.get(f) for f in BUILD_FIELDS})
    for f in ("refinement", "talent1", "talent2", "talent3"):
        member[f] = member[f] or 1
    return member


class ElidedLabel(QLabel):
    """One line of text, cut short with "…" to fit its width (the whole text in the tooltip)."""

    def __init__(self, text="", name=None):
        super().__init__()
        if name:
            self.setObjectName(name)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(10)
        self.full_text = ""
        self.set_full_text(text)

    def set_full_text(self, text):
        self.full_text = text
        self.setToolTip(text if text else "")
        self._fit()

    def _fit(self):
        self.setText(self.fontMetrics().elidedText(self.full_text, Qt.ElideRight, max(10, self.width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()


class TeamCard(QFrame):
    """One team column, compact so the whole run fits the smallest window: name; portrait with the weapon
    (refinement) and artifact set beside it; their names; talents and constellation."""

    changed = Signal()
    remove_requested = Signal(str)

    def __init__(self, member, info, index, kicker, main=False):
        super().__init__()
        self.setObjectName("LogMainCard" if main else "LogCard")
        self.member = dict(member)
        self.info = info
        self.index = index
        self.setMinimumWidth(150)
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 10)
        v.setSpacing(5)

        top = QHBoxLayout()
        top.addWidget(_label(kicker, "PanelKicker"), 1)
        if not main:
            remove = QPushButton("✕")
            remove.setObjectName("RemoveBtn")
            remove.setCursor(Qt.PointingHandCursor)
            remove.setToolTip("Remove from the team")
            remove.clicked.connect(lambda: self.remove_requested.emit(str(info.id)))
            top.addWidget(remove)
        v.addLayout(top)
        v.addWidget(ElidedLabel(info.name, "CardName"))

        # portrait | weapon over artifact set (click a tile to change it; hover it for what it is)
        row = QHBoxLayout()
        row.setSpacing(6)
        portrait = QLabel()
        portrait.setFixedSize(CARD_PORTRAIT, CARD_PORTRAIT)
        _portrait(portrait, info, CARD_PORTRAIT)
        row.addWidget(portrait)
        self.weapon_tile = ImageTile(CARD_GEAR)
        self.weapon_tile.clicked.connect(self._edit_weapon)
        self.artifact_tile = ImageTile(CARD_GEAR)
        self.artifact_tile.clicked.connect(self._edit_artifacts)
        gear = QVBoxLayout()
        gear.setSpacing(4)
        for tile in (self.weapon_tile, self.artifact_tile):
            tile.instant_tip = True
            gear.addWidget(tile)
        row.addLayout(gear)
        row.addStretch()
        v.addLayout(row)

        levels = QHBoxLayout()
        levels.setSpacing(8)
        talents_col = QVBoxLayout()
        talents_col.setSpacing(0)
        talents_col.addWidget(_label("TALENTS", "FieldLabel"))
        talents = QHBoxLayout()
        talents.setSpacing(0)
        for i in range(3):
            if i:
                slash = QLabel("/")
                slash.setStyleSheet("color: rgba(255,255,255,0.55);")
                talents.addWidget(slash)
            box = self._combo([str(n) for n in range(1, 16)], (self.member.get(f"talent{i + 1}") or 1) - 1,
                              ["Normal Attack", "Elemental Skill", "Elemental Burst"][i])
            box.currentIndexChanged.connect(lambda idx, i=i: self._set(**{f"talent{i + 1}": idx + 1}))
            talents.addWidget(box)
        talents.addStretch()
        talents_col.addLayout(talents)
        levels.addLayout(talents_col, 1)
        cons_col = QVBoxLayout()
        cons_col.setSpacing(0)
        cons_col.addWidget(_label("CONS", "FieldLabel"))
        cons = self._combo([f"C{n}" for n in range(7)], self.member.get("constellation") or 0, "Constellation level")
        cons.currentIndexChanged.connect(lambda idx: self._set(constellation=idx))
        cons_col.addWidget(cons)
        levels.addLayout(cons_col)
        v.addLayout(levels)
        v.addStretch()
        self._show_gear()

    @staticmethod
    def _combo(items, index, tooltip):
        box = QComboBox()
        box.setObjectName("TalentBox")
        box.setCursor(Qt.PointingHandCursor)
        box.addItems(items)
        box.setMaxVisibleItems(len(items))  # the whole list (1-15) without scrolling
        box.view().setMinimumWidth(56)
        box.setMinimumWidth(box.fontMetrics().horizontalAdvance("C66") + 10)
        box.setCurrentIndex(index)
        box.setToolTip(tooltip)
        return box

    def _show_gear(self):
        weapon = self.index.weapons.get(self.member.get("weapon_id"))
        if weapon:
            ref = self.member.get("refinement") or 1
            self.weapon_tile.set_content([weapon.icon], weapon.rarity, f"R{ref}")
            self.weapon_tile.setToolTip(f"R{ref}: {weapon.name}")
        else:
            self.weapon_tile.clear()
            self.weapon_tile.setToolTip("Choose a weapon")
        sets = [self.index.artifacts.get(self.member.get(k)) for k in ("artifact1", "artifact2")]
        sets = [s for s in sets if s]
        if len(sets) == 1:
            self.artifact_tile.set_content([sets[0].icon], sets[0].rarity, "4p")
            self.artifact_tile.setToolTip(f"4p: {sets[0].name}")
        elif sets:  # two 2-piece sets: what each one's 2-piece bonus gives
            self.artifact_tile.set_content([s.icon for s in sets], max(s.rarity for s in sets), "2p2p")
            effects = [(s.bonuses[0] if s.bonuses else s.name).rstrip(". ") for s in sets]
            self.artifact_tile.setToolTip(f"2p2p: {' / '.join(effects)}")
        else:
            self.artifact_tile.clear()
            self.artifact_tile.setToolTip("Choose artifact sets")

    def _set(self, **fields):
        self.member.update(fields)
        self._show_gear()
        self.changed.emit()

    def _edit_weapon(self):
        weapons = [w for w in self.index.weapons.values() if w.type == self.info.weapon_type]
        dialog = WeaponDialog(weapons, self.member.get("weapon_id"), self.member.get("refinement") or 1, self)
        if dialog.exec() and dialog.weapon_id:
            self._set(weapon_id=dialog.weapon_id, refinement=dialog.refinement)

    def _edit_artifacts(self):
        current = (self.member.get("artifact1"), self.member.get("artifact2"))
        dialog = ArtifactDialog(self.index.artifacts.values(), current, self)
        if dialog.exec() and dialog.chosen:
            chosen = dialog.chosen + [None]
            self._set(artifact1=chosen[0], artifact2=chosen[1])


class RunEditor(QWidget):
    """Everything about one run: mode, team, notes, total damage and the 'highest DPS' mark.

    new=True shows Submit/Cancel; otherwise every edit emits `changed` (the page saves it).
    """

    changed = Signal()
    submitted = Signal()
    cancelled = Signal()
    delete_requested = Signal()  # a saved run's "Delete run"

    def __init__(self, store, index, data, new=False):
        super().__init__()
        self.store = store
        self.index = index
        self.data = {
            "run_date": data.get("run_date") or date.today().isoformat(),
            "mode": data.get("mode") or MODES[0][0],
            "damage": data.get("damage"),
            "notes": data.get("notes") or "",
            "team": [dict(m) for m in data.get("team") or []],
            "team_name": data.get("team_name") or "",
        }
        self.new = new
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        # mode (and date, for saved runs)
        top = QHBoxLayout()
        top.setSpacing(4)
        self.mode_group = QButtonGroup(self)
        for n, (key, label, seconds) in enumerate(MODES):
            btn = filter_button(label, tooltip=f"DPS = total damage ÷ {seconds}")
            btn.setChecked(key == self.data["mode"])
            self.mode_group.addButton(btn, n)
            top.addWidget(btn)
        self.mode_group.idClicked.connect(self._mode_changed)
        top.addStretch()
        # optional team name, suggesting names used before
        top.addWidget(_label("TEAM NAME", "FieldLabel"))
        self.team_name = QLineEdit(self.data["team_name"])
        self.team_name.setPlaceholderText("e.g. Mavuika National")
        self.team_name.setMinimumWidth(140)
        self.team_name.setMaximumWidth(230)
        completer = QCompleter(store.team_names(), self.team_name)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.team_name.setCompleter(completer)
        self.team_name.textChanged.connect(self._team_name_edited)
        self.team_name.editingFinished.connect(self._damage_committed)  # saves a logged run
        top.addWidget(self.team_name)
        top.addSpacing(12)
        if not new:
            top.addWidget(_label("DATE", "FieldLabel"))
            self.date_edit = QDateEdit(QDate.fromString(self.data["run_date"], "yyyy-MM-dd"))
            self.date_edit.setCalendarPopup(True)
            self.date_edit.setDisplayFormat("yyyy-MM-dd")
            themed_calendar(self.date_edit)
            self.date_edit.dateChanged.connect(self._date_changed)
            top.addWidget(self.date_edit)
        v.addLayout(top)

        # 5 columns: the logged character, three teammates (alphabetical), notes
        self.columns = QHBoxLayout()
        self.columns.setSpacing(12)
        v.addLayout(self.columns)
        self._notes_timer = QTimer(self, singleShot=True, interval=500)
        self._notes_timer.timeout.connect(self.changed)
        self._render_team()

        # one row: total damage, what it is in millions, the DPS it works out to, and (new runs) the buttons
        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        bottom.addWidget(_label("TOTAL DAMAGE", "FieldLabel"))
        self.damage_input = QLineEdit()
        self.damage_input.setPlaceholderText("e.g. 108000000")
        self.damage_input.setMaximumWidth(240)
        validator = QDoubleValidator(0, 1e15, 2, self.damage_input)
        validator.setNotation(QDoubleValidator.StandardNotation)
        self.damage_input.setValidator(validator)
        if self.data["damage"]:
            self.damage_input.setText(f"{self.data['damage']:.0f}")
        self.damage_input.textEdited.connect(self._damage_edited)
        self.damage_input.editingFinished.connect(self._damage_committed)
        bottom.addWidget(self.damage_input, 1)
        self.millions = _label("—", "RunValue")
        self.millions.setToolTip("The damage in millions")
        bottom.addWidget(self.millions)
        bottom.addWidget(_label("·", "RunHeader"))
        self.dps_label = _label("", "RunValue")
        self.dps_label.setStyleSheet("color: #009eec;")
        self.dps_label.setToolTip("DPS = total damage ÷ the mode's time (the highest run in each mode is marked)")
        bottom.addWidget(self.dps_label)
        bottom.addStretch()
        if not new:
            delete = QPushButton("Delete run")
            delete.setObjectName("DeleteRun")
            delete.setCursor(Qt.PointingHandCursor)
            delete.setToolTip("Delete this run (asks first)")
            delete.clicked.connect(self.delete_requested)
            bottom.addWidget(delete)
        if new:
            cancel = QPushButton("Cancel")
            cancel.clicked.connect(self.cancelled)
            submit = QPushButton("Submit run")
            submit.setObjectName("Primary")
            submit.clicked.connect(self.submitted)
            bottom.addWidget(cancel)
            bottom.addWidget(submit)
        v.addLayout(bottom)
        self._update_numbers()

    # ----- the numbers -----
    def dps(self):
        return (self.data["damage"] or 0) / DIVISORS[self.data["mode"]]

    def payload(self):
        return {**self.data, "dps": self.dps(), "notes": self.notes.toPlainText()}

    def _update_numbers(self):
        damage = self.data["damage"]
        self.millions.setText(f"{_millions(damage)} DMG" if damage else "— DMG")
        self.dps_label.setText(f"{self.dps():,.0f} DPS")

    def _damage_edited(self, text):
        self.data["damage"] = _parse_number(text)
        self._update_numbers()

    def _team_name_edited(self, text):
        self.data["team_name"] = text

    def _damage_committed(self):
        if not self.new:
            self.changed.emit()

    def _mode_changed(self, n):
        self.data["mode"] = MODES[n][0]
        self._update_numbers()
        if not self.new:
            self.changed.emit()

    def _date_changed(self, d):
        self.data["run_date"] = d.toString("yyyy-MM-dd")
        self.changed.emit()

    # ----- team -----
    def _info(self, char_id):
        return _lookup(self.index, char_id)

    def _render_team(self):
        notes_text = self.notes.toPlainText() if hasattr(self, "notes") else self.data["notes"]
        clear_layout(self.columns)
        team = self.data["team"]
        main, mates = team[0], sorted(team[1:], key=lambda m: m["name"])
        self.data["team"] = [main] + mates
        for n, member in enumerate(self.data["team"]):
            info = self._info(member["char_id"])
            if info is None:
                continue
            card = TeamCard(member, info, self.index, "LOGGED CHARACTER" if n == 0 else "TEAMMATE", main=(n == 0))
            card.changed.connect(lambda c=card, n=n: self._member_changed(n, c))
            card.remove_requested.connect(self._remove_member)
            self.columns.addWidget(card, 1)
        for _ in range(TEAM_SIZE - len(mates)):
            add = QPushButton("+\nAdd teammate")
            add.setObjectName("AddTeammate")
            add.setCursor(Qt.PointingHandCursor)
            add.setMinimumSize(150, 160)
            add.clicked.connect(self._add_member)
            self.columns.addWidget(add, 1)
        box = QFrame()
        box.setObjectName("LogCard")
        box.setMinimumWidth(150)
        nv = QVBoxLayout(box)
        nv.setContentsMargins(12, 10, 12, 12)
        nv.addWidget(_label("NOTES", "PanelKicker"))
        self.notes = QPlainTextEdit(notes_text)
        self.notes.setMinimumHeight(60)
        self.notes.setPlaceholderText("Rotation, buffs, what went wrong…")
        self.notes.textChanged.connect(self._notes_changed)
        nv.addWidget(self.notes, 1)
        self.columns.addWidget(box, 1)

    def _notes_changed(self):
        self.data["notes"] = self.notes.toPlainText()
        if not self.new:
            self._notes_timer.start()

    def _member_changed(self, n, card):
        self.data["team"][n] = card.member
        if not self.new:
            self.changed.emit()

    def _remove_member(self, char_id):
        self.data["team"] = [m for m in self.data["team"] if m is self.data["team"][0] or str(m["char_id"]) != char_id]
        self._render_team()
        if not self.new:
            self.changed.emit()

    def _add_member(self):
        taken = {str(m["char_id"]) for m in self.data["team"]}
        candidates = [c for c in self.index.characters.values() if str(c.id) not in taken]
        dialog = CharacterSearchDialog(candidates, None, self, title="Add teammate")
        if not dialog.exec() or dialog.chosen is None:
            return
        info = self._info(dialog.chosen)
        # filled in from the build this character last had on a team (or their own logged build)
        self.data["team"].append(_member(info, self.store.saved_build(str(info.id))))
        self._render_team()
        if not self.new:
            self.changed.emit()


def visible_room(widget, fallback):
    """How wide a widget can be on screen: the visible width of the scroll area it's in, less the margins on
    either side of it (fallback when it isn't in one)."""
    from PySide6.QtWidgets import QScrollArea

    parent = widget.parentWidget()
    while parent is not None and not isinstance(parent, QScrollArea):
        parent = parent.parentWidget()
    if parent is None:
        return fallback
    offset = widget.mapTo(parent.widget(), widget.rect().topLeft()).x()  # (the page's margin on the left)
    return parent.viewport().width() - 2 * offset


class _ClickFrame(QFrame):
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


class RunItem(QFrame):
    """A saved run: a summary line (date, mode, team, damage, DPS) that expands into its editor."""

    saved = Signal(int)  # run id
    delete_requested = Signal(int)
    toggled = Signal(object)  # this run, opened or closed

    def __init__(self, store, index, run, best=False, expanded=False, dense=False):
        """best: the run is the highest in its mode (the mark says which mode). dense: start with the narrow
        row's cells (the page knows its width; worked out again once the row is laid out)."""
        super().__init__()
        self.setObjectName("RunItem")
        self.setProperty("best", "true" if best else "false")
        # never taller than it needs (with a single run it used to stretch to fill the page)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.store = store
        self.index = index
        self.run_id = run["id"]
        self.char_id = run["char_id"]
        self.best = best
        v = QVBoxLayout(self)
        v.setContentsMargins(1, 1, 1, 1)
        v.setSpacing(0)

        self.head = _ClickFrame()
        self.head.setObjectName("RunHead")
        self.head.setCursor(Qt.PointingHandCursor)
        self.head.setToolTip("Show or hide this run")
        self.head.setMinimumHeight(104)
        self.head.clicked.connect(self.toggle)
        h = QHBoxLayout(self.head)
        h.setContentsMargins(14, 10, 10, 10)
        h.setSpacing(12)
        self.arrow = _label("", "RunHeader")
        self.summary = QLabel()
        self.summary.setStyleSheet("font-size: 10pt;")
        self.summary.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.summary.setFixedWidth(SUMMARY_COLUMN)
        self.summary.setWordWrap(True)  # (a long team name wraps)
        self.portraits = QHBoxLayout()
        self.portraits.setSpacing(10)
        self._mode_name = MODE_NAMES.get(run.get('mode'), '').upper()
        self.best_badge = _label(f"★ HIGHEST · {self._mode_name}", "BestBadge")
        self.best_badge.setAlignment(Qt.AlignCenter)
        self._dense = dense  # a narrow row: smaller team cells, the mark on two lines
        for w in (self.arrow, self.summary, self.best_badge):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        h.addWidget(self.arrow)
        h.addWidget(self.summary)
        h.addLayout(self.portraits)
        self.team_label = QLabel()
        self.team_label.setStyleSheet("font-size: 10pt; font-weight: 700; color: #ffffff;")
        self.team_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        h.addWidget(self.team_label)
        # the run's notes, on the right before the HIGHEST mark (they get the row's spare width)
        self.notes = QLabel()
        self.notes.setObjectName("RunNotes")
        self.notes.setMaximumWidth(NOTES_WIDTH)
        self.notes.setWordWrap(True)
        self.notes.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)  # gives way first when it's tight
        self.notes.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.notes.setAttribute(Qt.WA_TransparentForMouseEvents)
        h.addWidget(self.notes, 1)
        h.addStretch()  # (keeps the summary on the left when the notes are hidden)
        h.addWidget(self.best_badge, 0, Qt.AlignVCenter)
        v.addWidget(self.head)

        # the editor is built the first time the run is opened (building every run's editor up front, with its
        # team cards and their dozens of dropdowns, made opening a log freeze for half a second)
        self.run = run
        self.editor = None
        self._expanded = False
        self.body = QWidget()
        self._body_layout = QVBoxLayout(self.body)
        self._body_layout.setContentsMargins(12, 8, 12, 10)
        v.addWidget(self.body)
        self.set_expanded(expanded)

    @property
    def expanded(self):
        return self._expanded

    def toggle(self):
        self.set_expanded(not self.expanded)
        self.toggled.emit(self)

    def set_expanded(self, on):
        if on and self.editor is None:
            self.editor = RunEditor(self.store, self.index, self.run)
            self.editor.changed.connect(self._save)
            self.editor.delete_requested.connect(lambda: self.delete_requested.emit(self.run_id))
            self._body_layout.addWidget(self.editor)
        self._expanded = on
        self.body.setVisible(on)
        self.head.setMinimumHeight(0 if on else 104)
        self._render_summary()

    def _payload(self):
        """The run as it is now: from its editor once it has one, else as it was saved."""
        if self.editor is not None:
            return self.editor.payload()
        run = self.run
        mode = run.get("mode") or MODES[0][0]
        return {"run_date": run.get("run_date") or date.today().isoformat(), "mode": mode,
                "damage": run.get("damage"), "notes": run.get("notes") or "", "team": run.get("team") or [],
                "team_name": run.get("team_name") or "", "dps": (run.get("damage") or 0) / DIVISORS[mode]}

    def _render_summary(self):
        d = self._payload()
        self.arrow.setText("▾" if self.expanded else "▸")
        damage = f"{_millions(d['damage'])} DMG" if d["damage"] else "No damage entered"
        name = (d.get("team_name") or "").strip()
        team = f"<br><b style='color:#ffffff'>“{name}”</b>" if name else ""
        self.summary.setText(
            f"<b>{d['run_date']}</b>&nbsp; · &nbsp;{MODE_NAMES[d['mode']]}<br>{damage}"
            f"&nbsp; · &nbsp;<b style='color:#009eec'>{d['dps']:,.0f} DPS</b>{team}"
        )
        clear_layout(self.portraits)
        for member in d["team"] if not self.expanded else ():  # open: the team is in the editor below
            info = _lookup(self.index, member["char_id"])
            if info:
                self.portraits.addWidget(self._member_cell(member, info))
        self.best_badge.setText(f"★ HIGHEST\n{self._mode_name}" if self._dense else f"★ HIGHEST · {self._mode_name}")
        self.team_label.hide()  # the team name is under the summary now
        self.best_badge.setVisible(self.best)
        notes = " ".join((d.get("notes") or "").split())
        if len(notes) > NOTES_CHARS:
            notes = notes[:NOTES_CHARS].rstrip() + "…"
        self._notes = notes
        self.notes.setText(notes)
        self.notes.setToolTip(d.get("notes") or "")
        self.notes.setVisible(bool(notes) and not self.expanded)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._fit_width)

    def _fit_width(self):
        """Narrow row (a small window): the team cells drop their weapon / artifact icons (still in the
        tooltip) and the mark goes on two lines, so nothing is cut off; notes show when there's room."""
        dense = self._room() < ROW_FULL_WIDTH
        if dense != self._dense:
            self._dense = dense
            self._render_summary()
        self.notes.setText(getattr(self, "_notes", "") if self.notes.width() >= 70 else "")

    def _room(self):
        """The width the row has on screen: the page's visible width (the row's own width can't tell, since a
        row too wide for it would widen the page instead of going dense)."""
        return visible_room(self, self.head.width())

    def _member_cell(self, member, info):
        """A teammate in the summary: portrait, with their weapon and artifact set beside it."""
        cell = QWidget()
        cell.setAttribute(Qt.WA_TransparentForMouseEvents)
        row = QHBoxLayout(cell)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)
        size = DENSE_PORTRAIT if self._dense else PORTRAIT
        pic = QLabel()
        pic.setFixedSize(size, size)
        _portrait(pic, info, size)
        row.addWidget(pic)
        gear = QVBoxLayout()
        gear.setSpacing(3)
        weapon = self.index.weapons.get(member.get("weapon_id")) if member.get("weapon_id") else None
        sets = [self.index.artifacts.get(member.get(k)) for k in ("artifact1", "artifact2") if member.get(k)]
        sets = [a for a in sets if a]
        for url, rarity in ((weapon.icon if weapon else None, weapon.rarity if weapon else 1),
                            (sets[0].icon if sets else None, max((a.rarity for a in sets), default=1))):
            icon = QLabel()
            icon.setObjectName("GearIcon")
            icon.setFixedSize(GEAR_ICON, GEAR_ICON)
            if url:
                def loaded(pm, icon=icon, rarity=rarity):
                    card = card_pixmap(pm, None, rarity, GEAR_ICON)
                    card.setDevicePixelRatio(2)
                    icon.setPixmap(card)

                gamedata.load_pixmap(url, loaded)
            gear.addWidget(icon)
        if not self._dense:  # (a narrow row: just the portrait and levels; the gear is in the tooltip)
            row.addLayout(gear)
        else:
            for i in range(gear.count()):
                gear.itemAt(i).widget().deleteLater()
        levels_box = QWidget()
        levels_box.setFixedWidth(LEVELS_COLUMN)
        levels = QVBoxLayout(levels_box)
        levels.setContentsMargins(0, 0, 0, 0)
        levels.setSpacing(0)
        cons = QLabel(f"C{member.get('constellation') or 0}")
        cons.setObjectName("MemberCons")
        talents = QLabel("/".join(str(member.get(f"talent{i}") or 1) for i in (1, 2, 3)))
        talents.setObjectName("MemberTalents")
        levels.addStretch()
        levels.addWidget(cons)
        levels.addWidget(talents)
        levels.addStretch()
        row.addSpacing(2)
        row.addWidget(levels_box)
        cell.setToolTip(f"{info.name}  C{member.get('constellation') or 0}"
                        + (f"\n{weapon.name}  R{member.get('refinement') or 1}" if weapon else "")
                        + (f"\n{'  +  '.join(a.name for a in sets)}" if sets else ""))
        return cell

    def _save(self):
        self.store.save_run(self.char_id, self.editor.payload(), self.run_id)
        self._render_summary()
        self.saved.emit(self.run_id)


class LogPage(QWidget):
    back_home = Signal()
    open_guide = Signal(str)
    changed = Signal()  # a run was added, edited or deleted (Home's DPS may change)
    message = Signal(str)

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.index = None
        self.char_id = None
        self.info = None
        self.new_editor = None
        self._best_ids = {}
        self._request = 0
        self._accent = PRYDWEN_ELEMENTS["GEO"]
        self._apply_css()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.scroll = scroll
        content = QWidget()
        self.v = QVBoxLayout(content)
        self.v.setContentsMargins(28, 22, 28, 28)
        self.v.setSpacing(18)
        scroll.setWidget(content)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # everything fits the width
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self.hero = Hero(compact=True, kicker="GENSHIN IMPACT CHARACTER LOG")
        self.v.addWidget(self.hero)
        self.star = QPushButton("\u2606")
        self.star.setObjectName("FavStar")
        self.star.setCheckable(True)
        self.star.setCursor(Qt.PointingHandCursor)
        self.star.toggled.connect(self._favourite_toggled)
        self.hero.set_corner(self.star)

        # "■ NAME LOG" with the Add run button on the right
        title_row = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("SectionTitle")
        title_row.addWidget(self.title, 1)
        self.add_button = QPushButton("+  Add run")
        self.add_button.setObjectName("Primary")
        self.add_button.setCursor(Qt.PointingHandCursor)
        self.add_button.clicked.connect(self.start_run)
        title_row.addWidget(self.add_button, 0, Qt.AlignBottom)
        self.title_row = title_row
        self.v.addLayout(title_row)

        self.new_section = KitSection("New run", "DPS = total damage ÷ 90 s (Spiral Abyss) or ÷ 120 s (Stygian Onslaught)")
        self.new_section.hide()
        self.v.addWidget(self.new_section)

        self.runs_host = QVBoxLayout()
        self.runs_host.setSpacing(10)
        self.v.addLayout(self.runs_host)
        self.v.addStretch()

    def _apply_css(self):
        self.setStyleSheet(page_css(self._accent) + LOG_CSS.replace("ACCENT", f"rgb{self._accent}"))

    def set_index(self, index):
        self.index = index

    # ----- showing a character -----
    def show_character(self, char_id):
        record = self.store.character(char_id)
        if not record or not self.index:
            return
        info = _lookup(self.index, char_id)
        if info is None:
            return
        self.char_id, self.info = char_id, info
        accent = PRYDWEN_ELEMENTS[info.element]
        if accent != self._accent:
            self._accent = accent
            self._apply_css()
        self.title.setText(f"<span style='color:rgb{accent}'>■</span>&nbsp; {info.name.upper()} LOG")
        self._render_hero_actions()
        self.star.blockSignals(True)
        self.star.setChecked(str(char_id) in self.store.favourites())
        self.star.blockSignals(False)
        self._show_star()
        self._close_new_run()
        self._render_runs()
        self.scroll.verticalScrollBar().setValue(0)

        self._request += 1
        request = self._request

        def done(detail, error):
            if request == self._request and not error:
                fill_hero(self.hero, info, detail, accent, with_profile=False)

        gamedata.run_async(lambda: gamedata.fetch_character_detail(info.id), done)

    def _favourite_toggled(self, on):
        self.store.set_favourite(self.char_id, on)
        self._show_star()
        self.message.emit(f"{self.info.name} {'added to' if on else 'removed from'} your favourites")

    def _show_star(self):
        on = self.star.isChecked()
        self.star.setText("\u2605" if on else "\u2606")
        self.star.setToolTip("Favourite: Record Book can open on your favourites (Settings)" if not on
                             else "A favourite (click to remove)")
        self.hero._place_corner()

    def _render_hero_actions(self):
        clear_layout(self.hero.actions)
        home = QPushButton("←  DPS Log")
        home.clicked.connect(self.back_home)
        guide = QPushButton("Character page")
        guide.clicked.connect(lambda: self.open_guide.emit(str(self.info.id)))
        self.hero.actions.addWidget(home)
        self.hero.actions.addWidget(guide)
        self.hero.actions.addStretch()

    # ----- new run -----
    def _prefill(self):
        """The logged character's current build, plus the team from their latest run (with each
        teammate's latest saved build)."""
        record = self.store.character(self.char_id)
        # the most recently added run that has a team
        runs = sorted((r for r in self.store.runs(self.char_id) if r["team"]), key=lambda r: r["id"], reverse=True)
        last = runs[0] if runs else {}
        last_team = last.get("team") or []
        main_cons = last_team[0].get("constellation", 0) if last_team else 0
        team = [_member(self.info, record, main_cons)]
        for mate in last_team[1:]:
            info = _lookup(self.index, mate["char_id"])
            if info:
                saved = self.store.saved_build(str(info.id)) or mate
                team.append(_member(info, saved, mate.get("constellation", 0)))
        return {"mode": last.get("mode") or MODES[0][0], "team": team, "team_name": last.get("team_name") or ""}

    def start_run(self):
        if self.new_editor is not None:
            self.new_editor.damage_input.setFocus()
            return
        self.new_editor = RunEditor(self.store, self.index, self._prefill(), new=True)
        self.new_editor.submitted.connect(self._submit)
        self.new_editor.cancelled.connect(self._close_new_run)
        self.new_section.body.addWidget(self.new_editor)
        self.new_section.show()
        self.add_button.setEnabled(False)
        for item in self._items():  # one run at a time
            item.set_expanded(False)
        self._update_focus()

    def _close_new_run(self):
        if self.new_editor is not None:
            self.new_editor.hide()
            self.new_editor.deleteLater()
            self.new_editor = None
        self.new_section.hide()
        self.add_button.setEnabled(True)
        self._update_focus()

    def _submit(self):
        data = self.new_editor.payload()
        if not data["damage"]:
            self.message.emit("Enter the total damage before submitting the run.")
            self.new_editor.damage_input.setFocus()
            return
        run_id = self.store.save_run(self.char_id, data)
        self._close_new_run()
        self._render_runs()
        self.changed.emit()
        self.message.emit(f"Run saved: {data['dps']:,.0f} DPS ({MODE_NAMES[data['mode']]}).")
        return run_id

    # ----- saved runs -----
    def _render_runs(self, keep_open=()):
        clear_layout(self.runs_host)
        runs = self.store.runs(self.char_id)
        self._runs_kicker = _label(f"RUNS · {len(runs)}", "PanelKicker")
        self.runs_host.addWidget(self._runs_kicker)
        if not runs:
            empty = QLabel("No runs yet. Use “+ Add run” to log a team, its damage and the DPS it works out to.")
            empty.setStyleSheet("color: rgba(255,255,255,0.55);")
            self.runs_host.addWidget(empty)
        record = self.store.character(self.char_id)
        # each mode's highest-DPS run is marked automatically and listed first (Spiral Abyss, then the
        # Stygian ones); the rest newest first
        self._best_ids = self._bests()
        order = list(self._best_ids.values())
        runs.sort(key=lambda r: order.index(r["id"]) if r["id"] in order else len(order))
        # narrow or not, worked out once here, so the rows aren't drawn wide and then again narrow
        kicker_room = visible_room(self._runs_kicker, ROW_FULL_WIDTH)
        dense = kicker_room < ROW_FULL_WIDTH
        for run in runs:
            if not run["team"]:  # DPS logged before the character log existed: no team saved
                run["team"] = [_member(self.info, record)]
            best = run["id"] in order
            item = RunItem(self.store, self.index, run, best=best, expanded=run["id"] in keep_open, dense=dense)
            item.saved.connect(self._run_saved)
            item.delete_requested.connect(self._delete_run)
            item.toggled.connect(self._run_toggled)
            self.runs_host.addWidget(item)
        self._update_focus()

    def _bests(self):
        """{mode: id of its highest-DPS run} for the modes that have runs."""
        bests = {key: self.store.best_run_id(self.char_id, key) for key, _, _ in MODES}
        return {key: run_id for key, run_id in bests.items() if run_id}

    def _items(self):
        return [self.runs_host.itemAt(i).widget() for i in range(self.runs_host.count())
                if isinstance(self.runs_host.itemAt(i).widget(), RunItem)]

    def _run_toggled(self, item):
        if item.expanded:  # one run open at a time
            if self.new_editor is not None:
                self._close_new_run()
            for other in self._items():
                if other is not item:
                    other.set_expanded(False)
        self._update_focus()

    def _update_focus(self):
        """The page stays as it is (banner, every run); a run that's open, or the new one, is scrolled
        into view whole, so it can be filled in without scrolling."""
        target = self.new_section if self.new_editor is not None else next((i for i in self._items() if i.expanded), None)
        if target is not None:
            QTimer.singleShot(0, lambda: self._show_whole(target))

    def _show_whole(self, widget):
        bar = self.scroll.verticalScrollBar()
        top = widget.mapTo(self.scroll.widget(), widget.rect().topLeft()).y()
        view = self.scroll.viewport().height()
        if widget.height() <= view:  # all of it on screen: as little movement as needed
            if top < bar.value():
                bar.setValue(top - 8)
            elif top + widget.height() > bar.value() + view:
                bar.setValue(top + widget.height() - view + 8)
        else:
            bar.setValue(top - 8)

    def _open_ids(self):
        return {
            self.runs_host.itemAt(i).widget().run_id
            for i in range(self.runs_host.count())
            if isinstance(self.runs_host.itemAt(i).widget(), RunItem) and self.runs_host.itemAt(i).widget().expanded
        }

    def _run_saved(self, run_id):
        if self._bests() != self._best_ids:  # a new highest: re-mark and re-order
            QTimer.singleShot(0, lambda: self._render_runs(self._open_ids()))
        self.changed.emit()

    def _delete_run(self, run_id):
        run = self.store.run(run_id)
        when = f" from {run['run_date']}" if run else ""
        if not confirm(self, "Delete run", f"Are you sure you want to delete this run{when}?", "Delete"):
            return
        self.store.delete_run(run_id)
        self._render_runs(self._open_ids())
        self.changed.emit()
