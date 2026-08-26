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
                # Living/attacking sprite follow the head; custom_dead is left as
                # the role's corpse/gore sprite so a killed or gibbed NPC shows
                # gore, not the living head.
                for k in ("custom_idle", "custom_shoot"):
                    self.thing.properties[k] = path
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


# --- Player Spells tab: pastel, one-card-per-line, RPG-styled ----------------

#: Pastel wash + dark ink per magic school (mirrors make_spell_icons).
_SCHOOL_PASTEL = {
    "destruction": ("#f6cdc8", "#7a3730"),
    "restoration": ("#cdeed2", "#2f6f4a"),
    "alteration":  ("#cee0f8", "#37628f"),
    "conjuration": ("#e0d2f6", "#5f4296"),
    "illusion":    ("#f7d6f0", "#8a4276"),
    "mysticism":   ("#cdeeec", "#2e7674"),
    "default":     ("#e4e2e8", "#5a5a66"),
}


def _school_pastel(school):
    return _SCHOOL_PASTEL.get(str(school or "").lower(), _SCHOOL_PASTEL["default"])


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

            # 100x100 icon placeholder (its own art when present).
            icon = QtWidgets.QLabel()
            icon.setFixedSize(100, 100)
            icon.setAlignment(Qt.AlignCenter)
            icon.setStyleSheet("background:rgba(255,255,255,60); border:1px solid %s;"
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
            name.setStyleSheet("color:#241f18; border:none; background:transparent;")
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
            stat.setStyleSheet("color:#4a4034; border:none; background:transparent;")
            mid.addWidget(stat)
            if desc:
                dl = QtWidgets.QLabel(desc)
                dl.setWordWrap(True)
                df = _rpg_font(QtGui, 9); df.setItalic(True)
                dl.setFont(df)
                dl.setStyleSheet("color:#5a5045; border:none; background:transparent;")
                mid.addWidget(dl)
            mid.addStretch(1)
            lay.addLayout(mid, 1)

            self.tick = QtWidgets.QLabel("✓")
            tf = _rpg_font(QtGui, 20, bold=True); self.tick.setFont(tf)
            self.tick.setStyleSheet("color:#2f7a3a; border:none; background:transparent;")
            self.tick.setFixedWidth(24)
            self.tick.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
            lay.addWidget(self.tick)
            self._restyle()

        def _restyle(self):
            self.tick.setVisible(self.selected)
            border = ("3px solid %s" % self.ink) if self.selected else "1px solid #7a7a86"
            self.setStyleSheet("QFrame { background:%s; border:%s; border-radius:10px; }"
                               % (self.bg, border))

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
    from PyQt5 import QtGui
    from .rpg import magic

    COLS = ["Spell", "Colour", "Dmg/shot", "Speed"]

    class Tab(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.thing = thing
            self._loading = False
            self._choices = _castable_spells()
            layout = QtWidgets.QVBoxLayout(self)

            # Add / Remove pinned to the very top of the tab.
            btns = QtWidgets.QHBoxLayout()
            add = QtWidgets.QPushButton("Add Spell")
            rem = QtWidgets.QPushButton("Remove Selected")
            add.clicked.connect(self._add)
            rem.clicked.connect(self._remove)
            btns.addWidget(add); btns.addWidget(rem); btns.addStretch(1)
            layout.addLayout(btns)

            layout.addWidget(_hint_label(
                QtWidgets,
                "Spells this NPC casts. Each bolt uses its own colour, damage and "
                "speed. A magic-armed NPC cycles through the list, one per shot."))

            # Casting only happens when the NPC's combat style is Magic.
            self.cast_cb = QtWidgets.QCheckBox("Casts spells (sets combat style to Magic)")
            self.cast_cb.setChecked(
                str(thing.properties.get("attack_style", "")).lower() == "magic")
            self.cast_cb.stateChanged.connect(self._on_cast_toggle)
            layout.addWidget(self.cast_cb)

            self.table = QtWidgets.QTableWidget(0, len(COLS))
            self.table.setHorizontalHeaderLabels(COLS)
            self.table.horizontalHeader().setStretchLastSection(True)
            layout.addWidget(self.table)
            self._reload()

        # -- data ------------------------------------------------------
        def _spells(self):
            s = self.thing.properties.get("spells")
            if not isinstance(s, list):
                s = []
                self.thing.properties["spells"] = s
            return s

        def _on_cast_toggle(self, _state):
            if self.cast_cb.isChecked():
                self.thing.properties["attack_style"] = "magic"
                self.thing.properties["combatant"] = True
            elif str(self.thing.properties.get("attack_style", "")).lower() == "magic":
                self.thing.properties["attack_style"] = "melee"

        def _reload(self):
            self._loading = True
            spells = self._spells()
            self.table.setRowCount(len(spells))
            for r, entry in enumerate(spells):
                self._build_row(r, entry)
            self._loading = False

        def _build_row(self, r, entry):
            # Spell picker
            combo = QtWidgets.QComboBox()
            for sid, label in self._choices:
                combo.addItem(label, sid)
            idx = combo.findData(entry.get("id"))
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.currentIndexChanged.connect(lambda _i, row=r: self._on_spell_changed(row))
            self.table.setCellWidget(r, 0, combo)

            # Colour swatch button
            btn = QtWidgets.QPushButton()
            btn.setFixedWidth(60)
            self._paint_swatch(btn, entry.get("color") or [140, 160, 255])
            btn.clicked.connect(lambda _c, row=r: self._pick_colour(row))
            self.table.setCellWidget(r, 1, btn)

            # Damage per shot
            dmg = QtWidgets.QSpinBox()
            dmg.setRange(0, 100000)
            dmg.setValue(int(entry.get("damage", 0) or 0))
            dmg.valueChanged.connect(lambda v, row=r: self._set(row, "damage", int(v)))
            self.table.setCellWidget(r, 2, dmg)

            # Projectile speed
            spd = QtWidgets.QDoubleSpinBox()
            spd.setRange(0.0, 100000.0)
            spd.setDecimals(0)
            spd.setSingleStep(50.0)
            spd.setValue(float(entry.get("speed", 0) or 0))
            spd.valueChanged.connect(lambda v, row=r: self._set(row, "speed", float(v)))
            self.table.setCellWidget(r, 3, spd)

        def _paint_swatch(self, btn, rgb):
            r, g, b = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
            btn.setStyleSheet(
                f"background-color: rgb({r},{g},{b}); border: 1px solid #222;")
            btn.setText(f"{r},{g},{b}")

        def _defaults_for(self, sid):
            sp = magic.get(sid)
            if sp is None:
                return {"color": [140, 160, 255], "damage": 0, "speed": 900.0}
            return {"color": list(sp.color), "damage": int(sp.damage),
                    "speed": float(sp.projectile_speed)}

        # -- edits -----------------------------------------------------
        def _add(self):
            sid = self._choices[0][0] if self._choices else "flare"
            d = self._defaults_for(sid)
            self._spells().append({"id": sid, "color": d["color"],
                                   "damage": d["damage"], "speed": d["speed"]})
            self._reload()

        def _remove(self):
            row = self.table.currentRow()
            spells = self._spells()
            if 0 <= row < len(spells):
                del spells[row]
                self._reload()

        def _on_spell_changed(self, row):
            if self._loading:
                return
            spells = self._spells()
            if not (0 <= row < len(spells)):
                return
            combo = self.table.cellWidget(row, 0)
            sid = combo.currentData()
            # Adopt the spell's own colour/damage/speed as sensible new defaults.
            d = self._defaults_for(sid)
            spells[row].update({"id": sid, "color": d["color"],
                                "damage": d["damage"], "speed": d["speed"]})
            self._reload()

        def _set(self, row, key, value):
            if self._loading:
                return
            spells = self._spells()
            if 0 <= row < len(spells):
                spells[row][key] = value

        def _pick_colour(self, row):
            spells = self._spells()
            if not (0 <= row < len(spells)):
                return
            cur = spells[row].get("color") or [140, 160, 255]
            initial = QtGui.QColor(int(cur[0]), int(cur[1]), int(cur[2]))
            chosen = QtWidgets.QColorDialog.getColor(initial, self, "Projectile colour")
            if chosen.isValid():
                rgb = [chosen.red(), chosen.green(), chosen.blue()]
                spells[row]["color"] = rgb
                btn = self.table.cellWidget(row, 1)
                if btn is not None:
                    self._paint_swatch(btn, rgb)

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

    class Dialog(QtWidgets.QDialog):
        def __init__(self):
            super().__init__(parent)
            self.setWindowTitle("Spell Editor")
            self.resize(760, 460)
            # Work on a copy of every current spell (built-ins + any custom).
            self.rows = [magic.get(sid).to_dict() for sid in sorted(magic.SPELLS)]
            self._loading = False

            layout = QtWidgets.QVBoxLayout(self)
            layout.addWidget(_hint_label(
                QtWidgets,
                "Edit the spell definitions. Colour drives the projectile bolt and "
                "its light. Saving writes game/data/spells.json and applies to the "
                "live game."))
            self.table = QtWidgets.QTableWidget(0, len(COLS))
            self.table.setHorizontalHeaderLabels(COLS)
            self.table.horizontalHeader().setStretchLastSection(True)
            layout.addWidget(self.table)

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
            self._loading = True
            self.table.setRowCount(len(self.rows))
            for r, d in enumerate(self.rows):
                self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(str(d.get("id", ""))))
                self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(d.get("name", ""))))
                elem = QtWidgets.QComboBox(); elem.addItems(ELEMENTS)
                elem.setCurrentText(str(d.get("element", "magic")))
                elem.currentTextChanged.connect(lambda t, row=r: self._set(row, "element", t))
                self.table.setCellWidget(r, 2, elem)
                swatch = QtWidgets.QPushButton()
                self._paint(swatch, d.get("color") or magic.element_color(d.get("element")))
                swatch.clicked.connect(lambda _c, row=r: self._pick(row))
                self.table.setCellWidget(r, 3, swatch)
                dmg = QtWidgets.QSpinBox(); dmg.setRange(0, 100000)
                dmg.setValue(int(_damage_of(d)))
                dmg.valueChanged.connect(lambda v, row=r: self._set_dmg(row, v))
                self.table.setCellWidget(r, 4, dmg)
                cost = QtWidgets.QSpinBox(); cost.setRange(0, 100000)
                cost.setValue(int(d.get("cost", 0)))
                cost.valueChanged.connect(lambda v, row=r: self._set(row, "cost", int(v)))
                self.table.setCellWidget(r, 5, cost)
                spd = QtWidgets.QDoubleSpinBox(); spd.setRange(0.0, 100000.0)
                spd.setDecimals(0); spd.setSingleStep(50.0)
                spd.setValue(float(d.get("projectile_speed", 900.0)))
                spd.valueChanged.connect(lambda v, row=r: self._set(row, "projectile_speed", float(v)))
                self.table.setCellWidget(r, 6, spd)
                dlv = QtWidgets.QComboBox(); dlv.addItems(DELIVERIES)
                dlv.setCurrentText(str(d.get("delivery", magic.PROJECTILE)))
                dlv.currentTextChanged.connect(lambda t, row=r: self._set(row, "delivery", t))
                self.table.setCellWidget(r, 7, dlv)
            self._loading = False
            self.table.itemChanged.connect(self._on_item_changed)

        def _paint(self, btn, rgb):
            r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
            btn.setStyleSheet(f"background-color: rgb({r},{g},{b}); border: 1px solid #222;")
            btn.setText(f"{r},{g},{b}")

        def _on_item_changed(self, item):
            if self._loading:
                return
            r, c = item.row(), item.column()
            if 0 <= r < len(self.rows):
                if c == 0:
                    self.rows[r]["id"] = item.text().strip()
                elif c == 1:
                    self.rows[r]["name"] = item.text()

        def _set(self, row, key, value):
            if 0 <= row < len(self.rows):
                self.rows[row][key] = value

        def _set_dmg(self, row, value):
            if 0 <= row < len(self.rows):
                _set_damage(self.rows[row], int(value))

        def _pick(self, row):
            cur = self.rows[row].get("color") or magic.element_color(self.rows[row].get("element"))
            initial = QtGui.QColor(int(cur[0]), int(cur[1]), int(cur[2]))
            chosen = QtWidgets.QColorDialog.getColor(initial, self, "Projectile colour")
            if chosen.isValid():
                rgb = [chosen.red(), chosen.green(), chosen.blue()]
                self.rows[row]["color"] = rgb
                self._paint(self.table.cellWidget(row, 3), rgb)

        def _add(self):
            base = {"id": "new_spell", "name": "New Spell", "school": sk.DESTRUCTION,
                    "cost": 15, "delivery": magic.PROJECTILE,
                    "effects": [{"kind": "damage_health", "magnitude": 20, "duration": 0}],
                    "desc": "", "element": "magic", "projectile_speed": 900.0,
                    "color": None}
            self.rows.append(base)
            self._reload()

        def _remove(self):
            row = self.table.currentRow()
            if 0 <= row < len(self.rows):
                del self.rows[row]
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
_QUEST_STAGE_HELP = (
    "Stages (one per line):  index | journal text | objective | finishes\n"
    "  e.g.  0 | Clear the cave of goblins. | Clear the cave | no\n"
    "        10 | The cave is clear. Return for your reward. | Return | no\n"
    "        20 | Paid in full. | | yes")


