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
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QListWidget,
    QToolButton,
    QWidget,
)

import gamedata
import theme


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
        if area.property("paged"):  # scrolls a page at a time itself (Home)
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
        active = bool(running) and running[0].state() == QAbstractAnimation.Running
        start_target = running[1] if active else bar.value()
        target = max(bar.minimum(), min(bar.maximum(), round(start_target - steps * self.STEP_PX)))
        if abs(target - bar.value()) <= 1 and not active:
            return False  # already at the end: let the outer area scroll instead (a finished glide doesn't count)
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


class SelectableText(QObject):
    """App-wide: any label with text can be highlighted and copied (links keep working). Labels that are
    clicked themselves (rows, chips, tiles) are left alone, so clicking them still works.
    Install once with app.installEventFilter(SelectableText(app))."""

    def eventFilter(self, obj, event):
        # (also on Show: many labels get their text after they're made)
        if event.type() in (QEvent.Type.Polish, QEvent.Type.Show) and isinstance(obj, QLabel) and obj.text():
            from PySide6.QtWidgets import QAbstractButton

            if (obj.testAttribute(Qt.WA_TransparentForMouseEvents)
                    or "mousePressEvent" in vars(obj)  # given its own click (Home's showcase name)
                    or type(obj).mousePressEvent is not QLabel.mousePressEvent
                    or obj.window().windowType() == Qt.ToolTip
                    or isinstance(obj.parent(), QAbstractButton)
                    or _in_clickable(obj)):
                return False
            flags = obj.textInteractionFlags()
            if not flags & Qt.TextSelectableByMouse:
                obj.setTextInteractionFlags(flags | Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        return False


def _in_clickable(widget):
    """Whether a widget sits in one of Record Book's own clickable rows or cards (a class of ours that
    handles the mouse itself): selectable text there would take the click."""
    parent = widget.parentWidget()
    while parent is not None:
        for cls in type(parent).__mro__:
            if cls.__module__.startswith("PySide6"):
                break
            if "mousePressEvent" in vars(cls) or "mouseReleaseEvent" in vars(cls):
                return True
        parent = parent.parentWidget()
    return False


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
#ElementBoard {{ border: 1px solid {PANEL_BORDER}; border-radius: 0;
                 background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(28,29,34,0.72), stop:1 rgba(20,21,25,0.96)); }}
#ElementColumn {{ background: transparent; border: none; }}
#ElementColumn[alt="true"] {{ background: rgba(255,255,255,0.035); }}
#ColumnName {{ font-size: 10pt; font-weight: 800; }}
#RowName {{ font-size: 9.5pt; color: #ffffff; }}
#RowDps {{ font-size: 8pt; font-weight: 600; color: rgba(255,255,255,0.55); }}
#GearIcon {{ background: rgba(12,13,16,0.6); border: 1px solid {PANEL_BORDER}; color: {MUTED}; font-size: 8pt; }}
#ElementColumn QScrollArea, #ElementColumn QScrollArea > QWidget > QWidget {{ background: transparent; }}
#ElementColumn #AddRow {{ padding: 4px 6px; font-size: 9pt; }}
#ElementColumn #AddRow {{ background: transparent; border: none; }}
#LinkBtn {{ text-align: left; padding: 6px 12px; }}
#NavPanel QPushButton#NavLinks {{ color: {MUTED}; font-size: 8.5pt; padding: 8px 14px 4px 14px; letter-spacing: 0.5px; }}
#NavPanel QPushButton#NavLinks:hover {{ color: {ACCENT}; }}
#NavPanel QPushButton#NavLink {{ font-size: 9.5pt; padding: 6px 14px 6px 22px; color: rgba(255,255,255,0.7); }}
/* the loading screen */
#LoadingPanel {{ background: {BAR_BG}; border: 1px solid {PANEL_BORDER}; border-radius: 10px; }}
#LoadingTitle {{ font-size: 18pt; font-weight: 800; color: #ffffff; }}
#LoadingNote {{ color: {MUTED}; font-size: 9pt; }}
QProgressBar#LoadingBar {{ background: rgba(255,255,255,0.08); border: none; border-radius: 3px; }}
QProgressBar#LoadingBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
/* Home */
#HomePanel {{ background: rgba(28,29,34,0.92); border: 1px solid {PANEL_BORDER}; }}
#ShowKicker {{ font-size: 8pt; font-weight: 800; letter-spacing: 0.5px; background: transparent; }}
#ShowName {{ font-size: 28pt; font-weight: 800; color: #ffffff; background: transparent; }}
#ShowSub {{ font-size: 9pt; color: {MUTED}; background: transparent; }}
#ShowDps {{ font-size: 32pt; font-weight: 400; color: #ffffff; background: transparent; }}
#ShowDpsUnit {{ font-size: 10pt; font-weight: 700; color: {ACCENT}; background: transparent; padding-bottom: 8px; }}
QPushButton#ShowLink {{ background: transparent; border: none; color: {ACCENT}; font-weight: 700; font-size: 9pt; padding: 0; }}
QPushButton#ShowLink:hover {{ color: #ffffff; }}
#HomeCard {{ background: rgba(28,29,35,0.95); border: 1px solid #30323c; border-radius: 10px; }}
#HomeGlyph {{ color: {ACCENT}; font-size: 11pt; }}
#HomeTitle {{ font-size: 10.5pt; font-weight: 700; color: #ffffff; }}
#HomeSub {{ color: {MUTED}; font-size: 8.5pt; }}
#HomeNote {{ color: {MUTED}; font-size: 8pt; }}
QPushButton#HomeItem, QFrame#HomeItem {{ background: rgba(12,13,16,0.45); border: 1px solid #30323c; border-radius: 6px;
                                        text-align: left; padding: 0; }}
