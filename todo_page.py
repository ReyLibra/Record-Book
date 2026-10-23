"""To Do List page: a planner for leveling characters and weapons.

Add a character (level, and the three talents, from now to the goal) or a weapon (level), and every goal
lists the materials it needs. On the right: everything added up, and the domains open today. The goals'
order is their priority (Reorder: drag and drop), and Home shows the top three.
"""

import uuid

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QIcon

import gamedata
import materials
import servers
from dialogs import CharacterSearchDialog, Popup, _IconList, _buttons, _field_label, _search_box, _stars, confirm
from widgets import RARITY_COLORS, FlowLayout, card_pixmap, clear_layout, section_header

TASKS_KEY = "todo"
OWNED_KEY = "todo_owned"  # {material id: how many you have}, taken off the summary's totals
CARD_WIDTH = 330  # a goal's card
MAT_ICON = 40
PORTRAIT = 80
SUMMARY_WIDTH = 300
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
SHORT_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def short_count(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M".replace(".00M", "M")
    if n >= 10_000:
        return f"{n / 1000:.1f}K".replace(".0K", "K")
    return f"{n:,}"


class MaterialTile(QWidget):
    """A material's picture on its rarity background with how many are needed under it. With owned (the
    summary), it shows how many are still needed, ✓ once you have enough, and clicking it asks how many
    you have."""

    clicked = Signal(int)

    def __init__(self, item_id, count, size=MAT_ICON, owned=None, count_on_top=False, crafted=0):
        """crafted: how many of owned are crafted from leftovers of the tier below (a ⚒ badge on the picture)."""
        super().__init__()
        self.item_id = item_id
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0 if count_on_top else 1)
        pic = QLabel()
        pic.setFixedSize(size, size)
        rank = (materials.items().get(item_id) or {}).get("rank", 1)

        def loaded(pm, pic=pic):
            card = card_pixmap(pm, None, rank, size)
            card.setDevicePixelRatio(2)
            pic.setPixmap(card)

        url = materials.icon_url(item_id)
        if url:
            gamedata.load_pixmap(url, loaded)
        v.addWidget(pic, 0, Qt.AlignHCenter)
        if crafted:
            badge = QLabel(f"⚒{short_count(crafted)}", pic)
            badge.setObjectName("CraftBadge")
            badge.adjustSize()
            badge.move(0, size - badge.height())
        name = materials.name(item_id)
        if owned is None:
            text, tip = short_count(count), f"{name}  × {count:,}"
        else:
            left = max(0, count - owned)
            text = "✓" if not left else short_count(left)
            have = f"have {owned - crafted:,} + craft {crafted:,}" if crafted else f"have {owned:,}"
            tip = f"{name}\nNeeded {count:,}  ·  {have}  ·  still needed {left:,}\nClick to enter how many you have"
            self.setCursor(Qt.PointingHandCursor)
        label = QLabel(text)
        label.setAlignment(Qt.AlignHCenter)
        label.setObjectName("MatDone" if owned is not None and owned >= count else "MatCount")
        if count_on_top:  # a dark tag as wide as the picture, under it (Genshin Center's planner style)
            label.setObjectName("MatCountTopDone" if owned is not None and owned >= count else "MatCountTop")
            label.setFixedWidth(size)
            v.addWidget(label, 0, Qt.AlignHCenter)
        else:
            label.setFixedWidth(size + 6)
            v.addWidget(label, 0, Qt.AlignHCenter)
        for w in (pic, label, *pic.findChildren(QLabel)):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setToolTip(tip)
        self._clickable = owned is not None

    def mouseReleaseEvent(self, event):
        if self._clickable and event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.item_id)


INVENTORY_ICON = 64
INVENTORY_GROUPS_PER_ROW = 2
INVENTORY_HEADING_WIDTH = 220  # a group's heading wraps at this width (or its pictures', if wider)


def _scaled_card(pm):
    pm.setDevicePixelRatio(2)
    return pm


CROWN = 104319
FAMILY_TYPES = {"characterAscensionMaterial", "characterTalentMaterial", "characterandWeaponEnhancementMaterial",
                "weaponAscensionMaterial"}


def family(item_id):
    """A material with the others it's crafted from / into (Teachings, Guide, Philosophies of Diligence; a mob's
    three drops; a gem's four sizes), lowest rarity first; most materials are on their own."""
    items = materials.items()
    item = items.get(item_id)
    if not item or item["type"] not in FAMILY_TYPES or item_id == CROWN:
        return [item_id]
    found = [item_id]
    step = item_id
    while (prev := items.get(step - 1)) and prev["type"] == item["type"] and prev["rank"] == items[step]["rank"] - 1:
        step -= 1
        found.insert(0, step)
    step = item_id
    while (nxt := items.get(step + 1)) and nxt["type"] == item["type"] and nxt["rank"] == items[step]["rank"] + 1 \
            and step + 1 != CROWN:
        step += 1
        found.append(step)
    return found


GEM_ELEMENTS = {"Agnidus": "Pyro", "Varunada": "Hydro", "Nagadus": "Dendro", "Vajrada": "Electro",
                "Vayuda": "Anemo", "Shivada": "Cryo", "Prithiva": "Geo"}


def boss_group(item_id):
    """A boss material with the others the same boss drops. A weekly boss drops three (their ids run in threes,
    counted from the start of each run of weekly drops); a normal boss, one."""
    items = materials.items()
    item = items.get(item_id) or {}
    if item.get("rank", 0) < 5:
        return [item_id]

    def weekly(i):
        it = items.get(i) or {}
        return it.get("type") == "characterLevelUpMaterial" and it.get("rank", 0) >= 5

    start = item_id
    while weekly(start - 1):
        start -= 1
    first = start + (item_id - start) // 3 * 3
    return [i for i in range(first, first + 3) if weekly(i)]


def inventory_groups(item_id, context=()):
    """[(heading, [material ids])] for the inventory popup of a material. A boss drop comes with the gems of the
    goal it was clicked in (bosses drop those too), and a gem with the goal's boss drop; anything else is one
    group, its family. context: the goal's materials."""
    items = materials.items()
    kind = (items.get(item_id) or {}).get("type")
    if kind not in ("characterLevelUpMaterial", "characterAscensionMaterial") or item_id == CROWN:
        return [(None, family(item_id))]
    in_goal = set(context) | {item_id}
    if kind == "characterLevelUpMaterial":
        bosses = [item_id]
    else:
        bosses = sorted(i for i in in_goal if (items.get(i) or {}).get("type") == "characterLevelUpMaterial"
                        and (items.get(i) or {}).get("rank", 0) < 5)
    gems = item_id if kind == "characterAscensionMaterial" else next(
        (i for i in sorted(in_goal) if (items.get(i) or {}).get("type") == "characterAscensionMaterial"), None)
    gem_families = [family(gems)] if gems else []
    groups = []
    for b in bosses:
        drops = materials.known_boss_drops(b)  # (looked up in the background when the page loads)
        heading = "Weekly Boss Material" if items[b]["rank"] >= 5 else "Boss Material"
        if drops:
            heading = f"{heading}  ·  {drops['boss']}"
            groups.append((heading, drops["materials"]))
            for gem in drops["gems"]:  # every gem it drops (the goal's own first)
                if not any(gem in f for f in gem_families):
                    gem_families.append(family(gem))
        else:  # not looked up yet: its drops by their ids, and the goal's gem
            groups.append((heading, boss_group(b)))
    for chain in gem_families:
        word = materials.name(chain[0]).split()[0]
        groups.append((f"{GEM_ELEMENTS[word]} Gems" if word in GEM_ELEMENTS else "Gems", chain))
    return groups


