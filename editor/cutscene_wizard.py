"""MiniWind cutscene authoring wizard: capture timeline data into cutscenes/*.json."""

from __future__ import annotations

import json
import uuid

from PyQt5 import QtWidgets, QtCore

from game import cutscene_files


def _v3(value):
    if hasattr(value, "x"):
        return [float(value.x), float(value.y), float(value.z)]
    values = list(value)
    return [float(values[0]), float(values[1]), float(values[2])]


def _selected_actors(main_window):
    out = []
    for obj in getattr(main_window.state, "selected_objects", []) or []:
        if getattr(obj, "properties", {}).get("type") in ("npc", "creature"):
            out.append(obj)
    single = getattr(main_window.state, "selected_object", None)
    if single is not None and getattr(single, "properties", {}).get("type") in ("npc", "creature") and single not in out:
        out.append(single)
    return out


class CutsceneWizard(QtWidgets.QWizard):
    """Capture actors, camera moves and timed events into a standalone JSON file."""

    def __init__(self, main_window, parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.setWindowTitle("MiniWind Cutscene Wizard")
        self.setMinimumSize(980, 720)

        self.actor_meta = {}
        self.actor_tracks = {}
        self.camera_keys = []
        self.events = []

        # --------------------------------------------------------------- page 1
        page = QtWidgets.QWizardPage()
        page.setTitle("Cutscene file")
        page.setSubTitle("The cinematic is saved as a separate JSON asset in the cutscenes/ folder.")
        form = QtWidgets.QFormLayout(page)
        self.name = QtWidgets.QLineEdit("cutscene")
        self.filename = QtWidgets.QLineEdit("cutscene.json")
        self.trigger_mode = QtWidgets.QComboBox()
        self.trigger_mode.addItem("Player enters trigger radius", "proximity")
        self.trigger_mode.addItem("Start when Play Mode begins", "play_start")
        self.trigger_mode.addItem("I/O only (Start input)", "manual")
        self.radius = QtWidgets.QDoubleSpinBox(); self.radius.setRange(1, 100000); self.radius.setValue(180); self.radius.setDecimals(1)
        self.once = QtWidgets.QCheckBox("Play once per game session"); self.once.setChecked(True)
        self.restore = QtWidgets.QCheckBox("Restore actors after the cutscene"); self.restore.setChecked(True)
        self.stop_escape = QtWidgets.QCheckBox("Escape stops the cutscene"); self.stop_escape.setChecked(True)
        form.addRow("Name", self.name)
        form.addRow("JSON file", self.filename)
        form.addRow("Trigger", self.trigger_mode)
        form.addRow("Trigger radius", self.radius)
        form.addRow("", self.once); form.addRow("", self.restore); form.addRow("", self.stop_escape)
        self.addPage(page)

        # --------------------------------------------------------------- page 2
        page = QtWidgets.QWizardPage(); page.setTitle("Actors");
        page.setSubTitle("Select NPCs/creatures in the editor and capture them. The same actors can be reused in movement and battle groups.")
        v = QtWidgets.QVBoxLayout(page)
        self.actor_list = QtWidgets.QListWidget(); self.actor_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        v.addWidget(self.actor_list, 1)
        row = QtWidgets.QHBoxLayout()
        b = QtWidgets.QPushButton("Capture selected actors"); b.clicked.connect(self._capture_selected_actors); row.addWidget(b)
        b = QtWidgets.QPushButton("Remove selected"); b.clicked.connect(self._remove_selected_actors); row.addWidget(b)
        v.addLayout(row); self.addPage(page)

        # --------------------------------------------------------------- page 3
        page = QtWidgets.QWizardPage(); page.setTitle("Actor movement");
        page.setSubTitle("Move a group in the normal editor, set a timeline time, then capture their positions. Multiple keyframes make the actors walk between locations.")
        v = QtWidgets.QVBoxLayout(page)
        top = QtWidgets.QHBoxLayout(); self.actor_time = QtWidgets.QDoubleSpinBox(); self.actor_time.setRange(0, 3600); self.actor_time.setDecimals(2); self.actor_time.setValue(0)
        top.addWidget(QtWidgets.QLabel("Keyframe time")); top.addWidget(self.actor_time); top.addStretch(1); v.addLayout(top)
        self.actor_keys_list = QtWidgets.QListWidget(); v.addWidget(self.actor_keys_list, 1)
        b = QtWidgets.QPushButton("Capture selected actors at this time"); b.clicked.connect(self._capture_actor_keyframe); v.addWidget(b)
        self.addPage(page)

        # --------------------------------------------------------------- page 4
        page = QtWidgets.QWizardPage(); page.setTitle("Camera movement");
        page.setSubTitle("Place the editor camera, choose what it looks at, and capture a camera keyframe. The runtime pans smoothly between them.")
        v = QtWidgets.QVBoxLayout(page)
        top = QtWidgets.QHBoxLayout(); self.camera_time = QtWidgets.QDoubleSpinBox(); self.camera_time.setRange(0, 3600); self.camera_time.setDecimals(2); self.camera_time.setValue(0)
        top.addWidget(QtWidgets.QLabel("Keyframe time")); top.addWidget(self.camera_time)
        self.look_at = QtWidgets.QComboBox(); self.look_at.addItem("Keep camera rotation", "")
        top.addWidget(QtWidgets.QLabel("Look at")); top.addWidget(self.look_at, 1); v.addLayout(top)
        self.camera_keys_list = QtWidgets.QListWidget(); v.addWidget(self.camera_keys_list, 1)
        b = QtWidgets.QPushButton("Capture current camera"); b.clicked.connect(self._capture_camera_keyframe); v.addWidget(b)
        self.addPage(page)

        # --------------------------------------------------------------- page 5
        page = QtWidgets.QWizardPage(); page.setTitle("Battle & effects");
        tabs = QtWidgets.QTabWidget();
        # Fight tab
        fight = QtWidgets.QWidget(); fv = QtWidgets.QVBoxLayout(fight)
        self.fight_time = QtWidgets.QDoubleSpinBox(); self.fight_time.setRange(0, 3600); self.fight_time.setDecimals(2); self.fight_time.setValue(0)
        self.fight_duration = QtWidgets.QDoubleSpinBox(); self.fight_duration.setRange(0.05, 300); self.fight_duration.setDecimals(2); self.fight_duration.setValue(5)
        ff = QtWidgets.QFormLayout(); ff.addRow("Start time", self.fight_time); ff.addRow("Duration", self.fight_duration); fv.addLayout(ff)
        lists = QtWidgets.QHBoxLayout()
        self.attackers = QtWidgets.QListWidget(); self.attackers.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.defenders = QtWidgets.QListWidget(); self.defenders.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        lists.addWidget(self._labelled_list("Attackers", self.attackers)); lists.addWidget(self._labelled_list("Defenders", self.defenders)); fv.addLayout(lists, 1)
        b = QtWidgets.QPushButton("Add fight event"); b.clicked.connect(self._add_fight); fv.addWidget(b)
        tabs.addTab(fight, "Fight")
        # Blood tab
        blood = QtWidgets.QWidget(); bv = QtWidgets.QVBoxLayout(blood)
        bf = QtWidgets.QFormLayout()
        self.blood_time = QtWidgets.QDoubleSpinBox(); self.blood_time.setRange(0, 3600); self.blood_time.setDecimals(2)
        self.blood_variant = QtWidgets.QComboBox(); self.blood_variant.addItem("Random", "random")
        try:
            from game.rpg import gib
            for i, path in enumerate(gib.stain_paths(False)): self.blood_variant.addItem(f"Variant {i + 1} — {path.rsplit("/", 1)[-1]}", i)
        except Exception: pass
        self.blood_x = QtWidgets.QDoubleSpinBox(); self.blood_y = QtWidgets.QDoubleSpinBox(); self.blood_z = QtWidgets.QDoubleSpinBox()
        for spin in (self.blood_x, self.blood_y, self.blood_z): spin.setRange(-100000, 100000); spin.setDecimals(2)
        self.blood_w = QtWidgets.QDoubleSpinBox(); self.blood_h = QtWidgets.QDoubleSpinBox(); self.blood_w.setRange(8, 512); self.blood_h.setRange(8, 512); self.blood_w.setValue(72); self.blood_h.setValue(48)
        bf.addRow("Time", self.blood_time); bf.addRow("Variant", self.blood_variant); bf.addRow("X", self.blood_x); bf.addRow("Y", self.blood_y); bf.addRow("Z", self.blood_z); bf.addRow("Width", self.blood_w); bf.addRow("Height", self.blood_h)
        bv.addLayout(bf)
        brow = QtWidgets.QHBoxLayout(); b = QtWidgets.QPushButton("Use selected actor position"); b.clicked.connect(self._use_selected_position); brow.addWidget(b); b = QtWidgets.QPushButton("Add blood keyframe"); b.clicked.connect(self._add_blood); brow.addWidget(b); bv.addLayout(brow)
        tabs.addTab(blood, "Blood")
        # Dialogue tab
        dialog = QtWidgets.QWidget(); dv = QtWidgets.QVBoxLayout(dialog); df = QtWidgets.QFormLayout()
        self.dialogue_time = QtWidgets.QDoubleSpinBox(); self.dialogue_time.setRange(0, 3600); self.dialogue_time.setDecimals(2)
        self.dialogue_duration = QtWidgets.QDoubleSpinBox(); self.dialogue_duration.setRange(0.05, 300); self.dialogue_duration.setValue(3); self.dialogue_duration.setDecimals(2)
        self.dialogue_speaker = QtWidgets.QComboBox(); self.dialogue_text = QtWidgets.QPlainTextEdit(); self.dialogue_text.setFixedHeight(100)
        df.addRow("Time", self.dialogue_time); df.addRow("Duration", self.dialogue_duration); df.addRow("Speaker", self.dialogue_speaker); df.addRow("Text", self.dialogue_text); dv.addLayout(df)
        b = QtWidgets.QPushButton("Add dialogue keyframe"); b.clicked.connect(self._add_dialogue); dv.addWidget(b); tabs.addTab(dialog, "Dialogue")
        # Message tab
        message = QtWidgets.QWidget(); mv = QtWidgets.QFormLayout(message)
        self.message_time = QtWidgets.QDoubleSpinBox(); self.message_time.setRange(0, 3600); self.message_time.setDecimals(2)
        self.message_line = QtWidgets.QComboBox(); self.message_line.addItems(["message", "message2", "message3"])

        self.message_text = QtWidgets.QLineEdit(); mv.addRow("Time", self.message_time); mv.addRow("Line", self.message_line); mv.addRow("Text", self.message_text)
        b = QtWidgets.QPushButton("Add message keyframe"); b.clicked.connect(self._add_message); mv.addRow("", b); tabs.addTab(message, "Message")
        # event list
        v = QtWidgets.QVBoxLayout(page); v.addWidget(tabs, 1)
        self.event_list = QtWidgets.QListWidget(); v.addWidget(self.event_list, 1)
        b = QtWidgets.QPushButton("Remove selected event"); b.clicked.connect(self._remove_event); v.addWidget(b)
        self.addPage(page)

        # --------------------------------------------------------------- page 6
        page = QtWidgets.QWizardPage(); page.setTitle("Save cutscene"); self.summary = QtWidgets.QLabel(); self.summary.setWordWrap(True)
        v = QtWidgets.QVBoxLayout(page); v.addWidget(self.summary); v.addStretch(1); self.addPage(page)
        self.currentPageChanged.connect(self._page_changed)
        self._refresh_actor_lists()

    @staticmethod
    def _labelled_list(title, widget):
        box = QtWidgets.QGroupBox(title); lay = QtWidgets.QVBoxLayout(box); lay.addWidget(widget); return box

    def _capture_selected_actors(self):
        selected = _selected_actors(self.main_window)
        if not selected:
            QtWidgets.QMessageBox.information(self, "Actors", "Select one or more NPCs or creatures in the editor first."); return
        for actor in selected:
            props = actor.properties; aid = str(props.get("id", "") or "")
            if not aid:
                aid = str(uuid.uuid4()); props["id"] = aid
            self.actor_meta[aid] = {"id": aid, "name": str(props.get("display_name") or props.get("name") or aid)}
        self._refresh_actor_lists()

    def _remove_selected_actors(self):
        for item in self.actor_list.selectedItems(): self.actor_meta.pop(str(item.data(QtCore.Qt.UserRole)), None)
        self._refresh_actor_lists()

    def _refresh_actor_lists(self):
        widgets = [self.actor_list, self.attackers, self.defenders]
        current = {id(w): [str(x.data(QtCore.Qt.UserRole)) for x in w.selectedItems()] for w in widgets if w.count()}
        for widget in widgets: widget.clear()
        for aid, meta in self.actor_meta.items():
            for widget in widgets:
                item = QtWidgets.QListWidgetItem(meta["name"]); item.setData(QtCore.Qt.UserRole, aid); widget.addItem(item)
        for widget in widgets:
            for i in range(widget.count()):
                if str(widget.item(i).data(QtCore.Qt.UserRole)) in current.get(id(widget), []): widget.item(i).setSelected(True)
        self.look_at.blockSignals(True); self.look_at.clear(); self.look_at.addItem("Keep camera rotation", "")
        self.dialogue_speaker.clear(); self.dialogue_speaker.addItem("Narrator", "")
        for aid, meta in self.actor_meta.items(): self.look_at.addItem(meta["name"], aid); self.dialogue_speaker.addItem(meta["name"], aid)
        self.look_at.blockSignals(False)

    def _capture_actor_keyframe(self):
        actors = _selected_actors(self.main_window)
        if not actors: QtWidgets.QMessageBox.information(self, "Movement", "Select actors in the editor first."); return
        t = float(self.actor_time.value())
        for actor in actors:
            aid = str(actor.properties.get("id", "") or "")
            if not aid: continue
            row = {"time": t, "pos": _v3(actor.pos), "yaw": float(getattr(actor, "angle", 0.0))}
            self.actor_tracks.setdefault(aid, []).append(row); self.actor_tracks[aid].sort(key=lambda x: x["time"])

            if aid not in self.actor_meta: self.actor_meta[aid] = {"id": aid, "name": str(actor.properties.get("display_name") or actor.properties.get("name") or aid)}
        self._refresh_actor_lists(); self._refresh_actor_keys_list()

    def _refresh_actor_keys_list(self):
        self.actor_keys_list.clear()
        for aid, rows in sorted(self.actor_tracks.items()):
            name = self.actor_meta.get(aid, {}).get("name", aid)
            for row in rows: self.actor_keys_list.addItem(f"{row["time"]:.2f}s — {name} → {row["pos"]}")

    def _capture_camera_keyframe(self):
        camera = self.main_window.view_3d.camera
        frame = {"time": float(self.camera_time.value()), "pos": _v3(camera.pos), "yaw": float(camera.yaw), "pitch": float(camera.pitch), "fov": float(getattr(camera, "fov", 90.0))}
        aid = self.look_at.currentData()
        if aid: frame["look_at"] = {"actor": str(aid)}
        self.camera_keys.append(frame); self.camera_keys.sort(key=lambda x: x["time"])

        self.camera_keys_list.clear()
        for row in self.camera_keys: self.camera_keys_list.addItem(f"{row["time"]:.2f}s — camera {row["pos"]}")

    def _add_fight(self):
        a = [str(x.data(QtCore.Qt.UserRole)) for x in self.attackers.selectedItems()]
        d = [str(x.data(QtCore.Qt.UserRole)) for x in self.defenders.selectedItems()]
        if not a or not d: QtWidgets.QMessageBox.warning(self, "Fight", "Choose at least one attacker and one defender."); return
        self.events.append({"time": float(self.fight_time.value()), "type": "fight", "duration": float(self.fight_duration.value()), "attackers": a, "defenders": d})
        self._refresh_event_list()

    def _use_selected_position(self):
        actors = _selected_actors(self.main_window)
        if actors:
            pos = _v3(actors[0].pos); self.blood_x.setValue(pos[0]); self.blood_y.setValue(pos[1]); self.blood_z.setValue(pos[2])

    def _add_blood(self):
        self.events.append({"time": float(self.blood_time.value()), "type": "blood", "position": [self.blood_x.value(), self.blood_y.value(), self.blood_z.value()], "variant": self.blood_variant.currentData()})
        self.events[-1]["width"] = float(self.blood_w.value()); self.events[-1]["height"] = float(self.blood_h.value()); self.events[-1]["persist"] = True
        self._refresh_event_list()

    def _add_dialogue(self):
        self.events.append({"time": float(self.dialogue_time.value()), "type": "dialogue", "duration": float(self.dialogue_duration.value()), "speaker_id": self.dialogue_speaker.currentData() or "", "text": self.dialogue_text.toPlainText().strip()})
        self._refresh_event_list()

    def _add_message(self):
        self.events.append({"time": float(self.message_time.value()), "type": "message", "line": self.message_line.currentText(), "text": self.message_text.text()})
        self._refresh_event_list()

    def _remove_event(self):
        row = self.event_list.currentRow()

        if 0 <= row < len(self.events): self.events.pop(row); self._refresh_event_list()

    def _refresh_event_list(self):
        self.event_list.clear()
        for event in sorted(self.events, key=lambda x: x.get("time", 0)):
            kind = event["type"]; label = f"{event["time"]:.2f}s — {kind}"
            if kind == "fight": label += f" ({len(event["attackers"])} vs {len(event["defenders"])})"
            elif kind == "dialogue": label += f" — {event["text"][:45]}"
            elif kind == "message": label += f" — {event["line"]}: {event["text"][:45]}"
            self.event_list.addItem(label)

    def _page_changed(self, index):
        if index == 5:
            self.summary.setText(f"<b>{self.name.text().strip() or "cutscene"}</b><br><br>"
                f"File: cutscenes/{self._filename()}<br>"
                f"Actors: {len(self.actor_meta)}<br>"
                f"Actor keyframes: {sum(len(v) for v in self.actor_tracks.values())}<br>"
                f"Camera keyframes: {len(self.camera_keys)}<br>"
                f"Timed events: {len(self.events)}")

    def _filename(self):
        name = self.filename.text().strip() or self.name.text().strip() or "cutscene"
        if not name.lower().endswith(".json"): name += ".json"
        return name.split("/")[-1].split("\\")[-1]

    def accept(self):
        if not self.camera_keys:
            QtWidgets.QMessageBox.warning(self, "No camera keyframes", "Capture at least one camera keyframe."); return
        if not self.actor_meta and not self.events:
            QtWidgets.QMessageBox.warning(self, "Empty cutscene", "Add at least one actor or timed event."); return
        filename = self._filename(); path = cutscene_files.cutscene_path(filename)
        if QtCore.QFileInfo(path).exists():
            result = QtWidgets.QMessageBox.question(self, "Overwrite cutscene", f"{filename} already exists. Replace it?")
            if result != QtWidgets.QMessageBox.Yes: return
        data = {
            "version": 2, "id": str(uuid.uuid4()), "name": self.name.text().strip() or "Cutscene",
            "actors": list(self.actor_meta.values()), "camera": self.camera_keys, "actor_tracks": self.actor_tracks,
            "events": sorted(self.events, key=lambda x: x.get("time", 0)),
            "settings": {"restore_actors": self.restore.isChecked(), "stop_on_escape": self.stop_escape.isChecked()},
        }
        written = cutscene_files.save_cutscene(data, filename)
        if not written:
            QtWidgets.QMessageBox.warning(self, "Save failed", "The cutscene JSON could not be written."); return
        from game.entities import MiniwindCutscene
        selected = _selected_actors(self.main_window)
        pos = _v3(selected[0].pos) if selected else _v3(self.main_window.view_3d.camera.pos)
        props = {"type": "miniwindcutscene", "id": str(uuid.uuid4()), "cutscene_file": filename,
                 "trigger_mode": self.trigger_mode.currentData(), "trigger_radius": float(self.radius.value()),
                 "once": self.once.isChecked(), "restore_actors": self.restore.isChecked(),
                 "stop_on_escape": self.stop_escape.isChecked(), "hidden_in_game": True}
        scene = MiniwindCutscene(pos=pos, properties=props)
        self.main_window.state.save_state(); self.main_window.state.things.append(scene)
        self.main_window.set_selected_object(scene); self.main_window.unsaved_changes = True; self.main_window.update_all_ui()
        self.main_window.show_toast(f"Created cutscene {filename}")
        super().accept()