QPushButton#HomeItem:hover {{ border-color: {ACCENT}; background: rgba(0,158,236,0.08); }}
#HomeItemTitle {{ font-size: 9.5pt; font-weight: 700; color: #ffffff; }}
#HomeItemSub {{ font-size: 8pt; color: {MUTED}; }}
#RankCircle {{ background: rgba(0,158,236,0.18); color: {ACCENT}; border-radius: 11px; font-weight: 800; font-size: 8.5pt; }}
#Pill {{ border-radius: 4px; padding: 1px 7px; font-size: 7.5pt; font-weight: 700; }}
#Pill[kind="accent"] {{ background: rgba(0,158,236,0.16); color: #6cc6f5; }}
#Pill[kind="solid"] {{ background: {ACCENT}; color: #ffffff; padding: 2px 7px; }}
#Pill[kind="green"] {{ background: rgba(61,220,132,0.16); color: #3ddc84; }}
#Pill[kind="muted"] {{ background: rgba(255,255,255,0.07); color: rgba(255,255,255,0.78); }}
QPushButton#PillButton {{ background: rgba(0,158,236,0.16); color: #6cc6f5; border: none; border-radius: 4px; padding: 2px 8px;
                         font-size: 8pt; font-weight: 700; }}
QPushButton#PillButton:hover {{ background: rgba(0,158,236,0.3); }}
QComboBox#SmallCombo {{ padding: 2px 8px; font-size: 8.5pt; }}
QToolButton#ShowDot {{ background: rgba(12,13,16,0.6); border: 1px solid {PANEL_BORDER}; border-radius: 11px; }}
QToolButton#ShowDot:hover {{ border-color: {ACCENT}; }}
QToolButton#ShowDot[active="true"] {{ border: 2px solid {ACCENT}; background: rgba(0,158,236,0.2); }}
QPushButton#SupportRow, QPushButton#TimerRow {{ background: transparent; border: 1px solid transparent; border-radius: 0;
                                               text-align: left; padding: 0; }}
QPushButton#SupportRow:hover, QPushButton#TimerRow:hover {{ background: rgba(0,158,236,0.12); border-color: {ACCENT}; }}
QPushButton#TimerRow {{ background: rgba(12,13,16,0.4); border-color: {PANEL_BORDER}; }}
QPushButton#SupportCard {{ background: rgba(12,13,16,0.45); border: 1px solid {PANEL_BORDER}; border-radius: 0; padding: 0; }}
QPushButton#SupportCard:hover {{ border-color: {ACCENT}; background: rgba(0,158,236,0.12); }}
#SupportName {{ font-size: 8.5pt; font-weight: 600; color: #ffffff; }}
#SupportTeams {{ font-size: 8pt; font-weight: 700; }}
#SupportRank {{ color: {MUTED}; font-weight: 800; font-size: 10pt; min-width: 14px; }}
#TimerValue {{ color: #ffffff; font-weight: 800; font-size: 11.5pt; }}
#BannerTimer {{ color: {ACCENT}; font-weight: 700; font-size: 9pt; }}
#BannerTitle {{ font-size: 10.5pt; }}
QPushButton#CarouselArrow {{ font-size: 13pt; padding: 0 9px 3px 9px; border-radius: 4px; }}
#TodoHomeRow {{ background: rgba(12,13,16,0.4); border: 1px solid {PANEL_BORDER}; }}
#DomainOpen {{ color: #3ddc84; font-weight: 700; font-size: 8.5pt; }}
/* To Do List */
#TodoCard {{ background: rgba(28,29,34,0.92); border: 1px solid {PANEL_BORDER}; }}
#TodoName {{ font-size: 13pt; font-weight: 700; }}
#TodoRank {{ color: {ACCENT}; font-size: 13pt; font-weight: 800; min-width: 26px; }}
#MatCount {{ font-size: 8pt; font-weight: 700; color: #e5e7ec; }}
#MatDone {{ font-size: 9pt; font-weight: 800; color: #3ddc84; }}
#MatCountTopDone {{ font-size: 9pt; font-weight: 900; color: #3ddc84; background: rgba(8,8,10,0.85); padding: 0; }}
/* the To Do List's inventory popup (the usual popup; amounts in the build popup's style) */
#InventoryName {{ font-size: 9pt; color: #d6d9df; }}
QSpinBox#InventoryBox {{ background: rgba(0,0,0,0.28); color: #ffffff; border: 1px solid {BAR_BORDER}; border-radius: 3px;
                        padding: 3px 2px; font-size: 12pt; font-weight: 700; selection-background-color: rgba(0,158,236,0.45); }}