def boss_materials(item_ids):
    """The boss materials among some materials (looked up with materials.boss_drops in the background)."""
    items = materials.items()
    return [i for i in item_ids if (items.get(i) or {}).get("type") == "characterLevelUpMaterial" and i != CROWN]


def material_rows(counts, kind):
    """A goal's materials in rows, the way the game groups them. A character: Mora, EXP and specialty across
    the top, then two columns: boss drop, weekly boss drop and Crown over the gem; the mob drops over the talent
    books (that part is one ("columns", left rows, right rows) entry). A weapon: Mora and ore; its two kinds of
    mob drops (the one that starts grey first); its ascension materials."""
    items = materials.items()
    need = [i for i, n in counts.items() if n > 0]

    def of(test):
        return sorted((i for i in need if test(items.get(i) or {}, i)), key=lambda i: (items[i]["rank"], i))

    mob = of(lambda it, i: it.get("type") == "characterandWeaponEnhancementMaterial")
    mob_families = []
    for item_id in mob:
        if not any(item_id in f for f in mob_families):
            mob_families.append([i for i in family(item_id) if i in need])
    mob_families.sort(key=lambda f: (items[f[0]]["rank"], f[0]))
    if kind == "character":
        left = [r for r in [
            of(lambda it, i: it.get("type") == "characterLevelUpMaterial" and it.get("rank", 0) < 5)
            + of(lambda it, i: it.get("type") == "characterLevelUpMaterial" and it.get("rank", 0) >= 5)
            + [i for i in need if i == CROWN],
            of(lambda it, i: it.get("type") == "characterAscensionMaterial"),
        ] if r]
        right = [r for r in mob_families + [
            of(lambda it, i: it.get("type") == "characterTalentMaterial" and i != CROWN)] if r]
        rows = [[i for i in need if i == materials.MORA] + of(lambda it, i: it.get("type") == "characterEXPMaterial")
                + of(lambda it, i: str(it.get("type", "")).startswith("localSpecialty"))]
        placed = {i for row in rows + left + right for i in row}
        if left or right:
            rows.append(("columns", left, right))
    else:
        rows = [[i for i in need if i == materials.MORA] + of(lambda it, i: it.get("type") == "weaponEnhancementMaterial")]
        rows += mob_families
        rows.append(of(lambda it, i: it.get("type") == "weaponAscensionMaterial"))
        placed = {i for row in rows for i in row}
    rows.append(sorted(i for i in need if i not in placed))  # (anything else)
    return [row for row in rows if row]


CRAFT_RATIO = 3  # three of a tier craft one of the next (gems, talent books, mob drops, weapon materials)


