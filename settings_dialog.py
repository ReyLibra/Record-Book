"""Settings popup (from the gear at the bottom of the navigation panel): the look, the Traveler twin,
unreleased content, what the app opens on, and updating the game data."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QComboBox, QHBoxLayout, QLabel, QPushButton

import gamedata
import theme
from dialogs import Popup
from widgets import filter_button


def _section(text):
    label = QLabel(text)
    label.setObjectName("FieldLabel")
    return label


def _choice(options, current, on_pick):
    """A row of toggle buttons, one checked: options are (value, label, tooltip)."""
    row = QHBoxLayout()
    row.setSpacing(4)
    group = QButtonGroup(row)
    group.setExclusive(True)
    buttons = {}
    for value, label, tip in options:
        btn = filter_button(label, tooltip=tip)
        btn.setChecked(value == current)
        btn.setMinimumWidth(90)
        btn.clicked.connect(lambda _=False, v=value: on_pick(v))
        group.addButton(btn)
        buttons[value] = btn
        row.addWidget(btn)
    row.addStretch()
    row.buttons = buttons
    return row


class SettingsDialog(Popup):
    def __init__(self, window):
        super().__init__(window, "Settings", 480)
        self.window_ = window
        store = window.store
        self._look = (store.get_setting("appearance", "dark"), store.get_setting("theme", "default"))
        self._chosen = list(self._look)

        # ----- look -----
        self.body.addWidget(_section("APPEARANCE"))
        self.body.addLayout(_choice(
            [("dark", "Dark", "The dark look (default)"), ("light", "Light", "A soft light look, easy on the eyes")],
            self._chosen[0], lambda v: self._pick_look(0, v)))
        self.body.addWidget(_section("THEME"))
        self.theme_box = QComboBox()
        for key in theme.THEMES:
            self.theme_box.addItem(theme.THEME_NAMES[key], key)
        self.theme_box.setCurrentIndex(max(0, theme.THEMES.index(self._chosen[1]) if self._chosen[1] in theme.THEMES else 0))
        self.theme_box.setToolTip("Reskin the app in an element's colours")
        self.theme_box.currentIndexChanged.connect(lambda i: self._pick_look(1, theme.THEMES[i]))
        self.body.addWidget(self.theme_box)
        look_row = QHBoxLayout()
        self.look_note = QLabel("Record Book restarts to apply the new look.")
        self.look_note.setStyleSheet("color: rgba(255,255,255,0.55); font-size: 9pt;")
        look_row.addWidget(self.look_note, 1)
        self.apply_button = QPushButton("Apply && restart")
        self.apply_button.setObjectName("Primary")
        self.apply_button.setCursor(Qt.PointingHandCursor)
        self.apply_button.clicked.connect(self._apply_look)
        look_row.addWidget(self.apply_button)
        self.body.addLayout(look_row)
        self._sync_look()
        self.body.addSpacing(6)

        # ----- what shows up -----
        self.body.addWidget(_section("TRAVELER"))
        self.body.addLayout(_choice([(t, t, f"Show {t} as the Traveler") for t in gamedata.TWINS],
                                    window.traveler, window.set_traveler))
        self.body.addWidget(_section("UNRELEASED CONTENT"))
        self.body.addLayout(_choice(
            [(False, "Hide", "Hide unreleased characters and weapons"),
             (True, "Show", "Show unreleased characters and weapons (datamined; changes before release)")],
            window.show_unreleased, window.set_unreleased))
        self.body.addWidget(_section("ON LAUNCH"))
        self.body.addLayout(_choice(
            [(True, "Open a favourite", "Start on one of your favourite characters (★ on their log page), "
                                         "a random one if there are several"),
             (False, "Last visited", "Start on the character you last visited")],
            bool(store.get_setting("open_favourite", True)), lambda v: store.set_setting("open_favourite", v)))
        self.body.addSpacing(6)

        # ----- game data -----
        self.body.addWidget(_section("GAME DATA"))
        data_row = QHBoxLayout()
        self.update_button = QPushButton("Update data")
        self.update_button.setCursor(Qt.PointingHandCursor)
        self.update_button.setToolTip("Fetch the latest characters, weapons and artifacts")
        self.update_button.clicked.connect(window.update_data)
        data_row.addWidget(self.update_button)
        data_row.addStretch()
        self.body.addLayout(data_row)
        self._updating(getattr(window, "_updating", False))
        window.updating.connect(self._updating)

    def _updating(self, busy):
        self.update_button.setEnabled(not busy)
        self.update_button.setText("Updating…" if busy else "Update data")

    def _pick_look(self, i, value):
        self._chosen[i] = value
        self._sync_look()

    def _sync_look(self):
        changed = tuple(self._chosen) != self._look
        self.apply_button.setVisible(changed)
        self.look_note.setVisible(changed)

    def _apply_look(self):
        store = self.window_.store
        store.set_setting("appearance", self._chosen[0])
        store.set_setting("theme", self._chosen[1])
        self.accept()
        self.window_.restart()

    def done(self, result):
        try:
            self.window_.updating.disconnect(self._updating)
        except (RuntimeError, TypeError):
            pass
        super().done(result)