QSpinBox#InventoryBox:hover, QSpinBox#InventoryBox:focus {{ border-color: {ACCENT}; }}
QSpinBox#InventoryBox::up-button, QSpinBox#InventoryBox::down-button {{ width: 0; border: none; }}
QSpinBox#InventoryBox::up-arrow, QSpinBox#InventoryBox::down-arrow {{ image: none; width: 0; }}
QSpinBox#InventoryBox QLineEdit {{ color: #ffffff; background: transparent; border: none; padding: 0;
                                  font-size: 12pt; font-weight: 700; selection-background-color: rgba(0,158,236,0.45); }}
#MatCountTop {{ font-size: 8.5pt; font-weight: 700; color: #ffffff; background: rgba(8,8,10,0.85); padding: 1px 0; }}
#NoteText {{ color: #d6d9df; font-size: 10pt; }}
QPushButton#NotePicture {{ background: transparent; border: 1px solid transparent; padding: 0; }}
QPushButton#NotePicture:hover {{ border-color: #e05561; }}
#CraftBadge {{ font-size: 7.5pt; font-weight: 800; color: #ffffff; background: rgba(8,8,10,0.78); padding: 0 3px;
               border-top-right-radius: 4px; /* fixed */ }}
#TodoCard #TodoName {{ font-size: 13pt; font-weight: 800; color: #ffffff; background: transparent; /* fixed */ }}
#TodoBand #TodoRank {{ color: #ffffff; background: transparent; font-size: 11pt; /* fixed */ }}
#GoalHeading {{ color: #d6d9df; font-size: 9.5pt; font-weight: 800; padding-top: 4px; }}
#GoalValue {{ color: #ffffff; font-size: 10pt; font-weight: 700; }}
#GoalArrow {{ color: #8c909b; font-size: 10pt; }}
#GoalWhat {{ color: #8c909b; font-size: 9pt; }}
#DomainRow {{ background: rgba(12,13,16,0.4); border: 1px solid {PANEL_BORDER}; }}
#DomainRow[needed="true"] {{ border-color: #3ddc84; background: rgba(61,220,132,0.08); }}
/* End Game */
#EndGameHeader, #EndGameCard {{ background: rgba(28,29,34,0.92); border: 1px solid {PANEL_BORDER}; }}
#EndGameHeader[live="true"] {{ border: 1px solid #3ddc84; background: rgba(61,220,132,0.07); }}
#EndGameTitle {{ font-size: 18pt; font-weight: 800; }}
#StygianName {{ font-size: 12pt; font-weight: 700; }}
#StygianStats {{ background: rgba(12,13,16,0.6); border: 1px solid {PANEL_BORDER}; }}
#StygianStat {{ color: #ffffff; font-size: 15pt; font-weight: 800; }}
#StygianLevel {{ color: #8c909b; font-size: 10pt; font-weight: 800; }}
#HalfDivider {{ background: {PANEL_BORDER}; border: none; }}
#EndGameHeading {{ color: #8c909b; font-size: 8pt; font-weight: 900; }}
#EndGameMuted {{ color: {MUTED}; font-size: 9pt; }}
#EndGameText {{ color: #e5e7ec; font-size: 9.5pt; }}
#LiveTag {{ background: rgba(61,220,132,0.16); color: #3ddc84; border: 1px solid #3ddc84; font-weight: 800;
            font-size: 8pt; padding: 1px 8px; }}
#TestTag {{ background: rgba(245,166,35,0.14); color: #f5a623; border: 1px solid #f5a623; font-weight: 800;
            font-size: 8pt; padding: 1px 8px; }}
QPushButton#EntryRow {{ background: rgba(12,13,16,0.4); border: 1px solid {PANEL_BORDER}; border-radius: 0; text-align: left; }}
QPushButton#EntryRow:hover {{ border-color: {ACCENT}; }}
QPushButton#EntryRow[live="true"] {{ border-color: #3ddc84; background: rgba(61,220,132,0.08); }}
QPushButton#EntryRow[current="true"] {{ background: rgba(0,158,236,0.15); }}
#MonsterIcon {{ background: rgba(12,13,16,0.6); border: 1px solid {PANEL_BORDER}; }}
QPushButton#ModeCycle {{ background: rgba(28,29,34,0.92); border: 1px solid {PANEL_BORDER}; padding: 8px 14px;
                        color: {ACCENT}; font-weight: 700; }}