def allocate(tasks, details, owned):
    """What you have, shared out to the goals one at a time in priority order: ({task id: {material: how many
    of it are covered}}, {task id: {material: how many of those are crafted}}).

    Each goal takes what it needs of what's left, then crafts up from what's left after that (three of a tier
    make one of the next, through as many tiers as it takes), before the next goal gets anything: 100 of a mob
    drop go to crafting for the top goal, not to a goal further down that needs them as they are."""
    left = {int(k): v for k, v in owned.items()}
    covered, crafted = {}, {}

    def obtainable(chain, i):
        """How many of chain[i] the leftovers give, its own and crafted from the tiers below."""
        below = obtainable(chain, i - 1) // CRAFT_RATIO if i else 0
        return left.get(chain[i], 0) + below

    def use(chain, i, n):
        own = min(n, left.get(chain[i], 0))
        left[chain[i]] = left.get(chain[i], 0) - own
        if n > own:
            use(chain, i - 1, (n - own) * CRAFT_RATIO)

    for task in tasks:
        costs = (details.get(task["id"]) or {}).get("costs")
        if not costs:
            continue
        need = materials.total(costs)
        mine, made = {}, {}
        for item_id, count in need.items():  # what it needs, as it is
            take = min(count, left.get(item_id, 0))
            mine[item_id] = take
            left[item_id] = left.get(item_id, 0) - take
        covered[task["id"]] = mine
        for item_id in sorted(need, key=lambda i: (materials.items().get(i) or {}).get("rank", 0)):  # lowest first
            short = need[item_id] - mine.get(item_id, 0)
            chain = family(item_id)
            i = chain.index(item_id)
            if short <= 0 or i == 0:
                continue
            make = min(short, obtainable(chain, i - 1) // CRAFT_RATIO)
            if make:
                use(chain, i - 1, make * CRAFT_RATIO)
                mine[item_id] = mine.get(item_id, 0) + make
                made[item_id] = make
        crafted[task["id"]] = made
    return covered, crafted


def material_grid(counts, kind, covered, on_click, crafted=None):
    """A goal's materials in their rows (material_rows), counts on top; covered ({material: how many you have
    for this goal}) turns them into what's still needed, ✓ once there's enough."""
    holder = QWidget()
    v = QVBoxLayout(holder)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(4)

    def tiles(row_items, centred=True):
        row = QHBoxLayout()
        row.setSpacing(4)
        if centred:
            row.addStretch()  # (each row centred in the card; in a column, they start at its left)
        for item_id in row_items:
            tile = MaterialTile(item_id, counts[item_id], owned=covered.get(item_id, 0), count_on_top=True,
                                crafted=(crafted or {}).get(item_id, 0))
            tile.clicked.connect(lambda i: on_click(i, tuple(counts)))  # (with the goal's materials)
            row.addWidget(tile)
        row.addStretch()
        return row

    for entry in material_rows(counts, kind):
        if entry[0] == "columns":  # the two columns side by side, together centred in the card
            columns = QHBoxLayout()
            columns.setSpacing(16)
            columns.addStretch()
            for rows in entry[1:]:
                if not rows:
                    continue
                col = QVBoxLayout()
                col.setSpacing(4)
                for row_items in rows:
                    col.addLayout(tiles(row_items, centred=False))
                col.addStretch()
                columns.addLayout(col)
            columns.addStretch()
            v.addLayout(columns)
        else:
            v.addLayout(tiles(entry))
    return holder


def materials_flow(counts, owned=None, on_click=None, counts_on_top=False, crafted=None):
    """The materials as tiles that wrap; owned ({item: count}) shows what's still needed (the summary), crafted
    ({item: count}) what leftovers of the tier below make up besides."""
    holder = QWidget()
    flow = FlowLayout(holder, spacing=4)
    crafted = crafted or {}
    for item_id in materials.sort_items([i for i, n in counts.items() if n > 0]):
        made = crafted.get(item_id, 0)
        tile = MaterialTile(item_id, counts[item_id],
                            owned=None if owned is None else owned.get(str(item_id), 0) + made,
                            count_on_top=counts_on_top, crafted=made)
        if on_click:
            tile.clicked.connect(on_click)
        flow.addWidget(tile)
    return holder


class InventoryDialog(Popup):
    """How many of a material (and the others of its family, or the other drops of its boss: inventory_groups)
    you have, in the app's usual popup: each group under its heading, side by side and centred, each material's
    picture with its name and an amount box under it; Done saves."""

    def __init__(self, item_id, owned, parent=None, context=()):
        groups = inventory_groups(item_id, context)
        self.items = [m for _, ids in groups for m in ids]
        title = materials.name(groups[0][1][-1]) if len(groups) == 1 else "Boss Drops"
        rows = [groups[i:i + INVENTORY_GROUPS_PER_ROW] for i in range(0, len(groups), INVENTORY_GROUPS_PER_ROW)]
        super().__init__(parent, title, 380)
        self.inventory = {}
        for groups_in_row in rows:  # two groups a row (a boss with three kinds of gems: two rows)
            row = QHBoxLayout()
            row.setSpacing(40)
            row.addStretch()
            for heading, ids in groups_in_row:
                col = QVBoxLayout()
                col.setSpacing(8)
                grid = self._grid(ids, owned)
                # the heading wraps to its group's width (a boss's name on its own line), never wider
                width = max(grid.sizeHint().width(), INVENTORY_HEADING_WIDTH)
                label = QLabel((heading or "Inventory").upper().replace("  ·  ", "\n"))
                label.setObjectName("FieldLabel")
                label.setAlignment(Qt.AlignCenter)
                label.setWordWrap(True)
                label.setFixedWidth(width)
                col.addWidget(label, 0, Qt.AlignHCenter)
                col.addLayout(grid)
                col.setAlignment(grid, Qt.AlignHCenter)
                col.addStretch()
                row.addLayout(col)
            row.addStretch()
            self.body.addLayout(row)
            self.body.addSpacing(8)
        self.body.addSpacing(6)
        self.body.addWidget(_buttons(self, "Done", "Cancel"))
        # as wide as what's in it (it used to guess from the number of pictures, and a long heading got cut off)
        self.panel.layout().activate()
        self._box_size = (max(380, self.panel.layout().sizeHint().width()), None)
        box = self.inventory[item_id]
        box.setFocus()
        box.selectAll()

    def _grid(self, ids, owned):
        from PySide6.QtWidgets import QSpinBox

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        names = []
        for col, material in enumerate(ids):
            pic = QLabel()
            pic.setFixedSize(INVENTORY_ICON, INVENTORY_ICON)
            rank = (materials.items().get(material) or {}).get("rank", 1)
            url = materials.icon_url(material)
            if url:
                gamedata.load_pixmap(url, lambda pm, pic=pic, rank=rank: pic.setPixmap(
                    _scaled_card(card_pixmap(pm, None, rank, INVENTORY_ICON))))
            pic.setToolTip(materials.name(material))
            grid.addWidget(pic, 0, col, Qt.AlignHCenter)
            name = QLabel(materials.name(material))
            name.setObjectName("InventoryName")
            name.setWordWrap(True)
            name.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
            name.setFixedWidth(INVENTORY_ICON + 24)
            names.append(name)
            grid.addWidget(name, 1, col, Qt.AlignHCenter | Qt.AlignTop)
            box = QSpinBox()
            box.setObjectName("InventoryBox")
            box.setRange(0, 999_999_999)
            box.setAlignment(Qt.AlignCenter)  # (its step buttons stay, at no width: removed, the number vanishes)
            box.setFixedWidth(INVENTORY_ICON + 24)
            box.setValue(owned.get(str(material), 0))
            box.setToolTip(f"How many {materials.name(material)} you have")
            grid.addWidget(box, 2, col, Qt.AlignHCenter)
            self.inventory[material] = box
        # every name gets the height its wrapped lines need (a grid doesn't give wrapped labels their height, so
        # a second line was cut off), all the same so the boxes under them line up
        tallest = 0
        for name in names:
            name.ensurePolished()
            tallest = max(tallest, name.heightForWidth(name.width()))
        for name in names:
            name.setFixedHeight(tallest)
        return grid

    def values(self):
        """{material: how many you have now}."""
        return {m: self.inventory[m].value() for m in self.items}


def goal_text(task, steps):
    """'Lv. 20 → 90  ·  Normal Attack 1 → 10 …' for a goal (only the parts that change)."""
    parts = []
    a, b = task["level"]
    if steps and b > a:
        parts.append(f"Lv. {materials.step_label(steps, a)} → {materials.step_label(steps, b)}")
    for name, (x, y) in zip(("NA", "Skill", "Burst"), task.get("talents") or []):
        if y > x:
            parts.append(f"{name} {x} → {y}")
    return "   ·   ".join(parts) or "Nothing left to level"


def home_order(tasks, details, weekday):
    """The goals in the order Home lists them: the ones whose talent / weapon domain is open today first, then
    the rest; each part in priority order."""
    def open_today(task):
        days = (details.get(task["id"]) or {}).get("days") or {}
        return any(weekday in d for d in days.values())

    return sorted(tasks, key=lambda task: not open_today(task))  # (a stable sort keeps the priority order)


class WeaponPicker(Popup):
    def __init__(self, weapons, parent=None):
        super().__init__(parent, "Add weapon", 460, 600)
        self.chosen = None
        self.search = _search_box("Search weapons…  (e.g. Homa, PJWS, EL)", self)
        self.list = _IconList()
        for w in sorted(weapons, key=lambda w: (-w.rarity, w.name)):
            self.list.add(f"{w.name}\n{_stars(w.rarity)}  {gamedata.weapon_type_name(w.type)}", w.icon, w.id, rarity=w.rarity)
        self.search.textChanged.connect(self.list.filter)
        self.list.itemDoubleClicked.connect(lambda _: self.accept())
        self.body.addWidget(self.search)
        self.body.addWidget(self.list, 1)
        self.body.addWidget(_buttons(self, "Choose"))
        self.search.setFocus()

    def accept(self):
        item = self.list.currentItem()
        if item is None or item.isHidden():
            return
        self.chosen = item.data(Qt.UserRole)
        super().accept()


class GoalDialog(Popup):
    """Current level and goal (and the three talents, for a character)."""

    def __init__(self, title, steps, task, talents=True, parent=None):
        super().__init__(parent, title, 460)
        self.steps = steps
        labels = [materials.step_label(steps, i) for i in range(len(steps))]
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.addWidget(QLabel(""), 0, 0)
        for col, text in ((1, "Current"), (3, "Goal")):
            head = QLabel(text)
            head.setObjectName("FieldLabel")
            grid.addWidget(head, 0, col)
        self.level = self._pair(grid, 1, "Level", labels, task["level"])
        self.talents = []
        if talents:
            for n, name in enumerate(materials.TALENT_NAMES):
                self.talents.append(self._pair(grid, n + 2, name, [str(i) for i in range(1, 11)],
                                               [x - 1 for x in task["talents"][n]]))
        self.body.addLayout(grid)
        self.body.addSpacing(6)
        self.body.addWidget(_buttons(self, "Save"))

    @staticmethod
    def _pair(grid, row, label, options, values):
        grid.addWidget(QLabel(label), row, 0)
        boxes = []
        for col, value in ((1, values[0]), (3, values[1])):
            box = QComboBox()
            box.addItems(options)
            box.setCurrentIndex(max(0, min(len(options) - 1, value)))
            grid.addWidget(box, row, col)
            boxes.append(box)
        arrow = QLabel("→")
        arrow.setAlignment(Qt.AlignCenter)
        grid.addWidget(arrow, row, 2)
        start, end = boxes
        start.currentIndexChanged.connect(lambda i: end.currentIndex() < i and end.setCurrentIndex(i))
        end.currentIndexChanged.connect(lambda i: start.currentIndex() > i and start.setCurrentIndex(i))
        return boxes

    def values(self):
        level = [self.level[0].currentIndex(), self.level[1].currentIndex()]
        talents = [[a.currentIndex() + 1, b.currentIndex() + 1] for a, b in self.talents]
        return level, talents


class ReorderDialog(Popup):
    """The goals as a list to drag into priority order (top = most important)."""

    def __init__(self, rows, parent=None):
        super().__init__(parent, "Priority", 440, 560)
        hint = QLabel("Drag the goals into order: the top three show on Home.")
        hint.setWordWrap(True)
        hint.setObjectName("EndGameMuted")
        self.body.addWidget(hint)
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        self.list.setIconSize(QSize(40, 40))
        self.list.setCursor(Qt.OpenHandCursor)
        for task_id, text, icon_url, rarity in rows:
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, task_id)
            self.list.addItem(item)
            if icon_url:
                gamedata.load_pixmap(icon_url, lambda pm, item=item, rarity=rarity:
                                     pm and item.setIcon(QIcon(card_pixmap(pm, None, rarity, 40))))
        self.body.addWidget(self.list, 1)
        self.body.addWidget(_buttons(self, "Save"))

    def order(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]


