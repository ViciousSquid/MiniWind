"""
Property-Manager tabs for authoring the RPG *in the editor* — no JSON by hand.

Three factories, registered via ``EditorAPI.register_property_tab``:

* :func:`make_inventory_tab` — an NPC's item stacks (add/remove, editable fields).
* :func:`make_dialogue_tab`  — an NPC's branching dialogue tree, including
  per-response **conditions** and **actions** (start/complete quests, give items,
  open trade, join a guild…) and per-node on-enter actions, using the small
  human-writable grammar in :mod:`game.rpg.authoring`.
* :func:`make_quests_tab`    — quests authored on the ``GameSettings`` entity: a
  full quest (id, name, giver, rewards and staged journal) that the game loads at
  play start, so a level can add or replace quests without any code.

All Qt imports are local so a headless/player process never imports PyQt5. Each
factory returns a plain "not available" label if Qt is missing rather than raising.
"""

from __future__ import annotations

import json

from .rpg import inventory as inv
from .rpg import authoring


def _qt():
    from PyQt5 import QtWidgets, QtCore
    return QtWidgets, QtCore


def _hint_label(QtWidgets, text):
    """A small, word-wrapped help label sized in *points* (relative to the app
    font) rather than px, so it scales correctly on high-DPI displays."""
    lbl = QtWidgets.QLabel(text)
    lbl.setWordWrap(True)
    f = lbl.font()
    f.setPointSizeF(max(7.0, f.pointSizeF() - 1.0))
    lbl.setFont(f)
    lbl.setStyleSheet("color:#9a9;")
    return lbl


# ===========================================================================
# Inventory editor
# ===========================================================================
def make_appearance_tab(thing):
    """Pick the head sprite an NPC/creature uses (a single billboard, no
    animation). '(random)' lets the game assign a head never used by the player.
    Setting a head updates the entity's sprite immediately."""
    try:
        QtWidgets, QtCore = _qt()
    except Exception:  # pragma: no cover
        return None
    import os
    from PyQt5 import QtGui
    from .rpg import heads

    class Tab(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.thing = thing
            v = QtWidgets.QVBoxLayout(self)
            v.addWidget(_hint_label(
                QtWidgets, "This NPC's sprite is a single head image (no animation "
                "frames). Choose one, or leave (random) to let the game assign a "
                "head that is never the player's."))
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel("Head:"))
            self.combo = QtWidgets.QComboBox()
            self.combo.addItem("(random)", "")
            for hid in heads.HEAD_IDS:
                self.combo.addItem(hid, hid)
            cur = str(thing.properties.get("head", "") or "")
            i = self.combo.findData(cur)
            self.combo.setCurrentIndex(i if i >= 0 else 0)
            self.combo.currentIndexChanged.connect(self._changed)
            row.addWidget(self.combo, 1)
            v.addLayout(row)
            self.preview = QtWidgets.QLabel()
            self.preview.setFixedSize(140, 140)
            self.preview.setAlignment(QtCore.Qt.AlignCenter)
            self.preview.setStyleSheet(
                "background:#1f2124; border:1px solid #555; border-radius:6px; color:#9aa;")
            v.addWidget(self.preview, 0, QtCore.Qt.AlignHCenter)
            v.addStretch(1)
            self._refresh()

        def _repo_root(self):
            return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

        def _changed(self, *_):
            hid = self.combo.currentData() or ""
            self.thing.properties["head"] = hid
            if hid in heads.HEAD_IDS:
                path = heads.head_path(hid)
                # Living/attacking sprites follow the head; there is no custom
                # death sprite (a slain actor shows its head + dead.png overlay).
                for k in ("custom_idle", "custom_shoot"):
                    self.thing.properties[k] = path
            self.thing.properties.pop("custom_dead", None)
            # Drop cached sprites so the viewport shows the new head.
            try:
                from editor.things import Monster
                Monster.clear_sprite_cache()
            except Exception:
                pass
            self._refresh()

        def _refresh(self):
            hid = str(self.thing.properties.get("head", "") or "")
            pm = None
            if hid in heads.HEAD_IDS:
                p = os.path.join(self._repo_root(), heads.head_path(hid))
                if os.path.isfile(p):
                    q = QtGui.QPixmap(p)
                    if not q.isNull():
                        pm = q.scaled(132, 132, QtCore.Qt.KeepAspectRatio,
                                      QtCore.Qt.SmoothTransformation)
            if pm is not None:
                self.preview.setPixmap(pm)
            else:
                self.preview.setText(hid or "(random head\nassigned at play)")

    return Tab()


def make_inventory_tab(thing):
    try:
        QtWidgets, QtCore = _qt()
    except Exception:  # pragma: no cover
        return None
    return _InventoryTab(thing, QtWidgets, QtCore)


