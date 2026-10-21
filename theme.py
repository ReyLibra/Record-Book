"""Light / dark mode and the element colour themes.

The app's styles are written once, for the dark look with Prydwen's blue. Every stylesheet and coloured
label goes through css() here, which turns that palette into the chosen one:

- light mode: the greys turn into soft light ones (backgrounds) and dark grey (text), and bright colours
  get a little darker so they stay readable on the light background;
- an element theme: the blue accent becomes the element's colour, and the greys take a slight tint of it.

The look is set once at startup (configure(), before the pages are built); Settings restarts the app to
change it. Colours drawn in code go through qcolor() / color().
"""

import colorsys
import json
import re
import sqlite3
from functools import lru_cache

MODES = ("dark", "light")
THEMES = ["default", "PYRO", "HYDRO", "DENDRO", "ELECTRO", "ANEMO", "CRYO", "GEO"]
THEME_NAMES = {"default": "Default (blue)", "PYRO": "Pyro", "HYDRO": "Hydro", "DENDRO": "Dendro",
               "ELECTRO": "Electro", "ANEMO": "Anemo", "CRYO": "Cryo", "GEO": "Geo"}
ELEMENT_ACCENTS = {
    "PYRO": (239, 122, 53),
    "HYDRO": (76, 194, 241),
    "DENDRO": (165, 200, 59),
    "ELECTRO": (176, 143, 194),
    "ANEMO": (116, 194, 168),
    "CRYO": (159, 214, 227),
    "GEO": (250, 182, 50),
}
BLUE = (0, 158, 236)  # the accent the styles are written with
_BLUES = {BLUE, (26, 170, 240)}  # it and its hover shade
TINT = 0.16  # how much of the theme's hue the greys take

_state = {"mode": "dark", "theme": "default"}
_accent = BLUE
_on_accent = (255, 255, 255)

_COLOR = re.compile(r"#[0-9a-fA-F]{6}\b|rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*(?:,\s*[\d.]+\s*)?\)")


def configure(mode="dark", theme="default"):
    global _accent, _on_accent
    _state["mode"] = mode if mode in MODES else "dark"
    _state["theme"] = theme if theme in THEMES else "default"
    base = ELEMENT_ACCENTS.get(_state["theme"], BLUE)
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in base))
    if _state["mode"] == "light" and l > 0.5:
        l = 0.42  # a deeper accent on the light background
    _accent = tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, l, s))
    # text on accent-coloured buttons: white, or dark on a pale accent
    _on_accent = (21, 23, 28) if _luminance(_accent) > 0.55 else (255, 255, 255)
    css.cache_clear()


def load(db_path):
    """Read the saved look from the database (before any Qt module is imported)."""
    mode, theme = "dark", "default"
    try:
        conn = sqlite3.connect(db_path)
        for key, value in conn.execute("SELECT key, value FROM settings WHERE key IN ('appearance', 'theme')"):
            if key == "appearance":
                mode = json.loads(value)
            else:
                theme = json.loads(value)
        conn.close()
    except (sqlite3.Error, ValueError):
        pass  # first launch, or no settings yet
    configure(mode, theme)


def mode():
    return _state["mode"]


def theme():
    return _state["theme"]


def is_default():
    return _state["mode"] == "dark" and _state["theme"] == "default"


def _luminance(rgb):
    return 0.299 * rgb[0] / 255 + 0.587 * rgb[1] / 255 + 0.114 * rgb[2] / 255


def _transform(r, g, b):
    if (r, g, b) in _BLUES:
        return _accent
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    light = _state["mode"] == "light"
    neutral = s < 0.22 or l < 0.06 or l > 0.94
    if neutral:
        if _state["theme"] != "default" and 0.04 < l < 0.9:
            h = colorsys.rgb_to_hls(*(c / 255 for c in _accent))[0]
            s = TINT if not light else TINT + 0.08
        if light:
            l = 0.97 - 0.78 * l  # dark backgrounds -> soft light ones; white text -> dark grey
    elif light and l > 0.55:
        l = 0.38 + (l - 0.55) * 0.4  # bright colours, a little deeper for the light background
    return tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, l, s))


def _format(match, rgb):
    text = match.group(0)
    if text.startswith("#"):
        return "#%02x%02x%02x" % rgb
    numbers = re.findall(r"[\d.]+", text)
    if text.startswith("rgba"):
        return f"rgba({rgb[0]},{rgb[1]},{rgb[2]},{numbers[3]})"
    return f"rgb({rgb[0]}, {rgb[1]}, {rgb[2]})"


def _parse(text):
    if text.startswith("#"):
        return int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16)
    return tuple(int(float(n)) for n in re.findall(r"[\d.]+", text)[:3])


def _recolor(text):
    return _COLOR.sub(lambda m: _format(m, _transform(*_parse(m.group(0)))), text)


_BLOCK = re.compile(r"\{[^{}]*\}")
_ON_BLUE = re.compile(r"background(?:-color)?\s*:\s*(?:#009eec|#1aaaf0)\b", re.I)
_WHITE_TEXT = re.compile(r"(?<![-\w])color\s*:\s*#ffffff", re.I)


@lru_cache(maxsize=8192)
def css(text):
    """A stylesheet, or rich text with inline colours, in the current look."""
    if is_default() or not text or ("#" not in text and "rgb" not in text):
        return text
    on_accent = "#%02x%02x%02x" % _on_accent

    def block(m):
        part = m.group(0)
        if _ON_BLUE.search(part):  # text on an accent-coloured button stays readable on it
            part = _WHITE_TEXT.sub("color: @@ON_ACCENT@@", part)
        return part

    text = _BLOCK.sub(block, text)
    return _recolor(text).replace("@@ON_ACCENT@@", on_accent)


def color(hex_text):
    """One '#rrggbb' colour in the current look."""
    return css(hex_text)


def qcolor(r, g, b, a=255):
    from PySide6.QtGui import QColor

    if is_default():
        return QColor(r, g, b, a)
    return QColor(*_transform(r, g, b), a)


def accent_hex():
    return "#%02x%02x%02x" % _accent


# ---------- applying it everywhere ----------
def install(app):
    """Route the app's styles and coloured labels through css() (nothing to do for the default look)."""
    if is_default():
        return
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QLabel, QTextEdit, QWidget

    set_style = QWidget.setStyleSheet
    set_text = QLabel.setText
    set_html = QTextEdit.setHtml
    QWidget.setStyleSheet = lambda self, text: set_style(self, css(text))

    def label_text(self, text):
        themed = css(text) if isinstance(text, str) else text
        set_text(self, themed)
        self.setProperty("_themed", themed)

    QLabel.setText = label_text
    QTextEdit.setHtml = lambda self, text: set_html(self, css(text))

    class _Labels(QObject):
        """Labels given their text when created (not through setText) are recoloured when first shown."""

        def eventFilter(self, obj, event):
            if event.type() == QEvent.Type.Polish and isinstance(obj, QLabel):
                text = obj.text()
                if text and obj.property("_themed") != text and ("#" in text or "rgb" in text):
                    label_text(obj, text)
            return False

    app._theme_labels = _Labels(app)
    app.installEventFilter(app._theme_labels)