NOTE_PICTURE = 56  # a note's pictures


class MaterialPicker(Popup):
    """Type to search, then pick a material (for a note's pictures)."""

    def __init__(self, parent=None):
        super().__init__(parent, "Add material", 460, 600)
        self.chosen = None
        self.search = _search_box("Search materials…  (e.g. Diligence, Agnidus, Crown)", self)
        self.list = _IconList()
        for item_id, item in sorted(materials.items().items(), key=lambda pair: (pair[1]["name"], pair[0])):
            if item.get("type") in MATERIAL_TYPES or str(item.get("type")).startswith("localSpecialty"):
                self.list.add(f"{item['name']}\n{_stars(item.get('rank', 1))}", materials.icon_url(item_id), item_id,
                              rarity=item.get("rank", 1))
        self.search.textChanged.connect(self.list.filter)
        self.list.itemDoubleClicked.connect(lambda _: self.accept())
        self.body.addWidget(self.search)
        self.body.addWidget(self.list, 1)
        self.body.addWidget(_buttons(self, "Choose"))
        self.search.setFocus()

    def accept(self):
        item = self.list.currentItem()
        if item is None or item.isHidden():
            return
        self.chosen = item.data(Qt.UserRole)
        super().accept()


class ArtifactPicker(Popup):
    """Type to search, then pick an artifact set (for a note's pictures)."""

    def __init__(self, artifacts, parent=None):
        super().__init__(parent, "Add artifact", 460, 600)
        self.chosen = None
        self.search = _search_box("Search artifact sets…  (e.g. Emblem, Codex, NO)", self)
        self.list = _IconList()
        for a in sorted(artifacts, key=lambda a: (-a.rarity, a.name)):
            self.list.add(f"{a.name}\n{_stars(a.rarity)}", a.icon, a.id, rarity=a.rarity)
        self.search.textChanged.connect(self.list.filter)
        self.list.itemDoubleClicked.connect(lambda _: self.accept())
        self.body.addWidget(self.search)
        self.body.addWidget(self.list, 1)
        self.body.addWidget(_buttons(self, "Choose"))
        self.search.setFocus()

    def accept(self):
        item = self.list.currentItem()
        if item is None or item.isHidden():
            return
        self.chosen = item.data(Qt.UserRole)
        super().accept()


MATERIAL_TYPES = {"commonCurrency", "characterEXPMaterial", "weaponEnhancementMaterial", "characterLevelUpMaterial",
                  "characterAscensionMaterial", "characterTalentMaterial", "characterandWeaponEnhancementMaterial",
                  "weaponAscensionMaterial"}  # (and local specialties: "localSpecialty…")


def picture_info(index, picture):
    """(icon url, rarity, name) of a note's picture ({"kind": character / weapon / artifact / material, "id"})."""
    kind, item_id = picture.get("kind"), picture.get("id")
    if kind == "material":
        item = materials.items().get(int(item_id)) or {}
        return materials.icon_url(item_id), item.get("rank", 1), item.get("name", "?")
    pools = {"character": "characters", "weapon": "weapons", "artifact": "artifacts"}
    pool = getattr(index, pools.get(kind, "weapons")) if index else {}
    info = pool.get(item_id) or pool.get(str(item_id)) or (pool.get(int(item_id)) if str(item_id).isdigit() else None)
    return (info.icon, info.rarity, info.name) if info else (None, 1, "?")


def picture_tile(index, picture, size=NOTE_PICTURE):
    """A note's picture on its rarity background, named in its tooltip."""
    url, rarity, name = picture_info(index, picture)
    pic = QLabel()
    pic.setFixedSize(size, size)
    pic.setToolTip(name)
    if url:
        gamedata.load_pixmap(url, lambda pm, pic=pic: pm and pic.setPixmap(_scaled_card(card_pixmap(pm, None, rarity,
                                                                                                     size))))
    return pic