def _InventoryTab(thing, QtWidgets, QtCore):
    """A grid of item icons with drag-and-drop reordering, an icon-based item
    picker, and an inline detail editor — replacing the old spreadsheet table."""
    Qt = QtCore.Qt
    try:
        from game import item_icons
    except Exception:  # pragma: no cover
        item_icons = None
    try:
        from game.rpg import items as itemdb
    except Exception:  # pragma: no cover
        itemdb = None

    ROLE_STACK = int(Qt.UserRole)
    ICON = 56

    def _badged_icon(stack):
        """QIcon for a stack, with a small quantity badge when qty > 1."""
        from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QPen
        pm = None
        if item_icons is not None:
            pm = item_icons.icon_pixmap(stack.get("id"), stack, ICON)
        if pm is None:
            pm = QPixmap(ICON, ICON)
            pm.fill(QColor(70, 72, 82))
        qty = int(stack.get("qty", 1) or 1)
        # Rarity ring
        rgb = None
        if itemdb is not None:
            try:
                if itemdb.rarity_of(stack) != itemdb.COMMON:
                    rgb = itemdb.rarity_rgb(stack)
            except Exception:
                rgb = None
        if qty > 1 or rgb:
            canvas = QPixmap(ICON, ICON)
            canvas.fill(Qt.transparent)
            p = QPainter(canvas)
            p.setRenderHint(QPainter.Antialiasing, True)
            if rgb:
                p.setPen(QPen(QColor(*rgb), 2))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(1, 1, ICON - 2, ICON - 2, 6, 6)
            p.drawPixmap((ICON - pm.width()) // 2, (ICON - pm.height()) // 2, pm)
            if qty > 1:
                txt = f"×{qty}"
                f = QFont(); f.setPointSize(9); f.setBold(True); p.setFont(f)
                fm = p.fontMetrics(); tw = fm.horizontalAdvance(txt) + 6
                p.setBrush(QColor(20, 20, 26, 220)); p.setPen(Qt.NoPen)
                p.drawRoundedRect(ICON - tw - 1, ICON - 17, tw, 15, 4, 4)
                p.setPen(QColor(245, 224, 150))
                p.drawText(ICON - tw + 2, ICON - 5, txt)
            p.end()
            return QIcon(canvas)
        return QIcon(pm)

    def _compact_font():
        """A smaller-than-default font so item names stay readable and wrap to
        two lines in the icon grids (the labels were oversized on high-DPI)."""
        f = QtWidgets.QApplication.font()
        pt = f.pointSizeF()
        f.setPointSizeF(max(7.0, (pt if pt > 0 else 9.0) - 2.0))
        return f

    class InventoryGrid(QtWidgets.QListWidget):
        orderChanged = QtCore.pyqtSignal()

        def __init__(self):
            super().__init__()
            self.setFont(_compact_font())
            self.setViewMode(QtWidgets.QListView.IconMode)
            self.setIconSize(QtCore.QSize(ICON, ICON))
            # Cell wide/tall enough for the icon + two wrapped lines of the name.
            self.setGridSize(QtCore.QSize(96, ICON + 46))
            self.setResizeMode(QtWidgets.QListView.Adjust)
            self.setMovement(QtWidgets.QListView.Snap)
            self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
            self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
            self.setSpacing(6)
            self.setWordWrap(True)
            self.setUniformItemSizes(True)
            self.setStyleSheet(
                "QListWidget { background:#2b2d33; border:1px solid #3a3d44; border-radius:6px; }"
                "QListWidget::item { color:#d8dae0; padding:4px; border-radius:6px; }"
                "QListWidget::item:selected { background:#3d5f5d; color:#fff; }")

        def dropEvent(self, e):
            super().dropEvent(e)
            self.orderChanged.emit()

    class Tab(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.thing = thing
            self._loading = False
            root = QtWidgets.QVBoxLayout(self)
            root.setSpacing(6)

            root.addWidget(_hint_label(
                QtWidgets, "Drag icons to reorder. Add items from the catalogue; "
                "select one to edit its quantity below."))

            self.grid = InventoryGrid()
            self.grid.orderChanged.connect(self._on_reordered)
            self.grid.currentItemChanged.connect(lambda *_: self._sync_detail())
            self.grid.itemDoubleClicked.connect(lambda *_: self._focus_qty())
            root.addWidget(self.grid, 1)

            btns = QtWidgets.QHBoxLayout()
            add = QtWidgets.QPushButton("＋ Add Item…")
            rem = QtWidgets.QPushButton("🗑 Remove")
            add.clicked.connect(self._pick_item)
            rem.clicked.connect(self._remove)
            btns.addWidget(add); btns.addWidget(rem); btns.addStretch(1)
            root.addLayout(btns)

            # Inline detail editor for the selected stack.
            self.detail = QtWidgets.QGroupBox("Selected item")
            dl = QtWidgets.QFormLayout(self.detail)
            self.d_name = QtWidgets.QLineEdit()
            self.d_qty = QtWidgets.QSpinBox(); self.d_qty.setRange(1, 9999)
            self.d_value = QtWidgets.QSpinBox(); self.d_value.setRange(0, 9_999_999)
            self.d_name.editingFinished.connect(self._edit_name)
            self.d_qty.valueChanged.connect(self._edit_qty)
            self.d_value.valueChanged.connect(self._edit_value)
            dl.addRow("Name", self.d_name)
            dl.addRow("Quantity", self.d_qty)
            dl.addRow("Value", self.d_value)
            root.addWidget(self.detail)

            self.summary = QtWidgets.QLabel("")
            self.summary.setStyleSheet("color:#9aa; padding:2px;")
            root.addWidget(self.summary)

            self._reload()

        # -- data <-> view ------------------------------------------------
        def _reload(self):
            self._loading = True
            self.grid.clear()
            for stack in inv.get_inventory(self.thing):
                self._add_tile(stack)
            self._loading = False
            self._sync_detail()
            self._update_summary()

        def _add_tile(self, stack):
            name = stack.get("name") or str(stack.get("id", "item")).replace("_", " ").title()
            it = QtWidgets.QListWidgetItem(_badged_icon(stack), name)
            it.setData(ROLE_STACK, stack)
            it.setToolTip(self._tooltip(stack))
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            # Explicit size hint so the name wraps at the cell width (IconMode
            # otherwise wraps at the icon width and clips longer names).
            it.setSizeHint(QtCore.QSize(90, ICON + 44))
            self.grid.addItem(it)
            return it

        def _refresh_tile(self, it):
            stack = it.data(ROLE_STACK)
            it.setIcon(_badged_icon(stack))
            it.setText(stack.get("name") or str(stack.get("id", "")).replace("_", " ").title())
            it.setToolTip(self._tooltip(stack))

        def _tooltip(self, stack):
            return (f"<b>{stack.get('name','?')}</b><br>id: {stack.get('id','?')}<br>"
                    f"type: {stack.get('type','?')} &nbsp; qty: {stack.get('qty',1)}<br>"
                    f"value: {stack.get('value',0)} &nbsp; weight: {stack.get('weight',0)}")

        def _on_reordered(self):
            # Rebuild the backing list to match the on-screen tile order.
            items = inv.get_inventory(self.thing)
            items[:] = [self.grid.item(i).data(ROLE_STACK)
                        for i in range(self.grid.count())]
            self._update_summary()

        # -- actions ------------------------------------------------------
        def _pick_item(self):
            stack = _ItemPicker(self, QtWidgets, QtCore, item_icons, itemdb, _badged_icon).choose()
            if stack is not None:
                inv.get_inventory(self.thing).append(stack)
                it = self._add_tile(stack)
                self.grid.setCurrentItem(it)
                self._update_summary()

        def _remove(self):
            it = self.grid.currentItem()
            if it is None:
                return
            stack = it.data(ROLE_STACK)
            items = inv.get_inventory(self.thing)
            try:
                items.remove(stack)
            except ValueError:
                pass
            self.grid.takeItem(self.grid.row(it))
            self._sync_detail()
            self._update_summary()

        def _sync_detail(self):
            it = self.grid.currentItem()
            self.detail.setEnabled(it is not None)
            self._loading = True
            if it is None:
                self.d_name.clear(); self.d_qty.setValue(1); self.d_value.setValue(0)
            else:
                s = it.data(ROLE_STACK)
                self.d_name.setText(str(s.get("name", "")))
                self.d_qty.setValue(int(s.get("qty", 1) or 1))
                self.d_value.setValue(int(s.get("value", 0) or 0))
            self._loading = False

        def _focus_qty(self):
            self.d_qty.setFocus(); self.d_qty.selectAll()

        def _cur_stack(self):
            it = self.grid.currentItem()
            return (it, it.data(ROLE_STACK)) if it else (None, None)

        def _edit_name(self):
            if self._loading:
                return
            it, s = self._cur_stack()
            if s is not None:
                s["name"] = self.d_name.text(); self._refresh_tile(it)

        def _edit_qty(self, v):
            if self._loading:
                return
            it, s = self._cur_stack()
            if s is not None:
                s["qty"] = int(v); self._refresh_tile(it); self._update_summary()

        def _edit_value(self, v):
            if self._loading:
                return
            it, s = self._cur_stack()
            if s is not None:
                s["value"] = int(v); self._refresh_tile(it); self._update_summary()

        def _update_summary(self):
            items = inv.get_inventory(self.thing)
            self.summary.setText(
                f"{len(items)} stack(s)   weight {inv.total_weight(items):.1f}   "
                f"value {inv.total_value(items)}")

    return Tab()


def _ItemPicker(parent, QtWidgets, QtCore, item_icons, itemdb, badged):
    """A modal catalogue: every item from the DB shown as an icon grid with a
    live filter box; returns a fresh stack dict for the chosen item (or None)."""
    Qt = QtCore.Qt

    class Picker(QtWidgets.QDialog):
        def __init__(self):
            super().__init__(parent)
            self.setWindowTitle("Add Item")
            self.resize(520, 440)
            self.result_stack = None
            v = QtWidgets.QVBoxLayout(self)
            self.filter = QtWidgets.QLineEdit()
            self.filter.setPlaceholderText("Filter by name, id or category…")
            self.filter.textChanged.connect(self._apply_filter)
            v.addWidget(self.filter)
            self.grid = QtWidgets.QListWidget()
            # A smaller-than-default font keeps the item names readable and lets
            # them wrap onto two lines instead of being cut off (they were
            # oversized, especially on high-DPI displays).
            gf = QtWidgets.QApplication.font()
            _pt = gf.pointSizeF()
            gf.setPointSizeF(max(7.0, (_pt if _pt > 0 else 9.0) - 2.0))
            self.grid.setFont(gf)
            self.grid.setViewMode(QtWidgets.QListView.IconMode)
            self.grid.setIconSize(QtCore.QSize(44, 44))
            self.grid.setGridSize(QtCore.QSize(118, 100))
            self.grid.setResizeMode(QtWidgets.QListView.Adjust)
            self.grid.setMovement(QtWidgets.QListView.Static)
            self.grid.setWordWrap(True)
            self.grid.setUniformItemSizes(True)
            self.grid.setSpacing(4)
            self.grid.setStyleSheet(
                "QListWidget { background:#2b2d33; border:1px solid #3a3d44; }"
                "QListWidget::item { color:#d8dae0; padding:3px; }"
                "QListWidget::item:selected { background:#3d5f5d; color:#fff; }")
            self.grid.itemDoubleClicked.connect(lambda *_: self._accept())
            v.addWidget(self.grid, 1)
            row = QtWidgets.QHBoxLayout()
            row.addStretch(1)
            ok = QtWidgets.QPushButton("Add"); cancel = QtWidgets.QPushButton("Cancel")
            ok.clicked.connect(self._accept); cancel.clicked.connect(self.reject)
            row.addWidget(ok); row.addWidget(cancel)
            v.addLayout(row)
            self._populate()

        def _catalogue(self):
            if itemdb is not None and getattr(itemdb, "ITEMS", None):
                for iid, d in sorted(itemdb.ITEMS.items(),
                                     key=lambda kv: (kv[1].category, kv[1].name)):
                    yield iid, d.name, d.category, d.make_stack(1)
            else:  # DB unavailable — offer a blank
                yield "new_item", "New Item", "misc", inv.make_item("new_item", name="New Item")

        def _populate(self):
            for iid, name, cat, stack in self._catalogue():
                it = QtWidgets.QListWidgetItem(badged(stack), name)
                it.setData(int(Qt.UserRole), stack)
                it.setData(int(Qt.UserRole) + 1, f"{iid} {name} {cat}".lower())
                it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
                it.setToolTip(f"{name}  ({cat})\nid: {iid}")
                # Explicit size hint so the name wraps at the cell width rather
                # than being clipped to the icon width.
                it.setSizeHint(QtCore.QSize(112, 96))
                self.grid.addItem(it)
            if self.grid.count():
                self.grid.setCurrentRow(0)

        def _apply_filter(self, text):
            t = text.strip().lower()
            for i in range(self.grid.count()):
                it = self.grid.item(i)
                hay = it.data(int(Qt.UserRole) + 1) or ""
                it.setHidden(bool(t) and t not in hay)

        def _accept(self):
            it = self.grid.currentItem()
            if it is not None and not it.isHidden():
                # Return a copy so repeated adds don't share one dict.
                self.result_stack = dict(it.data(int(Qt.UserRole)))
            self.accept()

        def choose(self):
            return self.result_stack if self.exec_() == QtWidgets.QDialog.Accepted else None

    return Picker()


# ===========================================================================
# Spawn-point editor (the 'logicspawner' / creaturespawn entity)
# ===========================================================================
# Two kinds an author can spawn, with a plain-English description each, so the
# creature-vs-NPC distinction is obvious in the UI (not two identical lists).
_SPAWN_KINDS = [
    ("creature", "Creature — a monster or wild animal (combat, loot, roams)"),
    ("npc", "NPC — a townsperson / guard / bandit (schedule, dialogue, home)"),
]
_SPAWN_FACTIONS = ["player", "villagers", "guards", "bandits", "cultists",
                   "wildlife", "monsters"]


def make_spawn_tab(thing):
    try:
        QtWidgets, QtCore = _qt()
    except Exception:  # pragma: no cover
        return None
    return _SpawnTab(thing, QtWidgets, QtCore)


def _roles_for_kind(kind):
    """(role_id, human label) pairs for a spawn kind, from the bestiary."""
    from .rpg import bestiary
    want = bestiary.NPC if kind == "npc" else bestiary.CREATURE
    out = []
    for role in bestiary.roles_of_kind(want):
        tmpl = bestiary.get(role)
        label = tmpl.name if tmpl else role.title()
        out.append((role, f"{label}  ({role})"))
    return out


def _SpawnTab(thing, QtWidgets, QtCore):
    class Tab(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.thing = thing
            self._loading = True
            p = thing.properties

            root = QtWidgets.QVBoxLayout(self)
            root.addWidget(_hint_label(
                QtWidgets,
                "What this spawn point creates when the game starts. Set Count "
                "to 2+ (and, optionally, a shared Faction) to drop a whole group."))

            form = QtWidgets.QFormLayout()
            form.setSpacing(6)

            # --- Kind (clear, described) ---
            self.kind = QtWidgets.QComboBox()
            for _id, label in _SPAWN_KINDS:
                self.kind.addItem(label, _id)
            cur_kind = str(p.get("spawn_kind", "creature")).lower()
            self.kind.setCurrentIndex(max(0, self.kind.findData(cur_kind)))
            self.kind.currentIndexChanged.connect(self._on_kind)
            form.addRow("Spawns:", self.kind)

            # --- Role (filtered to the chosen kind) ---
            self.role = QtWidgets.QComboBox()
            form.addRow("Role / appearance:", self.role)

            # --- Faction (shared across the whole group) ---
            self.faction = QtWidgets.QComboBox()
            self.faction.addItem("(role default)", "")
            for f in _SPAWN_FACTIONS:
                self.faction.addItem(f, f)
            cur_fac = str(p.get("faction", "") or "")
            self.faction.setCurrentIndex(max(0, self.faction.findData(cur_fac)))
            self.faction.currentIndexChanged.connect(self._write_back)
            form.addRow("Faction:", self.faction)

            # --- Count ---
            self.count = QtWidgets.QSpinBox()
            self.count.setRange(1, 100)
            self.count.setValue(int(p.get("count", 1) or 1))
            self.count.valueChanged.connect(self._write_back)
            form.addRow("Count:", self.count)

            # --- Scatter radius ---
            self.radius = QtWidgets.QDoubleSpinBox()
            self.radius.setRange(0.0, 100000.0)
            self.radius.setDecimals(1)
            self.radius.setSingleStep(10.0)
            self.radius.setValue(float(p.get("spawn_radius", 0.0) or 0.0))
            self.radius.valueChanged.connect(self._write_back)
            form.addRow("Scatter radius:", self.radius)

            # --- Respawn ---
            self.respawn = QtWidgets.QCheckBox("Respawns the group when cleared")
            self.respawn.setChecked(bool(p.get("respawn", False)))
            self.respawn.stateChanged.connect(self._write_back)
            form.addRow("", self.respawn)

            root.addLayout(form)

            # --- Inventory (proper item table, each member gets a copy) ---
            root.addWidget(_hint_label(
                QtWidgets,
                "Starting inventory — every member spawns with its own copy of "
                "these items."))
            self._normalise_inventory()
            inv_widget = _InventoryTab(self.thing, QtWidgets, QtCore)
            root.addWidget(inv_widget)

            self._loading = False
            self._populate_roles(cur_kind, str(p.get("creature_role", "")))

        # -- helpers -----------------------------------------------------
        def _normalise_inventory(self):
            """The Inventory table edits a list of stacks; migrate a legacy
            'id:qty' string (or None) into a list so the table can bind to it."""
            p = self.thing.properties
            invval = p.get("inventory")
            if isinstance(invval, list):
                return
            try:
                from game.runtime import MiniwindSession
                p["inventory"] = MiniwindSession._spawn_inventory(invval)
            except Exception:
                p["inventory"] = []

        def _populate_roles(self, kind, want_role):
            self.role.blockSignals(True)
            self.role.clear()
            first = None
            for role_id, label in _roles_for_kind(kind):
                self.role.addItem(label, role_id)
                if first is None:
                    first = role_id
            idx = self.role.findData(want_role)
            if idx < 0:
                idx = 0
                if first is not None:
                    self.thing.properties["creature_role"] = first
            self.role.setCurrentIndex(max(0, idx))
            self.role.blockSignals(False)
            try:
                self.role.currentIndexChanged.disconnect(self._on_role)
            except Exception:
                pass
            self.role.currentIndexChanged.connect(self._on_role)

        def _on_kind(self, *_):
            if self._loading:
                return
            kind = self.kind.currentData()
            self.thing.properties["spawn_kind"] = kind
            # Repopulate the role list for the new kind (this is what stops the
            # two lists from being identical), keeping the role if still valid.
            self._populate_roles(kind, str(self.thing.properties.get("creature_role", "")))
            self._on_role()

        def _on_role(self, *_):
            if self._loading:
                return
            data = self.role.currentData()
            if data is not None:
                self.thing.properties["creature_role"] = data

        def _write_back(self, *_):
            if self._loading:
                return
            p = self.thing.properties
            p["spawn_kind"] = self.kind.currentData()
            p["faction"] = self.faction.currentData() or ""
            p["count"] = int(self.count.value())
            p["spawn_radius"] = float(self.radius.value())
            p["respawn"] = bool(self.respawn.isChecked())

    return Tab()


# ===========================================================================
# Dialogue editor (with conditions & actions)
# ===========================================================================
_DLG_HELP = (
    "Responses (one per line):  Text -> NODE | if COND | do ACTIONS\n"
    "  NODE: another node id, or END.   COND: key == value / key != value / "
    "has item_id / lacks item_id\n"
    "  ACTIONS (';'-separated): start_quest qid ; complete_quest qid ; "
    "give item_id,qty ; take item_id,qty ;\n"
    "                          set key=value ; open_trade ; persuade ; "
    "join_guild guild_id")


def make_dialogue_tab(thing):
    """Composable Aurora-style dialogue tree editor (also embeddable in wizards)."""
    try:
        QtWidgets, QtCore = _qt()
    except Exception:  # pragma: no cover
        return None
    return dialogue_tree_widget(thing, QtWidgets, QtCore)


def dialogue_tree_widget(thing, QtWidgets, QtCore):
    """Return a QWidget presenting an NPC's dialogue as a branching **tree**
    (BioWare Aurora style): nodes are what the NPC says, their child items are
    the player's responses, and each response links to the node it leads to.
    Selecting a node or a response opens a details form. The stored format is the
    same data-driven ``{start, nodes:{id:{text, responses:[…]}}}`` dict, so it
    stays text/mod-friendly. Reused by the Dialogue property tab and the NPC
    wizard — a composable component, not a monolithic panel."""

    class Tab(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.thing = thing
            self.thing.properties.setdefault("dialogue", {})
            self._loading = False
            root = QtWidgets.QVBoxLayout(self)

            split = QtWidgets.QHBoxLayout()
            # -- left: the conversation tree + structural buttons --
            left = QtWidgets.QVBoxLayout()
            left.addWidget(QtWidgets.QLabel("Conversation tree:"))
            self.tree = QtWidgets.QTreeWidget()
            self.tree.setHeaderLabels(["Node / response"])
            self.tree.setColumnCount(1)
            self.tree.currentItemChanged.connect(lambda *_: self._select())
            left.addWidget(self.tree)
            btns = QtWidgets.QHBoxLayout()
            b_node = QtWidgets.QPushButton("Add Node")
            b_resp = QtWidgets.QPushButton("Add Response")
            b_start = QtWidgets.QPushButton("Set Start")
            b_del = QtWidgets.QPushButton("Delete")
            b_node.clicked.connect(self._add_node)
            b_resp.clicked.connect(self._add_response)
            b_start.clicked.connect(self._set_start)
            b_del.clicked.connect(self._delete)
            for b in (b_node, b_resp, b_start, b_del):
                btns.addWidget(b)
            left.addLayout(btns)
            split.addLayout(left, 3)

            # -- right: details form (swaps between node and response) --
            self.details = QtWidgets.QStackedWidget()
            self.details.addWidget(self._build_node_form())      # index 0
            self.details.addWidget(self._build_resp_form())      # index 1
            self.details.addWidget(QtWidgets.QLabel("Select a node or response."))  # 2
            split.addWidget(self.details, 4)
            root.addLayout(split)
            self._reload()

        # ---- data helpers ----
        def _tree_data(self):
            t = self.thing.properties.get("dialogue")
            if not isinstance(t, dict):
                t = {"start": "", "nodes": {}}
                self.thing.properties["dialogue"] = t
            t.setdefault("nodes", {})
            return t

        # ---- forms ----
        def _build_node_form(self):
            w = QtWidgets.QWidget()
            f = QtWidgets.QFormLayout(w)
            self.n_id = QtWidgets.QLabel("")
            self.n_text = QtWidgets.QPlainTextEdit()
            self.n_text.textChanged.connect(self._write_node)
            self.n_enter = QtWidgets.QLineEdit()
            self.n_enter.setPlaceholderText("set flag=1 ; start_quest qid")
            self.n_enter.editingFinished.connect(self._write_node)
            f.addRow("Node id", self.n_id)
            f.addRow("NPC says", self.n_text)
            f.addRow("On enter", self.n_enter)
            return w

        def _build_resp_form(self):
            w = QtWidgets.QWidget()
            f = QtWidgets.QFormLayout(w)
            self.r_text = QtWidgets.QLineEdit()
            self.r_goto = QtWidgets.QComboBox()
            self.r_goto.setEditable(True)
            self.r_cond = QtWidgets.QLineEdit()
            self.r_cond.setPlaceholderText("flag == 1  /  has item_id")
            self.r_act = QtWidgets.QLineEdit()
            self.r_act.setPlaceholderText("give sword,1 ; open_trade")
            for wdg in (self.r_text, self.r_cond, self.r_act):
                wdg.editingFinished.connect(self._write_resp)
            self.r_goto.currentTextChanged.connect(lambda *_: self._write_resp())
            f.addRow("Player says", self.r_text)
            f.addRow("Leads to", self.r_goto)
            f.addRow("Condition", self.r_cond)
            f.addRow("Actions", self.r_act)
            f.addRow(_hint_label(QtWidgets, _DLG_HELP))
            return w

        # ---- tree build ----
        def _reload(self):
            self._loading = True
            self.tree.clear()
            data = self._tree_data()
            start = data.get("start", "")
            for nid, node in data.get("nodes", {}).items():
                label = f"◆ {nid}" + ("  (start)" if nid == start else "")
                item = QtWidgets.QTreeWidgetItem([f"{label}: {str(node.get('text',''))[:40]}"])
                item.setData(0, QtCore.Qt.UserRole, ("node", nid, -1))
                for i, r in enumerate(node.get("responses", []) or []):
                    goto = r.get("goto", "END")
                    child = QtWidgets.QTreeWidgetItem([f"↳ {str(r.get('text',''))[:36]}  → {goto}"])
                    child.setData(0, QtCore.Qt.UserRole, ("resp", nid, i))
                    item.addChild(child)
                self.tree.addTopLevelItem(item)
            self.tree.expandAll()
            self._refresh_goto_choices()
            self._loading = False

        def _refresh_goto_choices(self):
            cur = self.r_goto.currentText()
            self.r_goto.blockSignals(True)
            self.r_goto.clear()
            self.r_goto.addItem("END")
            for nid in self._tree_data().get("nodes", {}):
                self.r_goto.addItem(nid)
            if cur:
                self.r_goto.setEditText(cur)
            self.r_goto.blockSignals(False)

        # ---- selection ----
        def _sel(self):
            item = self.tree.currentItem()
            if item is None:
                return (None, None, -1)
            return item.data(0, QtCore.Qt.UserRole) or (None, None, -1)

        def _node(self, nid):
            return self._tree_data().get("nodes", {}).get(nid)

        def _select(self):
            self._loading = True
            kind, nid, idx = self._sel()
            if kind == "node":
                node = self._node(nid) or {}
                self.n_id.setText(nid)
                self.n_text.setPlainText(str(node.get("text", "")))
                self.n_enter.setText(authoring.format_actions(node.get("on_enter", [])))
                self.details.setCurrentIndex(0)
            elif kind == "resp":
                node = self._node(nid) or {}
                resp = (node.get("responses", []) or [])[idx] if idx >= 0 else {}
                self.r_text.setText(str(resp.get("text", "")))
                self._refresh_goto_choices()
                self.r_goto.setEditText(str(resp.get("goto", "END")))
                self.r_cond.setText(authoring.format_condition(resp.get("condition")))
                self.r_act.setText(authoring.format_actions(resp.get("actions", [])))
                self.details.setCurrentIndex(1)
            else:
                self.details.setCurrentIndex(2)
            self._loading = False

        # ---- writes ----
        def _write_node(self):
            if self._loading:
                return
            kind, nid, _ = self._sel()
            if kind != "node":
                return
            node = self._node(nid)
            if node is None:
                return
            node["text"] = self.n_text.toPlainText()
            acts = authoring.parse_actions(self.n_enter.text())
            if acts:
                node["on_enter"] = acts
            else:
                node.pop("on_enter", None)
            self._refresh_labels()

        def _write_resp(self):
            if self._loading:
                return
            kind, nid, idx = self._sel()
            if kind != "resp":
                return
            node = self._node(nid)
            if node is None or idx < 0:
                return
            resp = node.setdefault("responses", [])[idx]
            resp["text"] = self.r_text.text()
            resp["goto"] = self.r_goto.currentText().strip() or "END"
            cond = authoring.parse_condition(self.r_cond.text())
            if cond:
                resp["condition"] = cond
            else:
                resp.pop("condition", None)
            acts = authoring.parse_actions(self.r_act.text())
            if acts:
                resp["actions"] = acts
            else:
                resp.pop("actions", None)
            self._refresh_labels()

        def _refresh_labels(self):
            # Cheap: rebuild the tree text without changing selection semantics.
            sel = self._sel()
            self._reload()
            self._reselect(sel)

        def _reselect(self, sel):
            kind, nid, idx = sel
            it = self.tree.invisibleRootItem()
            for i in range(it.childCount()):
                node_item = it.child(i)
                d = node_item.data(0, QtCore.Qt.UserRole)
                if d == ("node", nid, -1) and kind == "node":
                    self.tree.setCurrentItem(node_item)
                    return
                for j in range(node_item.childCount()):
                    ch = node_item.child(j)
                    if ch.data(0, QtCore.Qt.UserRole) == ("resp", nid, idx):
                        self.tree.setCurrentItem(ch)
                        return

        # ---- structural edits ----
        def _add_node(self):
            data = self._tree_data()
            n = 1
            while f"node{n}" in data["nodes"]:
                n += 1
            nid = f"node{n}"
            data["nodes"][nid] = {"text": "", "responses": []}
            if not data.get("start"):
                data["start"] = nid
            self._reload()
            self._reselect(("node", nid, -1))

        def _add_response(self):
            kind, nid, _ = self._sel()
            if kind not in ("node", "resp"):
                return
            node = self._node(nid)
            if node is None:
                return
            resps = node.setdefault("responses", [])
            resps.append({"text": "New response", "goto": "END"})
            self._reload()
            self._reselect(("resp", nid, len(resps) - 1))

        def _set_start(self):
            kind, nid, _ = self._sel()
            if kind == "node":
                self._tree_data()["start"] = nid
                self._reload()
                self._reselect(("node", nid, -1))

        def _delete(self):
            kind, nid, idx = self._sel()
            data = self._tree_data()
            if kind == "node":
                data["nodes"].pop(nid, None)
                if data.get("start") == nid:
                    data["start"] = next(iter(data["nodes"]), "")
            elif kind == "resp":
                node = self._node(nid)
                if node and 0 <= idx < len(node.get("responses", [])):
                    del node["responses"][idx]
            self._reload()

    return Tab()


# ===========================================================================
# Schedule editor (an NPC's day, as a table — no raw dicts)
# ===========================================================================
_SCHED_STATES = ["IDLE", "GOING_TO_WORK", "WORKING", "GOING_HOME", "SLEEPING"]


def make_schedule_tab(thing):
    try:
        QtWidgets, QtCore = _qt()
    except Exception:  # pragma: no cover
        return None
    return _ScheduleTab(thing, QtWidgets, QtCore)


def _ScheduleTab(thing, QtWidgets, QtCore):
    class Tab(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.thing = thing
            self._loading = False
            layout = QtWidgets.QVBoxLayout(self)
            layout.addWidget(QtWidgets.QLabel(
                "Daily schedule — each entry starts at its hour and runs until "
                "the next. 'Location' is a World Marker name, or home/work."))
            self.table = QtWidgets.QTableWidget(0, 3)
            self.table.setHorizontalHeaderLabels(["Hour", "State", "Location"])
            self.table.horizontalHeader().setStretchLastSection(True)
            layout.addWidget(self.table)
            btns = QtWidgets.QHBoxLayout()
            add = QtWidgets.QPushButton("Add Entry")
            rem = QtWidgets.QPushButton("Remove Selected")
            up = QtWidgets.QPushButton("Sort by Hour")
            add.clicked.connect(self._add)
            rem.clicked.connect(self._remove)
            up.clicked.connect(self._sort)
            for b in (add, rem, up):
                btns.addWidget(b)
            btns.addStretch(1)
            layout.addLayout(btns)
            self.table.itemChanged.connect(self._write_back)
            self._reload()

        def _sched(self):
            s = self.thing.properties.get("schedule")
            if not isinstance(s, list):
                s = []
                self.thing.properties["schedule"] = s
            return s

        def _reload(self):
            self._loading = True
            sched = self._sched()
            self.table.setRowCount(len(sched))
            for r, e in enumerate(sched):
                self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(str(e.get("hour", 0))))
                combo = QtWidgets.QComboBox()
                combo.addItems(_SCHED_STATES)
                cur = str(e.get("state", "IDLE"))
                if cur not in _SCHED_STATES:
                    combo.addItem(cur)
                combo.setCurrentText(cur)
                combo.currentTextChanged.connect(lambda _t, row=r: self._write_back())
                self.table.setCellWidget(r, 1, combo)
                self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(str(e.get("location", "home"))))
            self._loading = False

        def _add(self):
            self._sched().append({"hour": 8, "state": "WORKING", "location": "work"})
            self._reload()

        def _remove(self):
            row = self.table.currentRow()
            sched = self._sched()
            if 0 <= row < len(sched):
                del sched[row]
                self._reload()

        def _sort(self):
            self._sched().sort(key=lambda e: float(e.get("hour", 0)))
            self._reload()

        def _write_back(self, *_):
            if self._loading:
                return
            sched = self._sched()
            for r in range(self.table.rowCount()):
                if r >= len(sched):
                    break
                e = sched[r]
                hour_cell = self.table.item(r, 0)
                if hour_cell is not None:
                    try:
                        e["hour"] = int(float(hour_cell.text()))
                    except ValueError:
                        e["hour"] = 0
                combo = self.table.cellWidget(r, 1)
                if combo is not None:
                    e["state"] = combo.currentText()
                loc_cell = self.table.item(r, 2)
                if loc_cell is not None:
                    e["location"] = loc_cell.text()

    return Tab()


# ===========================================================================
# Spells editor — assign spells to an NPC/creature (like inventory), with a
# per-spell projectile colour, damage-per-shot and speed.
# ===========================================================================
def _castable_spells():
    """(id, label) for spells an NPC can hurl as a projectile, from the registry."""
    from .rpg import magic
    out = []
    for sid, sp in magic.SPELLS.items():
        if sp.delivery in (magic.PROJECTILE, magic.TARGET) or sp.damage > 0:
            out.append((sid, sp.name))
    out.sort(key=lambda t: t[1])
    return out


# --- Spell cards: dark-theme, one-card-per-line, RPG-styled ------------------

#: Dark card palette shared by every spell card (assign pickers + Spell Editor)
#: so cards sit on the editor's dark theme instead of clashing pastels.
_CARD_BG = "#26232e"          # normal card background
_CARD_BG_SEL = "#302b3d"      # selected card background
_CARD_EDGE = "#4a4658"        # unselected border
_CARD_INK = "#e8e4f0"         # primary (title) text — light
_CARD_SUB = "#b9b4c6"         # secondary text — dim light
_CARD_WELL = "rgba(255,255,255,22)"   # icon well fill

#: Vivid per-school ACCENT (used for the border, school label and icon rim) —
#: keeps cards distinguishable by school while staying readable on dark.
_SCHOOL_ACCENT = {
    "destruction": "#e8836f",
    "restoration": "#7fd39b",
    "alteration":  "#7fb2f0",
    "conjuration": "#b79bf0",
    "illusion":    "#f08fd6",
    "mysticism":   "#6fd6cf",
    "default":     "#b9b6c4",
}

#: Dark stylesheet for the input widgets that live inside a spell card, so their
#: text — and a QComboBox's drop-down popup — is readable on the dark card.
_CARD_INPUT_QSS = """
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #1e1b26; color: #e8e4f0;
    border: 1px solid #4a4658; border-radius: 4px; padding: 2px;
}
QComboBox::drop-down { border: none; width: 16px; }
QComboBox QAbstractItemView {
    background: #26232e; color: #e8e4f0;
    selection-background-color: #4a4270; selection-color: #ffffff;
    border: 1px solid #4a4658;
}
"""


def _school_accent(school):
    return _SCHOOL_ACCENT.get(str(school or "").lower(), _SCHOOL_ACCENT["default"])


def _school_pastel(school):
    """Back-compat shim: (card background, school accent) on the dark theme."""
    return _CARD_BG, _school_accent(school)


def _spell_icon_path(sid, school):
    """The best 100x100 icon for a spell: its own art, else a per-school
    placeholder, else the generic one (all under assets/sprites/spells)."""
    import os
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    base = os.path.join(root, "assets", "sprites", "spells")
    for name in (f"{sid}.png", f"_{str(school or '').lower()}.png", "_spell.png"):
        p = os.path.join(base, name)
        if os.path.isfile(p):
            return p
    return None


def _rpg_font(QtGui, size, bold=False):
    """An old-looking serif/fantasy font, using whatever the OS provides
    (Papyrus / Palatino / Book Antiqua / Georgia …)."""
    f = QtGui.QFont()
    try:
        f.setFamilies(["Papyrus", "Luminari", "Palatino Linotype", "Book Antiqua",
                       "Georgia", "Cambria", "serif"])
    except Exception:
        f.setFamily("Georgia")
    f.setStyleHint(QtGui.QFont.Serif)
    f.setPointSize(size)
    f.setBold(bold)
    return f


def make_player_spells_tab(thing):
    """A vertical list of spell *cards* — every spell (built-in + custom) the
    player can start knowing, one per line, tinted by magic school, with a
    100x100 icon (placeholder until real art is added) and an old-RPG typeface.
    Click a card to grant/revoke it. Writes ``properties['player_spells']``."""
    try:
        QtWidgets, QtCore = _qt()
    except Exception:  # pragma: no cover
        return None
    from PyQt5 import QtGui
    from .rpg import magic

    Qt = QtCore.Qt
    _DELIV = {magic.SELF: "self", magic.TOUCH: "touch",
              magic.TARGET: "target", magic.PROJECTILE: "bolt"}

    class SpellCard(QtWidgets.QFrame):
        H = 116

        def __init__(self, sid, sp, selected, on_toggle):
            super().__init__()
            self.sid = sid
            self.selected = selected
            self._on_toggle = on_toggle
            self.bg, self.ink = _school_pastel(sp.school)
            self.setMinimumHeight(self.H)
            self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                               QtWidgets.QSizePolicy.Fixed)
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip(f"<b>{sp.name}</b> ({sid})<br>{getattr(sp,'desc','') or ''}")

            lay = QtWidgets.QHBoxLayout(self)
            lay.setContentsMargins(10, 8, 12, 8)
            lay.setSpacing(12)

            # Selection tick on the LEFT so it survives a narrow property panel
            # (the right edge is clipped first).
            self.tick = QtWidgets.QLabel("✓")
            tf = _rpg_font(QtGui, 20, bold=True); self.tick.setFont(tf)
            self.tick.setStyleSheet("color:#5fcf7a; border:none; background:transparent;")
            self.tick.setFixedWidth(20)
            self.tick.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
            lay.addWidget(self.tick)

            # 100x100 icon placeholder (its own art when present).
            icon = QtWidgets.QLabel()
            icon.setFixedSize(100, 100)
            icon.setAlignment(Qt.AlignCenter)
            icon.setStyleSheet("background:rgba(255,255,255,22); border:1px solid %s;"
                               "border-radius:8px;" % self.ink)
            path = _spell_icon_path(sid, sp.school)
            if path:
                pm = QtGui.QPixmap(path)
                if not pm.isNull():
                    icon.setPixmap(pm.scaled(96, 96, Qt.KeepAspectRatio,
                                             Qt.SmoothTransformation))
            lay.addWidget(icon)

            mid = QtWidgets.QVBoxLayout(); mid.setSpacing(3)
            name = QtWidgets.QLabel(sp.name)
            name.setFont(_rpg_font(QtGui, 15, bold=True))
            name.setStyleSheet("color:#e8e4f0; border:none; background:transparent;")
            mid.addWidget(name)
            sub = QtWidgets.QLabel(f"{str(sp.school).title()}  ·  {_DELIV.get(sp.delivery, sp.delivery)}")
            sf = _rpg_font(QtGui, 10); sf.setBold(False)
            sub.setFont(sf)
            sub.setStyleSheet("color:%s; border:none; background:transparent;" % self.ink)
            mid.addWidget(sub)
            bits = [f"{int(getattr(sp,'base_cost',0) or 0)} magicka"]
            if getattr(sp, "damage", 0):
                bits.append(f"{int(sp.damage)} damage")
            desc = getattr(sp, "desc", "") or ""
            stat = QtWidgets.QLabel("   ·   ".join(bits))
            stat.setFont(_rpg_font(QtGui, 10))
            stat.setStyleSheet("color:#b9b4c6; border:none; background:transparent;")
            mid.addWidget(stat)
            if desc:
                dl = QtWidgets.QLabel(desc)
                dl.setWordWrap(True)
                df = _rpg_font(QtGui, 9); df.setItalic(True)
                dl.setFont(df)
                dl.setStyleSheet("color:#b9b4c6; border:none; background:transparent;")
                mid.addWidget(dl)
            mid.addStretch(1)
            lay.addLayout(mid, 1)
            self._restyle()

        def _restyle(self):
            self.tick.setVisible(self.selected)
            border = ("3px solid %s" % self.ink) if self.selected else ("1px solid %s" % _CARD_EDGE)
            bg = _CARD_BG_SEL if self.selected else _CARD_BG
            self.setStyleSheet(
                "QFrame { background:%s; border:%s; border-radius:10px; } %s"
                % (bg, border, _CARD_INPUT_QSS))

        def set_selected(self, v):
            self.selected = v; self._restyle()

        def mousePressEvent(self, e):
            if e.button() == Qt.LeftButton:
                self.selected = not self.selected
                self._restyle()
                self._on_toggle(self.sid, self.selected)

    class Tab(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.thing = thing
            self.cards = {}
            root = QtWidgets.QVBoxLayout(self)
            root.addWidget(_hint_label(
                QtWidgets, "Spells the player starts the game knowing (on top of "
                "any from their race, birthsign or class). Click a card to grant "
                "it. Create new spells in Tools ▸ Spell Editor — they appear here. "
                "Drop a 100x100 PNG at assets/sprites/spells/<id>.png for real art."))
            self.search = QtWidgets.QLineEdit()
            self.search.setPlaceholderText("Filter spells…")
            self.search.textChanged.connect(self._filter)
            root.addWidget(self.search)

            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
            holder = QtWidgets.QWidget()
            col = QtWidgets.QVBoxLayout(holder)
            col.setContentsMargins(2, 2, 2, 2)
            col.setSpacing(8)
            chosen = set(self._current())
            for sid, sp in sorted(magic.SPELLS.items(),
                                  key=lambda kv: (kv[1].school, kv[1].name)):
                card = SpellCard(sid, sp, sid in chosen, self._toggle)
                self.cards[sid] = card
                col.addWidget(card)
            col.addStretch(1)
            scroll.setWidget(holder)
            root.addWidget(scroll, 1)

            self.summary = QtWidgets.QLabel("")
            self.summary.setStyleSheet("color:#9aa;")
            root.addWidget(self.summary)
            self._update_summary()

        def _current(self):
            v = self.thing.properties.get("player_spells")
            if isinstance(v, str):
                v = [s.strip() for s in v.split(",") if s.strip()]
            return list(v) if isinstance(v, list) else []

        def _toggle(self, sid, selected):
            chosen = self._current()
            if selected and sid not in chosen:
                chosen.append(sid)
            elif not selected and sid in chosen:
                chosen.remove(sid)
            self.thing.properties["player_spells"] = chosen
            self._update_summary()

        def _filter(self, text):
            from .rpg import magic as _m
            t = text.strip().lower()
            for sid, card in self.cards.items():
                sp = _m.get(sid)
                hay = f"{sid} {sp.name if sp else ''} {sp.school if sp else ''}".lower()
                card.setVisible(not t or t in hay)

        def _update_summary(self):
            n = len(self.thing.properties.get("player_spells") or [])
            self.summary.setText(f"{n} spell(s) granted to the player at start")

    return Tab()


def make_spells_tab(thing):
    try:
        QtWidgets, QtCore = _qt()
    except Exception:  # pragma: no cover
        return None
    return _SpellsTab(thing, QtWidgets, QtCore)


def _SpellsTab(thing, QtWidgets, QtCore):
    """The NPC/creature spell picker — the *same* pastel spell cards the player's
    starting-spell picker uses. Click a card to give the NPC that spell; a
    selected card expands to show its per-bolt colour, damage and speed (an NPC
    cycles through its chosen spells, one per shot)."""
    from PyQt5 import QtGui
    from .rpg import magic

    Qt = QtCore.Qt
    _DELIV = {magic.SELF: "self", magic.TOUCH: "touch",
              magic.TARGET: "target", magic.PROJECTILE: "bolt"}

    def _defaults_for(sid):
        sp = magic.get(sid)
        if sp is None:
            return {"color": [140, 160, 255], "damage": 0, "speed": 900.0}
        return {"color": list(sp.color), "damage": int(sp.damage),
                "speed": float(sp.projectile_speed)}

    class NpcSpellCard(QtWidgets.QFrame):
        """A pastel spell card that also edits the NPC's per-bolt settings."""

        def __init__(self, sid, sp, entry, on_toggle, on_edit):
            super().__init__()
            self.sid = sid
            self._on_toggle = on_toggle
            self._on_edit = on_edit
            self.selected = entry is not None
            self.bg, self.ink = _school_pastel(sp.school)
            self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                               QtWidgets.QSizePolicy.Fixed)
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip(f"<b>{sp.name}</b> ({sid})<br>{getattr(sp,'desc','') or ''}")

            root = QtWidgets.QVBoxLayout(self)
            root.setContentsMargins(10, 8, 12, 8)
            root.setSpacing(6)

            top = QtWidgets.QHBoxLayout(); top.setSpacing(12)
            # Selection tick on the LEFT so it is never clipped when the property
            # panel is narrowed (the far-right edge is the first to be cut off).
            self.tick = QtWidgets.QLabel("✓")
            self.tick.setFont(_rpg_font(QtGui, 20, bold=True))
            self.tick.setStyleSheet("color:#5fcf7a; border:none; background:transparent;")
            self.tick.setFixedWidth(20)
            self.tick.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
            top.addWidget(self.tick)

            icon = QtWidgets.QLabel()
            icon.setFixedSize(100, 100)
            icon.setAlignment(Qt.AlignCenter)
            icon.setStyleSheet("background:rgba(255,255,255,22); border:1px solid %s;"
                               "border-radius:8px;" % self.ink)
            path = _spell_icon_path(sid, sp.school)
            if path:
                pm = QtGui.QPixmap(path)
                if not pm.isNull():
                    icon.setPixmap(pm.scaled(96, 96, Qt.KeepAspectRatio,
                                             Qt.SmoothTransformation))
            top.addWidget(icon)

            mid = QtWidgets.QVBoxLayout(); mid.setSpacing(3)
            name = QtWidgets.QLabel(sp.name)
            name.setFont(_rpg_font(QtGui, 15, bold=True))
            name.setStyleSheet("color:#e8e4f0; border:none; background:transparent;")
            mid.addWidget(name)
            sub = QtWidgets.QLabel(f"{str(sp.school).title()}  ·  "
                                   f"{_DELIV.get(sp.delivery, sp.delivery)}")
            sf = _rpg_font(QtGui, 10); sf.setBold(False)
            sub.setFont(sf)
            sub.setStyleSheet("color:%s; border:none; background:transparent;" % self.ink)
            mid.addWidget(sub)
            desc = getattr(sp, "desc", "") or ""
            if desc:
                dl = QtWidgets.QLabel(desc); dl.setWordWrap(True)
                df = _rpg_font(QtGui, 9); df.setItalic(True)
                dl.setFont(df)
                dl.setStyleSheet("color:#b9b4c6; border:none; background:transparent;")
                mid.addWidget(dl)
            mid.addStretch(1)
            top.addLayout(mid, 1)
            root.addLayout(top)

            # --- per-bolt controls (only meaningful once the card is chosen) ---
            self.controls = QtWidgets.QWidget()
            crow = QtWidgets.QHBoxLayout(self.controls)
            crow.setContentsMargins(0, 0, 0, 0); crow.setSpacing(8)
            e = entry or _defaults_for(sid)

            clab = QtWidgets.QLabel("Bolt:")
            clab.setStyleSheet("color:#cfc9db; border:none; background:transparent;")
            crow.addWidget(clab)
            self.swatch = QtWidgets.QPushButton(); self.swatch.setFixedWidth(64)
            self._paint_swatch(e.get("color") or [140, 160, 255])
            self.swatch.clicked.connect(self._pick_colour)
            crow.addWidget(self.swatch)

            dl2 = QtWidgets.QLabel("Dmg")
            dl2.setStyleSheet("color:#cfc9db; border:none; background:transparent;")
            crow.addWidget(dl2)
            self.dmg = QtWidgets.QSpinBox(); self.dmg.setRange(0, 100000)
            self.dmg.setValue(int(e.get("damage", 0) or 0))
            self.dmg.valueChanged.connect(lambda v: self._on_edit(self.sid, "damage", int(v)))
            crow.addWidget(self.dmg)

            sl2 = QtWidgets.QLabel("Speed")
            sl2.setStyleSheet("color:#cfc9db; border:none; background:transparent;")
            crow.addWidget(sl2)
            self.spd = QtWidgets.QDoubleSpinBox(); self.spd.setRange(0.0, 100000.0)
            self.spd.setDecimals(0); self.spd.setSingleStep(50.0)
            self.spd.setValue(float(e.get("speed", 0) or 0))
            self.spd.valueChanged.connect(lambda v: self._on_edit(self.sid, "speed", float(v)))
            crow.addWidget(self.spd)
            crow.addStretch(1)
            root.addWidget(self.controls)

            self._restyle()

        def _paint_swatch(self, rgb):
            r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
            self.swatch.setStyleSheet(
                f"background-color: rgb({r},{g},{b}); border:1px solid #222;")
            self.swatch.setText(f"{r},{g},{b}")

        def _pick_colour(self):
            cur = [0, 0, 0]
            try:
                parts = self.swatch.text().split(",")
                cur = [int(p) for p in parts]
            except Exception:
                cur = [140, 160, 255]
            initial = QtGui.QColor(*cur)
            chosen = QtWidgets.QColorDialog.getColor(initial, self, "Projectile colour")
            if chosen.isValid():
                rgb = [chosen.red(), chosen.green(), chosen.blue()]
                self._paint_swatch(rgb)
                self._on_edit(self.sid, "color", rgb)

        def _restyle(self):
            self.tick.setVisible(self.selected)
            self.controls.setVisible(self.selected)
            border = ("3px solid %s" % self.ink) if self.selected else ("1px solid %s" % _CARD_EDGE)
            bg = _CARD_BG_SEL if self.selected else _CARD_BG
            self.setStyleSheet(
                "QFrame { background:%s; border:%s; border-radius:10px; } %s"
                % (bg, border, _CARD_INPUT_QSS))

        def mousePressEvent(self, e):
            if e.button() == Qt.LeftButton:
                self.selected = not self.selected
                self._restyle()
                self._on_toggle(self.sid, self.selected)

    class Tab(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.thing = thing
            self.cards = {}
            root = QtWidgets.QVBoxLayout(self)
            root.addWidget(_hint_label(
                QtWidgets,
                "Spells this NPC casts — click a card to give it the spell. A "
                "magic-armed NPC cycles through its chosen spells, one per shot; "
                "each selected card sets that bolt's colour, damage and speed."))

            # Casting only happens when the NPC's combat style is Magic.
            self.cast_cb = QtWidgets.QCheckBox("Casts spells (sets combat style to Magic)")
            self.cast_cb.setChecked(
                str(thing.properties.get("attack_style", "")).lower() == "magic")
            self.cast_cb.stateChanged.connect(self._on_cast_toggle)
            root.addWidget(self.cast_cb)

            self.search = QtWidgets.QLineEdit()
            self.search.setPlaceholderText("Filter spells…")
            self.search.textChanged.connect(self._filter)
            root.addWidget(self.search)

            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
            holder = QtWidgets.QWidget()
            col = QtWidgets.QVBoxLayout(holder)
            col.setContentsMargins(2, 2, 2, 2); col.setSpacing(8)
            for sid, _label in _castable_spells():
                sp = magic.get(sid)
                if sp is None:
                    continue
                card = NpcSpellCard(sid, sp, self._entry(sid),
                                    self._toggle, self._edit)
                self.cards[sid] = card
                col.addWidget(card)
            col.addStretch(1)
            scroll.setWidget(holder)
            root.addWidget(scroll, 1)

            self.summary = QtWidgets.QLabel("")
            self.summary.setStyleSheet("color:#9aa;")
            root.addWidget(self.summary)
            self._update_summary()

        # -- data ------------------------------------------------------
        def _spells(self):
            s = self.thing.properties.get("spells")
            if not isinstance(s, list):
                s = []
                self.thing.properties["spells"] = s
            return s

        def _entry(self, sid):
            for e in self._spells():
                if e.get("id") == sid:
                    return e
            return None

        def _on_cast_toggle(self, _state):
            if self.cast_cb.isChecked():
                self.thing.properties["attack_style"] = "magic"
                self.thing.properties["combatant"] = True
            elif str(self.thing.properties.get("attack_style", "")).lower() == "magic":
                self.thing.properties["attack_style"] = "melee"

        def _toggle(self, sid, selected):
            spells = self._spells()
            if selected and self._entry(sid) is None:
                d = _defaults_for(sid)
                spells.append({"id": sid, "color": d["color"],
                               "damage": d["damage"], "speed": d["speed"]})
            elif not selected:
                self.thing.properties["spells"] = [e for e in spells
                                                   if e.get("id") != sid]
            self._update_summary()

        def _edit(self, sid, key, value):
            e = self._entry(sid)
            if e is not None:
                e[key] = value

        def _filter(self, text):
            t = text.strip().lower()
            for sid, card in self.cards.items():
                sp = magic.get(sid)
                hay = f"{sid} {sp.name if sp else ''} {sp.school if sp else ''}".lower()
                card.setVisible(not t or t in hay)

        def _update_summary(self):
            n = len(self._spells())
            self.summary.setText(f"{n} spell(s) in this NPC's rotation")

    return Tab()


# ===========================================================================
# Spell Editor — a standalone dialog (Tools ▸ Spell Editor) for authoring the
# spell definitions themselves (name, element, colour, damage, cost, speed).
# Saves to game/data/spells.json via magic.save_custom_spells().
# ===========================================================================
def open_spell_editor(parent=None):
    """Open the modal Spell Editor. Returns True if changes were saved."""
    try:
        QtWidgets, QtCore = _qt()
        from PyQt5 import QtGui
    except Exception:  # pragma: no cover
        return False
    from .rpg import magic
    from .rpg import skills as sk

    ELEMENTS = ["fire", "frost", "shock", "magic"]
    DELIVERIES = [magic.SELF, magic.TOUCH, magic.TARGET, magic.PROJECTILE]
    COLS = ["Id", "Name", "Element", "Colour", "Damage", "Cost", "Speed", "Delivery"]

    def _damage_of(d):
        return sum(float(e.get("magnitude", 0)) for e in d.get("effects", [])
                   if str(e.get("kind", "")).startswith("damage"))

    def _set_damage(d, value):
        for e in d.get("effects", []):
            if str(e.get("kind", "")).startswith("damage"):
                e["magnitude"] = value
                return
        d.setdefault("effects", []).append(
            {"kind": "damage_health", "magnitude": value, "duration": 0})

    Qt = QtCore.Qt

    class SpellDefCard(QtWidgets.QFrame):
        """A pastel card editing one spell definition in place (writes into *d*)."""

        def __init__(self, d, on_select):
            super().__init__()
            self.d = d
            self._on_select = on_select
            self.selected = False
            self.bg, self.ink = _school_pastel(d.get("school", sk.DESTRUCTION))
            self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                               QtWidgets.QSizePolicy.Fixed)
            self.setCursor(Qt.PointingHandCursor)

            root = QtWidgets.QVBoxLayout(self)
            root.setContentsMargins(10, 8, 12, 8); root.setSpacing(6)

            top = QtWidgets.QHBoxLayout(); top.setSpacing(12)
            icon = QtWidgets.QLabel(); icon.setFixedSize(72, 72)
            icon.setAlignment(Qt.AlignCenter)
            icon.setStyleSheet("background:rgba(255,255,255,22); border:1px solid %s;"
                               "border-radius:8px;" % self.ink)
            ip = _spell_icon_path(d.get("id"), d.get("school"))
            if ip:
                pm = QtGui.QPixmap(ip)
                if not pm.isNull():
                    icon.setPixmap(pm.scaled(68, 68, Qt.KeepAspectRatio,
                                             Qt.SmoothTransformation))
            top.addWidget(icon)

            idcol = QtWidgets.QVBoxLayout(); idcol.setSpacing(3)
            self.name = QtWidgets.QLineEdit(str(d.get("name", "")))
            self.name.setFont(_rpg_font(QtGui, 14, bold=True))
            self.name.setStyleSheet("background:#1e1b26; border:1px solid %s;"
                                    "border-radius:4px; padding:2px; color:#e8e4f0;" % self.ink)
            self.name.textChanged.connect(lambda t: self.d.__setitem__("name", t))
            idcol.addWidget(self.name)
            idrow = QtWidgets.QHBoxLayout(); idrow.setSpacing(6)
            lab = QtWidgets.QLabel("id"); lab.setStyleSheet(
                "color:%s; border:none; background:transparent;" % self.ink)
            idrow.addWidget(lab)
            self.id = QtWidgets.QLineEdit(str(d.get("id", "")))
            self.id.setStyleSheet("background:#1e1b26; border:1px solid %s;"
                                  "border-radius:4px; padding:1px; color:#cfc9db;" % self.ink)
            self.id.textChanged.connect(lambda t: self.d.__setitem__("id", t.strip()))
            idrow.addWidget(self.id, 1)
            idcol.addLayout(idrow)
            top.addLayout(idcol, 1)
            root.addLayout(top)

            grid = QtWidgets.QHBoxLayout(); grid.setSpacing(8)

            def _lab(txt):
                q = QtWidgets.QLabel(txt)
                q.setStyleSheet("color:#cfc9db; border:none; background:transparent;")
                return q

            grid.addWidget(_lab("Element"))
            self.elem = QtWidgets.QComboBox(); self.elem.addItems(ELEMENTS)
            self.elem.setCurrentText(str(d.get("element", "magic")))
            self.elem.currentTextChanged.connect(lambda t: self.d.__setitem__("element", t))
            grid.addWidget(self.elem)

            self.swatch = QtWidgets.QPushButton(); self.swatch.setFixedWidth(64)
            self._paint(d.get("color") or magic.element_color(d.get("element")))
            self.swatch.clicked.connect(self._pick)
            grid.addWidget(self.swatch)

            grid.addWidget(_lab("Delivery"))
            self.dlv = QtWidgets.QComboBox(); self.dlv.addItems(DELIVERIES)
            self.dlv.setCurrentText(str(d.get("delivery", magic.PROJECTILE)))
            self.dlv.currentTextChanged.connect(lambda t: self.d.__setitem__("delivery", t))
            grid.addWidget(self.dlv)
            grid.addStretch(1)
            root.addLayout(grid)

            nums = QtWidgets.QHBoxLayout(); nums.setSpacing(8)
            nums.addWidget(_lab("Damage"))
            self.dmg = QtWidgets.QSpinBox(); self.dmg.setRange(0, 100000)
            self.dmg.setValue(int(_damage_of(d)))
            self.dmg.valueChanged.connect(lambda v: _set_damage(self.d, int(v)))
            nums.addWidget(self.dmg)
            nums.addWidget(_lab("Cost"))
            self.cost = QtWidgets.QSpinBox(); self.cost.setRange(0, 100000)
            self.cost.setValue(int(d.get("cost", 0)))
            self.cost.valueChanged.connect(lambda v: self.d.__setitem__("cost", int(v)))
            nums.addWidget(self.cost)
            nums.addWidget(_lab("Speed"))
            self.spd = QtWidgets.QDoubleSpinBox(); self.spd.setRange(0.0, 100000.0)
            self.spd.setDecimals(0); self.spd.setSingleStep(50.0)
            self.spd.setValue(float(d.get("projectile_speed", 900.0)))
            self.spd.valueChanged.connect(lambda v: self.d.__setitem__("projectile_speed", float(v)))
            nums.addWidget(self.spd)
            nums.addStretch(1)
            root.addLayout(nums)
            self._restyle()

        def _paint(self, rgb):
            r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
            self.swatch.setStyleSheet(
                f"background-color: rgb({r},{g},{b}); border:1px solid #222;")
            self.swatch.setText(f"{r},{g},{b}")

        def _pick(self):
            cur = self.d.get("color") or magic.element_color(self.d.get("element"))
            initial = QtGui.QColor(int(cur[0]), int(cur[1]), int(cur[2]))
            chosen = QtWidgets.QColorDialog.getColor(initial, self, "Projectile colour")
            if chosen.isValid():
                rgb = [chosen.red(), chosen.green(), chosen.blue()]
                self.d["color"] = rgb
                self._paint(rgb)

        def _restyle(self):
            border = ("3px solid %s" % self.ink) if self.selected else ("1px solid %s" % _CARD_EDGE)
            bg = _CARD_BG_SEL if self.selected else _CARD_BG
            self.setStyleSheet(
                "QFrame { background:%s; border:%s; border-radius:10px; } %s"
                % (bg, border, _CARD_INPUT_QSS))

        def set_selected(self, v):
            self.selected = v; self._restyle()

        def mousePressEvent(self, e):
            if e.button() == Qt.LeftButton:
                self._on_select(self)

    class Dialog(QtWidgets.QDialog):
        def __init__(self):
            super().__init__(parent)
            self.setWindowTitle("Spell Editor")
            self.resize(720, 620)
            # Work on a copy of every current spell (built-ins + any custom).
            self.rows = [magic.get(sid).to_dict() for sid in sorted(magic.SPELLS)]
            self.cards = []
            self.selected_card = None

            layout = QtWidgets.QVBoxLayout(self)
            layout.addWidget(_hint_label(
                QtWidgets,
                "Edit the spell definitions as cards. Colour drives the projectile "
                "bolt and its light. Click a card to select it for deletion. Saving "
                "writes game/data/spells.json and applies to the live game."))

            self.scroll = QtWidgets.QScrollArea()
            self.scroll.setWidgetResizable(True)
            self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
            layout.addWidget(self.scroll, 1)

            btns = QtWidgets.QHBoxLayout()
            add = QtWidgets.QPushButton("New Spell")
            rem = QtWidgets.QPushButton("Delete Selected")
            add.clicked.connect(self._add)
            rem.clicked.connect(self._remove)
            btns.addWidget(add); btns.addWidget(rem); btns.addStretch(1)
            save = QtWidgets.QPushButton("Save")
            close = QtWidgets.QPushButton("Close")
            save.clicked.connect(self._save)
            close.clicked.connect(self.reject)
            btns.addWidget(save); btns.addWidget(close)
            layout.addLayout(btns)
            self.saved = False
            self._reload()

        def _reload(self):
            self.cards = []
            self.selected_card = None
            holder = QtWidgets.QWidget()
            col = QtWidgets.QVBoxLayout(holder)
            col.setContentsMargins(2, 2, 2, 2); col.setSpacing(8)
            for d in self.rows:
                card = SpellDefCard(d, self._select)
                self.cards.append(card)
                col.addWidget(card)
            col.addStretch(1)
            self.scroll.setWidget(holder)

        def _select(self, card):
            for c in self.cards:
                c.set_selected(c is card)
            self.selected_card = card

        def _add(self):
            base = {"id": "new_spell", "name": "New Spell", "school": sk.DESTRUCTION,
                    "cost": 15, "delivery": magic.PROJECTILE,
                    "effects": [{"kind": "damage_health", "magnitude": 20, "duration": 0}],
                    "desc": "", "element": "magic", "projectile_speed": 900.0,
                    "color": None}
            self.rows.append(base)
            self._reload()
            if self.cards:
                self._select(self.cards[-1])
                self.scroll.ensureWidgetVisible(self.cards[-1])

        def _remove(self):
            if self.selected_card is None:
                return
            d = self.selected_card.d
            self.rows = [r for r in self.rows if r is not d]
            self._reload()

        def _save(self):
            # Drop rows without an id; de-dupe by id (last wins).
            seen = {}
            for d in self.rows:
                sid = str(d.get("id", "")).strip()
                if sid:
                    d["id"] = sid
                    seen[sid] = d
            ok = magic.save_custom_spells(list(seen.values()))
            if ok:
                self.saved = True
                self.accept()
            else:
                QtWidgets.QMessageBox.warning(self, "Spell Editor",
                                              "Could not write spells.json.")

    dlg = Dialog()
    dlg.exec_()
    return bool(getattr(dlg, "saved", False))


# ===========================================================================
# Quest editor (on the GameSettings entity)
# ===========================================================================
#: Human labels for the stage completion-condition kinds (mirrors quests.COND_*).
_QUEST_COND_LABELS = [
    ("none",  "Scripted (advance via dialogue)"),
    ("talk",  "Talk to an NPC"),
    ("fetch", "Fetch / hold an item"),
    ("kill",  "Kill monsters"),
    ("visit", "Visit a location"),
]
#: Placeholder guidance for the condition target box, per kind.
_QUEST_COND_TARGET_HINT = {
    "none":  "(no target — advanced by a dialogue 'advance_quest')",
    "talk":  "NPC name or role, e.g. Bob  /  blacksmith",
    "fetch": "item id, e.g. iron_sword  (count = how many)",
    "kill":  "monster_type / npc_role / name, e.g. wolf  (count = how many)",
    "visit": "location marker place-name, e.g. Old Cave",
}


def make_quests_tab(thing):
    try:
        QtWidgets, QtCore = _qt()
    except Exception:  # pragma: no cover
        return None
    return _QuestsTab(thing, QtWidgets, QtCore)


def _QuestsTab(thing, QtWidgets, QtCore):
    """A proper quest editor on the Game Settings entity.

    Author a quest's identity and giver, write paragraph journal text per stage,
    and give each stage a completion *condition* (talk / fetch / kill / visit)
    that the running game checks and auto-advances. Quests are stored on
    ``properties['quests']`` and loaded when the map is played, so they are
    fully testable in Play mode."""

    class Tab(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.thing = thing
            self.thing.properties.setdefault("quests", [])
            self._loading = False
            root = QtWidgets.QVBoxLayout(self)
            root.addWidget(_hint_label(
                QtWidgets,
                "Create test quests here. Assign a giver, write each stage's "
                "journal paragraph, and set how each stage completes (talk to an "
                "NPC, fetch an item, kill monsters, or visit a location). Enter "
                "Play mode to test — a stage auto-advances when its condition is "
                "met, and finishing the last stage pays the rewards."))

            split = QtWidgets.QHBoxLayout()

            # ---- left: quest list -------------------------------------
            left = QtWidgets.QVBoxLayout()
            left.addWidget(QtWidgets.QLabel("Quests:"))
            self.qlist = QtWidgets.QListWidget()
            self.qlist.currentRowChanged.connect(self._select)
            left.addWidget(self.qlist)
            qb = QtWidgets.QHBoxLayout()
            add = QtWidgets.QPushButton("Add"); rem = QtWidgets.QPushButton("Remove")
            add.clicked.connect(self._add); rem.clicked.connect(self._remove)
            qb.addWidget(add); qb.addWidget(rem)
            left.addLayout(qb)
            lw = QtWidgets.QWidget(); lw.setLayout(left); lw.setMaximumWidth(220)
            split.addWidget(lw)

            # ---- right: quest detail (scrollable) ---------------------
            detail = QtWidgets.QVBoxLayout()
            form = QtWidgets.QFormLayout()
            self.f_id = QtWidgets.QLineEdit()
            self.f_name = QtWidgets.QLineEdit()
            self.f_giver = QtWidgets.QLineEdit()
            self.f_giver.setPlaceholderText("NPC who gives this quest")
            self.f_faction = QtWidgets.QLineEdit()
            self.f_xp = QtWidgets.QSpinBox(); self.f_xp.setRange(0, 100000)
            self.f_desc = QtWidgets.QPlainTextEdit()
            self.f_desc.setPlaceholderText("Quest summary / opening paragraph…")
            self.f_desc.setMaximumHeight(70)
            self.f_gold = QtWidgets.QSpinBox(); self.f_gold.setRange(0, 1000000)
            self.f_items = QtWidgets.QLineEdit()
            self.f_items.setPlaceholderText("item_id,qty ; item_id,qty")
            self.f_rep = QtWidgets.QLineEdit()
            self.f_rep.setPlaceholderText("guild_id,amount")
            for w in (self.f_id, self.f_name, self.f_giver, self.f_faction,
                      self.f_items, self.f_rep):
                w.editingFinished.connect(self._write)
            self.f_xp.valueChanged.connect(self._write)
            self.f_gold.valueChanged.connect(self._write)
            self.f_desc.textChanged.connect(self._write)
            form.addRow("Id", self.f_id)
            form.addRow("Name", self.f_name)
            form.addRow("Giver", self.f_giver)
            form.addRow("Faction/guild", self.f_faction)
            form.addRow("XP", self.f_xp)
            form.addRow("Summary", self.f_desc)
            form.addRow("Reward gold", self.f_gold)
            form.addRow("Reward items", self.f_items)
            form.addRow("Reward rep", self.f_rep)
            detail.addLayout(form)

            # ---- stages sub-editor ------------------------------------
            detail.addWidget(QtWidgets.QLabel("Stages:"))
            srow = QtWidgets.QHBoxLayout()
            self.slist = QtWidgets.QListWidget()
            self.slist.setMaximumWidth(200)
            self.slist.currentRowChanged.connect(self._select_stage)
            srow.addWidget(self.slist)

            sform = QtWidgets.QFormLayout()
            self.s_obj = QtWidgets.QLineEdit()
            self.s_obj.setPlaceholderText("Short objective shown in the HUD tracker")
            self.s_journal = QtWidgets.QPlainTextEdit()
            self.s_journal.setPlaceholderText("Journal paragraph for this stage…")
            self.s_journal.setMinimumHeight(80)
            self.s_cond = QtWidgets.QComboBox()
            for cid, label in _QUEST_COND_LABELS:
                self.s_cond.addItem(label, cid)
            self.s_target = QtWidgets.QLineEdit()
            self.s_count = QtWidgets.QSpinBox(); self.s_count.setRange(1, 100000)
            self.s_finishes = QtWidgets.QCheckBox("Finishing this stage completes the quest")
            self.s_obj.editingFinished.connect(self._write_stage)
            self.s_target.editingFinished.connect(self._write_stage)
            self.s_journal.textChanged.connect(self._write_stage)
            self.s_cond.currentIndexChanged.connect(self._on_cond_kind)
            self.s_count.valueChanged.connect(self._write_stage)
            self.s_finishes.stateChanged.connect(self._write_stage)
            sform.addRow("Objective", self.s_obj)
            sform.addRow("Journal", self.s_journal)
            sform.addRow("Completes by", self.s_cond)
            sform.addRow("Target", self.s_target)
            sform.addRow("Count", self.s_count)
            sform.addRow("", self.s_finishes)
            srow.addLayout(sform, 1)
            detail.addLayout(srow)

            sb = QtWidgets.QHBoxLayout()
            sadd = QtWidgets.QPushButton("Add stage")
            srem = QtWidgets.QPushButton("Remove stage")
            sup = QtWidgets.QPushButton("↑"); sdn = QtWidgets.QPushButton("↓")
            sadd.clicked.connect(self._add_stage); srem.clicked.connect(self._remove_stage)
            sup.clicked.connect(lambda: self._move_stage(-1))
            sdn.clicked.connect(lambda: self._move_stage(1))
            for b in (sadd, srem, sup, sdn):
                sb.addWidget(b)
            sb.addStretch(1)
            detail.addLayout(sb)

            dw = QtWidgets.QWidget(); dw.setLayout(detail)
            scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True)
            scroll.setWidget(dw)
            split.addWidget(scroll, 1)
            root.addLayout(split)
            self._reload()

        # -- quest-level data --------------------------------------------------
        def _quests(self):
            q = self.thing.properties.get("quests")
            if not isinstance(q, list):
                q = []; self.thing.properties["quests"] = q
            return q

        def _current(self):
            row = self.qlist.currentRow()
            qs = self._quests()
            return (row, qs[row]) if 0 <= row < len(qs) else (-1, None)

        def _reload(self):
            self._loading = True
            self.qlist.clear()
            for q in self._quests():
                self.qlist.addItem(q.get("name") or q.get("id") or "(unnamed)")
            self._loading = False
            if self.qlist.count():
                self.qlist.setCurrentRow(0)
            else:
                self._clear_form()

        def _clear_form(self):
            self._loading = True
            for w in (self.f_id, self.f_name, self.f_giver, self.f_faction,
                      self.f_items, self.f_rep):
                w.setText("")
            self.f_desc.setPlainText("")
            self.f_xp.setValue(0); self.f_gold.setValue(0)
            self.slist.clear()
            self._clear_stage_form()
            self._loading = False

        def _select(self, _):
            row, q = self._current()
            if q is None:
                self._clear_form(); return
            self._loading = True
            self.f_id.setText(str(q.get("id", "")))
            self.f_name.setText(str(q.get("name", "")))
            self.f_giver.setText(str(q.get("giver", "")))
            self.f_faction.setText(str(q.get("faction", "")))
            self.f_xp.setValue(int(q.get("xp", 0)))
            self.f_desc.setPlainText(str(q.get("desc", "")))
            rw = q.get("rewards", {}) or {}
            self.f_gold.setValue(int(rw.get("gold", 0)))
            self.f_items.setText(" ; ".join(f"{i[0]},{i[1]}" for i in rw.get("items", [])))
            rep = rw.get("rep")
            self.f_rep.setText(f"{rep[0]},{rep[1]}" if rep else "")
            self._reload_stages()
            self._loading = False

        def _write(self, *_):
            if self._loading:
                return
            row, q = self._current()
            if q is None:
                return
            q["id"] = self.f_id.text().strip()
            q["name"] = self.f_name.text().strip()
            q["giver"] = self.f_giver.text().strip()
            q["faction"] = self.f_faction.text().strip()
            q["xp"] = self.f_xp.value()
            q["desc"] = self.f_desc.toPlainText().strip()
            rewards = {"gold": self.f_gold.value()}
            items = []
            for chunk in self.f_items.text().replace("\n", ";").split(";"):
                chunk = chunk.strip()
                if not chunk:
                    continue
                if "," in chunk:
                    iid, qty = chunk.split(",", 1)
                    try: items.append([iid.strip(), int(qty.strip())])
                    except ValueError: items.append([iid.strip(), 1])
                else:
                    items.append([chunk, 1])
            if items:
                rewards["items"] = items
            rep = self.f_rep.text().strip()
            if "," in rep:
                g, a = rep.split(",", 1)
                try: rewards["rep"] = [g.strip(), int(a.strip())]
                except ValueError: pass
            q["rewards"] = rewards
            item = self.qlist.item(row)
            if item is not None:
                item.setText(q.get("name") or q.get("id") or "(unnamed)")

        def _add(self):
            self._quests().append({
                "id": f"quest_{len(self._quests())+1}", "name": "New Quest",
                "giver": "", "desc": "",
                "stages": [{"index": 0, "journal": "", "objective": "",
                            "finishes": False,
                            "condition": {"kind": "none", "target": "", "count": 1}}]})
            self._reload()
            self.qlist.setCurrentRow(self.qlist.count() - 1)

        def _remove(self):
            row, q = self._current()
            if q is not None:
                del self._quests()[row]; self._reload()

        # -- stage-level data --------------------------------------------------
        def _stages(self):
            _row, q = self._current()
            if q is None:
                return []
            s = q.get("stages")
            if not isinstance(s, list):
                s = []; q["stages"] = s
            return s

        def _cur_stage(self):
            row = self.slist.currentRow()
            st = self._stages()
            return (row, st[row]) if 0 <= row < len(st) else (-1, None)

        def _reload_stages(self):
            self.slist.clear()
            for s in self._stages():
                label = f"{s.get('index',0)}: {s.get('objective') or s.get('journal') or '(stage)'}"
                self.slist.addItem(label[:40])
            if self.slist.count():
                self.slist.setCurrentRow(0)
            else:
                self._clear_stage_form()

        def _clear_stage_form(self):
            self.s_obj.setText(""); self.s_journal.setPlainText("")
            self.s_target.setText(""); self.s_count.setValue(1)
            self.s_finishes.setChecked(False); self.s_cond.setCurrentIndex(0)
            self._update_target_hint()

        def _select_stage(self, _):
            _r, s = self._cur_stage()
            if s is None:
                self._clear_stage_form(); return
            self._loading = True
            self.s_obj.setText(str(s.get("objective", "")))
            self.s_journal.setPlainText(str(s.get("journal", "")))
            self.s_finishes.setChecked(bool(s.get("finishes")))
            cond = s.get("condition") or {}
            idx = self.s_cond.findData(str(cond.get("kind", "none")))
            self.s_cond.setCurrentIndex(idx if idx >= 0 else 0)
            self.s_target.setText(str(cond.get("target", "")))
            try:
                self.s_count.setValue(max(1, int(cond.get("count", 1))))
            except (TypeError, ValueError):
                self.s_count.setValue(1)
            self._update_target_hint()
            self._loading = False

        def _on_cond_kind(self, _):
            self._update_target_hint()
            self._write_stage()

        def _update_target_hint(self):
            kind = self.s_cond.currentData() or "none"
            self.s_target.setPlaceholderText(_QUEST_COND_TARGET_HINT.get(kind, ""))
            self.s_target.setEnabled(kind != "none")
            self.s_count.setEnabled(kind in ("fetch", "kill"))

        def _write_stage(self, *_):
            if self._loading:
                return
            row, s = self._cur_stage()
            if s is None:
                return
            s["objective"] = self.s_obj.text().strip()
            s["journal"] = self.s_journal.toPlainText().strip()
            s["finishes"] = self.s_finishes.isChecked()
            s["condition"] = {"kind": self.s_cond.currentData() or "none",
                              "target": self.s_target.text().strip(),
                              "count": self.s_count.value()}
            item = self.slist.item(row)
            if item is not None:
                label = f"{s.get('index',0)}: {s.get('objective') or s.get('journal') or '(stage)'}"
                item.setText(label[:40])

        def _add_stage(self):
            st = self._stages()
            if st is None:
                return
            nxt = (max((s.get("index", 0) for s in st), default=-10) + 10) if st else 0
            st.append({"index": nxt, "journal": "", "objective": "",
                       "finishes": False,
                       "condition": {"kind": "none", "target": "", "count": 1}})
            self._reload_stages()
            self.slist.setCurrentRow(self.slist.count() - 1)

        def _remove_stage(self):
            row, s = self._cur_stage()
            if s is not None:
                del self._stages()[row]; self._reload_stages()

        def _move_stage(self, delta):
            row, s = self._cur_stage()
            st = self._stages()
            j = row + delta
            if s is None or not (0 <= j < len(st)):
                return
            # Swap positions AND their index values so ordering stays coherent.
            st[row]["index"], st[j]["index"] = st[j].get("index", 0), st[row].get("index", 0)
            st[row], st[j] = st[j], st[row]
            self._reload_stages()
            self.slist.setCurrentRow(j)

    return Tab()
