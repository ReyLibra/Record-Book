"""Shared widgets, icons and the dark theme for Record Book."""

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QObject,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QListWidget,
    QWidget,
)

import gamedata


class SmoothScroller(QObject):
    """App-wide smooth scrolling: mouse-wheel steps on any scrollable area glide to their target
    instead of jumping. Install once with app.installEventFilter(SmoothScroller(app)).

    When an area is already at its end, the wheel event is left alone so it scrolls the area
    around it, as normal.
    """

    DURATION_MS = 260
    STEP_PX = 120  # per wheel notch

    def __init__(self, parent=None):
        super().__init__(parent)
        self._animations = {}  # scrollbar -> (animation, target)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show and isinstance(obj, QAbstractScrollArea):
            self._reserve_scrollbar(obj)
            return False
        if event.type() != QEvent.Type.Wheel or event.modifiers() & Qt.ControlModifier:
            return False
        from PySide6.QtWidgets import QAbstractSpinBox, QComboBox

        value_box = isinstance(obj, QAbstractSpinBox) or (isinstance(obj, QComboBox) and not obj.view().isVisible())
        if value_box:
            # the wheel over a dropdown or number box scrolls the page instead of changing its value
            area = obj.parent()
            while area is not None and not isinstance(area, QAbstractScrollArea):
                area = area.parent()
            if area is not None:
                self._scroll(area, event)
            return True
        area = obj.parent() if obj.parent() is not None else None
        if not isinstance(area, QAbstractScrollArea) or area.viewport() is not obj:
            return False
        return self._scroll(area, event)

    @staticmethod
    def _reserve_scrollbar(area):
        """Keep the vertical scrollbar's room permanently, so content never re-flows (and pages
        never jump) when the bar appears or disappears. When there's nothing to scroll the bar is
        disabled, which the stylesheet draws as an empty gutter. Popups (dropdown lists) are left alone."""
        if area.window().windowType() == Qt.Popup or area.verticalScrollBarPolicy() != Qt.ScrollBarAsNeeded:
            return
        area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        bar = area.verticalScrollBar()

        def idle(minimum, maximum):
            value = "true" if maximum <= minimum else "false"
            if bar.property("idle") != value:
                bar.setProperty("idle", value)
                bar.style().unpolish(bar)
                bar.style().polish(bar)

        bar.rangeChanged.connect(idle)
        idle(bar.minimum(), bar.maximum())

    def _scroll(self, area, event):
        delta = event.angleDelta()
        vertical = abs(delta.y()) >= abs(delta.x())
        bar = area.verticalScrollBar() if vertical else area.horizontalScrollBar()
        steps = (delta.y() if vertical else delta.x()) / 120
        if not steps or bar.maximum() <= bar.minimum():
            return False
        if isinstance(area, QAbstractItemView):  # pixel scrolling, or each notch jumps a whole row
            if vertical:
                area.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
            else:
                area.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        running = self._animations.get(bar)
        start_target = running[1] if running and running[0].state() == QAbstractAnimation.Running else bar.value()
        target = max(bar.minimum(), min(bar.maximum(), round(start_target - steps * self.STEP_PX)))
        if target == bar.value() and not running:
            return False  # already at the end: let the outer area scroll instead
        if running:
            anim = running[0]
        else:
            anim = QPropertyAnimation(bar, b"value", self)
            bar.destroyed.connect(lambda *_: self._animations.pop(bar, None))
        anim.stop()
        anim.setDuration(self.DURATION_MS)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setStartValue(bar.value())
        anim.setEndValue(target)
        anim.start()
        self._animations[bar] = (anim, target)
        return True


def clear_layout(layout):
    """Remove and delete every widget in a layout (recursing into nested layouts).

    Any tooltip is hidden first: Qt's tooltip keeps a plain pointer to the widget it belongs to, so
    deleting that widget while its tooltip is up can crash the app later.
    """
    from PySide6.QtWidgets import QToolTip

    QToolTip.hideText()
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