class NoteDialog(Popup):
    """A note on the To Do List: a title, text, and pictures of characters, weapons or materials (click a picture
    to take it off)."""

    def __init__(self, index, note=None, parent=None):
        from PySide6.QtWidgets import QLineEdit, QPlainTextEdit

        super().__init__(parent, "Edit note" if note else "Add note", 520)
        note = note or {}
        self.index = index
        self.pictures = list(note.get("pictures") or [])
        self.body.addWidget(_field_label("TITLE"))
        self.title = QLineEdit(note.get("title", ""), placeholderText="e.g. Farm for Mavuika")
        self.body.addWidget(self.title)
        self.body.addWidget(_field_label("NOTE"))
        self.text = QPlainTextEdit(note.get("text", ""))
        self.text.setPlaceholderText("Anything to remember…")
        self.text.setMinimumHeight(110)
        self.body.addWidget(self.text)
        self.body.addWidget(_field_label("PICTURES"))
        self.picture_row = QWidget()
        self.picture_flow = FlowLayout(self.picture_row, spacing=6)
        self.body.addWidget(self.picture_row)
        adds = QHBoxLayout()
        adds.setSpacing(6)
        for text, slot in (("+ Character", self._add_character), ("+ Weapon", self._add_weapon),
                           ("+ Artifact", self._add_artifact), ("+ Material", self._add_material)):
            btn = QPushButton(text)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setAutoDefault(False)
            btn.clicked.connect(slot)
            adds.addWidget(btn)
        adds.addStretch()
        self.body.addLayout(adds)
        self.body.addSpacing(6)
        self.body.addWidget(_buttons(self, "Save"))
        self._show_pictures()
        self.title.setFocus()

    def _show_pictures(self):
        clear_layout(self.picture_flow)
        if not self.pictures:
            self.picture_flow.addWidget(_muted("None yet"))
        for picture in self.pictures:
            button = QPushButton()
            button.setObjectName("NotePicture")
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedSize(NOTE_PICTURE, NOTE_PICTURE)
            inner = QVBoxLayout(button)
            inner.setContentsMargins(0, 0, 0, 0)
            tile = picture_tile(self.index, picture)
            tile.setAttribute(Qt.WA_TransparentForMouseEvents)
            inner.addWidget(tile)
            button.setToolTip(f"{tile.toolTip()}\nClick to take it off")
            button.clicked.connect(lambda _=False, p=picture: self._remove(p))
            self.picture_flow.addWidget(button)

    def _remove(self, picture):
        self.pictures.remove(picture)
        self._show_pictures()

    def _add(self, kind, item_id):
        if item_id is not None:
            self.pictures.append({"kind": kind, "id": item_id})
            self._show_pictures()

    def _add_character(self):
        if not self.index:
            return
        dialog = CharacterSearchDialog(list(self.index.characters.values()), "", self, title="Add character")
        if dialog.exec():
            self._add("character", dialog.chosen)

    def _add_weapon(self):
        if not self.index:
            return
        dialog = WeaponPicker(list(self.index.weapons.values()), self)
        if dialog.exec():
            self._add("weapon", dialog.chosen)

    def _add_artifact(self):
        if not self.index:
            return
        dialog = ArtifactPicker(list(self.index.artifacts.values()), self)
        if dialog.exec():
            self._add("artifact", dialog.chosen)

    def _add_material(self):
        dialog = MaterialPicker(self)
        if dialog.exec():
            self._add("material", dialog.chosen)

    def values(self):
        return {"title": self.title.text().strip(), "text": self.text.toPlainText().strip(),
                "pictures": self.pictures}