def make_quests_tab(thing):
    try:
        QtWidgets, QtCore = _qt()
    except Exception:  # pragma: no cover
        return None
    return _QuestsTab(thing, QtWidgets, QtCore)


def _QuestsTab(thing, QtWidgets, QtCore):
    class Tab(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.thing = thing
            self.thing.properties.setdefault("quests", [])
            self._loading = False
            layout = QtWidgets.QVBoxLayout(self)

            body = QtWidgets.QHBoxLayout()
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
            body.addLayout(left, 1)

            form = QtWidgets.QFormLayout()
            self.f_id = QtWidgets.QLineEdit()
            self.f_name = QtWidgets.QLineEdit()
            self.f_giver = QtWidgets.QLineEdit()
            self.f_faction = QtWidgets.QLineEdit()
            self.f_xp = QtWidgets.QSpinBox(); self.f_xp.setRange(0, 100000)
            self.f_desc = QtWidgets.QLineEdit()
            self.f_gold = QtWidgets.QSpinBox(); self.f_gold.setRange(0, 1000000)
            self.f_items = QtWidgets.QLineEdit()
            self.f_items.setPlaceholderText("item_id,qty ; item_id,qty")
            self.f_rep = QtWidgets.QLineEdit()
            self.f_rep.setPlaceholderText("guild_id,amount")
            self.f_stages = QtWidgets.QPlainTextEdit()
            for w in (self.f_id, self.f_name, self.f_giver, self.f_faction,
                      self.f_desc, self.f_items, self.f_rep):
                w.editingFinished.connect(self._write)
            self.f_xp.valueChanged.connect(self._write)
            self.f_gold.valueChanged.connect(self._write)
            self.f_stages.textChanged.connect(self._write)
            form.addRow("Id", self.f_id)
            form.addRow("Name", self.f_name)
            form.addRow("Giver", self.f_giver)
            form.addRow("Faction/guild", self.f_faction)
            form.addRow("XP", self.f_xp)
            form.addRow("Summary", self.f_desc)
            form.addRow("Reward gold", self.f_gold)
            form.addRow("Reward items", self.f_items)
            form.addRow("Reward rep", self.f_rep)
            form.addRow("Stages", self.f_stages)
            form.addRow(_hint_label(QtWidgets, _QUEST_STAGE_HELP))
            body.addLayout(form, 2)
            layout.addLayout(body)
            self._reload()

        def _quests(self):
            q = self.thing.properties.get("quests")
            if not isinstance(q, list):
                q = []; self.thing.properties["quests"] = q
            return q

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
                      self.f_desc, self.f_items, self.f_rep):
                w.setText("")
            self.f_xp.setValue(0); self.f_gold.setValue(0)
            self.f_stages.setPlainText("")
            self._loading = False

        def _current(self):
            row = self.qlist.currentRow()
            qs = self._quests()
            return (row, qs[row]) if 0 <= row < len(qs) else (-1, None)

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
            self.f_desc.setText(str(q.get("desc", "")))
            rw = q.get("rewards", {}) or {}
            self.f_gold.setValue(int(rw.get("gold", 0)))
            self.f_items.setText(" ; ".join(f"{i[0]},{i[1]}" for i in rw.get("items", [])))
            rep = rw.get("rep")
            self.f_rep.setText(f"{rep[0]},{rep[1]}" if rep else "")
            self.f_stages.setPlainText("\n".join(self._fmt_stage(s) for s in q.get("stages", [])))
            self._loading = False

        @staticmethod
        def _fmt_stage(s):
            return (f"{s.get('index',0)} | {s.get('journal','')} | "
                    f"{s.get('objective','')} | {'yes' if s.get('finishes') else 'no'}")

        def _write(self, *_):
            if self._loading: return
            row, q = self._current()
            if q is None: return
            q["id"] = self.f_id.text().strip()
            q["name"] = self.f_name.text().strip()
            q["giver"] = self.f_giver.text().strip()
            q["faction"] = self.f_faction.text().strip()
            q["xp"] = self.f_xp.value()
            q["desc"] = self.f_desc.text().strip()
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
            stages = []
            for line in self.f_stages.toPlainText().splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = [p.strip() for p in line.split("|")]
                try: idx = int(parts[0])
                except (ValueError, IndexError): idx = len(stages) * 10
                stages.append({
                    "index": idx,
                    "journal": parts[1] if len(parts) > 1 else "",
                    "objective": parts[2] if len(parts) > 2 else "",
                    "finishes": len(parts) > 3 and parts[3].lower() in ("yes", "true", "1"),
                })
            q["stages"] = stages
            # refresh the list label without losing selection
            item = self.qlist.item(row)
            if item is not None:
                item.setText(q.get("name") or q.get("id") or "(unnamed)")

        def _add(self):
            self._quests().append({"id": f"quest_{len(self._quests())+1}",
                                   "name": "New Quest", "stages": [
                                       {"index": 0, "journal": "", "finishes": False}]})
            self._reload()
            self.qlist.setCurrentRow(self.qlist.count() - 1)

        def _remove(self):
            row, q = self._current()
            if q is not None:
                del self._quests()[row]; self._reload()

    return Tab()