QPushButton#ModeCycle:hover {{ border-color: {ACCENT}; }}
/* Tier List Maker */
#TierCell {{ background: rgba(0,0,0,0.28); }}
#TierListRow {{ background: rgba(28,29,34,0.92); border: 1px solid {PANEL_BORDER}; }}
#TierListRow:hover {{ border-color: {ACCENT}; }}
QPushButton#DeleteRun {{ color: #f75058; }}
QPushButton#DeleteRun:hover {{ border-color: #f75058; background: rgba(247,80,88,0.12); }}
#TierPool {{ background: rgba(0,0,0,0.18); border: 1px solid {PANEL_BORDER}; }}
#TiersBox {{ background: {PANEL_BORDER}; }}
QLineEdit#TierTitle {{ font-size: 16pt; font-weight: 700; background: transparent; border: 1px solid transparent; }}
QLineEdit#TierTitle:hover, QLineEdit#TierTitle:focus {{ border-color: {PANEL_BORDER}; }}
QToolButton#TierArrow {{ background: transparent; border: none; color: rgba(255,255,255,0.6); font-size: 11pt; padding: 0 4px; }}
QToolButton#TierArrow:hover {{ color: {ACCENT}; }}
QToolButton#TierArrow:disabled {{ color: rgba(255,255,255,0.15); }}
#TierArrows {{ background: {PANEL_BG}; }}
#PageHint {{ background: transparent; border: none; color: {MUTED}; font-size: 9pt; padding: 2px 10px; }}
#PageHint:hover {{ color: {ACCENT}; }}
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
/* no arrow on any dropdown (like the talent levels): the box itself opens the list */
QComboBox::drop-down, QDateEdit::drop-down {{ width: 0; border: none; }}
QComboBox::down-arrow, QDateEdit::down-arrow {{ image: none; width: 0; }}
QDateEdit {{ background: {BUTTON_BG}; }}
QDateEdit::up-button, QDateEdit::down-button {{ width: 0; border: none; }}
QDateEdit::up-arrow, QDateEdit::down-arrow {{ image: none; width: 0; }}
/* the date picker's calendar, in the app's colours (so it follows light / dark and the theme too) */
QCalendarWidget QWidget {{ background: {PANEL_BG}; color: #ffffff; alternate-background-color: {BUTTON_BG}; }}
QCalendarWidget #qt_calendar_navigationbar {{ background: {BAR_BG}; border-bottom: 1px solid {PANEL_BORDER}; }}
QCalendarWidget QToolButton {{ background: transparent; border: none; color: #ffffff; font-weight: 700;
                               padding: 4px 8px; border-radius: 3px; }}
QCalendarWidget QToolButton:hover {{ background: rgba(0,158,236,0.18); }}
QCalendarWidget QToolButton::menu-indicator {{ image: none; width: 0; }}
QCalendarWidget QToolButton#qt_calendar_prevmonth, QCalendarWidget QToolButton#qt_calendar_nextmonth {{ font-size: 14pt; }}
QCalendarWidget QMenu {{ background: {PANEL_BG}; color: #ffffff; border: 1px solid {PANEL_BORDER}; }}
QCalendarWidget QMenu::item:selected {{ background: rgba(0,158,236,0.35); }}
QCalendarWidget QSpinBox {{ background: {BUTTON_BG}; color: #ffffff; border: 1px solid {PANEL_BORDER}; padding: 2px 6px;
                            selection-background-color: rgba(0,158,236,0.45); }}
QCalendarWidget QSpinBox::up-button, QCalendarWidget QSpinBox::down-button {{ width: 0; border: none; }}
QCalendarWidget QAbstractItemView {{ background: {PANEL_BG}; color: #ffffff; outline: 0; border: none;
                                     selection-background-color: {ACCENT}; selection-color: #ffffff; }}
QCalendarWidget QAbstractItemView:disabled {{ color: rgba(255,255,255,0.3); }}
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


CORNER = 10  # containers: the top-right and bottom-left corners are rounded, the other two square
SMALL_CORNER = 6  # (rows and tiles inside them)


def corners(selectors, radius=CORNER):
    """Style sheet rule rounding the top-right and bottom-left corners of these containers (Record Book's look)."""
    return (f"{', '.join(selectors)} {{ border-radius: 0; border-top-right-radius: {radius}px; "
            f"border-bottom-left-radius: {radius}px; }}\n")


def corner_path(rect, radius=CORNER, top_right=True, bottom_left=True):
    """A QPainterPath of rect with those corners rounded, for widgets that paint their own background."""
    path = QPainterPath()
    r = radius
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    path.moveTo(x, y)
    if top_right:
        path.lineTo(x + w - r, y)
        path.quadTo(x + w, y, x + w, y + r)
    else:
        path.lineTo(x + w, y)
    path.lineTo(x + w, y + h)
    if bottom_left:
        path.lineTo(x + r, y + h)
        path.quadTo(x, y + h, x, y + h - r)
    else:
        path.lineTo(x, y + h)
    path.closeSubpath()
    return path


# one look for every page's containers: the cards and panels share a fill and border (Home's cards), and the rows
# and tiles inside them share theirs (their highlighted states, like a live entry or a needed domain, keep their colours)
CARD_FILL, CARD_LINE, INSET_FILL = "rgba(28,29,35,0.95)", "#30323c", "rgba(12,13,16,0.45)"
STYLESHEET += (f"#Card, #Selector, #HomePanel, #HomeCard, #TodoCard, #EndGameHeader, #EndGameCard, #TierListRow "
               f"{{ background: {CARD_FILL}; border: 1px solid {CARD_LINE}; }}\n"
               f"QFrame#HomeItem, QPushButton#HomeItem, #TodoHomeRow, #DomainRow, #StygianStats, QPushButton#EntryRow, "
               f"#StatTile, #InsetTile {{ background: {INSET_FILL}; border: 1px solid {CARD_LINE}; }}\n")
STYLESHEET += corners(["#Card", "#Selector", "#ElementBoard", "#HomePanel", "#HomeCard", "#TodoCard", "#EndGameHeader",
                       "#EndGameCard", "#TierListRow", "#TierPool", "#PopupPanel", "#StatTile",
                       "#InsetTile"])
STYLESHEET += corners(["QPushButton#HomeItem", "QFrame#HomeItem", "#TodoHomeRow", "#DomainRow", "#StygianStats",
                       "QPushButton#EntryRow", "QPushButton#SupportCard", "QPushButton#ModeCycle"], SMALL_CORNER)


def themed_calendar(date_edit):
    """A date box with no arrow: clicking it opens a calendar in the app's look (it follows light / dark
    and the theme), and clicking a day picks it."""
    date_edit.setCalendarPopup(False)  # (its step buttons stay, at no width: hiding them squeezes the date to nothing)
    date_edit.setMinimumWidth(date_edit.fontMetrics().horizontalAdvance("0000-00-00") + 40)
    date_edit.setCursor(Qt.PointingHandCursor)
    date_edit._calendar_opener = _CalendarOpener(date_edit)
    date_edit.installEventFilter(date_edit._calendar_opener)
    date_edit.lineEdit().installEventFilter(date_edit._calendar_opener)
    return date_edit


def _style_calendar(calendar):
    """Text arrows for the months (Qt's arrow icons are dark, lost on a dark background) and every day in
    the normal text colour (not Qt's red weekends and dim weekdays)."""
    from PySide6.QtGui import QBrush, QTextCharFormat

    calendar.setGridVisible(False)
    calendar.setVerticalHeaderFormat(calendar.VerticalHeaderFormat.NoVerticalHeader)
    for name, text in (("qt_calendar_prevmonth", "\u2039"), ("qt_calendar_nextmonth", "\u203a")):
        button = calendar.findChild(QToolButton, name)
        if button is not None:
            button.setIcon(QIcon())
            button.setText(text)
    plain = QTextCharFormat()
    plain.setForeground(QBrush(QColor(theme.color("#e5e7ec"))))
    for day in (Qt.Monday, Qt.Tuesday, Qt.Wednesday, Qt.Thursday, Qt.Friday, Qt.Saturday, Qt.Sunday):
        calendar.setWeekdayTextFormat(day, plain)
    header = QTextCharFormat()
    header.setForeground(QBrush(QColor(theme.color("#8c909b"))))
    calendar.setHeaderTextFormat(header)


class _CalendarOpener(QObject):
    def __init__(self, date_edit):
        super().__init__(date_edit)
        self.date_edit = date_edit

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.LeftButton:
            self.open()
            return True
        if kind in (QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
            return True
        return False

    def open(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QCalendarWidget

        edit = self.date_edit
        calendar = QCalendarWidget(edit)
        calendar.setWindowFlags(Qt.Popup)
        calendar.setAttribute(Qt.WA_DeleteOnClose)
        _style_calendar(calendar)
        calendar.setSelectedDate(edit.date())
        calendar.setMinimumDate(edit.minimumDate())
        calendar.setMaximumDate(edit.maximumDate())

        def picked(day):
            edit.setDate(day)
            calendar.close()

        calendar.clicked.connect(picked)
        calendar.activated.connect(picked)
        calendar.adjustSize()
        below = edit.mapToGlobal(QPoint(edit.width() - calendar.width(), edit.height() + 4))
        screen = edit.screen().availableGeometry()
        if below.y() + calendar.height() > screen.bottom():  # no room below: open above the box
            below.setY(edit.mapToGlobal(QPoint(0, 0)).y() - calendar.height() - 4)
        below.setX(max(screen.left(), min(below.x(), screen.right() - calendar.width())))
        calendar.move(below)
        calendar.show()
        self.calendar = calendar


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
    """Nav icons drawn in code: house, circle, square, triangle, buff, book…"""
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
    elif shape == "buff":  # two stacked up-chevrons
        for top in (m + s * 0.05, m + s * 0.5):
            p.drawPolyline(QPolygonF([QPointF(m + s * 0.1, top + s * 0.4), QPointF(size / 2, top), QPointF(size - m - s * 0.1, top + s * 0.4)]))
    elif shape == "tiers":  # three stacked bars, shorter going down (a tier list)
        for n, frac in enumerate((1.0, 0.75, 0.5)):
            y = m + s * (0.12 + n * 0.38)
            p.drawLine(QPointF(m, y), QPointF(m + s * frac, y))
    elif shape == "chart":  # a bar chart: three bars rising
        p.drawLine(QPointF(m, size - m), QPointF(size - m, size - m))
        for n, frac in enumerate((0.45, 0.7, 1.0)):
            x = m + s * (0.18 + n * 0.32)
            p.drawLine(QPointF(x, size - m - s * 0.1), QPointF(x, size - m - s * frac))
    elif shape == "todo":  # a checklist: a tick and two lines
        p.drawPolyline(QPolygonF([QPointF(m, m + s * 0.2), QPointF(m + s * 0.12, m + s * 0.32),
                                  QPointF(m + s * 0.32, m + s * 0.06)]))
        p.drawLine(QPointF(m + s * 0.45, m + s * 0.2), QPointF(size - m, m + s * 0.2))
        p.drawRect(QRectF(m + s * 0.02, m + s * 0.62, s * 0.22, s * 0.22))
        p.drawLine(QPointF(m + s * 0.45, m + s * 0.73), QPointF(size - m, m + s * 0.73))
    elif shape == "crown":  # end-game content: a crown
        p.drawPolygon(QPolygonF([QPointF(m, size - m - s * 0.15), QPointF(m, m + s * 0.25),
                                 QPointF(m + s * 0.28, m + s * 0.5), QPointF(size / 2, m + s * 0.1),
                                 QPointF(size - m - s * 0.28, m + s * 0.5), QPointF(size - m, m + s * 0.25),
                                 QPointF(size - m, size - m - s * 0.15)]))
    elif shape == "gear":  # cog: a ring with eight teeth
        import math

        centre = QPointF(size / 2, size / 2)
        for i in range(8):
            a = math.pi / 4 * i
            inner = QPointF(centre.x() + math.cos(a) * s * 0.33, centre.y() + math.sin(a) * s * 0.33)
            outer = QPointF(centre.x() + math.cos(a) * s * 0.5, centre.y() + math.sin(a) * s * 0.5)
            p.drawLine(inner, outer)
        p.drawEllipse(centre, s * 0.33, s * 0.33)
        p.drawEllipse(centre, s * 0.12, s * 0.12)
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
        self.instant_tip = False  # show the tooltip at once on hover (not after Qt's usual delay)
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

    def enterEvent(self, event):
        super().enterEvent(event)
        if self.instant_tip and self.toolTip():
            from PySide6.QtGui import QCursor
            from PySide6.QtWidgets import QToolTip

            QToolTip.showText(QCursor.pos(), self.toolTip(), self)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self.instant_tip:
            from PySide6.QtWidgets import QToolTip

            QToolTip.hideText()

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
                p.setPen(QPen(QColor(theme.accent_hex()), 1.5, Qt.DashLine))
                p.drawRect(rect.adjusted(2, 2, -2, -2))
                p.setPen(QColor(theme.color(ACCENT)))
                f = QFont("Segoe UI", int(self.height() / 4))
                p.setFont(f)
                p.drawText(rect, Qt.AlignCenter, "+")

        p.setClipping(False)
        p.setPen(QPen(QColor(theme.color(PANEL_BORDER)), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(rect)
        if self._badge:
            # sized to the tile, so on a small one it covers only a corner of the picture
            small = self.height() < 80
            f = QFont("Segoe UI", 7 if small else 9, QFont.Bold)
            p.setFont(f)
            w = p.fontMetrics().horizontalAdvance(self._badge) + (6 if small else 10)
            h = 13 if small else 17
            badge = QRectF(rect.right() - w - 2, rect.bottom() - h - 2, w, h)
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


class FlowLayout(QLayout):
    """Widgets left to right, wrapping onto a new line when the row is full (Qt's flow layout example)."""

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._place(QRectF(0, 0, width, 0).toRect(), move=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, move=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _place(self, rect, move):
        margins = self.contentsMargins()
        left, top = rect.x() + margins.left(), rect.y() + margins.top()
        right = rect.right() - margins.right()
        x, y, line = left, top, 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > right + 1 and line > 0:
                x, y, line = left, y + line + self.spacing(), 0
            if move:
                from PySide6.QtCore import QRect

                item.setGeometry(QRect(x, y, hint.width(), hint.height()))
            x += hint.width() + self.spacing()
            line = max(line, hint.height())
        return y + line - rect.y() + margins.bottom()


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
    """A character card: rarity background, portrait, element symbol top-left (a weapon: its type's), ✔ if logged,
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
        p.setBrush(QColor(theme.color(ACCENT)))
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


def _soft_blur(pixmap, radius):
    """Gaussian-blur a (small) picture by radius pixels, same size out."""
    from PySide6.QtWidgets import QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene

    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(pixmap)
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(radius)
    effect.setBlurHints(QGraphicsBlurEffect.QualityHint)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    out = QPixmap(pixmap.size())
    out.fill(Qt.transparent)
    p = QPainter(out)
    scene.render(p, QRectF(out.rect()), QRectF(pixmap.rect()))
    p.end()
    return out


class Nebula:
    """A starry haze in one colour, like the backdrop of the game's character screen, that moves: soft blurred
    clouds (brightest in the middle, behind the character) sway slowly, a thinner mist drifts across them the other
    way, and stars fade in and out over a still field of faint ones. paint(painter, seconds) draws it at a moment;
    made once per page size and colour."""

    DRIFT = 0.05  # how far the clouds sway, as a share of the page
    DIM = 60  # the fog darkened by 10% and then 15% more (1 - 0.9 * 0.85 of 255)
    SCALE = 6  # the clouds are worked out this many times smaller (they're blurred anyway), then scaled up

    def __init__(self, width, height, color, ratio=1.0, seed=7):
        import random

        rng = random.Random(seed)
        self.w, self.h = w, h = max(1, width), max(1, height)
        base = QColor(color)

        def mix(c, other, share):
            return QColor(int(c.red() + (other.red() - c.red()) * share),
                          int(c.green() + (other.green() - c.green()) * share),
                          int(c.blue() + (other.blue() - c.blue()) * share))

        black, white = QColor(6, 7, 10), QColor(255, 255, 255)
        self.deep = deep = mix(base, black, 0.74)
        mid, self.light = mix(base, black, 0.3), mix(base, white, 0.35)
        light = self.light
        self.margin = m = int(max(w, h) * self.DRIFT) + 4  # room to sway without showing an edge

        def cloud(p, cx, cy, radius, c, alpha, stretch=1.0):
            g = QRadialGradient(QPointF(0, 0), radius)
            for stop, share in ((0.0, 1.0), (0.5, 0.45), (1.0, 0.0)):
                k = QColor(c)
                k.setAlpha(int(alpha * share))
                g.setColorAt(stop, k)
            p.save()
            p.translate(cx, cy)
            p.scale(stretch, 1 / stretch)
            p.fillRect(QRectF(-radius, -radius, 2 * radius, 2 * radius), g)
            p.restore()

        def layer(fill, paint, blur):
            # page plus margin, small, blurred, then scaled up to the screen's resolution
            sw, sh = max(1, (w + 2 * m) // self.SCALE), max(1, (h + 2 * m) // self.SCALE)
            small = QPixmap(sw, sh)
            small.fill(fill)
            p = QPainter(small)
            p.setRenderHint(QPainter.Antialiasing)
            p.translate(m / self.SCALE, m / self.SCALE)  # page coordinates (small) from here
            paint(p, w / self.SCALE, h / self.SCALE)
            p.end()
            out = _soft_blur(small, blur).scaled(int((w + 2 * m) * ratio), int((h + 2 * m) * ratio),
                                                 Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            out.setDevicePixelRatio(ratio)
            return out

        def clouds(p, sw, sh):
            big = max(sw, sh)
            cloud(p, sw * 0.55, sh * 0.45, big * 0.6, mid, 230)  # the glow behind the character
            cloud(p, sw * 0.58, sh * 0.42, big * 0.3, light, 110)
            for _ in range(34):
                cx, cy = rng.gauss(0.55, 0.28) * sw, rng.gauss(0.5, 0.3) * sh
                kind = rng.random()
                if kind < 0.45:
                    cloud(p, cx, cy, big * rng.uniform(0.15, 0.4), mid, rng.randint(90, 170))
                elif kind < 0.72:
                    cloud(p, cx, cy, big * rng.uniform(0.08, 0.22), light, rng.randint(45, 105))
                else:  # darker patches give the haze its depth
                    cloud(p, cx, cy, big * rng.uniform(0.12, 0.3), black, rng.randint(50, 110))

        def mist(p, sw, sh):  # long thin wisps, drawn over the clouds and drifting the other way
            big = max(sw, sh)
            for _ in range(16):
                cx, cy = rng.uniform(-0.1, 1.1) * sw, rng.gauss(0.5, 0.25) * sh
                cloud(p, cx, cy, big * rng.uniform(0.1, 0.25), light if rng.random() < 0.6 else mid,
                      rng.randint(35, 80), stretch=rng.uniform(1.6, 2.6))

        self.back = layer(deep, clouds, 4)
        self.mist = layer(Qt.transparent, mist, 6)

        # what stays still: a faint horizon, the darker edges, and a field of faint stars
        self.front = QPixmap(int(w * ratio), int(h * ratio))
        self.front.fill(Qt.transparent)
        self.front.setDevicePixelRatio(ratio)
        p = QPainter(self.front)
        p.setRenderHint(QPainter.Antialiasing)
        band = QLinearGradient(0, h * 0.55, 0, h)
        for stop, (c, alpha) in ((0.0, (light, 0)), (0.35, (light, 55)), (0.6, (mid, 30)), (1.0, (black, 90))):
            k = QColor(c)
            k.setAlpha(alpha)
            band.setColorAt(stop, k)
        p.fillRect(QRectF(0, h * 0.55, w, h * 0.45), band)
        vignette = QRadialGradient(QPointF(w * 0.5, h * 0.45), max(w, h) * 0.75)
        vignette.setColorAt(0.0, QColor(0, 0, 0, 0))
        vignette.setColorAt(0.7, QColor(0, 0, 0, 60))
        vignette.setColorAt(1.0, QColor(0, 0, 0, 170))
        p.fillRect(QRectF(0, 0, w, h), vignette)
        p.setPen(Qt.NoPen)
        for _ in range(int(w * h / 4000)):
            star = QColor(white if rng.random() < 0.6 else light)
            star.setAlpha(rng.randint(30, 120))
            p.setBrush(star)
            r = rng.uniform(0.5, 1.2)
            p.drawEllipse(QPointF(rng.random() * w, rng.random() * h), r, r)
        p.end()

        # stars that pop in and out: (x, y, radius, colour, brightest, seconds per twinkle, phase)
        self.stars = [(rng.random() * w, rng.random() * h, rng.uniform(0.8, 1.9),
                       QColor(white if rng.random() < 0.6 else light), rng.randint(150, 255),
                       rng.uniform(3, 9), rng.random()) for _ in range(int(w * h / 7000))]
        # a few brighter stars, slower: a slightly larger dot in a soft glow
        self.sparkles = [(rng.random() * w, rng.random() * h, rng.uniform(2.0, 3.0), rng.uniform(5, 12), rng.random())
                         for _ in range(16)]

    @staticmethod
    def _pulse(t, period, phase, sharp=3):
        """0 most of the time, rising to 1 and back once a period: a star appearing and fading."""
        import math

        return max(0.0, math.sin(2 * math.pi * (t / period + phase))) ** sharp

    def paint(self, p, t):
        import math

        w, h, m = self.w, self.h, self.margin
        p.save()
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(QRectF(0, 0, w, h), self.deep)

        def at(pm, x, y):  # fractional positions, so the slow sway doesn't step pixel by pixel
            size = pm.deviceIndependentSize()
            p.drawPixmap(QRectF(x, y, size.width(), size.height()), pm, QRectF(pm.rect()))

        tau = 2 * math.pi
        at(self.back, -m + m * 0.8 * math.sin(tau * t / 47), -m + m * 0.5 * math.sin(tau * t / 61 + 1.3))
        p.setOpacity(0.65 + 0.35 * math.sin(tau * t / 23))
        at(self.mist, -m - m * 0.9 * math.sin(tau * t / 31 + 0.7), -m + m * 0.4 * math.cos(tau * t / 43))
        p.setOpacity(1)
        p.fillRect(QRectF(0, 0, w, h), QColor(0, 0, 0, self.DIM))
        p.drawPixmap(0, 0, self.front)

        p.setPen(Qt.NoPen)
        for x, y, r, color, peak, period, phase in self.stars:
            alpha = int(peak * self._pulse(t, period, phase))
            if alpha < 6:
                continue
            k = QColor(color)
            k.setAlpha(alpha)
            p.setBrush(k)
            p.drawEllipse(QPointF(x, y), r, r)
        for x, y, size, period, phase in self.sparkles:
            shown = self._pulse(t, period, phase, sharp=2)
            if shown < 0.03:
                continue
            size *= 0.7 + 0.3 * shown
            glow = QRadialGradient(QPointF(x, y), size * 3)
            k = QColor(self.light)
            k.setAlpha(int(120 * shown))
            glow.setColorAt(0, k)
            k.setAlpha(0)
            glow.setColorAt(1, k)
            p.setBrush(glow)
            p.drawEllipse(QPointF(x, y), size * 3, size * 3)
            p.setBrush(QColor(255, 255, 255, int(235 * shown)))
            p.drawEllipse(QPointF(x, y), size, size)
        p.restore()


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