class TodoPage(QWidget):
    message = Signal(str)
    changed = Signal()  # goals added, edited, done or reordered (Home lists the top three)

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.index = None
        self.server = store.get_setting("server", servers.DEFAULT)
        self.tasks = store.get_setting(TASKS_KEY, []) or []
        self.details = {}  # task id -> {"steps", "costs", "days"} or {"error"}
        self._domains_ready = False  # True once the domain schedule is loaded (None: it couldn't be)

        v = QVBoxLayout(self)
        v.setContentsMargins(28, 22, 28, 20)
        v.setSpacing(10)
        head, self.count_label = section_header("To Do List")
        v.addWidget(head)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        for text, slot, tip in (("+ Add Character", self._add_character, "Plan a character's level and talents"),
                                ("+ Add Weapon", self._add_weapon, "Plan a weapon's level"),
                                ("+ Add Note", self._add_note,
                                 "A note of your own, with pictures of characters, weapons or materials")):
            btn = QPushButton(text)
            btn.setObjectName("Primary")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            bar.addWidget(btn)
        bar.addStretch()
        reorder = QPushButton("↕  Reorder")
        reorder.setCursor(Qt.PointingHandCursor)
        reorder.setToolTip("Drag and drop the goals into priority order (the top three show on Home)")
        reorder.clicked.connect(self._reorder)
        bar.addWidget(reorder)
        v.addLayout(bar)

        columns = QHBoxLayout()
        columns.setSpacing(12)
        self.list_scroll = QScrollArea()
        self.list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # the cards wrap instead
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        self.list_layout = QVBoxLayout(host)
        self.list_layout.setContentsMargins(0, 0, 8, 0)
        self.list_layout.setSpacing(8)
        self.list_scroll.setWidget(host)
        columns.addWidget(self.list_scroll, 1)

        self.summary_scroll = QScrollArea()
        self.summary_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.summary_scroll.setWidgetResizable(True)
        self.summary_scroll.setFrameShape(QFrame.NoFrame)
        self.summary_scroll.setFixedWidth(SUMMARY_WIDTH)
        side = QWidget()
        self.summary = QVBoxLayout(side)
        self.summary.setContentsMargins(0, 0, 8, 0)
        self.summary.setSpacing(8)
        self.summary_scroll.setWidget(side)
        columns.addWidget(self.summary_scroll)
        v.addLayout(columns, 1)

    # ----- outside -----
    def set_index(self, index):
        self.index = index
        if not self._domains_ready:
            def ready(_result, error):
                self._domains_ready = None if error else True
                self._render()
                self.changed.emit()

            gamedata.run_async(materials.domains, ready)
        self._load_all()

    def set_server(self, server):
        self.server = server
        self._render()

    def weekday(self):
        return servers.game_weekday(self.server)

    def top_tasks(self, n=3):
        """[(task, info, goal text, detail)] for Home: the first n in Home's order."""
        out = []
        for task in home_order(self.tasks, self.details, self.weekday()):
            if task["kind"] == "note":  # its first picture (a Dull Blade without one), its first line of text
                info = self._note_info(task)
                if info:
                    text = (task.get("text") or "").strip()
                    out.append((task, info, text.splitlines()[0] if text else "Note", {}))
                    if len(out) == n:
                        break
                continue
            info = self._info(task)
            if info is None:
                continue
            detail = self.details.get(task["id"]) or {}
            out.append((task, info, goal_text(task, detail.get("steps")), detail))
            if len(out) == n:
                break
        return out

    # ----- data -----
    def _save(self):
        self.store.set_setting(TASKS_KEY, self.tasks)
        self.changed.emit()

    def _info(self, task):
        if not self.index or task["kind"] == "note":
            return None
        pool = self.index.characters if task["kind"] == "character" else self.index.weapons
        item = task["item"]
        return pool.get(item) or pool.get(str(item)) or (pool.get(int(item)) if str(item).isdigit() else None)

    def _load_all(self):
        for task in self.tasks:
            if task["id"] not in self.details and task["kind"] != "note":
                self._load(task)
        self._render()

    def _load(self, task):
        info = self._info(task)
        rarity = getattr(info, "rarity", 4)

        def work(task=task):
            if task["kind"] == "character":
                steps = materials.level_steps(materials.character(task["item"]))
                costs = materials.character_costs(task["item"], *task["level"], task["talents"])
            else:
                steps = materials.level_steps(materials.weapon(task["item"]))
                costs = materials.weapon_costs(task["item"], rarity, *task["level"])
            materials.domains()
            return {"steps": steps, "costs": costs, "days": materials.domain_days(costs)}

        def done(result, error, task_id=task["id"]):
            self.details[task_id] = result or {"error": str(error)}
            self._render()
            self.changed.emit()
            if result:  # which gems its bosses drop, for the inventory popup (a download the first time)
                bosses = boss_materials(materials.total(result["costs"]))
                gamedata.run_async(lambda: [materials.boss_drops(b) for b in bosses], lambda *_: None)

        gamedata.run_async(work, done)

    # ----- adding, editing, finishing -----
    def _add_character(self):
        if not self.index:
            self.message.emit("Game data is still loading…")
            return
        dialog = CharacterSearchDialog(list(self.index.characters.values()), "", self, title="Add character")
        if dialog.exec() and dialog.chosen:
            self._new_goal("character", dialog.chosen)

    def _add_weapon(self):
        if not self.index:
            self.message.emit("Game data is still loading…")
            return
        dialog = WeaponPicker(list(self.index.weapons.values()), self)
        if dialog.exec() and dialog.chosen:
            self._new_goal("weapon", dialog.chosen)

    def _add_note(self):
        dialog = NoteDialog(self.index, None, self)
        if dialog.exec():
            note = {"id": uuid.uuid4().hex, "kind": "note", **dialog.values()}
            self.tasks.append(note)
            self._save()
            self._render()
            self.message.emit("Added a note to the To Do List")

    def _note_info(self, task):
        """What Home shows a note as (name, icon, rarity, like a character's or weapon's info)."""
        from types import SimpleNamespace

        if not self.index:
            return None
        pictures = task.get("pictures") or []
        if pictures:
            url, rarity, _ = picture_info(self.index, pictures[0])
        else:
            blade = next((w for w in self.index.weapons.values() if w.name == "Dull Blade"), None)
            url, rarity = (blade.icon, blade.rarity) if blade else (None, 1)
        return SimpleNamespace(name=self._task_name(task), icon=url, rarity=rarity, element=None)

    def _task_name(self, task):
        if task["kind"] == "note":
            return task.get("title") or "Note"
        info = self._info(task)
        return info.name if info else "this goal"

    def _new_goal(self, kind, item_id):
        """Read the item's levels (a download the first time), then ask for the goal."""
        self.message.emit("Reading level-up data…")

        def work():
            detail = materials.character(item_id) if kind == "character" else materials.weapon(item_id)
            return materials.level_steps(detail)

        def done(steps, error):
            if error or not steps:
                self.message.emit(f"Couldn't read the level-up data: {error}")
                return
            self.message.emit("")
            build = self.store.my_build(item_id) if kind == "character" else None
            talents = [[(build or {}).get(f"talent{n}") or 1, 10] for n in (1, 2, 3)]
            task = {"id": uuid.uuid4().hex, "kind": kind, "item": item_id, "level": [0, len(steps) - 1],
                    "talents": talents if kind == "character" else []}
            if self._edit(task, steps):
                self.tasks.append(task)
                self._save()
                self._load(task)
                info = self._info(task)
                self.message.emit(f"Added {info.name if info else 'goal'} to the To Do List")

        gamedata.run_async(work, done)

    def _edit(self, task, steps):
        info = self._info(task)
        dialog = GoalDialog(info.name if info else "Goal", steps, task, task["kind"] == "character", self)
        if not dialog.exec():
            return False
        task["level"], talents = dialog.values()
        if task["kind"] == "character":
            task["talents"] = talents
        return True

    def _edit_existing(self, task):
        if task["kind"] == "note":
            dialog = NoteDialog(self.index, task, self)
            if dialog.exec():
                task.update(dialog.values())
                self._save()
                self._render()
            return
        steps = (self.details.get(task["id"]) or {}).get("steps")
        if not steps:
            return
        if self._edit(task, steps):
            self.details.pop(task["id"], None)
            self._save()
            self._load(task)

    def _finish(self, task):
        name = self._task_name(task)
        if not confirm(self, "Done", f"Mark {name} as done and take it off the To Do List?", "Done"):
            return
        self.tasks = [t for t in self.tasks if t["id"] != task["id"]]
        self.details.pop(task["id"], None)
        self._save()
        self._render()
        self.message.emit(f"{name}: done")

    def _reorder(self):
        if len(self.tasks) < 2:
            self.message.emit("Add at least two goals to set their priority")
            return
        rows = []
        for n, task in enumerate(self.tasks, 1):
            if task["kind"] == "note":  # (its first picture, if any)
                pictures = task.get("pictures") or []
                url, rarity, _ = picture_info(self.index, pictures[0]) if pictures else (None, 1, "")
                rows.append((task["id"], f"📝  {self._task_name(task)}", url, rarity))
                continue
            info = self._info(task)
            rows.append((task["id"], f"{info.name if info else '?'}", getattr(info, "icon", None), getattr(info, "rarity", 1)))
        dialog = ReorderDialog(rows, self)
        if dialog.exec():
            by_id = {t["id"]: t for t in self.tasks}
            self.tasks = [by_id[i] for i in dialog.order() if i in by_id]
            self._save()
            self._render()

    # ----- drawing -----
    def _render(self):
        # rebuilt unseen and put back where it was scrolled to (it used to flash a one-column list)
        bars = [self.list_scroll.verticalScrollBar(), self.summary_scroll.verticalScrollBar()]
        scrolled = [bar.value() for bar in bars]
        self.setUpdatesEnabled(False)
        try:
            clear_layout(self.list_layout)
            clear_layout(self.summary)
            self.count_label.setText(f"{len(self.tasks)} goal{'s' if len(self.tasks) != 1 else ''}")
            weekday = self.weekday()
            # what you have goes to the goals in priority order: each card shows what it still needs
            # (and leftovers crafted up a tier where that covers what a goal still needs)
            self._covered, self._crafted = allocate(self.tasks, self.details,
                                                    self.store.get_setting(OWNED_KEY, {}) or {})
            if not self.tasks:
                empty = QLabel("Nothing planned yet. Add a character or a weapon to see the materials they need.")
                empty.setObjectName("EndGameMuted")
                empty.setWordWrap(True)
                self.list_layout.addWidget(empty)
            else:  # the goals as cards, as many to a row as fit
                cards = [self._card(n, task, weekday) for n, task in enumerate(self.tasks, 1)]
                margins = self.list_layout.contentsMargins()
                room = self.list_scroll.viewport().width() - margins.left() - margins.right()
                self.list_layout.addWidget(CardGrid(cards, room))
            self.list_layout.addStretch()
            self._render_summary(weekday)
            self.layout().activate()
        finally:
            self.setUpdatesEnabled(True)
        for bar, value in zip(bars, scrolled):
            QTimer.singleShot(0, lambda bar=bar, value=value: bar.setValue(value))

    def _set_owned(self, item_id, context=()):
        """Inventory popup for a material (its family, or its boss's drops); saving updates every card and the
        summary. context: the goal's materials, when it was clicked in a goal."""
        owned = self.store.get_setting(OWNED_KEY, {}) or {}
        dialog = InventoryDialog(item_id, owned, self, context)
        if dialog.exec():
            for material, count in dialog.values().items():
                if count:
                    owned[str(material)] = count
                else:
                    owned.pop(str(material), None)
            self.store.set_setting(OWNED_KEY, owned)
            self._render()

    def _card(self, n, task, weekday):
        """A goal's card (like Genshin Center's planner): its name on a band of its rarity's colour, the picture
        with the levels and talents beside it, then the materials it needs, counts on top."""
        if task["kind"] == "note":
            return self._note_card(n, task)
        info = self._info(task)
        detail = self.details.get(task["id"]) or {}
        card = QFrame()
        card.setObjectName("TodoCard")
        card.setMinimumWidth(CARD_WIDTH)  # (a row's cards share its width)
        v = QVBoxLayout(card)
        v.setContentsMargins(0, 0, 0, 8)
        v.setSpacing(6)
        band = QFrame()
        band.setObjectName("TodoBand")
        top, bottom = RARITY_COLORS.get(getattr(info, "rarity", 4), RARITY_COLORS[4])
        band.setStyleSheet(f"#TodoBand {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {top}, stop:1 {bottom}); /* fixed */ }}")
        head = QHBoxLayout(band)
        head.setContentsMargins(10, 6, 10, 6)
        rank = QLabel(f"#{n}")
        rank.setObjectName("TodoRank")
        rank.setToolTip("Priority (Reorder to change it)")
        name = QLabel(info.name if info else "Unknown")
        name.setObjectName("TodoName")
        name.setAlignment(Qt.AlignCenter)
        head.addWidget(rank)
        head.addWidget(name, 1)
        head.addSpacing(rank.sizeHint().width())  # keeps the name centred
        v.addWidget(band)

        body = QHBoxLayout()
        body.setContentsMargins(10, 0, 10, 0)
        body.setSpacing(10)
        pic = QLabel()
        pic.setFixedSize(PORTRAIT, PORTRAIT)
        if info is not None:
            element = getattr(info, "element", None)

            def with_element(element_pm, pic=pic, info=info):
                gamedata.load_pixmap(info.icon, lambda pm: pic.setPixmap(_card2(pm, element_pm, info.rarity)))

            if element:
                gamedata.load_pixmap(gamedata.element_icon_url(element), with_element)
            else:
                with_element(None)
        body.addStretch()  # (the picture and its goals centred in the card)
        body.addWidget(pic, 0, Qt.AlignTop)
        goals = QGridLayout()
        goals.setHorizontalSpacing(8)
        goals.setVerticalSpacing(2)
        steps = detail.get("steps")
        row = 0
        goals.addWidget(_goal_heading("Levels"), row, 0, 1, 4)
        row += 1
        a, b = task["level"]
        if steps:
            row = _goal_row(goals, row, materials.step_label(steps, a), materials.step_label(steps, b), "")
        if task["kind"] == "character":
            goals.addWidget(_goal_heading("Talents"), row, 0, 1, 4)
            row += 1
            for label, (x, y) in zip(("Attack", "Skill", "Burst"), task.get("talents") or []):
                row = _goal_row(goals, row, str(x), str(y), label)
        goals.setRowStretch(row, 1)
        body.addLayout(goals)
        body.addStretch()
        v.addLayout(body)

        for (domain, kind), days in sorted((detail.get("days") or {}).items()):
            today = weekday in days
            label = QLabel(f"{_kind_name(kind)}  ·  {_short_domain(domain)}  ·  "
                           + ("open today" if today else "/".join(SHORT_DAYS[d] for d in sorted(days) if d != 6)))
            label.setObjectName("DomainOpen" if today else "EndGameMuted")
            label.setAlignment(Qt.AlignCenter)
            label.setToolTip(domain)
            label.setWordWrap(True)
            v.addWidget(label)
        rule = QFrame()
        rule.setObjectName("HalfDivider")
        rule.setFixedHeight(1)
        v.addWidget(rule)
        mats = QVBoxLayout()
        mats.setContentsMargins(10, 0, 10, 0)
        if "costs" in detail:
            total = materials.total(detail["costs"])
            if any(total.values()):  # in rows by kind; what you have (by priority) is taken off, ✓ once covered
                covered = getattr(self, "_covered", {}).get(task["id"], {})
                crafted = getattr(self, "_crafted", {}).get(task["id"], {})
                mats.addWidget(material_grid(total, task["kind"], covered, self._set_owned, crafted))
        elif detail.get("error"):
            mats.addWidget(_muted("Couldn't read this one's materials (no data yet for unreleased items)."))
        else:
            mats.addWidget(_muted("Working out the materials…"))
        v.addLayout(mats)
        v.addStretch()
        buttons = QHBoxLayout()
        buttons.setContentsMargins(10, 0, 10, 0)
        buttons.setSpacing(6)
        buttons.addStretch()
        edit = QPushButton("Edit")
        edit.setCursor(Qt.PointingHandCursor)
        edit.clicked.connect(lambda _=False, t=task: self._edit_existing(t))
        done = QPushButton("\u2713  Done")
        done.setCursor(Qt.PointingHandCursor)
        done.setToolTip("Finished: take it off the list")
        done.clicked.connect(lambda _=False, t=task: self._finish(t))
        buttons.addWidget(edit)
        buttons.addWidget(done)
        v.addLayout(buttons)
        return card

    def _note_card(self, n, task):
        """A note's card: its title on a band, its text, its pictures, Edit and Done (in the goals' priority order)."""
        card = QFrame()
        card.setObjectName("TodoCard")
        card.setMinimumWidth(CARD_WIDTH)
        v = QVBoxLayout(card)
        v.setContentsMargins(0, 0, 0, 8)
        v.setSpacing(8)
        band = QFrame()
        band.setObjectName("TodoBand")
        band.setStyleSheet("#TodoBand { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3a4150, "
                           "stop:1 #5a6478); /* fixed */ }")
        head = QHBoxLayout(band)
        head.setContentsMargins(10, 6, 10, 6)
        rank = QLabel(f"#{n}")
        rank.setObjectName("TodoRank")
        rank.setToolTip("Priority (Reorder to change it)")
        name = QLabel(f"📝  {self._task_name(task)}")
        name.setObjectName("TodoName")
        name.setAlignment(Qt.AlignCenter)
        head.addWidget(rank)
        head.addWidget(name, 1)
        head.addSpacing(rank.sizeHint().width())
        v.addWidget(band)
        # the pictures (centred rows), a divider, then the text (centred)
        if task.get("pictures"):
            pictures = QGridLayout()
            pictures.setContentsMargins(12, 2, 12, 0)
            pictures.setSpacing(6)
            per_row = max(1, (CARD_WIDTH - 24 + 6) // (PORTRAIT + 6))
            for i, picture in enumerate(task["pictures"]):
                if i % per_row == 0:
                    row = QHBoxLayout()
                    row.setSpacing(6)
                    row.addStretch()
                    pictures.addLayout(row, i // per_row, 0)
                row.addWidget(picture_tile(self.index, picture, PORTRAIT))  # (as big as a goal's picture)
                if i % per_row == per_row - 1 or i == len(task["pictures"]) - 1:
                    row.addStretch()
            v.addLayout(pictures)
        if task.get("pictures") and task.get("text"):
            rule = QFrame()
            rule.setObjectName("HalfDivider")
            rule.setFixedHeight(1)
            v.addWidget(rule)
        if task.get("text"):
            text = QLabel(task["text"])
            text.setObjectName("NoteText")
            text.setWordWrap(True)
            text.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
            text.setContentsMargins(12, 0, 12, 0)
            v.addWidget(text)
        v.addStretch()
        buttons = QHBoxLayout()
        buttons.setContentsMargins(10, 0, 10, 0)
        buttons.setSpacing(6)
        buttons.addStretch()
        edit = QPushButton("Edit")
        edit.setCursor(Qt.PointingHandCursor)
        edit.clicked.connect(lambda _=False, t=task: self._edit_existing(t))
        done = QPushButton("✓  Done")
        done.setCursor(Qt.PointingHandCursor)
        done.setToolTip("Finished: take it off the list")
        done.clicked.connect(lambda _=False, t=task: self._finish(t))
        buttons.addWidget(edit)
        buttons.addWidget(done)
        v.addLayout(buttons)
        return card

    def _render_summary(self, weekday):
        box, v = _panel("ALL MATERIALS")
        total = {}
        needed_domains = {}
        for task in self.tasks:
            detail = self.details.get(task["id"]) or {}
            for item_id, count in materials.total(detail.get("costs") or {}).items():
                total[item_id] = total.get(item_id, 0) + count
            info = self._info(task)
            for key in detail.get("days") or {}:
                needed_domains.setdefault(key[0], []).append(info.name if info else "?")
        if total:
            v.addWidget(_muted("Click a material to enter how many you have: the counts show what's still needed."))
            owned = self.store.get_setting(OWNED_KEY, {}) or {}
            crafted = {}
            for made in getattr(self, "_crafted", {}).values():
                for item_id, n in made.items():
                    crafted[item_id] = crafted.get(item_id, 0) + n
            v.addWidget(materials_flow(total, owned, self._set_owned, crafted=crafted))
        else:
            v.addWidget(_muted("Add goals to see what they need altogether."))
        self.summary.addWidget(box)

        box, v = _panel(f"TODAY'S DOMAINS  ·  {DAY_NAMES[weekday].upper()}")
        try:
            opened = materials.open_domains(weekday) if self._domains_ready else []
        except Exception:
            opened = []
        if not opened:
            v.addWidget(_muted("Loading…" if self._domains_ready is False else "Couldn't load the domain schedule."))
        if weekday == 6:
            v.addWidget(_muted("Sunday: every domain is open."))
        # the domains your goals need first
        opened.sort(key=lambda d: (d[0] not in needed_domains, d[1], d[0]))
        for domain, kind, item_ids in opened:
            if weekday == 6 and domain not in needed_domains:
                continue
            row = QFrame()
            row.setObjectName("DomainRow")
            row.setProperty("needed", "true" if domain in needed_domains else "false")
            h = QHBoxLayout(row)
            h.setContentsMargins(6, 4, 8, 4)
            h.setSpacing(6)
            h.addWidget(_icon(item_ids[0], 36))  # its best material
            text = QVBoxLayout()
            text.setSpacing(1)
            title = QLabel(_family(item_ids))  # the materials it drops: "Diligence", "Guyun"
            title.setStyleSheet("font-weight: 700;")
            title.setWordWrap(True)  # (a long name wraps instead of widening the panel)
            title.setToolTip("\n".join(materials.name(i) for i in reversed(item_ids)))
            text.addWidget(title)
            what = f"{_kind_name(kind)}  ·  {_short_domain(domain)}"
            if domain in needed_domains:
                what += "  ·  for " + ", ".join(sorted(set(needed_domains[domain])))
            line = _muted(what)
            line.setToolTip(domain)
            text.addWidget(line)
            h.addLayout(text, 1)
            v.addWidget(row)
        self.summary.addWidget(box)
        self.summary.addStretch()


def _goal_heading(text):
    label = QLabel(text)
    label.setObjectName("GoalHeading")
    return label


def _goal_row(grid, row, start, end, what):
    """"1  →  90" (and what it is: Attack, Skill, Burst) in the card's goals; returns the next row."""
    for col, text, name in ((0, start, "GoalValue"), (1, "\u2192", "GoalArrow"), (2, end, "GoalValue"), (3, what, "GoalWhat")):
        label = QLabel(text)
        label.setObjectName(name)
        grid.addWidget(label, row, col)
    grid.setColumnStretch(3, 1)
    return row + 1


def _kind_name(kind):
    return "Talent books" if kind == "talent" else "Weapon ascension"


def _short_domain(domain):
    return domain.replace("Domain of Mastery: ", "").replace("Domain of Forgery: ", "")


def _family(item_ids):
    """The name a domain's materials go by: its best one's ("Philosophies of Diligence")."""
    return materials.name(item_ids[0]) if item_ids else ""


class CardGrid(QWidget):
    """The goals' cards (each at least CARD_WIDTH wide), as many to a row as fit, sharing the row's width."""

    def __init__(self, cards, width=0):
        """width: the room it will have (so it starts with the right columns, not one, and doesn't flicker)."""
        super().__init__()
        self.cards = cards
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(8)
        self.grid.setAlignment(Qt.AlignTop)
        self.grid.setSizeConstraint(QLayout.SetNoConstraint)
        self.columns = 0
        self._arrange(self._columns_for(width))

    def _columns_for(self, width):
        spacing = self.grid.spacing()
        return max(1, (width + spacing) // (CARD_WIDTH + spacing))

    def minimumSizeHint(self):
        return QSize(CARD_WIDTH, super().minimumSizeHint().height())

    def sizeHint(self):
        return QSize(CARD_WIDTH, super().sizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange(self._columns_for(event.size().width()))

    def _arrange(self, columns):
        columns = min(columns, max(1, len(self.cards)))
        if columns == self.columns:
            return
        self.columns = columns
        for card in self.cards:
            self.grid.removeWidget(card)
        for n, card in enumerate(self.cards):
            self.grid.addWidget(card, n // columns, n % columns)
        for c in range(len(self.cards) + 1):  # the cards fill the row between them
            self.grid.setColumnStretch(c, 1 if c < columns else 0)


def _card2(pm, element_pm, rarity):
    card = card_pixmap(pm, element_pm, rarity, PORTRAIT)
    card.setDevicePixelRatio(2)
    return card


def _icon(item_id, size):
    pic = QLabel()
    pic.setFixedSize(size, size)
    pic.setToolTip(materials.name(item_id))
    rank = (materials.items().get(item_id) or {}).get("rank", 1)
    url = materials.icon_url(item_id)
    if url:
        gamedata.load_pixmap(url, lambda pm: pic.setPixmap(_scaled(card_pixmap(pm, None, rank, size))))
    return pic


def _scaled(pm):
    pm.setDevicePixelRatio(2)
    return pm


def _muted(text):
    label = QLabel(text)
    label.setObjectName("EndGameMuted")
    label.setWordWrap(True)
    return label


def _panel(title):
    box = QFrame()
    box.setObjectName("TodoCard")
    v = QVBoxLayout(box)
    v.setContentsMargins(10, 8, 10, 10)
    v.setSpacing(6)
    head = QLabel(title)
    head.setObjectName("FieldLabel")
    v.addWidget(head)
    return box, v
