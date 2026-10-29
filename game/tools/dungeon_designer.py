"""
The Dungeon Designer: draw a dungeon on a grid, the way Fio's alpha editor
did, and save it as a playable MiniWind map.

* **Paint** -- left-click or drag paints the brush (SOLID or OPEN); right-
  click or drag paints the other one; Ctrl+click flood-fills.
* **Markers** -- the Entrance (the way in and out: the PlayerStart and the
  LevelChanger back), Monsters, Chests and Lights. Right-click removes one.
* **Generate** -- fills the grid with one of alpha's generators
  (``game/tilemap_gen.py``): rooms and corridors, or winding corridors.
  Whatever is not reachable from the entrance is filled in.
* **Save** writes ``maps/<name>.json`` (``game/dungeon_map.py``); the design
  rides inside the map, so **Load** opens any map made here again.

Opened from the editor's Tools menu (Dungeon Designer…), or on its own::

    python -m game.tools.dungeon_designer
"""

from __future__ import annotations

import json
import os
import random

import numpy as np
from PyQt5.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPen
from PyQt5.QtWidgets import (QApplication, QButtonGroup, QComboBox, QDialog,
                             QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                             QLabel, QLineEdit, QMessageBox, QPushButton,
                             QRadioButton, QScrollArea, QShortcut, QSpinBox, QVBoxLayout,
                             QWidget)

from .. import dungeon_map as dm
from .. import tilemap_gen as tg

#: Alpha's editor colours.
SOLID_COLOUR = QColor("#2c3e50")
OPEN_COLOUR = QColor("#bdc3c7")
MARKER_STYLE = {
    "entrance": (QColor("#27ae60"), "E"),
    "monster": (QColor("#c0392b"), "M"),
    "chest": (QColor("#f1c40f"), "C"),
    "light": (QColor("#f5e6a8"), "L"),
}
BRUSHES = (("solid", "Solid"), ("open", "Open (not solid)"), ("entrance", "Entrance"),
           ("monster", "Monster"), ("chest", "Chest"), ("light", "Light"))
UNDO_LIMIT = 60