def glossary_tooltips(widget):
    """Show a term's explanation while hovering a glossary link ('term:...') in a QLabel or
    QTextBrowser; clicking the link shows it too."""
    from PySide6.QtGui import QCursor
    from PySide6.QtWidgets import QToolTip

    def hovered(href):
        text = gamedata.glossary_html(href.toString() if hasattr(href, "toString") else href)
        if text:
            QToolTip.showText(QCursor.pos(), text, widget)
        else:
            QToolTip.hideText()

    if isinstance(widget, QLabel):
        widget.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        widget.setOpenExternalLinks(False)
        widget.linkHovered.connect(hovered)
        widget.linkActivated.connect(hovered)
    else:  # QTextBrowser
        widget.highlighted.connect(hovered)
        widget.anchorClicked.connect(hovered)
        widget.setOpenLinks(False)
    return widget


class EvenGrid(QListWidget):
    """Icon grid that stretches its cells so the columns fill the full width
    instead of leaving a gap on the right."""

    def __init__(self, cell):
        super().__init__()
        self._cell = cell
        self.setGridSize(cell)

    def resizeEvent(self, event):
        # Always leave room for the scrollbar: if the cell width depended on whether it's showing,
        # a list that only just overflows would flip between the two layouts forever (jitter).
        bar = self.verticalScrollBar()
        extent = self.style().pixelMetric(self.style().PixelMetric.PM_ScrollBarExtent)
        width = self.viewport().width() + (bar.width() if bar.isVisible() else 0) - extent - 1
        columns = max(1, width // self._cell.width())
        size = QSize(max(self._cell.width(), width // columns), self._cell.height())
        if size != self.gridSize():
            self.setGridSize(size)
        super().resizeEvent(event)

# Prydwen's site palette (prydwen.gg): charcoal page, darker sidebar/top bar, square corners and
# their brand blue for active items and primary buttons.
ACCENT = "#009eec"
PAGE_BG = "#23242a"
BAR_BG = "#1c1d21"  # sidebar, top bar, footer
BAR_BORDER = "#33343a"
PANEL_BG = "#1c1d22"  # boxes on the page
PANEL_BORDER = "#373a43"
BUTTON_BG = "#2c2d33"
MUTED = "rgba(255,255,255,0.55)"

# Prydwen's card backgrounds: top color -> bottom color (reached at 53% of the height)
RARITY_COLORS = {
    5: ("#885550", "#c9a36a"),
    4: ("#343659", "#8a5fcc"),
    3: ("#2f3f5a", "#4f86b8"),
    2: ("#2f4a40", "#4d8a6c"),
    1: ("#3c3f47", "#6b707a"),
}

STYLESHEET = f"""
QWidget {{ background: transparent; color: #ffffff; font-family: 'Segoe UI'; font-size: 10pt; }}
QMainWindow, #Root {{ background: {PAGE_BG}; }}
#NavPanel {{ background: {BAR_BG}; border-right: 1px solid {BAR_BORDER}; }}
#NavPanel QPushButton {{ background: transparent; border: none; border-radius: 0; padding: 10px 14px; text-align: left;
                         font-size: 11.5pt; color: rgba(255,255,255,0.75); }}
#NavPanel QPushButton:hover {{ color: #ffffff; background: rgba(255,255,255,0.03); }}
#NavPanel QPushButton:checked {{ color: {ACCENT}; font-weight: 600; }}
#NavSection {{ color: {MUTED}; font-size: 8.5pt; letter-spacing: 0.5px; padding: 14px 14px 4px 14px; }}
#Header {{ background: {BAR_BG}; border-bottom: 1px solid {BAR_BORDER}; }}
#Title {{ font-size: 19pt; font-weight: 800; color: #ffffff; }}
#NavToggle {{ border: none; font-size: 15pt; padding: 2px 8px; border-radius: 0; }}
#NavToggle:hover {{ background: rgba(255,255,255,0.06); }}
#Chip {{ background: {BUTTON_BG}; border: 1px solid {BAR_BORDER}; border-radius: 3px; }}
#Chip:hover {{ border-color: {ACCENT}; }}
#Chip[pinned="true"] {{ background: rgba(0,158,236,0.14); border-color: rgba(0,158,236,0.6); }}
#ChipPin {{ border: none; padding: 0 4px; font-size: 9pt; background: transparent; }}
#HeaderHint {{ color: {MUTED}; font-size: 9pt; }}
#Footer {{ background: {BAR_BG}; border-top: 1px solid {BAR_BORDER}; color: {MUTED}; font-size: 9pt; }}
#Footer QLabel {{ color: {MUTED}; font-size: 9pt; }}
#Card {{ background: rgba(28,29,34,0.92); border: 1px solid {PANEL_BORDER}; border-radius: 0; }}
#CharName {{ font-size: 22pt; font-weight: 700; color: #ffffff; }}
#CharTitle {{ color: #e5e7ec; font-size: 10.5pt; }}
#FieldLabel {{ color: #8c909b; font-size: 8pt; font-weight: 900; }}
#Dps {{ background: transparent; font-size: 20pt; font-weight: 700; color: {ACCENT}; border: none; text-align: left; padding: 0; }}
#Dps:disabled {{ color: #6f7685; }}
#Dps[empty="true"] {{ font-size: 12pt; font-weight: 600; color: {MUTED}; }}
#Selector {{ background: rgba(28,29,34,0.92); border: 1px solid {PANEL_BORDER}; border-radius: 0; }}
#SectionHeader {{ border: none; border-bottom: 2px solid {ACCENT}; padding-bottom: 6px; }}
#SectionHeaderTitle {{ font-size: 15pt; font-weight: 700; color: #ffffff; }}
#SectionHeaderNote {{ color: {MUTED}; font-size: 9.5pt; font-weight: 500; }}
#StatTile {{ background: rgba(12,13,16,0.52); border: 1px solid {PANEL_BORDER}; border-radius: 0; }}
#InsetTile {{ background: rgba(14,15,18,0.62); border: 1px solid rgba(255,255,255,0.11); border-radius: 0; }}
#StatNumber {{ font-size: 14pt; font-weight: 700; color: #ffffff; }}
#LevelBadge {{ background: rgba(12,13,16,0.6); border: 1px solid rgba(0,158,236,0.5); border-radius: 0; padding: 4px 10px;
               font-weight: 800; font-size: 8.5pt; color: #ffffff; }}
#FilterBtn {{ background: {BUTTON_BG}; border: 1px solid {BAR_BORDER}; border-radius: 3px; padding: 3px 8px;
              font-size: 9pt; font-weight: 600; color: rgba(255,255,255,0.9); }}
#FilterBtn:hover {{ border-color: {ACCENT}; }}
#FilterBtn:checked {{ border-color: {ACCENT}; background: {ACCENT}; color: #ffffff; }}
#ElementBtn {{ border: 1px solid {BAR_BORDER}; border-radius: 3px; padding: 4px; background: {BUTTON_BG}; }}
#ElementBtn:hover {{ border-color: {ACCENT}; }}
#CharRow {{ border-radius: 0; }}
#CharRow:hover, #CharRow[selected="true"] {{ background: rgba(0,158,236,0.15); }}
#AddRow {{ border: 1px dashed #4a4d57; border-radius: 0; color: {ACCENT}; }}
#AddRow:hover {{ background: rgba(0,158,236,0.12); }}
QPushButton {{ background: {BUTTON_BG}; border: 1px solid {BAR_BORDER}; border-radius: 3px; padding: 7px 14px;
               color: rgba(255,255,255,0.9); font-weight: 600; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: #ffffff; }}
QPushButton:disabled {{ color: #5d6370; background: #25262b; border-color: #2c2d33; }}
QPushButton#Primary {{ background: {ACCENT}; border-color: {ACCENT}; color: #ffffff; }}
QPushButton#Primary:hover {{ background: #1aaaf0; }}
QPushButton#Primary:disabled {{ background: #25262b; border-color: #2c2d33; color: #5d6370; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QPlainTextEdit, QTextBrowser, QListWidget, QTableWidget {{
    background: rgba(0,0,0,0.28); border: 1px solid {BAR_BORDER}; border-radius: 4px; padding: 6px 10px;
    selection-background-color: rgba(0,158,236,0.45);
}}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
QComboBox {{ background: {BUTTON_BG}; }}
QComboBox:disabled {{ background: #25262b; color: rgba(255,255,255,0.8); border-color: {BAR_BORDER}; }}
/* talent levels: just the number until hovered (blue), a 1-15 list when clicked */
QComboBox#TalentBox {{ background: transparent; border: 1px solid transparent; border-radius: 3px; padding: 2px 8px;
                       font-size: 13pt; font-weight: 700; color: #ffffff; }}
QComboBox#TalentBox:hover {{ background: rgba(0,158,236,0.18); border-color: {ACCENT}; }}
QComboBox#TalentBox:on {{ background: rgba(0,158,236,0.25); border-color: {ACCENT}; }}
QComboBox#TalentBox:disabled {{ background: transparent; border-color: transparent; color: #ffffff; }}
QComboBox#TalentBox::drop-down {{ width: 0; border: none; }}
QComboBox#TalentBox::down-arrow {{ image: none; width: 0; }}
QComboBox QAbstractItemView {{ background: {PANEL_BG}; border: 1px solid {PANEL_BORDER}; selection-background-color: rgba(0,158,236,0.35); }}
QListWidget {{ outline: 0; }}
QListWidget::item {{ border: 1px solid transparent; border-radius: 0; padding: 4px; }}
QListWidget::item:hover {{ background: rgba(255,255,255,0.05); }}
QListWidget::item:selected {{ background: rgba(0,158,236,0.2); border: 1px solid {ACCENT}; color: #ffffff; }}
QHeaderView::section {{ background: {BUTTON_BG}; border: none; padding: 4px; }}
QDialog {{ background: {PAGE_BG}; }}
/* popups: no window frame, a black see-through box over the dimmed app */
QDialog#Popup {{ background: transparent; }}
#PopupPanel {{ background: rgba(8,8,10,0.86); border: 1px solid {BAR_BORDER}; }}
#PopupPanel QListWidget {{ background: rgba(0,0,0,0.35); border: 1px solid {BAR_BORDER}; }}
#PopupTitle {{ font-size: 13pt; font-weight: 700; color: #ffffff; }}
QPushButton#PopupClose {{ background: transparent; border: none; padding: 2px 6px; color: rgba(255,255,255,0.6);
                          font-size: 12pt; }}
QPushButton#PopupClose:hover {{ color: #ffffff; }}
QToolTip {{ background: {PANEL_BG}; color: #e5e7ec; border: 1px solid {PANEL_BORDER}; padding: 6px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: #3a3d46; border-radius: 0; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #4a4d57; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:vertical:disabled, QScrollBar:vertical[idle="true"] {{ background: transparent; }}
QScrollBar::handle:vertical:disabled, QScrollBar[idle="true"]::handle:vertical {{ background: transparent; }}
QSlider::groove:horizontal {{ height: 4px; background: #3a3d46; border: none; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; }}
QSlider::handle:horizontal {{ background: {ACCENT}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
"""


def section_header(title, note=""):
    """Prydwen's page section heading: a small blue square, bold uppercase title, a muted note on the
    right and a blue underline. Returns (widget, note_label) so the note can be updated."""
    box = QWidget()
    box.setObjectName("SectionHeader")
    box.setAttribute(Qt.WA_StyledBackground, True)
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 6)
    row.setSpacing(10)
    mark = QLabel()
    mark.setFixedSize(13, 13)
    mark.setStyleSheet(f"background: {ACCENT};")
    row.addWidget(mark, 0, Qt.AlignVCenter)
    label = QLabel(title.upper())
    label.setObjectName("SectionHeaderTitle")
    row.addWidget(label)
    row.addStretch()
    note_label = QLabel(note)
    note_label.setObjectName("SectionHeaderNote")
    row.addWidget(note_label, 0, Qt.AlignVCenter)
    return box, note_label


def filter_button(text="", icon_url=None, tooltip="", size=36):
    """Prydwen's square filter button (solid blue when active)."""
    from PySide6.QtWidgets import QToolButton

    btn = QToolButton()
    btn.setObjectName("FilterBtn")
    btn.setCheckable(True)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setToolTip(tooltip)
    if icon_url:
        btn.setFixedSize(size, size)
        btn.setIconSize(QSize(size - 12, size - 12))
        gamedata.load_pixmap(icon_url, lambda pm: pm and btn.setIcon(QIcon(pm)))
    else:
        btn.setText(text)
        btn.setFixedHeight(size)
        btn.setMinimumWidth(size + 8)
    return btn


class FilterGroup(QWidget):
    """A row of filter buttons where at most one is active. Clicking the active one clears it.

    options: [(value, text, icon_url, tooltip)]. `value` is None when nothing is chosen.
    """

    changed = Signal(object)

    def __init__(self, options, size=36, parent=None):
        super().__init__(parent)
        self.value = None
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.buttons = {}
        for value, text, icon_url, tooltip in options:
            btn = filter_button(text, icon_url, tooltip, size)
            btn.clicked.connect(lambda _=False, v=value: self._clicked(v))
            self.buttons[value] = btn
            row.addWidget(btn)

    def _clicked(self, value):
        self.set_value(None if value == self.value else value)
        self.changed.emit(self.value)

    def set_value(self, value):
        self.value = value
        for v, btn in self.buttons.items():
            btn.setChecked(v == value)


def rarity_gradient(rect, rarity, fallback=("#2c2d33", "#3a3d46")):
    top, bottom = RARITY_COLORS.get(rarity, fallback)
    grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    grad.setColorAt(0, QColor(top))
    grad.setColorAt(0.53, QColor(bottom))
    grad.setColorAt(1, QColor(bottom))
    return grad


def shape_icon(shape, color="#e8e6e3", size=48):
    """Nav icons drawn in code: house, circle, square, triangle, book."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), size * 0.08)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    m = size * 0.18
    s = size - 2 * m
    if shape == "house":
        path = QPainterPath()
        path.moveTo(m, m + s * 0.45)
        path.lineTo(size / 2, m)
        path.lineTo(size - m, m + s * 0.45)
        path.moveTo(m + s * 0.15, m + s * 0.35)
        path.lineTo(m + s * 0.15, size - m)
        path.lineTo(size - m - s * 0.15, size - m)
        path.lineTo(size - m - s * 0.15, m + s * 0.35)
        path.addRect(QRectF(size / 2 - s * 0.12, size - m - s * 0.35, s * 0.24, s * 0.35))
        p.drawPath(path)
    elif shape == "circle":
        p.drawEllipse(QRectF(m, m, s, s))
    elif shape == "square":
        p.drawRoundedRect(QRectF(m, m, s, s), 3, 3)
    elif shape == "triangle":
        p.drawPolygon(QPolygonF([QPointF(size / 2, m), QPointF(size - m, size - m), QPointF(m, size - m)]))
    elif shape == "grid":
        cell = s * 0.42
        for gx in (m, size - m - cell):
            for gy in (m, size - m - cell):
                p.drawRoundedRect(QRectF(gx, gy, cell, cell), 2, 2)
    elif shape == "pin":  # push-pin: round head, short collar, needle
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(size * 0.3, size * 0.08, size * 0.4, size * 0.34))
        p.drawRect(QRectF(size * 0.2, size * 0.42, size * 0.6, size * 0.1))
        p.drawLine(QPointF(size / 2, size * 0.52), QPointF(size / 2, size * 0.94))
    elif shape == "refresh":  # circular arrow
        p.drawArc(QRectF(m, m, s, s), 60 * 16, 290 * 16)
        tip = QPointF(m + s * 0.75, m + s * 0.067)
        p.drawLine(tip, QPointF(tip.x() - s * 0.32, tip.y() + s * 0.02))
        p.drawLine(tip, QPointF(tip.x() - s * 0.02, tip.y() + s * 0.32))
    elif shape == "book":
        p.setBrush(QColor(color))
        p.drawRoundedRect(QRectF(m, m, s, s), 4, 4)
        p.setPen(QPen(QColor("#15171c"), size * 0.06))
        p.drawLine(QPointF(m + s * 0.25, m), QPointF(m + s * 0.25, size - m))
    p.end()
    return QIcon(pm)


class ImageTile(QWidget):
    """Square picture with a rarity background and a badge in the bottom-right corner.

    With two images it shows them split diagonally, the second over the first.
    With no image it shows a "+" placeholder (or nothing if show_plus is False).
    """

    clicked = Signal()

    def __init__(self, size=96, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self._pixmaps = []
        self._badge = ""
        self._rarity = 0
        self.show_plus = True
        self._urls = []

    def set_content(self, urls, rarity=0, badge=""):
        self._urls = list(urls)
        self._rarity = rarity
        self._badge = badge
        self._pixmaps = [None] * len(self._urls)
        for i, url in enumerate(self._urls):
            gamedata.load_pixmap(url, lambda pm, i=i, url=url: self._loaded(i, url, pm))
        self.update()

    def clear(self):
        self.set_content([], 0, "")

    def _loaded(self, i, url, pm):
        if i < len(self._urls) and self._urls[i] == url:
            self._pixmaps[i] = pm
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        clip = QPainterPath()
        clip.addRect(rect)
        p.setClipPath(clip)

        if self._urls:
            p.fillRect(rect, rarity_gradient(rect, self._rarity))
            for i, pm in enumerate(self._pixmaps):
                if pm is None:
                    continue
                if i == 1:  # second artifact set: lower-right triangle on top of the first
                    tri = QPainterPath()
                    tri.addPolygon(QPolygonF([rect.topRight(), rect.bottomRight(), rect.bottomLeft()]))
                    p.setClipPath(tri.intersected(clip))
                    p.fillRect(rect, QColor(0, 0, 0, 60))
                scaled = pm.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                p.drawPixmap(
                    int(rect.center().x() - scaled.width() / 2), int(rect.center().y() - scaled.height() / 2), scaled
                )
            if len(self._pixmaps) == 2:
                p.setClipPath(clip)
                p.setPen(QPen(QColor(255, 255, 255, 150), 1.5))
                p.drawLine(rect.topRight(), rect.bottomLeft())
        else:
            p.fillRect(rect, QColor(0, 0, 0, 70))
            if self.show_plus:
                p.setPen(QPen(QColor(ACCENT), 1.5, Qt.DashLine))
                p.drawRect(rect.adjusted(2, 2, -2, -2))
                p.setPen(QColor(ACCENT))
                f = QFont("Segoe UI", int(self.height() / 4))
                p.setFont(f)
                p.drawText(rect, Qt.AlignCenter, "+")

        p.setClipping(False)
        p.setPen(QPen(QColor(PANEL_BORDER), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(rect)
        if self._badge:
            f = QFont("Segoe UI", 9, QFont.Bold)
            p.setFont(f)
            w = p.fontMetrics().horizontalAdvance(self._badge) + 10
            badge = QRectF(rect.right() - w - 3, rect.bottom() - 20, w, 17)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(10, 11, 14, 184))
            p.drawRect(badge)
            p.setPen(QColor("#ffffff"))
            p.drawText(badge, Qt.AlignCenter, self._badge)
        p.end()


class ColumnGrid(QWidget):
    """Lays its widgets out in two columns when there's room, otherwise one, so it never forces
    a horizontal scrollbar. Widgets in the same row share its height.
    """

    def __init__(self, items, spacing=14, min_column_width=0, parent=None):
        super().__init__(parent)
        self.items = list(items)
        self.min_column_width = min_column_width
        self.columns = 0
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(spacing)
        # Our own minimumSizeHint decides how narrow we may get, not the grid's 2-column minimum.
        self.grid.setSizeConstraint(QLayout.SetNoConstraint)
        self._arrange(2)

    def _column_min(self):
        return max([self.min_column_width] + [w.minimumSizeHint().width() for w in self.items])

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        return QSize(self._column_min(), hint.height())

    def _columns_for(self, width):
        return 2 if width >= 2 * self._column_min() + self.grid.spacing() else 1

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange(self._columns_for(event.size().width()))

    def _arrange(self, columns):
        if columns == self.columns:
            return
        self.columns = columns
        for w in self.items:
            self.grid.removeWidget(w)
        for c in range(2):
            self.grid.setColumnStretch(c, 1 if c < columns else 0)
        for n, w in enumerate(self.items):
            self.grid.addWidget(w, n // columns, n % columns)
        self.updateGeometry()


class RemoteIcon(QLabel):
    """A QLabel that shows an image from a URL, scaled to a fixed size."""

    def __init__(self, size=32, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._url = None

    def set_url(self, url):
        self._url = url
        self.clear()
        if url:
            gamedata.load_pixmap(url, lambda pm, url=url: self._loaded(url, pm))

    def _loaded(self, url, pm):
        if url == self._url and pm is not None:
            self.setPixmap(pm.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))


def card_pixmap(portrait, element_pm, rarity, size=96, logged=False, border=None):
    """A character card: rarity background, portrait, element symbol top-left, ✔ if logged,
    and an optional coloured border (used for the selected character).

    Drawn at 2x so it stays crisp on high-DPI screens.
    """
    scale = 2
    full = size * scale
    pm = QPixmap(full, full)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    rect = QRectF(0, 0, full, full)
    p.fillRect(rect, rarity_gradient(rect, rarity))
    if portrait is not None:
        p.drawPixmap(rect.toRect(), portrait.scaled(full, full, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    if element_pm is not None:  # Prydwen: element icon in a small dark square, top-left
        d = full * 0.26
        badge = QRectF(0, 0, d, d)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(10, 11, 14, 184))
        p.drawRect(badge)
        p.drawPixmap(badge.adjusted(3 * scale, 3 * scale, -3 * scale, -3 * scale).toRect(),
                     element_pm.scaled(int(d), int(d), Qt.KeepAspectRatio, Qt.SmoothTransformation))
    if logged:
        d = full * 0.24
        badge = QRectF(full - d, full - d, d, d)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ACCENT))
        p.drawRect(badge)
        p.setPen(QPen(QColor("#ffffff"), 2.5 * scale))
        p.drawLine(QPointF(badge.left() + d * 0.27, badge.top() + d * 0.52), QPointF(badge.left() + d * 0.44, badge.top() + d * 0.7))
        p.drawLine(QPointF(badge.left() + d * 0.44, badge.top() + d * 0.7), QPointF(badge.left() + d * 0.75, badge.top() + d * 0.32))
    width = 3.5 * scale if border else 1 * scale
    p.setPen(QPen(QColor(border or "#333741"), width))
    p.setBrush(Qt.NoBrush)
    inset = width / 2
    p.drawRect(rect.adjusted(inset, inset, -inset, -inset))
    p.end()
    return pm


def tint(pixmap, color):
    """Recolor a white-ish icon (element symbols are white) to a color."""
    out = QPixmap(pixmap.size())
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.drawPixmap(0, 0, pixmap)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(out.rect(), QColor(color))
    p.end()
    return out


ICON_SIZE = QSize(22, 22)
