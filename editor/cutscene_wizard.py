"""Guided MiniWind cutscene authoring wizard."""

from __future__ import annotations

import json
import math
import uuid

from PyQt5 import QtWidgets, QtCore


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
    if single is not None and getattr(single, "properties", {}).get("type") in ("npc", "creature"):
        if single not in out:
            out.append(single)
    return out


class CutsceneWizard(QtWidgets.QWizard):
    """A small, capture-first authoring workflow.

    The editor camera and selected actor transforms are the authoring surface:
    the wizard records those existing poses into plain JSON on the cutscene
    entity.
    """

    def __init__(self, main_window, parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.setWindowTitle("MiniWind Cutscene Wizard")
        self.setMinimumSize(760, 620)
        self.setOption(QtWidgets.QWizard.IndependentPages, False)

        self.name = QtWidgets.QLineEdit("cutscene")
        self.trigger_mode = QtWidgets.QComboBox()
        self.trigger_mode.addItem("Player enters trigger radius", "proximity")
        self.trigger_mode.addItem("Start when Play Mode begins", "play_start")
        self.trigger_mode.addItem("I/O only (Start input)", "manual")
        self.radius = QtWidgets.QDoubleSpinBox()
        self.radius.setRange(1.0, 100000.0)
        self.radius.setValue(180.0)
        self.radius.setDecimals(1)
        self.once = QtWidgets.QCheckBox("Play once per game session")
        self.once.setChecked(True)
        self.restore = QtWidgets.QCheckBox("Restore actors when the cutscene ends")
        self.restore.setChecked(True)
        self.stop_escape = QtWidgets.QCheckBox("Escape stops the cutscene in Play Mode")
        self.stop_escape.setChecked(True)

        self.actor_list = QtWidgets.QListWidget()
        self.actor_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        capture = QtWidgets.QPushButton("Capture selected actors")
        capture.clicked.connect(self._capture_selected_actors)
        clear = QtWidgets.QPushButton("Clear actor staging")
        clear.clicked.connect(self._clear_actors)

        page1 = QtWidgets.QWizardPage()
        page1.setTitle("Cutscene")
        page1.setSubTitle("Choose how the scene is triggered and whether actors are restored afterwards.")
        form = QtWidgets.QFormLayout(page1)
        form.addRow("Name", self.name)
        form.addRow("Trigger", self.trigger_mode)
        form.addRow("Trigger radius", self.radius)
        form.addRow("", self.once)
        form.addRow("", self.restore)
        form.addRow("", self.stop_escape)
        self.addPage(page1)

        page2 = QtWidgets.QWizardPage()
        page2.setTitle("Actors")
        page2.setSubTitle("Move NPCs/creatures in the normal editor, select them, then capture their current positions.")
        v = QtWidgets.QVBoxLayout(page2)
        v.addWidget(self.actor_list, 1)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(capture)
        row.addWidget(clear)
        v.addLayout(row)
        self.addPage(page2)

        page3 = QtWidgets.QWizardPage()
        page3.setTitle("Camera shots")
        page3.setSubTitle("Put the editor camera where you want it and capture a shot. Each shot can also look at one staged actor.")
        self.shots = []
        self.shot_list = QtWidgets.QListWidget()

        self.duration = QtWidgets.QDoubleSpinBox()
        self.duration.setRange(0.05, 300.0)
        self.duration.setDecimals(2)
        self.duration.setValue(2.5)

        self.look_at = QtWidgets.QComboBox()
        self.look_at.addItem("Fixed camera", "")
        self.speaker = QtWidgets.QComboBox()
        self.speaker.addItem("Narrator", "")
        self.dialogue = QtWidgets.QPlainTextEdit()
        self.dialogue.setPlaceholderText("Optional dialogue shown in a floating window.")
        self.dialogue.setFixedHeight(90)
        self.dialogue_duration = QtWidgets.QDoubleSpinBox()
        self.dialogue_duration.setRange(0.0, 300.0)
        self.dialogue_duration.setDecimals(2)
        self.dialogue_duration.setValue(3.0)

        self.message1 = QtWidgets.QLineEdit()
        self.message2 = QtWidgets.QLineEdit()
        self.message3 = QtWidgets.QLineEdit()

        capture_shot = QtWidgets.QPushButton("Capture current camera as shot")
        capture_shot.clicked.connect(self._capture_shot)
        remove_shot = QtWidgets.QPushButton("Remove selected shot")
        remove_shot.clicked.connect(self._remove_shot)

        form = QtWidgets.QFormLayout()
        form.addRow("Shot duration", self.duration)
        form.addRow("Look at", self.look_at)
        form.addRow("Speaker", self.speaker)
        form.addRow("Dialogue", self.dialogue)
        form.addRow("Dialogue hold", self.dialogue_duration)
        form.addRow("message", self.message1)
        form.addRow("message2", self.message2)
        form.addRow("message3", self.message3)

        v = QtWidgets.QVBoxLayout(page3)
        v.addWidget(self.shot_list, 1)
        v.addLayout(form)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(capture_shot)
        row.addWidget(remove_shot)
        v.addLayout(row)
        self.addPage(page3)

        page4 = QtWidgets.QWizardPage()
        page4.setTitle("Create cutscene")
        page4.setSubTitle("A MiniWind Cutscene entity will be added to the map using the captured data.")
        self.summary = QtWidgets.QLabel()
        self.summary.setWordWrap(True)
        v = QtWidgets.QVBoxLayout(page4)
        v.addWidget(self.summary)
        v.addStretch(1)
        self.addPage(page4)

        self.currentPageChanged.connect(self._page_changed)

    def _capture_selected_actors(self):
        selected = _selected_actors(self.main_window)
        if not selected:
            QtWidgets.QMessageBox.information(self, "Capture actors",
                                              "Select one or more NPCs or creatures in the editor first.")
            return
        captured = {
            item.data(QtCore.Qt.UserRole): item for item in
            [self.actor_list.item(i) for i in range(self.actor_list.count())]
        }
        for actor in selected:
            p = actor.properties
            aid = str(p.get("id", "") or "")
            if not aid:
                aid = str(uuid.uuid4())
                p["id"] = aid
            name = str(p.get("display_name") or p.get("name") or aid)
            if aid in captured:
                continue
            item = QtWidgets.QListWidgetItem(name)
            item.setData(QtCore.Qt.UserRole, aid)
            item.setData(QtCore.Qt.UserRole + 1, _v3(actor.pos))
            item.setData(QtCore.Qt.UserRole + 2, float(getattr(actor, "angle", 0.0)))
            self.actor_list.addItem(item)
        self._refresh_actor_combos()

    def _clear_actors(self):
        self.actor_list.clear()
        self._refresh_actor_combos()

    def _refresh_actor_combos(self):
        actors = []
        for i in range(self.actor_list.count()):
            item = self.actor_list.item(i)
            aid = item.data(QtCore.Qt.UserRole)
            name = item.text()
            actors.append((aid, name))
        self.look_at.blockSignals(True)
        self.speaker.blockSignals(True)
        self.look_at.clear()
        self.look_at.addItem("Fixed camera", "")
        self.speaker.clear()
        self.speaker.addItem("Narrator", "")
        for aid, name in actors:
            self.look_at.addItem(name, aid)
            self.speaker.addItem(name, aid)
        self.look_at.blockSignals(False)
        self.speaker.blockSignals(False)

    def _camera_snapshot(self):
        camera = self.main_window.view_3d.camera
        return {
            "pos": _v3(camera.pos),
            "yaw": float(camera.yaw),
            "pitch": float(camera.pitch),
            "fov": float(getattr(camera, "fov", 90.0)),
        }

    def _capture_shot(self):
        self._refresh_actor_combos()
        data = {
            "duration": float(self.duration.value()),
            "camera": self._camera_snapshot(),
            "look_at": self.look_at.currentData() or "",
            "dialogue": {
                "speaker_id": self.speaker.currentData() or "",
                "text": self.dialogue.toPlainText().strip(),
                "duration": float(self.dialogue_duration.value()),
            },
            "messages": {
                "message": self.message1.text().strip(),
                "message2": self.message2.text().strip(),
                "message3": self.message3.text().strip(),
            },
        }
        self.shots.append(data)
        label = f"Shot {len(self.shots)} — {data['duration']:.2f}s"
        if data["look_at"]:
            label += " — look at actor"
        if data["dialogue"]["text"]:
            label += " — dialogue"
        self.shot_list.addItem(label)

    def _remove_shot(self):
        row = self.shot_list.currentRow()
        if row < 0:
            return
        self.shot_list.takeItem(row)
        self.shots.pop(row)
        for i in range(self.shot_list.count()):
            item = self.shot_list.item(i)
            item.setText(item.text().replace("Shot ", f"Shot {i+1} ", 1))

    def _page_changed(self, index):
        if index == 2:
            self._refresh_actor_combos()
            return
        if index == 3:
            self.summary.setText(
                f"<b>{self.name.text().strip() or 'cutscene'}</b><br><br>"
                f"Trigger: {self.trigger_mode.currentText()}<br>"
                f"Actors staged: {self.actor_list.count()}<br>"
                f"Camera shots: {len(self.shots)}<br>"
                f"Restore actors: {'yes' if self.restore.isChecked() else 'no'}")
    
    def accept(self):
        if not self.shots:
            QtWidgets.QMessageBox.warning(self, "No camera shots",
                                          "Capture at least one camera shot.")
            return
        selected = _selected_actors(self.main_window)
        if not self.actor_list.count() and selected:
            self._capture_selected_actors()
        from game.entities import MiniwindCutscene
        actors = []
        for i in range(self.actor_list.count()):
            item = self.actor_list.item(i)
            actors.append({
                "id": item.data(QtCore.Qt.UserRole),
                "name": item.text(),
                "pos": item.data(QtCore.Qt.UserRole + 1),
                "yaw": float(item.data(QtCore.Qt.UserRole + 2) or 0.0),
            })

        view = self.main_window.view_3d
        camera = view.camera
        pos = _v3(camera.pos)
        if actors:
            pos = list(actors[0]["pos"])

        sequence = {
            "version": 1,
            "actors": actors,
            "shots": self.shots,
        }
        props = {
            "type": "miniwindcutscene",
            "id": str(uuid.uuid4()),
            "name": self.name.text().strip() or "cutscene",
            "display_name": self.name.text().strip() or "Cutscene",
            "trigger_mode": self.trigger_mode.currentData(),
            "trigger_radius": float(self.radius.value()),
            "once": bool(self.once.isChecked()),
            "restore_actors": bool(self.restore.isChecked()),
            "stop_on_escape": bool(self.stop_escape.isChecked()),
            "hidden_in_game": True,
            "sequence": json.dumps(sequence, ensure_ascii=False, separators=(",", ":")),
        }
        scene = MiniwindCutscene(pos=pos, properties=props)
        self.main_window.state.things.append(scene)
        self.main_window.set_selected_object(scene)
        self.main_window.unsaved_changes = True
        self.main_window.update_all_ui()
        self.main_window.show_toast(f"Created cutscene '{props['name']}'")
        super().accept()
