"""MiniWind cutscene authoring panel.

The normal workflow is deliberately direct:

    create actor -> move it in the 3D editor -> add waypoint -> repeat -> save

Actors created here are temporary editor entities. Their definitions are embedded
in the cutscene JSON and the runtime creates/removes them when the cutscene plays.
Existing map actors can still be captured and all of the original advanced event
authoring remains available in the Advanced section.
"""

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
    if (
        single is not None
        and getattr(single, "properties", {}).get("type") in ("npc", "creature")
        and single not in out
    ):
        out.append(single)
    return out


class CutsceneWizard(QtWidgets.QDialog):
    """Modeless live cutscene authoring panel.

    The editor remains fully usable while this panel is open. Temporary actors
    are ordinary editor entities, which means selection, movement and property
    editing all work through the normal Fio/MiniWind editor machinery.
    """

    NPC_ROLES = ("villager", "guard", "merchant", "blacksmith", "farmer", "beggar")
    CREATURE_ROLES = (
        "wolf", "bear", "boar", "mudcrab", "bandit", "cultist",
        "skeleton", "wraith", "cow", "sheep", "hen",
    )

    def __init__(self, main_window, parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.setWindowTitle("MiniWind Cutscene Wizard")
        self.setMinimumSize(560, 760)
        self.resize(640, 900)
        self.setWindowModality(QtCore.Qt.NonModal)
        self.setWindowFlag(QtCore.Qt.Tool, True)

        self.actor_meta = {}
        self.actor_objects = {}
        self.temporary_actor_ids = set()
        self.actor_tracks = {}
        self.camera_keys = []
        self.events = []
        self._saved = False
        self._cleaned = False

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # -----------------------------------------------------------------
        # Always-visible essentials.
        # -----------------------------------------------------------------
        header = QtWidgets.QGroupBox("Cutscene")
        form = QtWidgets.QFormLayout(header)
        self.name = QtWidgets.QLineEdit("cutscene")
        self.filename = QtWidgets.QLineEdit("cutscene.json")
        self.trigger_mode = QtWidgets.QComboBox()
        self.trigger_mode.addItem("Player enters trigger radius", "proximity")
        self.trigger_mode.addItem("Start when Play Mode begins", "play_start")
        self.trigger_mode.addItem("I/O only (Start input)", "manual")
        self.radius = QtWidgets.QDoubleSpinBox()
        self.radius.setRange(1, 100000)
        self.radius.setValue(180)
        self.radius.setDecimals(1)
        self.once = QtWidgets.QCheckBox("Play once per game session")
        self.once.setChecked(True)
        self.restore = QtWidgets.QCheckBox("Restore existing actors after the cutscene")
        self.restore.setChecked(True)
        self.stop_escape = QtWidgets.QCheckBox("Escape stops the cutscene")
        self.stop_escape.setChecked(True)
        form.addRow("Name", self.name)
        form.addRow("File", self.filename)
        form.addRow("Trigger", self.trigger_mode)
        form.addRow("Radius", self.radius)
        form.addRow("", self.once)
        form.addRow("", self.restore)
        form.addRow("", self.stop_escape)
        root.addWidget(header)

        actors_box = QtWidgets.QGroupBox("Actors")
        av = QtWidgets.QVBoxLayout(actors_box)
        av.setContentsMargins(7, 7, 7, 7)

        help_label = QtWidgets.QLabel(
            "<b>Live scene authoring:</b> create an actor here, then move it in the "
            "3D view exactly like any other entity. Select an actor below to author "
            "its waypoints."
        )
        help_label.setWordWrap(True)
        av.addWidget(help_label)

        actor_buttons = QtWidgets.QHBoxLayout()
        self.add_npc_button = QtWidgets.QPushButton("+ NPC")
        self.add_creature_button = QtWidgets.QPushButton("+ Creature")
        self.capture_button = QtWidgets.QPushButton("Capture selected")
        self.remove_actor_button = QtWidgets.QPushButton("Remove")
        self.focus_actor_button = QtWidgets.QPushButton("Focus")
        actor_buttons.addWidget(self.add_npc_button)
        actor_buttons.addWidget(self.add_creature_button)
        actor_buttons.addWidget(self.capture_button)
        actor_buttons.addWidget(self.remove_actor_button)
        actor_buttons.addWidget(self.focus_actor_button)
        av.addLayout(actor_buttons)

        self.actor_list = QtWidgets.QListWidget()
        self.actor_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.actor_list.setMinimumHeight(125)
        av.addWidget(self.actor_list)

        selected_row = QtWidgets.QHBoxLayout()
        self.selected_actor_label = QtWidgets.QLabel("No actor selected")
        self.selected_actor_label.setStyleSheet("font-weight: bold;")
        selected_row.addWidget(self.selected_actor_label)
        selected_row.addStretch(1)
        av.addLayout(selected_row)
        root.addWidget(actors_box)

        waypoint_box = QtWidgets.QGroupBox("Waypoints")
        wv = QtWidgets.QVBoxLayout(waypoint_box)
        wv.setContentsMargins(7, 7, 7, 7)
        waypoint_help = QtWidgets.QLabel(
            "Move the selected actor in the 3D view, then press Add waypoint. "
            "Attack waypoints automatically create the corresponding fight event."
        )
        waypoint_help.setWordWrap(True)
        wv.addWidget(waypoint_help)

        waypoint_row = QtWidgets.QHBoxLayout()
        self.waypoint_time = QtWidgets.QDoubleSpinBox()
        self.waypoint_time.setRange(0, 3600)
        self.waypoint_time.setDecimals(2)
        self.waypoint_time.setValue(0)
        self.waypoint_action = QtWidgets.QComboBox()
        self.waypoint_action.addItem("Move", "move")
        self.waypoint_action.addItem("Attack", "attack")
        self.waypoint_target = QtWidgets.QComboBox()
        self.waypoint_attack_duration = QtWidgets.QDoubleSpinBox()
        self.waypoint_attack_duration.setRange(0.05, 300)
        self.waypoint_attack_duration.setDecimals(2)
        self.waypoint_attack_duration.setValue(5)
        waypoint_row.addWidget(QtWidgets.QLabel("Time"))
        waypoint_row.addWidget(self.waypoint_time)
        waypoint_row.addWidget(QtWidgets.QLabel("Action"))
        waypoint_row.addWidget(self.waypoint_action)
        waypoint_row.addWidget(QtWidgets.QLabel("Target"))
        waypoint_row.addWidget(self.waypoint_target, 1)
        waypoint_row.addWidget(QtWidgets.QLabel("Attack for"))
        waypoint_row.addWidget(self.waypoint_attack_duration)
        wv.addLayout(waypoint_row)

        waypoint_buttons = QtWidgets.QHBoxLayout()
        self.add_waypoint_button = QtWidgets.QPushButton("Add waypoint")
        self.capture_now_button = QtWidgets.QPushButton("Capture current position")
        self.remove_waypoint_button = QtWidgets.QPushButton("Remove selected")
        waypoint_buttons.addWidget(self.add_waypoint_button)
        waypoint_buttons.addWidget(self.capture_now_button)
        waypoint_buttons.addWidget(self.remove_waypoint_button)
        wv.addLayout(waypoint_buttons)

        self.waypoint_list = QtWidgets.QListWidget()
        self.waypoint_list.setMinimumHeight(130)
        wv.addWidget(self.waypoint_list)
        root.addWidget(waypoint_box)

        camera_box = QtWidgets.QGroupBox("Camera")
        cv = QtWidgets.QVBoxLayout(camera_box)
        cv.setContentsMargins(7, 7, 7, 7)
        camera_row = QtWidgets.QHBoxLayout()
        self.camera_time = QtWidgets.QDoubleSpinBox()
        self.camera_time.setRange(0, 3600)
        self.camera_time.setDecimals(2)
        self.camera_time.setValue(0)
        self.look_at = QtWidgets.QComboBox()
        self.look_at.addItem("Keep camera rotation", "")
        camera_row.addWidget(QtWidgets.QLabel("Time"))
        camera_row.addWidget(self.camera_time)
        camera_row.addWidget(QtWidgets.QLabel("Look at"))
        camera_row.addWidget(self.look_at, 1)
        camera_row.addWidget(QtWidgets.QPushButton("Capture"), 0)
        self.capture_camera_button = camera_row.itemAt(camera_row.count() - 1).widget()
        self.capture_camera_button.clicked.connect(self._capture_camera_keyframe)
        cv.addLayout(camera_row)
        self.camera_keys_list = QtWidgets.QListWidget()
        self.camera_keys_list.setMaximumHeight(90)
        cv.addWidget(self.camera_keys_list)
        root.addWidget(camera_box)

        # -----------------------------------------------------------------
        # Advanced = old functionality, deliberately retained rather than
        # forcing it into the simple workflow.
        # -----------------------------------------------------------------
        advanced_toggle = QtWidgets.QToolButton()
        advanced_toggle.setText("Advanced timeline & events")
        advanced_toggle.setCheckable(True)
        advanced_toggle.setChecked(False)
        advanced_toggle.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        advanced_toggle.setArrowType(QtCore.Qt.RightArrow)
        root.addWidget(advanced_toggle)

        advanced = QtWidgets.QWidget()
        advanced.setVisible(False)
        advanced_layout = QtWidgets.QVBoxLayout(advanced)
        advanced_layout.setContentsMargins(0, 0, 0, 0)

        exact_box = QtWidgets.QGroupBox("Exact actor keyframes")
        exact_form = QtWidgets.QFormLayout(exact_box)
        self.actor_time = QtWidgets.QDoubleSpinBox()
        self.actor_time.setRange(0, 3600)
        self.actor_time.setDecimals(2)
        self.actor_time.setValue(0)
        exact_form.addRow("Keyframe time", self.actor_time)
        self.actor_keys_list = QtWidgets.QListWidget()
        self.actor_keys_list.setMinimumHeight(85)
        exact_form.addRow(self.actor_keys_list)
        exact_buttons = QtWidgets.QHBoxLayout()
        self.capture_actor_button = QtWidgets.QPushButton(
            "Capture selected actors at this time"
        )
        self.capture_actor_button.clicked.connect(self._capture_actor_keyframe)
        exact_buttons.addWidget(self.capture_actor_button)
        exact_form.addRow(exact_buttons)
        advanced_layout.addWidget(exact_box)

        events_tabs = QtWidgets.QTabWidget()
        self._build_fight_tab(events_tabs)
        self._build_blood_tab(events_tabs)
        self._build_dialogue_tab(events_tabs)
        self._build_message_tab(events_tabs)
        advanced_layout.addWidget(events_tabs)

        self.event_list = QtWidgets.QListWidget()
        self.event_list.setMinimumHeight(120)
        advanced_layout.addWidget(self.event_list)
        remove_event = QtWidgets.QPushButton("Remove selected event")
        remove_event.clicked.connect(self._remove_event)
        advanced_layout.addWidget(remove_event)

        root.addWidget(advanced, 1)

        def toggle_advanced(checked):
            advanced.setVisible(checked)
            advanced_toggle.setArrowType(
                QtCore.Qt.DownArrow if checked else QtCore.Qt.RightArrow
            )
            self.adjustSize()

        advanced_toggle.toggled.connect(toggle_advanced)

        footer = QtWidgets.QHBoxLayout()
        self.summary = QtWidgets.QLabel("No actors created yet.")
        self.summary.setWordWrap(True)
        footer.addWidget(self.summary, 1)
        self.save_button = QtWidgets.QPushButton("Save Cutscene")
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.save_button.setDefault(True)
        footer.addWidget(self.save_button)
        footer.addWidget(self.cancel_button)
        root.addLayout(footer)

        self.add_npc_button.clicked.connect(lambda: self._create_temporary_actor("npc"))
        self.add_creature_button.clicked.connect(
            lambda: self._create_temporary_actor("creature")
        )
        self.capture_button.clicked.connect(self._capture_selected_actors)
        self.remove_actor_button.clicked.connect(self._remove_selected_actors)
        self.focus_actor_button.clicked.connect(self._focus_selected_actor)
        self.actor_list.itemSelectionChanged.connect(self._actor_selection_changed)
        self.actor_list.itemDoubleClicked.connect(
            lambda _item: self._focus_selected_actor()
        )
        self.add_waypoint_button.clicked.connect(
            lambda: self._add_waypoint(from_current=True)
        )
        self.capture_now_button.clicked.connect(
            lambda: self._add_waypoint(from_current=True)
        )
        self.remove_waypoint_button.clicked.connect(self._remove_selected_waypoint)
        self.waypoint_action.currentIndexChanged.connect(
            lambda _index: self._update_waypoint_controls()
        )
        self.save_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        self._refresh_actor_lists()
        self._update_waypoint_controls()
        self._refresh_summary()

    # ------------------------------------------------------------------
    # Advanced event widgets — these retain the original wizard controls.
    # ------------------------------------------------------------------
    def _build_fight_tab(self, tabs):
        fight = QtWidgets.QWidget()
        fv = QtWidgets.QVBoxLayout(fight)
        self.fight_time = QtWidgets.QDoubleSpinBox()
        self.fight_time.setRange(0, 3600)
        self.fight_time.setDecimals(2)
        self.fight_duration = QtWidgets.QDoubleSpinBox()
        self.fight_duration.setRange(0.05, 300)
        self.fight_duration.setDecimals(2)
        self.fight_duration.setValue(5)
        self.fight_style = QtWidgets.QComboBox()
        self.fight_style.addItem("Use each actor's normal combat style", "normal")
        self.fight_style.addItem("Melee — swords / claws / close combat", "melee")
        self.fight_style.addItem("Archery — bows / ranged attacks", "bow")
        self.fight_style.addItem("Spell — magical ranged attack", "magic")
        form = QtWidgets.QFormLayout()
        form.addRow("Start time", self.fight_time)
        form.addRow("Duration", self.fight_duration)
        form.addRow("How they fight", self.fight_style)
        fv.addLayout(form)
        lists = QtWidgets.QHBoxLayout()
        self.attackers = QtWidgets.QListWidget()
        self.attackers.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.defenders = QtWidgets.QListWidget()
        self.defenders.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        lists.addWidget(self._labelled_list("Attackers", self.attackers))
        lists.addWidget(self._labelled_list("Defenders", self.defenders))
        fv.addLayout(lists, 1)
        button = QtWidgets.QPushButton("Add fight event")
        button.clicked.connect(self._add_fight)
        fv.addWidget(button)
        tabs.addTab(fight, "Fight")

    def _build_blood_tab(self, tabs):
        blood = QtWidgets.QWidget()
        bv = QtWidgets.QVBoxLayout(blood)
        form = QtWidgets.QFormLayout()
        self.blood_time = QtWidgets.QDoubleSpinBox()
        self.blood_time.setRange(0, 3600)
        self.blood_time.setDecimals(2)
        self.blood_variant = QtWidgets.QComboBox()
        self.blood_variant.addItem("Random", "random")
        try:
            from game.rpg import gib
            for i, path in enumerate(gib.stain_paths(False)):
                self.blood_variant.addItem(
                    f'Variant {i + 1} — {path.rsplit("/", 1)[-1]}', i
                )
        except Exception:
            pass
        self.blood_x = QtWidgets.QDoubleSpinBox()
        self.blood_y = QtWidgets.QDoubleSpinBox()
        self.blood_z = QtWidgets.QDoubleSpinBox()
        for spin in (self.blood_x, self.blood_y, self.blood_z):
            spin.setRange(-100000, 100000)
            spin.setDecimals(2)
        self.blood_w = QtWidgets.QDoubleSpinBox()
        self.blood_h = QtWidgets.QDoubleSpinBox()
        self.blood_w.setRange(8, 512)
        self.blood_h.setRange(8, 512)
        self.blood_w.setValue(72)
        self.blood_h.setValue(48)
        form.addRow("Time", self.blood_time)
        form.addRow("Variant", self.blood_variant)
        form.addRow("X", self.blood_x)
        form.addRow("Y", self.blood_y)
        form.addRow("Z", self.blood_z)
        form.addRow("Width", self.blood_w)
        form.addRow("Height", self.blood_h)
        bv.addLayout(form)
        row = QtWidgets.QHBoxLayout()
        use_pos = QtWidgets.QPushButton("Use selected actor position")
        use_pos.clicked.connect(self._use_selected_position)
        add = QtWidgets.QPushButton("Add blood keyframe")
        add.clicked.connect(self._add_blood)
        row.addWidget(use_pos)
        row.addWidget(add)
        bv.addLayout(row)
        tabs.addTab(blood, "Blood")

    def _build_dialogue_tab(self, tabs):
        dialog = QtWidgets.QWidget()
        dv = QtWidgets.QVBoxLayout(dialog)
        form = QtWidgets.QFormLayout()
        self.dialogue_time = QtWidgets.QDoubleSpinBox()
        self.dialogue_time.setRange(0, 3600)
        self.dialogue_time.setDecimals(2)
        self.dialogue_duration = QtWidgets.QDoubleSpinBox()
        self.dialogue_duration.setRange(0.05, 300)
        self.dialogue_duration.setValue(3)
        self.dialogue_duration.setDecimals(2)
        self.dialogue_speaker = QtWidgets.QComboBox()
        self.dialogue_text = QtWidgets.QPlainTextEdit()
        self.dialogue_text.setFixedHeight(100)
        form.addRow("Time", self.dialogue_time)
        form.addRow("Duration", self.dialogue_duration)
        form.addRow("Speaker", self.dialogue_speaker)
        form.addRow("Text", self.dialogue_text)
        dv.addLayout(form)
        button = QtWidgets.QPushButton("Add dialogue keyframe")
        button.clicked.connect(self._add_dialogue)
        dv.addWidget(button)
        tabs.addTab(dialog, "Dialogue")

    def _build_message_tab(self, tabs):
        message = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(message)
        self.message_time = QtWidgets.QDoubleSpinBox()
        self.message_time.setRange(0, 3600)
        self.message_time.setDecimals(2)
        self.message_line = QtWidgets.QComboBox()
        self.message_line.addItems(["message", "message2", "message3"])
        self.message_text = QtWidgets.QLineEdit()
        form.addRow("Time", self.message_time)
        form.addRow("Line", self.message_line)
        form.addRow("Text", self.message_text)
        button = QtWidgets.QPushButton("Add message keyframe")
        button.clicked.connect(self._add_message)
        form.addRow("", button)
        tabs.addTab(message, "Message")

    @staticmethod
    def _labelled_list(title, widget):
        box = QtWidgets.QGroupBox(title)
        lay = QtWidgets.QVBoxLayout(box)
        lay.addWidget(widget)
        return box

    # ------------------------------------------------------------------
    # Live actor authoring.
    # ------------------------------------------------------------------
    def _create_temporary_actor(self, entity_type):
        try:
            from game.entities import Creature, NPC
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self, "Actor", f"Could not create a MiniWind actor: {exc}"
            )
            return

        camera = getattr(getattr(self.main_window, "view_3d", None), "camera", None)
        if camera is None:
            return
        try:
            front = camera.get_front_vector()
            pos = [
                float(camera.pos.x + front.x * 256.0),
                float(camera.pos.y + front.y * 256.0),
                float(camera.pos.z + front.z * 256.0),
            ]
        except Exception:
            pos = _v3(camera.pos)

        # One click creates a usable actor.  Role/name remain editable through
        # the normal Properties panel, so authoring a shot never turns into a
        # sequence of setup dialogs.
        role = "villager" if entity_type == "npc" else "wolf"
        label = "NPC" if entity_type == "npc" else "Creature"
        default_name = f"Cutscene {label} {len(self.actor_meta) + 1}"
        props = {
            "type": entity_type,
            "id": str(uuid.uuid4()),
            "name": default_name,
            "display_name": default_name,
            "npc_role": role,
            "triggered": True,
            "_cutscene_temporary": True,
        }
        actor = (NPC if entity_type == "npc" else Creature)(pos=pos, properties=props)
        actor.properties["npc_role"] = role
        actor.properties["_cutscene_temporary"] = True

        self.main_window.state.things.append(actor)
        self.actor_objects[str(actor.properties.get("id"))] = actor
        self.temporary_actor_ids.add(str(actor.properties.get("id")))
        self.actor_meta[str(actor.properties.get("id"))] = {
            "id": str(actor.properties.get("id")),
            "name": str(actor.properties.get("display_name") or actor.properties.get("name")),
            "spawn": True,
        }
        self.main_window.set_selected_object(actor)
        self.main_window.update_all_ui()
        self._refresh_actor_lists()
        self._select_actor_id(str(actor.properties.get("id")))
        self.main_window.show_toast(
            f"{default_name} created in the current 3D view"
        )

    def _capture_selected_actors(self):
        selected = _selected_actors(self.main_window)
        if not selected:
            QtWidgets.QMessageBox.information(
                self,
                "Actors",
                "Select one or more NPCs or creatures in the editor first.",
            )
            return
        for actor in selected:
            props = actor.properties
            aid = str(props.get("id", "") or "")
            if not aid:
                aid = str(uuid.uuid4())
                props["id"] = aid
            self.actor_objects[aid] = actor
            self.actor_meta[aid] = {
                "id": aid,
                "name": str(props.get("display_name") or props.get("name") or aid),
                "spawn": aid in self.temporary_actor_ids,
            }
        self._refresh_actor_lists()
        self._select_actor_id(str(selected[0].properties.get("id", "")))

    def _remove_selected_actors(self):
        item = self.actor_list.currentItem()
        if item is None:
            return
        aid = str(item.data(QtCore.Qt.UserRole))
        self.actor_meta.pop(aid, None)
        self.actor_tracks.pop(aid, None)
        if aid in self.temporary_actor_ids:
            actor = self.actor_objects.get(aid)
            if actor is not None:
                try:
                    self.main_window.state.things.remove(actor)
                except ValueError:
                    pass
            self.temporary_actor_ids.discard(aid)
        self.actor_objects.pop(aid, None)
        self._refresh_actor_lists()
        self._refresh_waypoints()
        self.main_window.update_all_ui()
        self._refresh_summary()

    def _actor_selection_changed(self):
        aid = self._current_actor_id()
        actor = self.actor_objects.get(aid) if aid else None
        if actor is not None:
            try:
                self.main_window.set_selected_object(actor)
            except Exception:
                pass
            name = self.actor_meta.get(aid, {}).get("name", aid)
            self.selected_actor_label.setText(f"Selected: {name}")
        else:
            self.selected_actor_label.setText("No actor selected")
        self._refresh_waypoints()

    def _focus_selected_actor(self):
        actor = self.actor_objects.get(self._current_actor_id())
        if actor is None:
            return
        try:
            self.main_window.focus_on_object(actor)
        except Exception:
            pass

    def _current_actor_id(self):
        item = self.actor_list.currentItem()
        return str(item.data(QtCore.Qt.UserRole)) if item is not None else ""

    def _select_actor_id(self, aid):
        for i in range(self.actor_list.count()):
            if str(self.actor_list.item(i).data(QtCore.Qt.UserRole)) == str(aid):
                self.actor_list.setCurrentRow(i)
                break

    def _target_actor_ids(self):
        return list(self.actor_meta.keys())

    def _refresh_actor_lists(self):
        wanted = self._current_actor_id()
        widgets = [self.actor_list, self.attackers, self.defenders]
        old_attackers = {
            str(x.data(QtCore.Qt.UserRole)) for x in self.attackers.selectedItems()
        } if hasattr(self, "attackers") else set()
        old_defenders = {
            str(x.data(QtCore.Qt.UserRole)) for x in self.defenders.selectedItems()
        } if hasattr(self, "defenders") else set()

        self.actor_list.blockSignals(True)
        self.actor_list.clear()
        for aid, meta in self.actor_meta.items():
            item = QtWidgets.QListWidgetItem(meta["name"])
            if meta.get("spawn"):
                item.setText(f"★ {meta['name']}")
                item.setToolTip("Temporary actor — embedded in the cutscene and deleted from the map after authoring")
            item.setData(QtCore.Qt.UserRole, aid)
            self.actor_list.addItem(item)
        self.actor_list.blockSignals(False)

        for widget in (self.attackers, self.defenders):
            widget.clear()
            for aid, meta in self.actor_meta.items():
                item = QtWidgets.QListWidgetItem(meta["name"])
                item.setData(QtCore.Qt.UserRole, aid)
                widget.addItem(item)

        self._restore_multi_selection(self.attackers, old_attackers)
        self._restore_multi_selection(self.defenders, old_defenders)
        if wanted:
            self._select_actor_id(wanted)

        for combo in (self.look_at, self.waypoint_target, self.dialogue_speaker):
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            if combo is self.look_at:
                combo.addItem("Keep camera rotation", "")
            elif combo is self.waypoint_target:
                combo.addItem("No target — use actor's current position", "")
            else:
                combo.addItem("Narrator", "")
            for aid, meta in self.actor_meta.items():
                combo.addItem(meta["name"], aid)
            idx = combo.findData(current)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.blockSignals(False)

        self._update_waypoint_controls()
        self._refresh_summary()

    @staticmethod
    def _restore_multi_selection(widget, ids):
        for i in range(widget.count()):
            if str(widget.item(i).data(QtCore.Qt.UserRole)) in ids:
                widget.item(i).setSelected(True)

    def _update_waypoint_controls(self):
        is_attack = self.waypoint_action.currentData() == "attack"
        self.waypoint_attack_duration.setEnabled(is_attack)
        self.waypoint_target.setToolTip(
            "Attack this actor" if is_attack else
            "Move to this actor's current position"
        )

    def _add_waypoint(self, from_current=True):
        aid = self._current_actor_id()
        actor = self.actor_objects.get(aid)
        if not aid or actor is None:
            QtWidgets.QMessageBox.information(
                self, "Waypoint", "Select an actor first."
            )
            return

        target_id = str(self.waypoint_target.currentData() or "")
        if target_id == aid:
            target_id = ""
        action = str(self.waypoint_action.currentData() or "move")
        if target_id and target_id not in self.actor_meta:
            target_id = ""

        if target_id:
            target_obj = self.actor_objects.get(target_id)
            pos = _v3(target_obj.pos) if target_obj is not None else _v3(actor.pos)
        else:
            pos = _v3(actor.pos)

        row = {
            "time": float(self.waypoint_time.value()),
            "pos": pos,
            "yaw": float(getattr(actor, "angle", 0.0)),
            "action": action,
        }
        if target_id:
            row["target_id"] = target_id
        if action == "attack":
            if not target_id:
                QtWidgets.QMessageBox.warning(
                    self, "Waypoint", "Attack waypoints need a target."
                )
                return
            duration = float(self.waypoint_attack_duration.value())
            row["duration"] = duration
            self.events.append({
                "time": row["time"],
                "type": "fight",
                "duration": duration,
                "attackers": [aid],
                "defenders": [target_id],
                "style": "normal",
                "_simple_waypoint": True,
            })

        self.actor_tracks.setdefault(aid, []).append(row)
        self.actor_tracks[aid].sort(key=lambda x: x["time"])
        self._refresh_actor_keys_list()
        self._refresh_waypoints()
        self._refresh_event_list()
        self._refresh_summary()

        # Fast authoring: next waypoint starts one second later.
        self.waypoint_time.setValue(float(row["time"]) + (float(row.get("duration", 0.0)) if action == "attack" else 1.0))

    def _remove_selected_waypoint(self):
        aid = self._current_actor_id()
        if not aid:
            return
        row = self.waypoint_list.currentRow()
        frames = self.actor_tracks.get(aid, [])
        if not (0 <= row < len(frames)):
            return
        frame = frames.pop(row)
        if frame.get("action") == "attack" and frame.get("target_id"):
            t = float(frame.get("time", 0))
            d = float(frame.get("duration", 0))
            self.events = [
                e for e in self.events
                if not (
                    e.get("_simple_waypoint")
                    and e.get("type") == "fight"
                    and float(e.get("time", -1)) == t
                    and e.get("attackers") == [aid]
                    and e.get("defenders") == [frame.get("target_id")]
                    and float(e.get("duration", -1)) == d
                )
            ]
        if not frames:
            self.actor_tracks.pop(aid, None)
        self._refresh_actor_keys_list()
        self._refresh_waypoints()
        self._refresh_event_list()
        self._refresh_summary()

    def _refresh_waypoints(self):
        self.waypoint_list.clear()
        aid = self._current_actor_id()
        for row in self.actor_tracks.get(aid, []):
            action = str(row.get("action", "move")).capitalize()
            target = row.get("target_id")
            target_name = self.actor_meta.get(str(target), {}).get("name", "") if target else ""
            suffix = f" → {target_name}" if target_name else ""
            self.waypoint_list.addItem(
                f"{float(row.get('time', 0.0)):.2f}s — {action}{suffix} — {row.get('pos')}"
            )

    # ------------------------------------------------------------------
    # Camera + exact keyframes.
    # ------------------------------------------------------------------
    def _capture_actor_keyframe(self):
        actors = _selected_actors(self.main_window)
        if not actors:
            QtWidgets.QMessageBox.information(
                self, "Movement", "Select actors in the editor first."
            )
            return
        t = float(self.actor_time.value())
        for actor in actors:
            aid = str(actor.properties.get("id", "") or "")
            if not aid:
                continue
            self.actor_objects[aid] = actor
            if aid not in self.actor_meta:
                self.actor_meta[aid] = {
                    "id": aid,
                    "name": str(actor.properties.get("display_name") or actor.properties.get("name") or aid),
                    "spawn": aid in self.temporary_actor_ids,
                }
            self.actor_tracks.setdefault(aid, []).append({
                "time": t,
                "pos": _v3(actor.pos),
                "yaw": float(getattr(actor, "angle", 0.0)),
            })
            self.actor_tracks[aid].sort(key=lambda x: x["time"])
        self._refresh_actor_lists()
        self._refresh_actor_keys_list()
        self._refresh_summary()

    def _capture_camera_keyframe(self):
        camera = self.main_window.view_3d.camera
        frame = {
            "time": float(self.camera_time.value()),
            "pos": _v3(camera.pos),
            "yaw": float(camera.yaw),
            "pitch": float(camera.pitch),
            "fov": float(getattr(camera, "fov", 90.0)),
        }
        aid = self.look_at.currentData()
        if aid:
            frame["look_at"] = {"actor": str(aid)}
        self.camera_keys.append(frame)
        self.camera_keys.sort(key=lambda x: x["time"])
        self.camera_keys_list.clear()
        for row in self.camera_keys:
            look = row.get("look_at", {}).get("actor", "")
            target = self.actor_meta.get(str(look), {}).get("name", "") if look else ""
            suffix = f" — look at {target}" if target else ""
            self.camera_keys_list.addItem(
                f"{row['time']:.2f}s — camera {row['pos']}{suffix}"
            )
        self.camera_time.setValue(float(frame["time"]) + 1.0)

    def _refresh_actor_keys_list(self):
        self.actor_keys_list.clear()
        for aid, rows in sorted(self.actor_tracks.items()):
            name = self.actor_meta.get(aid, {}).get("name", aid)
            for row in rows:
                self.actor_keys_list.addItem(
                    f"{float(row.get('time', 0)):.2f}s — {name} → {row.get('pos')}"
                )

    # ------------------------------------------------------------------
    # Existing event functionality.
    # ------------------------------------------------------------------
    def _add_fight(self):
        attackers = [
            str(x.data(QtCore.Qt.UserRole)) for x in self.attackers.selectedItems()
        ]
        defenders = [
            str(x.data(QtCore.Qt.UserRole)) for x in self.defenders.selectedItems()
        ]
        if not attackers or not defenders:
            QtWidgets.QMessageBox.warning(
                self, "Fight", "Choose at least one attacker and one defender."
            )
            return
        self.events.append({
            "time": float(self.fight_time.value()),
            "type": "fight",
            "duration": float(self.fight_duration.value()),
            "attackers": attackers,
            "defenders": defenders,
            "style": self.fight_style.currentData(),
        })
        self._refresh_event_list()
        self._refresh_summary()

    def _use_selected_position(self):
        actors = _selected_actors(self.main_window)
        if actors:
            pos = _v3(actors[0].pos)
            self.blood_x.setValue(pos[0])
            self.blood_y.setValue(pos[1])
            self.blood_z.setValue(pos[2])

    def _add_blood(self):
        self.events.append({
            "time": float(self.blood_time.value()),
            "type": "blood",
            "position": [
                self.blood_x.value(), self.blood_y.value(), self.blood_z.value()
            ],
            "variant": self.blood_variant.currentData(),
            "width": float(self.blood_w.value()),
            "height": float(self.blood_h.value()),
            "persist": True,
        })
        self._refresh_event_list()
        self._refresh_summary()

    def _add_dialogue(self):
        text = self.dialogue_text.toPlainText().strip()
        if not text:
            QtWidgets.QMessageBox.warning(self, "Dialogue", "Enter dialogue text first.")
            return
        self.events.append({
            "time": float(self.dialogue_time.value()),
            "type": "dialogue",
            "duration": float(self.dialogue_duration.value()),
            "speaker_id": self.dialogue_speaker.currentData() or "",
            "text": text,
        })
        self._refresh_event_list()
        self._refresh_summary()

    def _add_message(self):
        text = self.message_text.text()
        self.events.append({
            "time": float(self.message_time.value()),
            "type": "message",
            "line": self.message_line.currentText(),
            "text": text,
        })
        self._refresh_event_list()
        self._refresh_summary()

    def _remove_event(self):
        row = self.event_list.currentRow()
        if 0 <= row < len(self.events):
            # event list is sorted for display, so map the selected display
            # row back to the actual event object rather than assuming storage
            # order matches display order.
            ordered = sorted(
                enumerate(self.events), key=lambda item: item[1].get("time", 0)
            )
            index = ordered[row][0]
            self.events.pop(index)
            self._refresh_event_list()
            self._refresh_summary()

    def _refresh_event_list(self):
        self.event_list.clear()
        for event in sorted(self.events, key=lambda x: x.get("time", 0)):
            kind = event["type"]
            label = f"{event['time']:.2f}s — {kind}"
            if kind == "fight":
                label += f" ({len(event.get('attackers', []))} vs {len(event.get('defenders', []))})"
            elif kind == "dialogue":
                label += f" — {str(event.get('text', ''))[:45]}"
            elif kind == "message":
                label += f" — {event.get('line', 'message')}: {str(event.get('text', ''))[:45]}"
            self.event_list.addItem(label)

    # ------------------------------------------------------------------
    # Refresh / save / cleanup.
    # ------------------------------------------------------------------
    def _refresh_summary(self):
        self.summary.setText(
            f"Actors {len(self.actor_meta)}  |  "
            f"Waypoints {sum(len(v) for v in self.actor_tracks.values())}  |  "
            f"Camera {len(self.camera_keys)}  |  Events {len(self.events)}"
        )

    def _filename(self):
        name = self.filename.text().strip() or self.name.text().strip() or "cutscene"
        if not name.lower().endswith(".json"):
            name += ".json"
        return name.split("/")[-1].split("\\")[-1]

    def _actor_definition(self, aid):
        actor = self.actor_objects.get(aid)
        if actor is None:
            return None
        props = {
            key: value
            for key, value in dict(getattr(actor, "properties", {})).items()
            if key != "_io_connections" and not str(key).startswith("_cutscene_")
        }
        props["id"] = str(aid)
        return {
            "type": str(props.get("type") or "npc"),
            "pos": _v3(actor.pos),
            "properties": props,
        }

    def _delete_temporary_actors(self):
        if self._cleaned:
            return
        for aid in list(self.temporary_actor_ids):
            actor = self.actor_objects.get(aid)
            if actor is None:
                continue
            try:
                self.main_window.state.things.remove(actor)
            except ValueError:
                pass
        self.temporary_actor_ids.clear()
        self._cleaned = True
        try:
            selected = getattr(self.main_window.state, "selected_object", None)
            if selected is not None and bool(
                getattr(selected, "properties", {}).get("_cutscene_temporary")
            ):
                self.main_window.set_selected_object(None)
        except Exception:
            pass
        try:
            self.main_window.update_all_ui()
        except Exception:
            pass

    def _cleanup_after_cancel(self):
        # Temporary actors are authoring state, not a map edit.  Do not touch
        # the editor's dirty flag here: the user may have made unrelated map
        # edits while this modeless panel was open.
        self._delete_temporary_actors()

    def accept(self):
        if not self.camera_keys:
            QtWidgets.QMessageBox.warning(
                self, "No camera keyframes",
                "Capture at least one camera position."
            )
            return
        if not self.actor_meta and not self.events:
            QtWidgets.QMessageBox.warning(
                self, "Empty cutscene",
                "Create/capture at least one actor or add a timed event."
            )
            return

        filename = self._filename()
        path = cutscene_files.cutscene_path(filename)
        if QtCore.QFileInfo(path).exists():
            result = QtWidgets.QMessageBox.question(
                self, "Overwrite cutscene",
                f"{filename} already exists. Replace it?"
            )
            if result != QtWidgets.QMessageBox.Yes:
                return

        actors = []
        for aid, meta in self.actor_meta.items():
            row = {"id": aid, "name": meta["name"]}
            if meta.get("spawn") or aid in self.temporary_actor_ids:
                definition = self._actor_definition(aid)
                if definition is not None:
                    row["spawn"] = True
                    row["definition"] = definition
            actors.append(row)

        data = {
            "version": 2,
            "id": str(uuid.uuid4()),
            "name": self.name.text().strip() or "Cutscene",
            "actors": actors,
            "camera": self.camera_keys,
            "actor_tracks": self.actor_tracks,
            "events": sorted(
                self.events,
                key=lambda x: x.get("time", 0)
            ),
            "settings": {
                "restore_actors": self.restore.isChecked(),
                "stop_on_escape": self.stop_escape.isChecked(),
            },
        }

        written = cutscene_files.save_cutscene(data, filename)
        if not written:
            QtWidgets.QMessageBox.warning(
                self, "Save failed",
                "The cutscene JSON could not be written."
            )
            return

        from game.entities import MiniwindCutscene
        selected = _selected_actors(self.main_window)
        pos = (
            _v3(selected[0].pos)
            if selected
            else _v3(self.main_window.view_3d.camera.pos)
        )
        props = {
            "type": "miniwindcutscene",
            "id": str(uuid.uuid4()),
            "cutscene_file": filename,
            "trigger_mode": self.trigger_mode.currentData(),
            "trigger_radius": float(self.radius.value()),
            "once": self.once.isChecked(),
            "restore_actors": self.restore.isChecked(),
            "stop_on_escape": self.stop_escape.isChecked(),
            "hidden_in_game": True,
        }
        scene = MiniwindCutscene(pos=pos, properties=props)
        self.main_window.state.save_state()
        self.main_window.state.things.append(scene)
        self.main_window.set_selected_object(scene)
        self.main_window.unsaved_changes = True
        self.main_window.update_all_ui()

        self._delete_temporary_actors()
        self._saved = True
        self.main_window.show_toast(f"Created cutscene {filename}")
        super().accept()

    def reject(self):
        self._cleanup_after_cancel()
        super().reject()

    def closeEvent(self, event):
        if not self._saved:
            self._cleanup_after_cancel()
        super().closeEvent(event)


# Backwards-compatible class name retained for MainWindow.open_cutscene_wizard.
CutsceneWizard = CutsceneWizard