class GridCanvas(QWidget):
    """The grid: paints, fills and places markers on the design."""

    changed = pyqtSignal()
    about_to_change = pyqtSignal()

    def __init__(self, designer):
        super().__init__()
        self.designer = designer
        self.setMinimumSize(480, 360)
        self.setMouseTracking(True)
        self._painting = None        # "solid" / "open" while a drag paints
        self._hover = None

    # -- geometry --------------------------------------------------------------
    def _metrics(self):
        d = self.designer.design
        size = max(2, min(self.width() // d.width, self.height() // d.height))
        ox = (self.width() - size * d.width) // 2
        oy = (self.height() - size * d.height) // 2
        return size, ox, oy

    def cell_at(self, pos):
        d = self.designer.design
        size, ox, oy = self._metrics()
        j = (pos.x() - ox) // size
        i = (pos.y() - oy) // size
        if 0 <= i < d.height and 0 <= j < d.width:
            return int(i), int(j)
        return None

    # -- drawing ---------------------------------------------------------------
    def paintEvent(self, _event):
        d = self.designer.design
        size, ox, oy = self._metrics()
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1b2631"))
        for i in range(d.height):
            for j in range(d.width):
                p.fillRect(ox + j * size, oy + i * size, size, size,
                           SOLID_COLOUR if d.solid[i, j] else OPEN_COLOUR)
        if size >= 8:
            p.setPen(QPen(QColor(0, 0, 0, 50), 1))
            for j in range(d.width + 1):
                p.drawLine(ox + j * size, oy, ox + j * size, oy + d.height * size)
            for i in range(d.height + 1):
                p.drawLine(ox, oy + i * size, ox + d.width * size, oy + i * size)
        font = QFont("Fio UI", max(6, int(size * 0.55)), QFont.Bold)
        p.setFont(font)
        for m in d.markers:
            colour, letter = MARKER_STYLE.get(m["kind"], (QColor("white"), "?"))
            r = QRect(ox + m["j"] * size + 1, oy + m["i"] * size + 1, size - 2, size - 2)
            p.setPen(QPen(QColor(0, 0, 0, 160), 1))
            p.setBrush(colour)
            p.drawEllipse(r)
            if size >= 10:
                p.setPen(QColor("black"))
                p.drawText(r, Qt.AlignCenter, letter)
        if self._hover is not None:
            i, j = self._hover
            p.setPen(QPen(QColor("#e74c3c"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(ox + j * size, oy + i * size, size, size)
        p.end()

    # -- input -------------------------------------------------------------------
    def mousePressEvent(self, event):
        cell = self.cell_at(event.pos())
        if cell is None:
            return
        brush = self.designer.brush
        d = self.designer.design
        self.about_to_change.emit()
        right = event.button() == Qt.RightButton
        if brush in ("solid", "open"):
            paint = brush if not right else ("open" if brush == "solid" else "solid")
            if event.modifiers() & Qt.ControlModifier and not right:
                self._fill(cell, paint == "solid")
            else:
                self._painting = paint
                self._paint(cell)
        elif right:
            d.remove_marker(*cell)
        else:
            d.set_marker(cell[0], cell[1], brush, **self.designer.marker_options(brush))
        self.changed.emit()
        self.update()

    def mouseMoveEvent(self, event):
        cell = self.cell_at(event.pos())
        if cell != self._hover:
            self._hover = cell
            self.update()
        if self._painting and cell is not None:
            self._paint(cell)
            self.changed.emit()

    def mouseReleaseEvent(self, _event):
        self._painting = None

    def leaveEvent(self, _event):
        self._hover = None
        self.update()

    def _paint(self, cell):
        d = self.designer.design
        solid = self._painting == "solid"
        if d.solid[cell] != solid:
            d.solid[cell] = solid
            if solid:
                d.remove_marker(*cell)
            self.update()

    def _fill(self, cell, solid):
        """Flood-fill the region of like cells round *cell* (alpha's Ctrl+click)."""
        d = self.designer.design
        target = bool(d.solid[cell])
        if target == solid:
            return
        stack = [cell]
        while stack:
            i, j = stack.pop()
            if not (0 <= i < d.height and 0 <= j < d.width) or d.solid[i, j] != target:
                continue
            d.solid[i, j] = solid
            stack.extend(((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)))
        if solid:
            d.drop_buried_markers()


class DungeonDesigner(QDialog):
    def __init__(self, parent=None, main_window=None):
        super().__init__(parent)
        self.setWindowTitle("Dungeon Designer")
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        self.resize(1180, 760)
        self.main_window = main_window
        self.design = dm.Design(40, 30)
        self.brush = "open"
        self._undo = []
        self._build()
        self._load_fields()
        self._refresh_status()

    # -- layout ------------------------------------------------------------------
    def _build(self):
        root = QHBoxLayout(self)
        self.canvas = GridCanvas(self)
        self.canvas.about_to_change.connect(self._push_undo)
        self.canvas.changed.connect(self._refresh_status)
        root.addWidget(self.canvas, 1)
        side_widget = QWidget()
        side = QVBoxLayout(side_widget)
        side.setContentsMargins(0, 0, 0, 0)
        side_scroll = QScrollArea()
        side_scroll.setWidgetResizable(True)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        side_scroll.setWidget(side_widget)
        root.addWidget(side_scroll)

        box = QGroupBox("Map")
        form = QFormLayout(box)
        self.name_edit = QLineEdit()
        self.name_edit.textEdited.connect(self._name_changed)
        self.file_edit = QLineEdit()
        self.style_combo = QComboBox()
        self.style_combo.addItems(list(dm.STYLES))
        form.addRow("Name", self.name_edit)
        form.addRow("File", self.file_edit)
        form.addRow("Look", self.style_combo)
        side.addWidget(box)

        box = QGroupBox("Grid")
        row = QHBoxLayout(box)
        self.w_spin = QSpinBox()
        self.w_spin.setRange(8, 160)
        self.h_spin = QSpinBox()
        self.h_spin.setRange(8, 160)
        resize = QPushButton("Resize")
        resize.clicked.connect(self._resize)
        row.addWidget(QLabel("W"))
        row.addWidget(self.w_spin)
        row.addWidget(QLabel("H"))
        row.addWidget(self.h_spin)
        row.addWidget(resize)
        side.addWidget(box)

        box = QGroupBox("Generate (Fio alpha)")
        form = QFormLayout(box)
        self.method_combo = QComboBox()
        for key, label in tg.METHODS.items():
            self.method_combo.addItem(label, key)
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 999999)
        self.seed_spin.setValue(random.randint(0, 999999))
        dice = QPushButton()
        dice.setIcon(QIcon("assets/ui/controls/dice.svg"))
        dice.setFixedWidth(34)
        dice.setToolTip("A new random seed")
        dice.clicked.connect(lambda: self.seed_spin.setValue(random.randint(0, 999999)))
        seed_row = QHBoxLayout()
        seed_row.addWidget(self.seed_spin, 1)
        seed_row.addWidget(dice)
        gen = QPushButton("Generate")
        gen.clicked.connect(self._generate)
        form.addRow("Method", self.method_combo)
        form.addRow("Seed", seed_row)
        form.addRow(gen)
        side.addWidget(box)

        box = QGroupBox("Brush")
        col = QVBoxLayout(box)
        self.brush_group = QButtonGroup(self)
        for key, label in BRUSHES:
            rb = QRadioButton(label)
            rb.setChecked(key == self.brush)
            rb.toggled.connect(lambda on, k=key: on and self._set_brush(k))
            self.brush_group.addButton(rb)
            col.addWidget(rb)
        hint = QLabel("Left: paint · Right: the other / remove marker\nCtrl+click: fill")
        hint.setStyleSheet("color: gray;")
        col.addWidget(hint)
        side.addWidget(box)

        box = QGroupBox("Markers")
        form = QFormLayout(box)
        self.role_combo = QComboBox()
        for role in _monster_roles():
            self.role_combo.addItem(role.replace("_", " ").title(), role)
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 6)
        self.loot_edit = QLineEdit("gold:40, potion_heal:1")
        self.light_combo = QComboBox()
        self.light_combo.addItems(list(dm.LIGHT_COLOURS))
        form.addRow("Monster", self.role_combo)
        form.addRow("How many", self.count_spin)
        form.addRow("Chest loot", self.loot_edit)
        form.addRow("Light", self.light_combo)
        side.addWidget(box)

        box = QGroupBox("Way out")
        form = QFormLayout(box)
        self.exit_map_edit = QLineEdit()
        self.exit_spawn_edit = QLineEdit()
        self.exit_spawn_edit.setPlaceholderText("(that map's main start)")
        form.addRow("To map", self.exit_map_edit)
        form.addRow("At start", self.exit_spawn_edit)
        side.addWidget(box)

        self.status = QLabel()
        self.status.setWordWrap(True)
        side.addWidget(self.status)
        side.addStretch(1)

        buttons = QHBoxLayout()
        for label, slot in (("Undo", self._undo_last), ("Clear", self._clear),
                            ("Load…", self._load)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        side.addLayout(buttons)
        buttons = QHBoxLayout()
        save = QPushButton("Save")
        save.clicked.connect(lambda: self._save(open_after=False))
        save_open = QPushButton("Save && Open")
        save_open.setToolTip("Save, then open the map in the editor")
        save_open.clicked.connect(lambda: self._save(open_after=True))
        save_open.setEnabled(self.main_window is not None)
        buttons.addWidget(save)
        buttons.addWidget(save_open)
        side.addLayout(buttons)
        QShortcut(QKeySequence.Undo, self, activated=self._undo_last)
        side_scroll.setMinimumWidth(side_widget.minimumSizeHint().width() + 12)

    # -- fields <-> design ----------------------------------------------------------
    def _load_fields(self):
        d = self.design
        self.name_edit.setText(d.name)
        self.file_edit.setText(d.file)
        self.style_combo.setCurrentText(d.style)
        self.w_spin.setValue(d.width)
        self.h_spin.setValue(d.height)
        self.exit_map_edit.setText(d.exit_map)
        self.exit_spawn_edit.setText(d.exit_spawn)

    def _store_fields(self):
        d = self.design
        d.name = self.name_edit.text().strip() or "Dungeon"
        d.file = self.file_edit.text().strip() or "maps/dungeon01.json"
        d.style = self.style_combo.currentText()
        d.exit_map = self.exit_map_edit.text().strip()
        d.exit_spawn = self.exit_spawn_edit.text().strip()

    def _name_changed(self, text):
        slug = "".join(c.lower() if c.isalnum() else "_" for c in text).strip("_")
        if slug:
            self.file_edit.setText(f"maps/{slug}.json")

    def marker_options(self, kind):
        if kind == "monster":
            return {"role": self.role_combo.currentData(), "count": self.count_spin.value()}
        if kind == "chest":
            return {"loot": self.loot_edit.text()}
        if kind == "light":
            return {"colour": self.light_combo.currentText()}
        return {}

    def _set_brush(self, key):
        self.brush = key

    # -- editing -------------------------------------------------------------------
    def _push_undo(self):
        d = self.design
        self._undo.append((d.solid.copy(), json.dumps(d.markers)))
        del self._undo[:-UNDO_LIMIT]

    def _undo_last(self):
        if not self._undo:
            return
        solid, markers = self._undo.pop()
        self.design.solid = solid
        self.design.markers = json.loads(markers)
        self.w_spin.setValue(self.design.width)
        self.h_spin.setValue(self.design.height)
        self._changed()

    def _changed(self):
        self.canvas.update()
        self._refresh_status()

    def _resize(self):
        self._push_undo()
        self.design.resize(self.w_spin.value(), self.h_spin.value())
        self._changed()

    def _clear(self):
        self._push_undo()
        self.design.solid[:] = True
        self.design.markers = []
        self._changed()

    def _generate(self):
        self._push_undo()
        d = self.design
        if (d.width, d.height) != (self.w_spin.value(), self.h_spin.value()):
            d.resize(self.w_spin.value(), self.h_spin.value())
        d.generate(self.method_combo.currentData(), self.seed_spin.value())
        self._changed()

    def _refresh_status(self):
        d = self.design
        counts = {k: sum(1 for m in d.markers if m["kind"] == k) for k in dm.MARKER_KINDS}
        open_cells = int((~d.solid).sum())
        lines = [f"{d.width} × {d.height} · {open_cells} open cells",
                 f"{counts['monster']} monster markers · {counts['chest']} chests · "
                 f"{counts['light']} lights"]
        if not counts["entrance"]:
            lines.append("<b style='color:#c0392b'>No entrance yet</b> — one is put "
                         "on the open cell nearest the bottom when you save.")
        elif open_cells:
            e = d.entrance()
            dist = dm._distances(~d.solid, (e["i"], e["j"]))
            cut = int(((~d.solid) & (dist < 0)).sum())
            if cut:
                lines.append(f"<span style='color:#d35400'>{cut} open cells can't be "
                             f"reached from the entrance.</span>")
        self.status.setText("<br>".join(lines))

    # -- files -----------------------------------------------------------------------
    def _save(self, open_after):
        self._store_fields()
        d = self.design
        if not (~d.solid).any():
            QMessageBox.warning(self, "Dungeon Designer", "There is no open floor to save.")
            return
        d.ensure_entrance()
        path = d.file
        if not path.lower().endswith(".json"):
            path += ".json"
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if os.path.exists(path):
            try:
                with open(path) as f:
                    existing = json.load(f)
            except (OSError, ValueError):
                existing = {}
            if "_dungeon_design" not in existing:
                if QMessageBox.question(self, "Dungeon Designer",
                                        f"{path} exists and was not made here. Replace it?") \
                        != QMessageBox.Yes:
                    return
        dm.save(d, path)
        self._changed()
        msg = f"Saved {path}"
        toast = getattr(self.main_window, "show_toast", None)
        if toast:
            toast(msg)
        self.status.setText(self.status.text() + f"<br><b>{msg}</b>")
        if open_after and self.main_window is not None:
            opener = getattr(self.main_window, "open_level_file", None)
            if opener is not None:
                opener(path)

    def _load(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open a dungeon", "maps", "Maps (*.json)")
        if not path:
            return
        try:
            with open(path) as f:
                level = json.load(f)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Dungeon Designer", f"Cannot read {path}: {exc}")
            return
        design = dm.Design.from_map(level)
        if design is None:
            QMessageBox.information(self, "Dungeon Designer",
                                    f"{os.path.basename(path)} was not made in the Dungeon "
                                    "Designer, so it has no grid to edit.")
            return
        self._push_undo()
        self.design = design
        self._load_fields()
        self._changed()


def _monster_roles():
    try:
        from ..rpg import bestiary
        roles = [r for r in bestiary.roles_of_kind("creature")
                 if getattr(bestiary.get(r), "aggression", "") == "hostile"]
        if roles:
            return roles
    except Exception:
        pass
    return ["skeleton", "skeleton_archer", "wolf", "bandit", "cultist", "wraith"]


_open_windows = []


def open_designer(main_window=None):
    """Open a Dungeon Designer window (non-modal; several may be open)."""
    win = DungeonDesigner(main_window, main_window)
    win.setAttribute(Qt.WA_DeleteOnClose, True)
    _open_windows.append(win)
    win.destroyed.connect(lambda *_: _open_windows.remove(win) if win in _open_windows else None)
    win.show()
    return win


def main():
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    win = DungeonDesigner()
    win.show()
    app.exec_()


if __name__ == "__main__":
    main()
