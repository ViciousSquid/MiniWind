"""Fio cutscene authoring panel.

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

import glm

from PyQt5 import QtWidgets, QtCore

from pathlib import Path

CUTSCENE_DIR = "cutscenes"

#: What a cutscene actor can do on a keyframe. MOVE lives on the actor's track;
#: SAY and THINK are line events; ATTACK is a battle (a ``fight`` event).
KEYFRAME_KINDS = (("MOVE", "move"), ("SAY", "say"), ("THINK", "think"),
                  ("ATTACK", "attack"))
LINE_SECONDS = 3.0

# ---------------------------------------------------------------------------
# Extension points: a game casts its own actors and edits them its own way.
# ---------------------------------------------------------------------------
#: The kinds of actor the wizard's "+" buttons make, in order:
#: ``(button label, entity class name in ENTITY_TYPES, default properties)``.
ACTOR_KINDS = [("+ Actor", "Monster", {"monster_type": "human", "triggered": True})]
#: Panels editing the actors selected in the wizard, each
#: ``factory(wizard, actors) -> QWidget or None`` (None: nothing for these).
#: A panel edits the actors' properties in place and calls
#: ``wizard.actors_changed(actors)`` after any change.
ACTOR_PANELS = []
#: A top-down game sets this (MiniWind does): a camera keyframe is where the
#: camera is and how high -- it always looks straight down -- and "look at"
#: an actor keeps the camera over it.
TOP_DOWN_CAMERA = False
#: The editor camera's pitch for looking straight down (a touch off -90).
TOP_DOWN_PITCH = -89.9

#: Entity types the wizard accepts as actors ("+ Selected", loading).
ACTOR_TYPES = {"monster"}
#: Entity type -> the class that makes it, for kinds registered with a class
#: (found before the editor's ENTITY_TYPES, which may not list it yet).
ACTOR_CLASSES = {}


def register_actor_kind(label, cls, properties=None, *, replace_default=False,
                        entity_type=None):
    """Add a "+" button making a *cls* actor (a class, or a class name in
    ENTITY_TYPES) with *properties*. *entity_type* is the ``type`` such an
    actor carries, accepted from then on. *replace_default* drops the
    engine's plain "+ Actor"."""
    global ACTOR_KINDS
    if replace_default:
        ACTOR_KINDS = [k for k in ACTOR_KINDS if k[1] != "Monster"]
    ACTOR_KINDS = [k for k in ACTOR_KINDS if k[0] != label]
    ACTOR_KINDS.append((str(label), cls, dict(properties or {})))
    if entity_type:
        ACTOR_TYPES.add(str(entity_type))
        if isinstance(cls, type):
            ACTOR_CLASSES[str(entity_type).lower()] = cls


def register_actor_panel(factory):
    """Add an actor-editing panel (see :data:`ACTOR_PANELS`)."""
    if factory not in ACTOR_PANELS:
        ACTOR_PANELS.append(factory)


def _entity_class(type_name):
    """The editor entity class for *type_name* (a class, a class name or a
    type id)."""
    from .things import ENTITY_TYPES, Monster
    if isinstance(type_name, type):
        return type_name
    cls = ACTOR_CLASSES.get(str(type_name).lower()) or ENTITY_TYPES.get(str(type_name))
    if cls is None:
        cls = next((value for key, value in ENTITY_TYPES.items()
                    if str(key).lower() == str(type_name).lower()), None)
    return cls or Monster


def _v3(value):
    if hasattr(value, "x"):
        return [float(value.x), float(value.y), float(value.z)]
    values = list(value)
    return [float(values[0]), float(values[1]), float(values[2])]


def _facing(actor):
    """*actor*'s facing in degrees (0 = +Z, 90 = +X): its ``angle``
    property, the one the game turns its head by (engine.monster_facing)."""
    props = getattr(actor, "properties", {}) or {}
    try:
        return float(props.get("angle", getattr(actor, "angle", 0.0)) or 0.0) % 360.0
    except (TypeError, ValueError):
        return 0.0


def _set_facing(actor, degrees):
    """Turn *actor* to face *degrees*."""
    props = getattr(actor, "properties", None)
    if isinstance(props, dict):
        props["angle"] = float(degrees) % 360.0
    else:
        actor.angle = float(degrees)


def _is_actor(obj):
    return str(getattr(obj, "properties", {}).get("type", "")) in ACTOR_TYPES


def _selected_actors(main_window):
    return [obj for obj in main_window.state.selected_objects if _is_actor(obj)]


class CutsceneWizard(QtWidgets.QDialog):
    """Modeless live cutscene authoring panel.

    The editor remains fully usable while this panel is open. Temporary actors
    are ordinary editor entities, which means selection, movement and property
    editing all work through the normal Fio editor machinery.
    """

    @staticmethod
    def _scroll_page(page):
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setWidget(page)
        return scroll

    def __init__(self, main_window, parent=None):
        super().__init__(parent or main_window)
        self.main_window = main_window
        self.setWindowTitle("Fio Cutscenes")
        self.setMinimumSize(560, 760)
        self.resize(640, 900)
        self.setWindowModality(QtCore.Qt.NonModal)
        self.setWindowFlag(QtCore.Qt.Tool, True)
        # Use the same application stylesheet as the rest of Fio.
        app = QtWidgets.QApplication.instance()
        if app is not None and app.styleSheet():
            self.setStyleSheet(app.styleSheet())

        self.actor_meta = {}
        self.actor_objects = {}
        self.temporary_actor_ids = set()
        self.actor_tracks = {}
        self.camera_keys = []
        self.events = []
        self._saved = False
        self._cleaned = False
        self._saved_signature = None
        self._close_prompt_active = False

        # Editor-side cutscene preview transport. This previews choreography
        # without firing gameplay combat or permanently changing the map.
        self._preview_timer = QtCore.QTimer(self)
        self._preview_timer.setInterval(33)
        self._preview_timer.timeout.connect(self._preview_tick)
        self._preview_time = 0.0
        self._preview_rate = 0.0
        self._preview_duration = 0.0
        self._preview_actor_baseline = {}
        self._preview_camera_baseline = None

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # The wizard is deliberately wider than tall: most authoring happens
        # through the 3D viewport, while the wizard provides compact controls.
        self.setMinimumSize(900, 620)
        self.resize(980, 720)

        tabs = QtWidgets.QTabWidget()
        tabs.setStyleSheet(
            "QTabBar::tab:selected { border-bottom: 2px solid #e67e22; }"
        )
        root.addWidget(tabs, 1)

        # -----------------------------------------------------------------
        # Setup
        # -----------------------------------------------------------------
        setup_page = QtWidgets.QWidget()
        setup_layout = QtWidgets.QVBoxLayout(setup_page)
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
        self.restore = QtWidgets.QCheckBox("Restore existing actors after cutscene")
        self.restore.setChecked(True)
        self.stop_escape = QtWidgets.QCheckBox("Escape stops the cutscene")
        self.stop_escape.setChecked(True)
        checkbox_style = (
            "QCheckBox::indicator:checked { background-color: #e67e22; "
            "border: 1px solid #e67e22; }"
            "QCheckBox::indicator:unchecked { background-color: transparent; "
            "border: 1px solid #e67e22; }"
        )
        for checkbox in (self.once, self.restore, self.stop_escape):
            checkbox.setStyleSheet(checkbox_style)
        form.addRow("Name", self.name)
        form.addRow("File", self.filename)
        form.addRow("Trigger", self.trigger_mode)
        form.addRow("Radius", self.radius)
        form.addRow("", self.once)
        form.addRow("", self.restore)
        form.addRow("", self.stop_escape)
        setup_layout.addWidget(header)
        setup_help = QtWidgets.QLabel(
            "<b>Workflow:</b> cast actors and equip them (Actors &amp; Keyframes), place them "
            "in the 3D view, give them MOVE, SAY, THINK and ATTACK keyframes, then set the "
            "camera shots. Message and I/O events are optional. "
            "The temporary actors are removed after the cutscene finishes."
        )
        setup_help.setWordWrap(True)
        setup_help.setMinimumHeight(55)
        setup_layout.addWidget(setup_help)
        setup_layout.addStretch(1)
        tabs.addTab(self._scroll_page(setup_page), "Setup")

        # -----------------------------------------------------------------
        # Actors + keyframes — the main authoring workflow.
        # -----------------------------------------------------------------
        actors_page = QtWidgets.QWidget()
        actors_layout = QtWidgets.QHBoxLayout(actors_page)
        actors_layout.setContentsMargins(0, 0, 0, 0)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        actors_layout.addWidget(splitter)

        actors_box = QtWidgets.QGroupBox("Cast")
        av = QtWidgets.QVBoxLayout(actors_box)
        help_label = QtWidgets.QLabel(
            "Add actors, then place them in the 3D view. Select one to edit it, "
            "or many (Ctrl/Shift-click, or a group below) to give them all the "
            "same keyframe."
        )
        help_label.setWordWrap(True)
        av.addWidget(help_label)

        kind_row = QtWidgets.QHBoxLayout()
        self.kind_buttons = []
        for kind in ACTOR_KINDS:
            button = QtWidgets.QPushButton(kind[0])
            button.clicked.connect(lambda _c=False, k=kind: self._create_temporary_actor(k))
            kind_row.addWidget(button)
            self.kind_buttons.append(button)
        # The engine's plain "+ Actor", kept for code that asks for it.
        self.add_actor_button = self.kind_buttons[0] if self.kind_buttons else QtWidgets.QPushButton()
        av.addLayout(kind_row)

        actor_buttons = QtWidgets.QHBoxLayout()
        self.capture_button = QtWidgets.QPushButton("+ Selected")
        self.capture_button.setToolTip("Cast the actors selected in the map")
        self.duplicate_actor_button = QtWidgets.QPushButton("Duplicate")
        self.remove_actor_button = QtWidgets.QPushButton("Remove")
        self.focus_actor_button = QtWidgets.QPushButton("Focus")
        for button in (self.capture_button, self.duplicate_actor_button,
                       self.remove_actor_button, self.focus_actor_button):
            actor_buttons.addWidget(button)
        av.addLayout(actor_buttons)

        self.select_group = QtWidgets.QComboBox()
        self.select_group.setToolTip("Select every actor of a team or role")
        av.addWidget(self.select_group)

        self.actor_list = QtWidgets.QListWidget()
        self.actor_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.actor_list.setMinimumHeight(160)
        av.addWidget(self.actor_list, 1)
        self.selected_actor_label = QtWidgets.QLabel("No actor selected")
        self.selected_actor_label.setStyleSheet("font-weight: bold;")
        av.addWidget(self.selected_actor_label)
        splitter.addWidget(actors_box)

        right_tabs = QtWidgets.QTabWidget()
        self.actor_tabs = right_tabs

        # The selected actors themselves: the game's panels (inventory, attack
        # style, spells...) or, with none, their name.
        self.actor_panel_host = QtWidgets.QWidget()
        self.actor_panel_layout = QtWidgets.QVBoxLayout(self.actor_panel_host)
        self.actor_panel_layout.setContentsMargins(4, 4, 4, 4)
        right_tabs.addTab(self._scroll_page(self.actor_panel_host), "Actor")

        keys_page = QtWidgets.QWidget()
        kv = QtWidgets.QVBoxLayout(keys_page)
        keys_help = QtWidgets.QLabel(
            "Give the selected actors something to do at a moment in the cutscene: "
            "<b>MOVE</b> to where they stand in the 3D view, <b>SAY</b> or "
            "<b>THINK</b> a line, or <b>ATTACK</b> — fight other actors with the "
            "game's own combat (melee, bow or magic, as each is equipped)."
        )
        keys_help.setWordWrap(True)
        kv.addWidget(keys_help)

        time_row = QtWidgets.QHBoxLayout()
        time_row.addWidget(QtWidgets.QLabel("<b>At</b>"))
        self.key_time = QtWidgets.QDoubleSpinBox()
        self.key_time.setRange(0, 3600)
        self.key_time.setDecimals(2)
        self.key_time.setSuffix(" s")
        time_row.addWidget(self.key_time)
        time_row.addWidget(QtWidgets.QLabel("<b>do</b>"))
        self.key_kind = QtWidgets.QComboBox()
        for label, value in KEYFRAME_KINDS:
            self.key_kind.addItem(label, value)
        time_row.addWidget(self.key_kind)
        time_row.addStretch(1)
        kv.addLayout(time_row)

        self.key_stack = QtWidgets.QStackedWidget()
        # MOVE
        move_page = QtWidgets.QWidget()
        mf = QtWidgets.QFormLayout(move_page)
        self.move_to = QtWidgets.QComboBox()
        mf.addRow("To", self.move_to)
        self.move_teleport = QtWidgets.QCheckBox("Teleport (cut there at this moment)")
        mf.addRow("", self.move_teleport)
        self.key_stack.addWidget(move_page)
        # SAY / THINK
        line_page = QtWidgets.QWidget()
        lf = QtWidgets.QFormLayout(line_page)
        self.line_text = QtWidgets.QLineEdit()
        self.line_text.setPlaceholderText("What they say or think")
        lf.addRow("Line", self.line_text)
        self.line_duration = QtWidgets.QDoubleSpinBox()
        self.line_duration.setRange(0.5, 60)
        self.line_duration.setDecimals(1)
        self.line_duration.setValue(LINE_SECONDS)
        self.line_duration.setSuffix(" s")
        lf.addRow("Shown for", self.line_duration)
        self.key_stack.addWidget(line_page)
        # ATTACK
        attack_page = QtWidgets.QWidget()
        af = QtWidgets.QFormLayout(attack_page)
        self.attack_group = QtWidgets.QComboBox()
        self.attack_group.setToolTip("Tick every actor of a team or role as a target")
        af.addRow("Targets", self.attack_group)
        self.attack_targets = QtWidgets.QListWidget()
        self.attack_targets.setMinimumHeight(110)
        af.addRow("", self.attack_targets)
        self.attack_duration = QtWidgets.QDoubleSpinBox()
        self.attack_duration.setRange(0.5, 600)
        self.attack_duration.setDecimals(1)
        self.attack_duration.setValue(10.0)
        self.attack_duration.setSuffix(" s")
        af.addRow("Fight for", self.attack_duration)
        self.attack_mutual = QtWidgets.QCheckBox("Targets fight back")
        self.attack_mutual.setChecked(True)
        af.addRow("", self.attack_mutual)
        self.key_stack.addWidget(attack_page)
        kv.addWidget(self.key_stack)

        self.add_key_button = QtWidgets.QPushButton("Add keyframe")
        self.add_key_button.setStyleSheet(
            "QPushButton { background: #e67e22; color: white; font-weight: bold; padding: 6px 12px; }"
            "QPushButton:hover { background: #f39c12; }"
        )
        kv.addWidget(self.add_key_button)

        self.key_list = QtWidgets.QListWidget()
        self.key_list.setMinimumHeight(140)
        self.key_list.setToolTip("Double-click to edit")
        kv.addWidget(self.key_list, 1)
        key_buttons = QtWidgets.QHBoxLayout()
        self.edit_key_button = QtWidgets.QPushButton("Edit")
        self.remove_key_button = QtWidgets.QPushButton("Remove")
        key_buttons.addWidget(self.edit_key_button)
        key_buttons.addWidget(self.remove_key_button)
        key_buttons.addStretch(1)
        kv.addLayout(key_buttons)
        right_tabs.addTab(keys_page, "Keyframes")
        splitter.addWidget(right_tabs)
        splitter.setStretchFactor(1, 2)

        tabs.addTab(actors_page, "Actors && Keyframes")
        self._key_refs = []
        self._pick = None

        # -----------------------------------------------------------------
        # Camera
        # -----------------------------------------------------------------
        camera_page = QtWidgets.QWidget()
        camera_layout = QtWidgets.QVBoxLayout(camera_page)
        camera_box = QtWidgets.QGroupBox("Keyframes")
        cv = QtWidgets.QVBoxLayout(camera_box)
        camera_help = QtWidgets.QLabel(
            "Move the editor camera to the shot you want, choose a time, then "
            "press Capture. Optionally make the camera look at an actor."
        )
        camera_help.setWordWrap(True)
        cv.addWidget(camera_help)
        camera_row = QtWidgets.QHBoxLayout()
        self.camera_time = QtWidgets.QDoubleSpinBox()
        self.camera_time.setRange(0, 3600)
        self.camera_time.setDecimals(2)
        self.camera_time.setValue(0)
        self.camera_time.setSuffix(" s")
        self.look_at = QtWidgets.QComboBox()
        self.look_at.addItem("Keep camera rotation", "")
        camera_row.addWidget(QtWidgets.QLabel("At time"))
        camera_row.addWidget(self.camera_time)
        camera_row.addWidget(QtWidgets.QLabel("Look at"))
        camera_row.addWidget(self.look_at, 1)
        self.camera_teleport = QtWidgets.QCheckBox("Teleport")
        self.camera_teleport.setToolTip(
            "Cut instantly to this keyframe instead of moving the camera from the previous one."
        )
        camera_row.addWidget(self.camera_teleport)
        cv.addLayout(camera_row)
        self.capture_camera_button = QtWidgets.QPushButton("Capture camera position")
        self.capture_camera_button.setStyleSheet(
            "QPushButton { background: #e67e22; color: white; font-weight: bold; padding: 6px 12px; }"
            "QPushButton:hover { background: #f39c12; }"
        )
        self.capture_camera_button.clicked.connect(self._capture_camera_keyframe)
        cv.addWidget(self.capture_camera_button)
        self.camera_keys_list = QtWidgets.QListWidget()
        self.camera_keys_list.setMinimumHeight(120)
        cv.addWidget(self.camera_keys_list, 1)
        camera_buttons = QtWidgets.QHBoxLayout()
        camera_buttons.addWidget(QtWidgets.QLabel("Selected time"))
        self.camera_edit_time = QtWidgets.QDoubleSpinBox()
        self.camera_edit_time.setRange(0, 3600)
        self.camera_edit_time.setDecimals(2)
        self.camera_edit_time.setSuffix(" s")
        self.camera_edit_time.setEnabled(False)
        camera_buttons.addWidget(self.camera_edit_time)
        set_camera_time_button = QtWidgets.QPushButton("Set")
        set_camera_time_button.clicked.connect(self._set_selected_camera_keyframe_time)
        camera_buttons.addWidget(set_camera_time_button)
        delete_camera_button = QtWidgets.QPushButton("Remove")
        delete_camera_button.clicked.connect(self._remove_selected_camera_keyframe)
        camera_buttons.addWidget(delete_camera_button)
        camera_buttons.addStretch(1)
        cv.addLayout(camera_buttons)
        self.camera_keys_list.currentRowChanged.connect(self._camera_keyframe_selected)
        camera_layout.addWidget(camera_box, 1)
        tabs.addTab(self._scroll_page(camera_page), "Camera")

        # -----------------------------------------------------------------
        # Events. Advanced functionality remains available, but it no
        # longer makes the primary wizard vertically enormous.
        # -----------------------------------------------------------------
        events_page = QtWidgets.QWidget()
        events_outer = QtWidgets.QVBoxLayout(events_page)
        events_scroll = QtWidgets.QScrollArea(events_page)
        events_scroll.setWidgetResizable(True)
        events_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        events_content = QtWidgets.QWidget()
        events_layout = QtWidgets.QVBoxLayout(events_content)
        events_scroll.setWidget(events_content)
        events_outer.addWidget(events_scroll)
        events_tabs = QtWidgets.QTabWidget()
        self._build_message_tab(events_tabs)
        self._build_io_tab(events_tabs)
        events_layout.addWidget(events_tabs, 1)

        self.event_list = QtWidgets.QListWidget()
        self.event_list.setMinimumHeight(100)
        events_layout.addWidget(self.event_list)
        self.event_list.itemDoubleClicked.connect(self._edit_selected_event)
        remove_event = QtWidgets.QPushButton("Remove selected event")
        remove_event.clicked.connect(self._remove_event)
        events_layout.addWidget(remove_event)

        # Keep the exact keyframe authoring functionality, but tuck it behind
        # the Events tab rather than forcing it into the simple workflow.
        advanced_toggle = QtWidgets.QToolButton()
        advanced_toggle.setText("Advanced: exact actor keyframes")
        advanced_toggle.setCheckable(True)
        advanced_toggle.setChecked(False)
        advanced_toggle.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        advanced_toggle.setArrowType(QtCore.Qt.RightArrow)
        events_layout.addWidget(advanced_toggle)

        advanced = QtWidgets.QWidget()
        advanced.setVisible(False)
        advanced_layout = QtWidgets.QVBoxLayout(advanced)
        exact_box = QtWidgets.QGroupBox("Exact actor keyframes")
        exact_form = QtWidgets.QFormLayout(exact_box)
        self.actor_time = QtWidgets.QDoubleSpinBox()
        self.actor_time.setRange(0, 3600)
        self.actor_time.setDecimals(2)
        self.actor_time.setValue(0)
        self.actor_time.setSuffix(" s")
        exact_form.addRow("Keyframe time", self.actor_time)
        self.actor_keys_list = QtWidgets.QListWidget()
        self.actor_keys_list.setMinimumHeight(70)
        exact_form.addRow(self.actor_keys_list)
        exact_buttons = QtWidgets.QHBoxLayout()
        self.capture_actor_button = QtWidgets.QPushButton(
            "Capture selected actors at this time"
        )
        self.capture_actor_button.clicked.connect(self._capture_actor_keyframe)
        exact_buttons.addWidget(self.capture_actor_button)
        exact_form.addRow(exact_buttons)
        advanced_layout.addWidget(exact_box)
        events_layout.addWidget(advanced)

        def toggle_advanced(checked):
            advanced.setVisible(checked)
            advanced_toggle.setArrowType(
                QtCore.Qt.DownArrow if checked else QtCore.Qt.RightArrow
            )

        advanced_toggle.toggled.connect(toggle_advanced)
        tabs.addTab(events_page, "Events")

        footer = QtWidgets.QHBoxLayout()
        self.summary = QtWidgets.QLabel("No actors created yet.")
        self.summary.setWordWrap(True)
        footer.addWidget(self.summary, 1)
        self.load_button = QtWidgets.QPushButton("Load")
        self.save_button = QtWidgets.QPushButton("Save")
        self.apply_button = QtWidgets.QPushButton("Apply")
        self.apply_button.setStyleSheet(
            "QPushButton { background: #e67e22; color: white; font-weight: bold; padding: 6px 12px; }"
            "QPushButton:hover { background: #f39c12; }"
        )
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.save_button.setDefault(True)
        self.cancel_button.setDefault(False)
        footer.addWidget(self.load_button)
        footer.addWidget(self.save_button)
        footer.addWidget(self.apply_button)
        footer.addWidget(self.cancel_button)
        root.addLayout(footer)

        # Preview transport is deliberately a separate control strip.
        playback_box = QtWidgets.QGroupBox("Preview")
        playback = QtWidgets.QHBoxLayout(playback_box)
        playback.setContentsMargins(8, 6, 8, 6)
        self.rewind_button = QtWidgets.QPushButton("Rewind")
        self.play_button = QtWidgets.QPushButton("Play")
        self.fast_forward_button = QtWidgets.QPushButton("Fast Forward")
        self.play_button.setStyleSheet(
            "QPushButton { background: #238636; color: white; font-weight: bold; "
            "padding: 6px 18px; border-radius: 4px; }"
            "QPushButton:hover { background: #2ea043; }"
        )
        self.preview_time_label = QtWidgets.QLabel("0.00s / 0.00s")
        self.preview_time_label.setMinimumWidth(110)
        self.preview_time_label.setAlignment(QtCore.Qt.AlignCenter)
        playback.addWidget(self.rewind_button)
        playback.addWidget(self.play_button)
        playback.addWidget(self.fast_forward_button)
        self.preview_lines_label = QtWidgets.QLabel("")
        self.preview_lines_label.setStyleSheet("color: #e6c27a;")
        playback.addWidget(self.preview_lines_label, 1)
        playback.addWidget(self.preview_time_label)
        root.insertWidget(root.count() - 1, playback_box)

        self.rewind_button.clicked.connect(self._preview_rewind)
        self.play_button.clicked.connect(self._preview_play)
        self.fast_forward_button.clicked.connect(self._preview_fast_forward)

        self.capture_button.clicked.connect(self._capture_selected_actors)
        self.duplicate_actor_button.clicked.connect(self._duplicate_selected_actors)
        self.remove_actor_button.clicked.connect(self._remove_selected_actors)
        self.focus_actor_button.clicked.connect(self._focus_selected_actor)
        self.actor_list.itemSelectionChanged.connect(self._actor_selection_changed)
        self.actor_list.itemDoubleClicked.connect(
            lambda _item: self._focus_selected_actor()
        )
        self.select_group.activated.connect(self._select_group)
        self.attack_group.activated.connect(self._check_group)
        self.key_kind.currentIndexChanged.connect(lambda _i: self._update_key_controls())
        self.add_key_button.clicked.connect(self._add_keyframe)
        self.key_list.itemDoubleClicked.connect(lambda _item: self._edit_selected_keyframe())
        self.edit_key_button.clicked.connect(self._edit_selected_keyframe)
        self.remove_key_button.clicked.connect(self._remove_selected_keyframe)
        self.load_button.clicked.connect(lambda _checked=False: self._load_cutscene())
        self.save_button.clicked.connect(self._save_and_close)
        self.apply_button.clicked.connect(self._apply_to_map)
        self.cancel_button.clicked.connect(self.reject)

        self._refresh_actor_lists()
        self._update_key_controls()
        self._rebuild_actor_panel()
        self._refresh_summary()
        self._load_current_map_cutscene()
        if self._saved_signature is None:
            self._saved_signature = self._cutscene_signature()

    # ------------------------------------------------------------------
    # Authoring in the map: the views ask the open cutscene editor first
    # (main_window.cutscene_author) -- hover and select tints, the right-click
    # action menu, the target / destination click, and who-does-what lines.
    # ------------------------------------------------------------------
    def hideEvent(self, event):
        if getattr(self.main_window, "cutscene_author", None) is self:
            self.main_window.cutscene_author = None
        self._pick = None
        self._repaint_views()
        super().hideEvent(event)

    def _repaint_views(self):
        for name in ("view_3d", "view_top", "view_front", "view_side"):
            view = getattr(self.main_window, name, None)
            if view is not None:
                try:
                    view.update()
                except Exception:
                    pass
        for view in getattr(self.main_window, "views_2d", []) or []:
            try:
                view.update()
            except Exception:
                pass

    def previewing(self):
        """The preview is playing (the who-does-what lines step aside)."""
        return bool(self._preview_rate)

    def is_cast(self, obj):
        aid = str(getattr(obj, "properties", {}).get("id", "") or "")
        return bool(aid) and aid in self.actor_meta

    def _aid(self, obj):
        return str(getattr(obj, "properties", {}).get("id", "") or "")

    def pick_armed(self):
        return getattr(self, "_pick", None) is not None

    def select_from_view(self, obj, add=False):
        """A click on a cast actor in the map selects it -- and its group,
        if it is in one -- in the cast; with *add* (Shift or Ctrl) adds it
        to the selection or takes it out."""
        aid = self._aid(obj)
        if aid not in self.actor_meta:
            return False
        aids = self._current_actor_ids()
        mates = self._group_of(aid)
        if add:
            aids = [a for a in aids if a not in mates] if aid in aids else aids + [m for m in mates if m not in aids]
        else:
            aids = mates
        self._select_actor_ids(aids)
        self._repaint_views()
        return True

    def sync_selection_from_editor(self):
        """Whatever the editor selected among the cast is the cast selection."""
        chosen = [self._aid(o) for o in self.main_window.state.selected_objects]
        chosen = [a for a in chosen if a in self.actor_meta]
        if chosen and set(chosen) != set(self._current_actor_ids()):
            self._select_actor_ids(chosen)

    def action_menu(self, obj, global_pos, parent=None):
        """Right-click on a cast actor: what it (and every selected actor
        with it) will do."""
        aid = self._aid(obj)
        if aid not in self.actor_meta:
            return False
        aids = self._current_actor_ids()
        if aid not in aids:
            self._select_actor_ids([aid])
            aids = [aid]
        who = self.actor_meta[aid]["name"] if len(aids) == 1 else f"{len(aids)} actors"
        menu = QtWidgets.QMenu(parent or self)
        try:
            from .view_2d import CONTEXT_MENU_STYLE
            menu.setStyleSheet(CONTEXT_MENU_STYLE)
        except Exception:
            pass
        head = menu.addAction(f"{who} — at {self.key_time.value():g}s")
        head.setEnabled(False)
        menu.addSeparator()
        attack = menu.addAction("ATTACK…")
        attack.setToolTip("Then click the target (Shift: their whole team)")
        move = menu.addAction("MOVE…")
        move.setToolTip("Then click where to go")
        say = menu.addAction("SAY…")
        think = menu.addAction("THINK…")
        face = menu.addAction("FACE…")
        face.setToolTip("Then click an actor or a spot: they turn to face it")
        menu.addSeparator()
        when = menu.addAction("Set the time…")
        edit = menu.addAction("Edit actor")
        remove = menu.addAction("Remove from the cutscene")
        chosen = menu.exec_(global_pos)
        if chosen is None:
            return True
        if chosen is attack:
            self._arm_pick("attack", aids)
        elif chosen is move:
            self._arm_pick("move", aids)
        elif chosen is face:
            self._arm_pick("face", aids)
        elif chosen in (say, think):
            kind = "say" if chosen is say else "think"
            line = self._ask_line(kind, who)
            if line is not None:
                text, seconds = line
                self.line_text.setText(text)
                self.line_duration.setValue(seconds)
                self._arm_pick(kind, aids, text=text)
        elif chosen is when:
            value, ok = QtWidgets.QInputDialog.getDouble(
                self.main_window, "Keyframe time", "At (seconds):",
                self.key_time.value(), 0.0, 3600.0, 2)
            if ok:
                self.key_time.setValue(value)
        elif chosen is edit:
            self.actor_tabs.setCurrentIndex(0)
            self.show()
            self.raise_()
        elif chosen is remove:
            self._remove_selected_actors()
        self._repaint_views()
        return True

    def _ask_line(self, kind, who):
        """``(text, seconds)`` for a SAY / THINK, asked in a small dialog: the
        question above its box, how long it is shown below; None if cancelled."""
        dialog = QtWidgets.QDialog(self.main_window)
        dialog.setWindowTitle(kind.upper())
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setSpacing(8)
        layout.addWidget(QtWidgets.QLabel(f"What does {who} {kind}?"))
        text = QtWidgets.QLineEdit(self.line_text.text())
        text.setMinimumWidth(380)
        text.selectAll()
        layout.addWidget(text)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Shown for"))
        seconds = QtWidgets.QDoubleSpinBox()
        seconds.setRange(0.5, 60)
        seconds.setDecimals(1)
        seconds.setSuffix(" s")
        seconds.setValue(float(self.line_duration.value()))
        row.addWidget(seconds)
        row.addStretch(1)
        layout.addLayout(row)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok
                                             | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec_() != QtWidgets.QDialog.Accepted or not text.text().strip():
            return None
        return text.text().strip(), float(seconds.value())

    def _arm_pick(self, kind, aids, text=""):
        self._pick = {"kind": kind, "aids": list(aids), "text": text}
        prompt = {
            "attack": "Click who to ATTACK — anyone in a group takes the group; "
                      "Ctrl-click one actor. Right-click cancels.",
            "move": "Click where to MOVE to — the ground, or an actor. Right-click cancels.",
            "face": "Click what to FACE — an actor or a spot on the ground. Right-click cancels.",
            "say": "Click who they SAY it to, or empty ground for no one.",
            "think": "Click who they THINK about, or empty ground for no one.",
        }[kind]
        try:
            self.main_window.show_toast(prompt)
        except Exception:
            pass

    def cancel_pick(self):
        if self._pick is not None:
            self._pick = None
            self._repaint_views()
            return True
        return False

    def _group_of(self, aid):
        """The cast members of *aid*'s editor group (Fio's entity groups),
        or just *aid* when it is in none."""
        try:
            from .brush_groups import GROUP_KEY
        except Exception:
            GROUP_KEY = "brush_group"
        self._refresh_actor_objects_from_state()
        props = getattr(self.actor_objects.get(aid), "properties", {}) or {}
        group = str(props.get(GROUP_KEY, "") or "")
        if not group:
            return [aid]
        return [a for a in self.actor_meta
                if str((getattr(self.actor_objects.get(a), "properties", {}) or {}).get(GROUP_KEY, "") or "") == group]

    def pick_click(self, obj, point, shift=False, ctrl=False):
        """The click an armed action waits for: *obj* (the entity clicked, or
        None) and *point* (the world point, or None). An ATTACK on anyone in a
        group takes the whole group; Ctrl-click takes just that one."""
        pick, self._pick = self._pick, None
        if pick is None:
            return False
        kind, aids = pick["kind"], [a for a in pick["aids"] if a in self.actor_meta]
        when = float(self.key_time.value())
        target = self._aid(obj) if obj is not None and self.is_cast(obj) else ""
        if kind == "attack":
            if not target or target in aids:
                self.main_window.show_toast("No target: ATTACK cancelled.")
                return True
            targets = [target] if ctrl else [a for a in self._group_of(target) if a not in aids]
            targets = targets or [target]
            self.events.append({"time": when, "type": "fight",
                                "duration": float(self.attack_duration.value()),
                                "attackers": aids, "defenders": targets,
                                "mutual": self.attack_mutual.isChecked()})
        elif kind == "face":
            import math
            self._refresh_actor_objects_from_state()
            toward = self.actor_objects.get(target) if target else None
            spot = _v3(toward.pos) if toward is not None else point
            if spot is None:
                return True
            for aid in aids:
                actor = self.actor_objects.get(aid)
                if actor is None or aid == target:
                    continue
                here = _v3(actor.pos)
                dx, dz = spot[0] - here[0], spot[2] - here[2]
                if abs(dx) + abs(dz) < 1e-6:
                    continue
                degrees = math.degrees(math.atan2(dx, dz)) % 360.0
                if self._preview_actor_baseline.get(aid) is not None:
                    # Scrubbed to a moment: the MOVE keyframe there turns,
                    # and the placement keeps its own facing.
                    for row in self.actor_tracks.get(aid, []):
                        if abs(float(row.get("time", 0.0)) - when) < 1e-6:
                            row["yaw"] = degrees
                    _set_facing(actor, degrees)
                else:
                    _set_facing(actor, degrees)
            try:
                self.main_window.update_all_ui()
            except Exception:
                pass
        elif kind == "move":
            self._refresh_actor_objects_from_state()
            dest_obj = self.actor_objects.get(target) if target else None
            if dest_obj is None and point is None:
                return True
            centre = None
            members = [self.actor_objects.get(a) for a in aids if self.actor_objects.get(a) is not None]
            if len(members) > 1:
                # A company keeps its shape: each goes to the point plus its
                # place in the group.
                ps = [_v3(m.pos) for m in members]
                centre = [sum(p[i] for p in ps) / len(ps) for i in range(3)]
            # One order for the company: drawn as one arrow to one pin.
            order = str(uuid.uuid4()) if len(aids) > 1 else ""
            pin = _v3(dest_obj.pos) if dest_obj is not None else [float(v) for v in point]
            for aid in aids:
                actor = self.actor_objects.get(aid)
                if actor is None:
                    continue
                row = {"time": when, "yaw": _facing(actor), "action": "move"}
                if order:
                    row["order"], row["pin"] = order, pin
                if dest_obj is not None and target != aid:
                    row["pos"] = _v3(dest_obj.pos)
                    row["target_id"] = target
                else:
                    dest = list(point)
                    if centre is not None:
                        here = _v3(actor.pos)
                        dest = [dest[0] + here[0] - centre[0], dest[1], dest[2] + here[2] - centre[2]]
                    row["pos"] = [float(v) for v in dest]
                self.actor_tracks.setdefault(aid, []).append(row)
                self.actor_tracks[aid].sort(key=lambda r: float(r.get("time", 0.0)))
            self.key_time.setValue(when + 1.0)
        else:
            seconds = float(self.line_duration.value())
            for aid in aids:
                event = {"time": when, "type": kind, "actor": aid,
                         "text": pick["text"], "duration": seconds}
                if target and target != aid:
                    event["to"] = target
                self.events.append(event)
            self.key_time.setValue(when + seconds)
        self._refresh_actor_keys_list()
        self._refresh_key_list()
        self._refresh_event_list()
        self._refresh_summary()
        self._repaint_views()
        return True

    def _team_of(self, aid):
        props = getattr(self.actor_objects.get(aid), "properties", {}) or {}
        return str(props.get("team") or props.get("faction") or "")

    def paint_view(self, painter, project, cursor=None, size=None):
        """Draw the cast's tints and who-does-what in a view: *project* maps a
        world point to the view's ``(x, y)``; *cursor* is the mouse there.
        *size* (``(w, h)``, the 3D view's) adds the scrubber."""
        from . import cutscene_intents
        if not self.previewing():
            self.sync_selection_from_editor()
            cutscene_intents.paint_cast(painter, self, project, cursor)
            cutscene_intents.paint(painter, self, project, self._current_actor_ids())
        if size is not None:
            cutscene_intents.paint_scrubber(painter, self, *size)

    # -- the scrubber -----------------------------------------------------
    def scrub(self, seconds):
        """Show the cutscene at *seconds*: the actors where they will be then
        (the camera stays yours). New keyframes go in at this time. The
        actors go back to their places before anything is saved."""
        if self._preview_rate:
            self._preview_timer.stop()
            self._preview_rate = 0.0
            self.play_button.setText("Play")
        self._preview_start(camera=False)
        self._preview_time = max(0.0, float(seconds))
        self.key_time.setValue(self._preview_time)
        self._preview_apply(move_camera=False)
        self._repaint_views()

    def scrub_step(self, direction):
        """To the previous (-1) or next (+1) keyframe."""
        from . import cutscene_intents
        now = float(self._preview_time if self._preview_actor_baseline
                    else self.key_time.value())
        times = sorted({t for t, _k in cutscene_intents.keyframe_times(self)[0]} | {0.0})
        if direction > 0:
            later = [t for t in times if t > now + 1e-6]
            target = later[0] if later else max(times)
        else:
            earlier = [t for t in times if t < now - 1e-6]
            target = earlier[-1] if earlier else 0.0
        self.scrub(target)

    #: How far one Left / Right press moves the scrubber.
    SCRUB_STEP = 0.1

    def scrub_key(self, key, shift=False):
        """Left / Right: step the scrubber (Shift: to the previous / next
        keyframe). True when the key was the scrubber's."""
        direction = {QtCore.Qt.Key_Left: -1, QtCore.Qt.Key_Right: +1}.get(key)
        if direction is None:
            return False
        if shift:
            self.scrub_step(direction)
        else:
            now = float(self._preview_time if self._preview_actor_baseline
                        else self.key_time.value())
            self.scrub(max(0.0, now + direction * self.SCRUB_STEP))
        return True

    def scrubber_press(self, view, pos):
        """A press in the 3D view: the scrubber's, or not (False)."""
        from . import cutscene_intents
        hit = cutscene_intents.scrubber_hit(self, view.width(), view.height(), pos)
        if hit is None:
            return False
        kind, value = hit
        if kind == "time":
            self._scrubbing = True
            self.scrub(value)
        elif kind == "button":
            if value == "start":
                self.scrub(0.0)
            elif value == "prev":
                self.scrub_step(-1)
            elif value == "next":
                self.scrub_step(+1)
            elif value == "play":
                self._preview_play()
        return True

    def scrubber_drag(self, view, pos):
        if not getattr(self, "_scrubbing", False):
            return False
        from . import cutscene_intents
        self.scrub(cutscene_intents.scrub_time_at(self, view.width(), view.height(), pos.x()))
        return True

    def scrubber_release(self):
        was = getattr(self, "_scrubbing", False)
        self._scrubbing = False
        return was

    def _cutscene_signature(self):
        """Return a stable representation of the authored cutscene state."""
        data = self._build_cutscene_data()
        data.pop("id", None)
        return json.dumps(data, sort_keys=True, ensure_ascii=False)

    def _has_unsaved_changes(self):
        return self._saved_signature != self._cutscene_signature()

    def _confirm_close(self):
        if self._close_prompt_active or not self._has_unsaved_changes():
            return True

        self._close_prompt_active = True
        try:
            box = QtWidgets.QMessageBox(self)
            box.setIcon(QtWidgets.QMessageBox.Warning)
            box.setWindowTitle("Unsaved cutscene changes!")
            box.setText("Unsaved cutscene changes!")
            box.setInformativeText("Do you want to save them before closing?")
            save_button = box.addButton("Save", QtWidgets.QMessageBox.AcceptRole)
            discard_button = box.addButton("Discard", QtWidgets.QMessageBox.DestructiveRole)
            cancel_button = box.addButton("Cancel", QtWidgets.QMessageBox.RejectRole)
            box.setDefaultButton(save_button)
            box.exec_()

            clicked = box.clickedButton()
            if clicked is save_button:
                self._save_and_close()
                return False
            if clicked is discard_button:
                self._preview_stop_and_restore()
                self._cleanup_after_cancel()
                self._saved = False
                return True
            return False
        finally:
            self._close_prompt_active = False

    def showEvent(self, event):
        super().showEvent(event)
        # Keep the modeless wizard fully visible on screen.  Its height can
        # exceed the available desktop height on smaller displays, so clamp
        # the frame upward after Qt has applied window decorations.
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            frame = self.frameGeometry()
            frame.moveTop(available.top())
            self.move(frame.topLeft())
        self.raise_()
        self.activateWindow()
        self.main_window.cutscene_author = self
        self._repaint_views()

    # ------------------------------------------------------------------
    # Editor-side preview transport.
    # ------------------------------------------------------------------
    def _preview_end_time(self):
        times = [float(row.get("time", 0.0)) for rows in self.actor_tracks.values() for row in rows]
        times += [float(row.get("time", 0.0)) for row in self.camera_keys]
        times += [float(row.get("time", 0.0))
                  + (float(row.get("duration", LINE_SECONDS if row.get("type") in ("say", "think") else 0.0))
                     if row.get("type") in ("say", "think", "fight") else 0.0)
                  for row in self.events]
        return max(times, default=0.0)

    def _preview_lines(self, elapsed):
        """What is being said and thought at *elapsed*, for the preview."""
        out = []
        for event in sorted(self.events, key=lambda e: float(e.get("time", 0.0))):
            kind = event.get("type")
            start = float(event.get("time", 0.0))
            if kind in ("say", "think"):
                if start <= elapsed < start + float(event.get("duration", LINE_SECONDS)):
                    who = self.actor_meta.get(str(event.get("actor", "")), {}).get("name", "?")
                    mark = "💭 " if kind == "think" else ""
                    out.append(f"{mark}{who}: {event.get('text', '')}")
            elif kind == "fight":
                if start <= elapsed < start + float(event.get("duration", 0.0)):
                    out.append(f"⚔ battle: {len(event.get('attackers', []))} vs "
                               f"{len(event.get('defenders', []))} (simulated in play)")
        return out

    @staticmethod
    def _preview_pose(frames, elapsed):
        if not frames:
            return None
        frames = sorted(frames, key=lambda row: float(row.get("time", 0.0)))
        if elapsed <= float(frames[0].get("time", 0.0)):
            row = frames[0]
            return list(row.get("pos", (0, 0, 0))), float(row.get("yaw", 0.0))
        if elapsed >= float(frames[-1].get("time", 0.0)):
            row = frames[-1]
            return list(row.get("pos", (0, 0, 0))), float(row.get("yaw", 0.0))
        for left, right in zip(frames, frames[1:]):
            lt = float(left.get("time", 0.0))
            rt = float(right.get("time", 0.0))
            if lt <= elapsed <= rt:
                t = max(0.0, min(1.0, (elapsed - lt) / max(1e-6, rt - lt)))
                t = t * t * (3.0 - 2.0 * t)
                lp = list(left.get("pos", (0, 0, 0)))
                rp = list(right.get("pos", lp))
                if right.get("teleport", False):
                    if elapsed < rt:
                        return list(lp), float(left.get("yaw", 0.0))
                    return list(rp), float(right.get("yaw", 0.0))
                pos = [lp[i] + (rp[i] - lp[i]) * t for i in range(3)]
                ly, ry = float(left.get("yaw", 0.0)), float(right.get("yaw", 0.0))
                turn = (ry - ly + 180.0) % 360.0 - 180.0        # the short way round
                return pos, ly + turn * t
        return None

    def _preview_start(self, camera=True):
        self._refresh_actor_objects_from_state()
        if camera and self._preview_camera_baseline is None:
            camera = self.main_window.view_3d.camera
            self._preview_camera_baseline = {
                "pos": _v3(camera.pos),
                "yaw": float(camera.yaw),
                "pitch": float(camera.pitch),
                "fov": float(getattr(camera, "fov", 90.0)),
            }
        for aid, actor in self.actor_objects.items():
            if aid not in self._preview_actor_baseline and actor is not None:
                self._preview_actor_baseline[aid] = {
                    "pos": _v3(actor.pos),
                    "yaw": _facing(actor),
                }
        self._preview_duration = self._preview_end_time()

    def _preview_apply(self, move_camera=True):
        self._refresh_actor_objects_from_state()
        for aid, frames in self.actor_tracks.items():
            actor = self.actor_objects.get(aid)
            pose = self._preview_pose(frames, self._preview_time)
            if actor is None or pose is None:
                continue
            pos, yaw = pose
            actor.pos = glm.vec3(*pos)
            _set_facing(actor, yaw)

        pose = self._preview_pose(self.camera_keys, self._preview_time) if move_camera else None
        if pose is not None:
            pos, yaw = pose
            frames = sorted(self.camera_keys, key=lambda row: float(row.get("time", 0.0)))
            if len(frames) == 1:
                pitch = float(frames[0].get("pitch", 0.0))
                fov = float(frames[0].get("fov", 90.0))
            elif self._preview_time >= float(frames[-1].get("time", 0.0)):
                pitch = float(frames[-1].get("pitch", 0.0))
                fov = float(frames[-1].get("fov", 90.0))
            else:
                pitch = float(frames[0].get("pitch", 0.0))
                fov = float(frames[0].get("fov", 90.0))
                for left, right in zip(frames, frames[1:]):
                    lt = float(left.get("time", 0.0)); rt = float(right.get("time", 0.0))
                    if lt <= self._preview_time <= rt:
                        t = max(0.0, min(1.0, (self._preview_time - lt) / max(1e-6, rt - lt)))
                        if right.get("teleport", False):
                            if self._preview_time < rt:
                                pitch = float(left.get("pitch", 0.0))
                                fov = float(left.get("fov", 90.0))
                            else:
                                pitch = float(right.get("pitch", 0.0))
                                fov = float(right.get("fov", 90.0))
                        else:
                            t = t * t * (3.0 - 2.0 * t)
                            pitch = float(left.get("pitch", 0.0)) + (float(right.get("pitch", 0.0)) - float(left.get("pitch", 0.0))) * t
                            fov = float(left.get("fov", 90.0)) + (float(right.get("fov", 90.0)) - float(left.get("fov", 90.0))) * t
                        break
            camera = self.main_window.view_3d.camera
            camera.pos = glm.vec3(*pos)
            camera.yaw = yaw
            camera.pitch = pitch
            camera.fov = fov
            self.main_window.view_3d.logic_thread.camera.set_editor_camera(
                camera.pos, camera.yaw, camera.pitch, camera.fov
            )

        self.preview_time_label.setText(f"{self._preview_time:.2f}s / {self._preview_duration:.2f}s")
        self.preview_lines_label.setText("   ".join(self._preview_lines(self._preview_time)))
        try:
            self.main_window.update_all_ui()
        except Exception:
            pass

    def _preview_tick(self):
        if self._preview_rate == 0.0:
            return
        self._preview_time += 0.033 * self._preview_rate
        if self._preview_time >= self._preview_duration or self._preview_time <= 0.0:
            self._preview_stop_and_restore()
            return
        self._preview_apply()

    def _preview_play(self):
        self._preview_start()
        if self._preview_duration <= 0.0:
            self._preview_time = 0.0
            self._preview_apply()
            return
        if self._preview_rate == 1.0:
            self._preview_stop_and_restore()
            return
        if self._preview_time >= self._preview_duration:
            self._preview_time = 0.0
        self._preview_rate = 1.0
        self._preview_timer.start()
        self.play_button.setText("Pause")
        self._preview_apply()

    def _preview_rewind(self):
        self._preview_start()
        self._preview_rate = -2.0
        self._preview_timer.start()
        self.play_button.setText("Play")
        self._preview_apply()

    def _preview_fast_forward(self):
        self._preview_start()
        self._preview_rate = 2.0
        self._preview_timer.start()
        self.play_button.setText("Play")
        self._preview_apply()

    def _preview_stop_and_restore(self):
        self._refresh_actor_objects_from_state()
        self._preview_timer.stop()
        self._preview_rate = 0.0
        self.play_button.setText("Play")
        for aid, baseline in self._preview_actor_baseline.items():
            actor = self.actor_objects.get(aid)
            if actor is not None:
                actor.pos = glm.vec3(*baseline["pos"])
                _set_facing(actor, baseline["yaw"])
        if self._preview_camera_baseline is not None:
            camera = self.main_window.view_3d.camera
            camera.pos = glm.vec3(*self._preview_camera_baseline["pos"])
            camera.yaw = self._preview_camera_baseline["yaw"]
            camera.pitch = self._preview_camera_baseline["pitch"]
            camera.fov = self._preview_camera_baseline["fov"]
            self.main_window.view_3d.logic_thread.camera.set_editor_camera(
                camera.pos, camera.yaw, camera.pitch, camera.fov
            )
        self._preview_camera_baseline = None
        self._preview_actor_baseline.clear()
        self._preview_time = 0.0
        self._preview_duration = 0.0
        self.preview_time_label.setText("0.00s / 0.00s")
        self.preview_lines_label.setText("")
        try:
            self.main_window.update_all_ui()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Advanced event widgets — these retain the original wizard controls.
    # ------------------------------------------------------------------
    def _refresh_io_sources(self):
        """Refresh the I/O source list from the live map entities."""
        current = self.io_source.currentData()
        self.io_source.blockSignals(True)
        self.io_source.clear()
        for thing in self.main_window.state.things:
            props = getattr(thing, "properties", {})
            if props.get("_cutscene_temporary"):
                continue
            entity_id = str(props.get("id", ""))
            if not entity_id:
                continue
            name = str(props.get("name") or entity_id)
            self.io_source.addItem(name, entity_id)
        idx = self.io_source.findData(current)
        self.io_source.setCurrentIndex(idx if idx >= 0 else (0 if self.io_source.count() else -1))
        self.io_source.blockSignals(False)
        self._refresh_io_outputs()

    def _refresh_io_outputs(self):
        from .io_system import get_input_names
        current = self.io_output.currentText()
        self.io_output.blockSignals(True)
        self.io_output.clear()
        source_id = str(self.io_source.currentData() or "")
        source = next((t for t in self.main_window.state.things
                       if str(getattr(t, "properties", {}).get("id", "")) == source_id), None)
        if source is not None:
            entity_type = str(source.properties.get("type", ""))
            for output in sorted(get_input_names(entity_type)):
                self.io_output.addItem(output)
        self.io_output.setCurrentText(current)
        self.io_output.blockSignals(False)

    def _build_io_tab(self, tabs):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        box = QtWidgets.QGroupBox("Send an I/O input during the cutscene")
        form = QtWidgets.QFormLayout(box)
        self.io_time = QtWidgets.QDoubleSpinBox()
        self.io_time.setRange(0, 3600)
        self.io_time.setDecimals(2)
        self.io_time.setSuffix(" s")
        form.addRow("At time", self.io_time)
        self.io_source = QtWidgets.QComboBox()
        self.io_source.setMinimumWidth(260)
        form.addRow("Target entity", self.io_source)
        self.io_source.currentIndexChanged.connect(lambda _i: self._refresh_io_outputs())
        self.io_output = QtWidgets.QComboBox()
        self.io_output.setEditable(True)
        self.io_output.setMinimumWidth(260)
        form.addRow("Input", self.io_output)
        self.io_parameter = QtWidgets.QLineEdit()
        self.io_parameter.setPlaceholderText("Optional parameter")
        form.addRow("Parameter", self.io_parameter)
        add = QtWidgets.QPushButton("Add I/O input")
        add.clicked.connect(self._add_io_event)
        form.addRow("", add)
        layout.addWidget(box)
        help_text = QtWidgets.QLabel(
            "This sends a real Fio input directly to the selected target entity at the authored cutscene time. "
            "For example, Target entity = Door and Input = Open."
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        layout.addStretch(1)
        tabs.addTab(page, "I/O Input")
        self._refresh_io_sources()

    def _add_io_event(self):
        source_id = str(self.io_source.currentData() or "")
        source_name = self.io_source.currentText().strip()
        output = self.io_output.currentText().strip()
        if not source_id or not source_name:
            QtWidgets.QMessageBox.warning(self, "I/O Input", "Choose a target entity first.")
            return
        if not output:
            QtWidgets.QMessageBox.warning(self, "I/O Input", "Choose or enter an input name.")
            return
        event = {
            "time": float(self.io_time.value()),
            "type": "io",
            "target_id": source_id,
            "target_name": source_name,
            "input": output,
        }
        parameter = self.io_parameter.text()
        if parameter:
            event["parameter"] = parameter
        self.events.append(event)
        self.events.sort(key=lambda x: x.get("time", 0))
        self._refresh_event_list()
        self._refresh_summary()
        self.io_time.setValue(float(event["time"]) + 1.0)

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

    # ------------------------------------------------------------------
    # Live actor authoring.
    # ------------------------------------------------------------------
    def _spawn_point(self):
        camera = self.main_window.view_3d.camera
        try:
            front = camera.get_front_vector()
            return [float(camera.pos.x + front.x * 256.0),
                    float(camera.pos.y + front.y * 256.0),
                    float(camera.pos.z + front.z * 256.0)]
        except Exception:
            return _v3(camera.pos)

    #: How close two actors may stand: a new one is pushed clear of the rest.
    ACTOR_SPACING = 64.0

    def _clear_spot(self, pos, ignore=None):
        """*pos*, or the nearest point to it (on rings around it) that no
        other actor stands within :data:`ACTOR_SPACING` of."""
        import math
        others = []
        for obj in self.main_window.state.things:
            if obj is ignore or not _is_actor(obj):
                continue
            p = _v3(obj.pos)
            others.append((p[0], p[2]))
        gap = self.ACTOR_SPACING

        def free(x, z):
            return all((x - ox) ** 2 + (z - oz) ** 2 >= gap * gap for ox, oz in others)
        x, y, z = pos
        if free(x, z):
            return [x, y, z]
        for ring in range(1, 40):
            steps = 6 * ring
            for k in range(steps):
                a = 2.0 * math.pi * k / steps
                cx, cz = x + math.cos(a) * gap * ring, z + math.sin(a) * gap * ring
                if free(cx, cz):
                    return [cx, y, cz]
        return [x, y, z]

    def _add_temporary_actor(self, actor, select=True):
        """Put *actor* (made here, embedded in the cutscene) in the map and
        cast -- never on top of another actor: it is pushed clear."""
        actor.pos = glm.vec3(*self._clear_spot(_v3(actor.pos), ignore=actor))
        aid = str(actor.properties.get("id"))
        actor.properties["_cutscene_temporary"] = True
        self.main_window.state.things.append(actor)
        self.actor_objects[aid] = actor
        self.temporary_actor_ids.add(aid)
        self.actor_meta[aid] = {
            "id": aid,
            "name": str(actor.properties.get("display_name") or actor.properties.get("name")),
            "spawn": True,
        }
        if select:
            self.main_window.set_selected_objects([actor])
            self.main_window.update_all_ui()
            self._refresh_actor_lists()
            self._select_actor_ids([aid])
        return actor

    def _create_temporary_actor(self, kind=None):
        """A new actor of *kind* (an :data:`ACTOR_KINDS` entry; the first by
        default) in front of the editor camera."""
        if not isinstance(kind, (tuple, list)):
            kind = ACTOR_KINDS[0] if ACTOR_KINDS else ("+ Actor", "Monster", {})
        label, type_name, defaults = kind
        if self.main_window.view_3d.camera is None:
            return None
        cls = _entity_class(type_name)
        noun = str(label).lstrip("+ ").strip() or "Actor"
        default_name = f"{noun} {len(self.actor_meta) + 1}"
        props = dict(defaults)
        props.update({
            "id": str(uuid.uuid4()),
            "name": default_name,
            "display_name": default_name,
            "_cutscene_temporary": True,
        })
        try:
            actor = cls(pos=self._spawn_point(), properties=props)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Actor", f"Could not create the actor: {exc}")
            return None
        self._add_temporary_actor(actor)
        self.main_window.show_toast(f"{default_name} created in the current 3D view")
        return actor

    def _duplicate_selected_actors(self):
        """A copy of each selected actor -- its kit, style and spells too --
        beside it: the quick way to raise a company."""
        import copy
        self._refresh_actor_objects_from_state()
        made = []
        for aid in self._current_actor_ids():
            actor = self.actor_objects.get(aid)
            if actor is None:
                continue
            props = {k: copy.deepcopy(v) for k, v in actor.properties.items()
                     if k != "_io_connections" and not str(k).startswith("_cutscene_")}
            props["id"] = str(uuid.uuid4())
            name = str(props.get("display_name") or props.get("name") or "Actor")
            props["name"] = props["display_name"] = f"{name} copy"
            pos = _v3(actor.pos)
            pos[0] += 64.0
            try:
                twin = type(actor)(pos=pos, properties=props)
                _set_facing(twin, _facing(actor))
            except Exception as exc:
                QtWidgets.QMessageBox.warning(self, "Duplicate", f"Could not copy {name}: {exc}")
                continue
            made.append(self._add_temporary_actor(twin, select=False))
        if made:
            self.main_window.set_selected_objects(made)
            self.main_window.update_all_ui()
            self._refresh_actor_lists()
            self._select_actor_ids([str(a.properties["id"]) for a in made])
            self._refresh_summary()

    def _capture_selected_actors(self):
        selected = _selected_actors(self.main_window)
        if not selected:
            QtWidgets.QMessageBox.information(
                self,
                "Actors",
                "Select one or more actors in the editor first.",
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
        self._refresh_actor_objects_from_state()
        aids = self._current_actor_ids()
        for aid in aids[1:]:
            self._remove_actor(aid, refresh=False)
        if aids:
            self._remove_actor(aids[0])

    def _remove_actor(self, aid, refresh=True):
        aid = str(aid)
        self.actor_meta.pop(aid, None)
        self.actor_tracks.pop(aid, None)

        # Remove every authored reference to the deleted actor. A cutscene
        # must never save dangling actor IDs in fights, camera look-at
        # targets, or waypoint destinations.
        self.camera_keys = [
            row for row in self.camera_keys
            if str(row.get("look_at", {}).get("actor", "")) != aid
        ]
        for row in self.actor_tracks.values():
            for frame in row:
                if str(frame.get("target_id", "")) == aid:
                    frame.pop("target_id", None)
        cleaned_events = []
        for event in self.events:
            if event.get("type") == "fight":
                attackers = [str(x) for x in event.get("attackers", []) if str(x) != aid]
                defenders = [str(x) for x in event.get("defenders", []) if str(x) != aid]
                if not attackers or not defenders:
                    continue
                event = dict(event)
                event["attackers"] = attackers
                event["defenders"] = defenders
            elif event.get("type") == "io" and str(event.get("source_id", "")) == aid:
                continue
            elif event.get("type") in ("say", "think") and str(event.get("actor", "")) == aid:
                continue
            elif event.get("type") == "dialogue" and str(event.get("speaker_id", "")) == aid:
                # Older cutscenes still carry dialogue speakers.
                event = dict(event)
                event["speaker_id"] = ""
            cleaned_events.append(event)
        self.events = cleaned_events

        if aid in self.temporary_actor_ids:
            state = self.main_window.state

            # Remove the deleted temporary actor from the authoritative
            # multi-selection so "+ Selected" cannot capture it again.
            state.selected_objects = [
                actor for actor in state.selected_objects
                if str(getattr(actor, "properties", {}).get("id", "")) != aid
            ]

            state.things[:] = [
                actor for actor in state.things
                if not (
                    getattr(actor, "properties", {}).get("_cutscene_temporary")
                    and str(getattr(actor, "properties", {}).get("id", "")) == aid
                )
            ]
            self.temporary_actor_ids.discard(aid)
        self.actor_objects.pop(aid, None)
        if not refresh:
            return
        self._refresh_actor_lists()
        self._rebuild_actor_panel()
        self._refresh_key_list()
        self._refresh_event_list()
        self._refresh_camera_list()
        self.main_window.update_all_ui()
        self._refresh_summary()

    def _actor_selection_changed(self):
        self._refresh_actor_objects_from_state()
        aids = self._current_actor_ids()
        actors = [self.actor_objects[a] for a in aids if self.actor_objects.get(a) is not None]
        if actors:
            try:
                self.main_window.set_selected_objects(actors)
            except Exception:
                pass
        if len(aids) == 1:
            name = self.actor_meta.get(aids[0], {}).get("name", aids[0])
            self.selected_actor_label.setText(f"Selected: {name}")
        elif aids:
            self.selected_actor_label.setText(f"{len(aids)} actors selected")
        else:
            self.selected_actor_label.setText("No actor selected")
        self._rebuild_actor_panel()
        self._update_key_controls()
        self._refresh_key_list()

    def _focus_selected_actor(self):
        self._refresh_actor_objects_from_state()
        actor = self.actor_objects.get(self._current_actor_id())
        if actor is None:
            return
        try:
            self.main_window.focus_on_object(actor)
        except Exception:
            pass

    def _current_actor_ids(self):
        """The ids of the actors selected in the cast list, in list order."""
        return [str(self.actor_list.item(i).data(QtCore.Qt.UserRole))
                for i in range(self.actor_list.count())
                if self.actor_list.item(i).isSelected()]

    def _current_actor_id(self):
        aids = self._current_actor_ids()
        if aids:
            return aids[0]
        item = self.actor_list.currentItem()
        return str(item.data(QtCore.Qt.UserRole)) if item is not None else ""

    def _select_actor_ids(self, aids):
        wanted = {str(a) for a in aids}
        self.actor_list.blockSignals(True)
        first = None
        for i in range(self.actor_list.count()):
            item = self.actor_list.item(i)
            chosen = str(item.data(QtCore.Qt.UserRole)) in wanted
            item.setSelected(chosen)
            if chosen and first is None:
                first = i
        if first is not None:
            self.actor_list.setCurrentRow(first, QtCore.QItemSelectionModel.NoUpdate)
        self.actor_list.blockSignals(False)
        self._actor_selection_changed()

    def _select_actor_id(self, aid):
        self._select_actor_ids([aid])

    def _target_actor_ids(self):
        return list(self.actor_meta.keys())

    def _groups(self):
        """``[(label, [actor ids])]``: the cast by team and by role."""
        self._refresh_actor_objects_from_state()
        teams, roles = {}, {}
        for aid in self.actor_meta:
            props = getattr(self.actor_objects.get(aid), "properties", {}) or {}
            team = str(props.get("team") or props.get("faction") or "")
            role = str(props.get("npc_role") or props.get("monster_type") or "")
            if team:
                teams.setdefault(team, []).append(aid)
            if role:
                roles.setdefault(role, []).append(aid)
        out = [(f"Team: {k} ({len(v)})", v) for k, v in sorted(teams.items())]
        out += [(f"Role: {k} ({len(v)})", v) for k, v in sorted(roles.items())]
        return out

    def _fill_group_combo(self, combo, first):
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(first, None)
        combo.addItem(f"Everyone ({len(self.actor_meta)})", list(self.actor_meta))
        for label, aids in self._groups():
            combo.addItem(label, aids)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _select_group(self, index):
        aids = self.select_group.itemData(index)
        self.select_group.setCurrentIndex(0)
        if aids:
            self._select_actor_ids(aids)

    def _check_group(self, index):
        aids = set(self.attack_group.itemData(index) or ())
        self.attack_group.setCurrentIndex(0)
        if not aids:
            return
        for i in range(self.attack_targets.count()):
            item = self.attack_targets.item(i)
            if str(item.data(QtCore.Qt.UserRole)) in aids:
                item.setCheckState(QtCore.Qt.Checked)

    def _refresh_actor_lists(self):
        """Refresh every widget that lists the cast."""
        wanted = self._current_actor_ids()
        self.actor_list.blockSignals(True)
        self.actor_list.clear()
        for aid, meta in self.actor_meta.items():
            item = QtWidgets.QListWidgetItem(meta["name"])
            if meta.get("spawn"):
                item.setText(f"★ {meta['name']}")
                item.setToolTip(
                    "Temporary actor — embedded in the cutscene and deleted "
                    "from the map after authoring"
                )
            item.setData(QtCore.Qt.UserRole, aid)
            self.actor_list.addItem(item)
            item.setSelected(aid in wanted)
        self.actor_list.blockSignals(False)

        current = self.look_at.currentData()
        self.look_at.blockSignals(True)
        self.look_at.clear()
        self.look_at.addItem("Keep camera rotation", "")
        for aid, meta in self.actor_meta.items():
            self.look_at.addItem(meta["name"], aid)
        idx = self.look_at.findData(current)
        self.look_at.setCurrentIndex(idx if idx >= 0 else 0)
        self.look_at.blockSignals(False)

        current = self.move_to.currentData()
        self.move_to.clear()
        self.move_to.addItem("Where each stands now in the 3D view", "")
        for aid, meta in self.actor_meta.items():
            self.move_to.addItem(f"{meta['name']}'s position", aid)
        idx = self.move_to.findData(current)
        self.move_to.setCurrentIndex(idx if idx >= 0 else 0)

        checked = self._checked_targets()
        self.attack_targets.clear()
        for aid, meta in self.actor_meta.items():
            item = QtWidgets.QListWidgetItem(meta["name"])
            item.setData(QtCore.Qt.UserRole, aid)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if aid in checked else QtCore.Qt.Unchecked)
            self.attack_targets.addItem(item)
        self._fill_group_combo(self.select_group, "Select a group…")
        self._fill_group_combo(self.attack_group, "Tick a group…")
        self._update_key_controls()
        self._refresh_summary()

    def _checked_targets(self):
        return [str(self.attack_targets.item(i).data(QtCore.Qt.UserRole))
                for i in range(self.attack_targets.count())
                if self.attack_targets.item(i).checkState() == QtCore.Qt.Checked]

    # ------------------------------------------------------------------
    # The selected actors' own panels (a game's kit, style and spells).
    # ------------------------------------------------------------------
    def _rebuild_actor_panel(self):
        layout = self.actor_panel_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._refresh_actor_objects_from_state()
        actors = [self.actor_objects[a] for a in self._current_actor_ids()
                  if self.actor_objects.get(a) is not None]
        if not actors:
            note = QtWidgets.QLabel("Select an actor in the cast to edit it.")
            note.setWordWrap(True)
            layout.addWidget(note)
            layout.addStretch(1)
            return
        built = False
        for factory in list(ACTOR_PANELS):
            try:
                panel = factory(self, actors)
            except Exception as exc:
                panel = QtWidgets.QLabel(f"This actor panel failed: {exc}")
            if panel is not None:
                layout.addWidget(panel)
                built = True
        if not built:
            layout.addWidget(self._name_panel(actors))
        layout.addStretch(1)

    def _name_panel(self, actors):
        """The engine's own actor panel: a name, for one actor."""
        box = QtWidgets.QGroupBox("Actor")
        form = QtWidgets.QFormLayout(box)
        if len(actors) != 1:
            form.addRow(QtWidgets.QLabel(f"{len(actors)} actors selected"))
            return box
        actor = actors[0]
        name = QtWidgets.QLineEdit(str(actor.properties.get("display_name") or actor.properties.get("name") or ""))

        def rename():
            text = name.text().strip()
            if text:
                actor.properties["name"] = actor.properties["display_name"] = text
                self.actors_changed([actor])
        name.editingFinished.connect(rename)
        form.addRow("Name", name)
        return box

    def actors_changed(self, actors, rebuild=False):
        """A panel changed *actors*: names and groups follow, and the map
        redraws. *rebuild* builds the panels again (an actor was replaced)."""
        self._refresh_actor_objects_from_state()
        for actor in actors:
            aid = str(getattr(actor, "properties", {}).get("id", ""))
            if aid in self.actor_meta:
                props = actor.properties
                self.actor_meta[aid]["name"] = str(props.get("display_name") or props.get("name") or aid)
                self.actor_objects[aid] = actor
        for i in range(self.actor_list.count()):
            item = self.actor_list.item(i)
            meta = self.actor_meta.get(str(item.data(QtCore.Qt.UserRole)))
            if meta is not None:
                item.setText(("★ " if meta.get("spawn") else "") + meta["name"])
        # Every other list naming the cast follows a rename.
        for i in range(self.attack_targets.count()):
            item = self.attack_targets.item(i)
            meta = self.actor_meta.get(str(item.data(QtCore.Qt.UserRole)))
            if meta is not None:
                item.setText(meta["name"])
        for combo, fmt in ((self.move_to, "{}'s position"), (self.look_at, "{}")):
            for i in range(combo.count()):
                meta = self.actor_meta.get(str(combo.itemData(i) or ""))
                if meta is not None:
                    combo.setItemText(i, fmt.format(meta["name"]))
        self._fill_group_combo(self.select_group, "Select a group…")
        self._fill_group_combo(self.attack_group, "Tick a group…")
        if rebuild:
            self._rebuild_actor_panel()
        self._refresh_key_list()
        try:
            self.main_window.update_all_ui()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Keyframes: MOVE / SAY / THINK / ATTACK for the selected actors.
    # ------------------------------------------------------------------
    def _update_key_controls(self):
        kind = str(self.key_kind.currentData() or "move")
        self.key_stack.setCurrentIndex({"move": 0, "say": 1, "think": 1, "attack": 2}[kind])
        n = len(self._current_actor_ids())
        who = "the selected actor" if n == 1 else f"{n} selected actors" if n else "no actor"
        self.add_key_button.setText(f"Add {kind.upper()} for {who}")
        self.add_key_button.setEnabled(n > 0)

    def _add_keyframe(self):
        self._refresh_actor_objects_from_state()
        aids = [a for a in self._current_actor_ids() if a in self.actor_meta]
        if not aids:
            QtWidgets.QMessageBox.information(self, "Keyframe", "Select one or more actors first.")
            return
        kind = str(self.key_kind.currentData() or "move")
        when = float(self.key_time.value())
        advance = 1.0
        if kind == "move":
            dest = str(self.move_to.currentData() or "")
            dest_obj = self.actor_objects.get(dest) if dest else None
            for aid in aids:
                actor = self.actor_objects.get(aid)
                if actor is None:
                    continue
                source = dest_obj if dest_obj is not None and dest != aid else actor
                row = {"time": when, "pos": _v3(source.pos),
                       "yaw": _facing(actor), "action": "move"}
                if self.move_teleport.isChecked():
                    row["teleport"] = True
                if dest_obj is not None and dest != aid:
                    row["target_id"] = dest
                self.actor_tracks.setdefault(aid, []).append(row)
                self.actor_tracks[aid].sort(key=lambda r: float(r.get("time", 0.0)))
        elif kind in ("say", "think"):
            text = self.line_text.text().strip()
            if not text:
                QtWidgets.QMessageBox.information(self, "Keyframe", "Write the line first.")
                return
            seconds = float(self.line_duration.value())
            for aid in aids:
                self.events.append({"time": when, "type": kind, "actor": aid,
                                    "text": text, "duration": seconds})
            advance = seconds
        else:
            targets = [t for t in self._checked_targets() if t not in aids]
            if not targets:
                QtWidgets.QMessageBox.information(
                    self, "Keyframe", "Tick the actors to attack (not the attackers themselves).")
                return
            self.events.append({"time": when, "type": "fight",
                                "duration": float(self.attack_duration.value()),
                                "attackers": list(aids), "defenders": targets,
                                "mutual": self.attack_mutual.isChecked()})
            advance = 0.0
        self.key_time.setValue(when + advance)
        self._refresh_actor_keys_list()
        self._refresh_key_list()
        self._refresh_event_list()
        self._refresh_summary()

    def _keyframes_for(self, aids):
        """``[(time, label, ref)]`` of every keyframe involving *aids*; *ref*
        is ``("track", aid, row)`` or ``("event", event)``."""
        wanted = set(aids)
        names = {aid: meta["name"] for aid, meta in self.actor_meta.items()}
        many = len(wanted) > 1
        out = []
        for aid in aids:
            for row in self.actor_tracks.get(aid, []):
                where = row.get("target_id")
                dest = f"{names.get(where, 'an actor')}'s position" if where else \
                    "(" + ", ".join(f"{float(v):.0f}" for v in row.get("pos", (0, 0, 0))) + ")"
                cut = " (teleport)" if row.get("teleport") else ""
                who = f"{names.get(aid, aid)}  " if many else ""
                out.append((float(row.get("time", 0.0)), f"{who}MOVE to {dest}{cut}",
                            ("track", aid, row)))
        for event in self.events:
            kind = event.get("type")
            t = float(event.get("time", 0.0))
            if kind in ("say", "think") and str(event.get("actor", "")) in wanted:
                who = f"{names.get(str(event.get('actor')), '')}  " if many else ""
                out.append((t, f"{who}{kind.upper()} “{event.get('text', '')}” "
                               f"({float(event.get('duration', LINE_SECONDS)):.1f}s)",
                            ("event", event)))
            elif kind == "fight":
                attackers = [str(a) for a in event.get("attackers", [])]
                defenders = [str(d) for d in event.get("defenders", [])]
                if not (wanted & set(attackers + defenders)):
                    continue
                back = ", fought back" if event.get("mutual", True) else ""
                out.append((t, f"ATTACK: {len(attackers)} vs {len(defenders)} for "
                               f"{float(event.get('duration', 0.0)):.1f}s{back} — "
                               + ", ".join(names.get(a, a) for a in attackers[:3])
                               + ("…" if len(attackers) > 3 else "")
                               + " → " + ", ".join(names.get(d, d) for d in defenders[:3])
                               + ("…" if len(defenders) > 3 else ""),
                            ("event", event)))
        out.sort(key=lambda entry: entry[0])
        return out

    def _refresh_key_list(self):
        self.key_list.clear()
        self._key_refs = []
        for t, label, ref in self._keyframes_for(self._current_actor_ids()):
            self.key_list.addItem(f"{t:6.2f}s  {label}")
            self._key_refs.append(ref)

    def _selected_key_ref(self):
        row = self.key_list.currentRow()
        return self._key_refs[row] if 0 <= row < len(self._key_refs) else None

    def _remove_selected_keyframe(self):
        ref = self._selected_key_ref()
        if ref is None:
            return
        if ref[0] == "track":
            _kind, aid, row = ref
            rows = self.actor_tracks.get(aid, [])
            if row in rows:
                rows.remove(row)
            if not rows:
                self.actor_tracks.pop(aid, None)
        else:
            event = ref[1]
            self.events = [e for e in self.events if e is not event]
        self._refresh_actor_keys_list()
        self._refresh_key_list()
        self._refresh_event_list()
        self._refresh_summary()

    def _edit_selected_keyframe(self):
        ref = self._selected_key_ref()
        if ref is None:
            return
        if ref[0] == "event":
            self._edit_event(ref[1])
            self._refresh_key_list()
            return
        _kind, aid, row = ref
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Edit MOVE")
        form = QtWidgets.QFormLayout(dialog)
        time = QtWidgets.QDoubleSpinBox()
        time.setRange(0, 3600)
        time.setDecimals(2)
        time.setSuffix(" s")
        time.setValue(float(row.get("time", 0.0)))
        form.addRow("At", time)
        teleport = QtWidgets.QCheckBox("Teleport")
        teleport.setChecked(bool(row.get("teleport")))
        form.addRow("", teleport)
        here = QtWidgets.QCheckBox("Move to where the actor stands now")
        form.addRow("", here)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save
                                             | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        row["time"] = float(time.value())
        if teleport.isChecked():
            row["teleport"] = True
        else:
            row.pop("teleport", None)
        actor = self.actor_objects.get(aid)
        if here.isChecked() and actor is not None:
            row["pos"] = _v3(actor.pos)
            row["yaw"] = _facing(actor)
            row.pop("target_id", None)
        self.actor_tracks.get(aid, []).sort(key=lambda r: float(r.get("time", 0.0)))
        self._refresh_actor_keys_list()
        self._refresh_key_list()
        self._refresh_summary()

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
                "yaw": _facing(actor),
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
        if TOP_DOWN_CAMERA:
            # Where and how high: the camera always looks straight down.
            frame["yaw"], frame["pitch"] = 0.0, TOP_DOWN_PITCH
        if self.camera_teleport.isChecked():
            frame["teleport"] = True
        aid = self.look_at.currentData()
        if aid:
            frame["look_at"] = {"actor": str(aid)}
        self.camera_keys.append(frame)
        self.camera_keys.sort(key=lambda x: x["time"])
        self._refresh_camera_list()
        self.camera_time.setValue(float(frame["time"]) + 1.0)

    def _camera_keyframe_selected(self, row):
        valid = 0 <= row < len(self.camera_keys)
        self.camera_edit_time.setEnabled(valid)
        if valid:
            self.camera_edit_time.blockSignals(True)
            self.camera_edit_time.setValue(float(self.camera_keys[row].get("time", 0.0)))
            self.camera_edit_time.blockSignals(False)

    def _set_selected_camera_keyframe_time(self):
        row = self.camera_keys_list.currentRow()
        if not (0 <= row < len(self.camera_keys)):
            return
        selected = self.camera_keys[row]
        selected["time"] = float(self.camera_edit_time.value())
        self.camera_keys.sort(key=lambda x: float(x.get("time", 0.0)))
        new_row = self.camera_keys.index(selected)
        self._refresh_camera_list()
        self.camera_keys_list.setCurrentRow(new_row)
        self._refresh_summary()

    def _remove_selected_camera_keyframe(self):
        row = self.camera_keys_list.currentRow()
        if not (0 <= row < len(self.camera_keys)):
            return
        self.camera_keys.pop(row)
        self._refresh_camera_list()
        self._refresh_summary()

    def _refresh_camera_list(self):
        self.camera_keys_list.clear()
        for row in self.camera_keys:
            look = row.get("look_at", {}).get("actor", "")
            target = self.actor_meta.get(str(look), {}).get("name", "") if look else ""
            suffix = f" — look at {target}" if target else ""
            if row.get("teleport", False):
                suffix += " — TELEPORT"
            self.camera_keys_list.addItem(
                f"{row['time']:.2f}s — camera {row['pos']}{suffix}"
            )

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


    def _edit_selected_event(self, _item=None):
        row = self.event_list.currentRow()
        ordered = sorted(enumerate(self.events), key=lambda item: item[1].get("time", 0))
        if not (0 <= row < len(ordered)):
            return
        self._edit_event(ordered[row][1])

    def _edit_event(self, event):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Edit event")
        dialog.setMinimumWidth(520)
        layout = QtWidgets.QVBoxLayout(dialog)
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        time = QtWidgets.QDoubleSpinBox()
        time.setRange(0, 3600)
        time.setDecimals(2)
        time.setSuffix(" s")
        time.setValue(float(event.get("time", 0.0)))
        form.addRow("At time", time)

        kind = str(event.get("type", ""))
        widgets = {}

        if kind == "message":
            line = QtWidgets.QComboBox()
            line.addItems(["message", "message2", "message3"])
            line.setCurrentText(str(event.get("line", "message")))
            text = QtWidgets.QLineEdit(str(event.get("text", "")))
            form.addRow("Line", line)
            form.addRow("Text", text)
            widgets.update(line=line, text=text)

        elif kind == "io":
            target = QtWidgets.QLineEdit(str(event.get("target_name", event.get("source_name", ""))))
            input_name = QtWidgets.QLineEdit(str(event.get("input", event.get("output", ""))))
            parameter = QtWidgets.QLineEdit(str(event.get("parameter", "")))
            form.addRow("Target entity", target)
            form.addRow("Input", input_name)
            form.addRow("Parameter", parameter)
            widgets.update(target=target, input_name=input_name, parameter=parameter)

        elif kind in ("say", "think"):
            text = QtWidgets.QLineEdit(str(event.get("text", "")))
            seconds = QtWidgets.QDoubleSpinBox()
            seconds.setRange(0.5, 60)
            seconds.setDecimals(1)
            seconds.setSuffix(" s")
            seconds.setValue(float(event.get("duration", LINE_SECONDS)))
            actor = self.actor_meta.get(str(event.get("actor", "")), {}).get("name", "")
            form.addRow("Actor", QtWidgets.QLabel(actor or "(missing)"))
            form.addRow("Line", text)
            form.addRow("Shown for", seconds)
            widgets.update(text=text, seconds=seconds)

        elif kind == "fight":
            duration = QtWidgets.QDoubleSpinBox()
            duration.setRange(0.05, 300)
            duration.setDecimals(2)
            duration.setSuffix(" s")
            duration.setValue(float(event.get("duration", 5.0)))
            style = QtWidgets.QComboBox()
            for label, value in (("Normal", "normal"), ("Melee", "melee")):
                style.addItem(label, value)
            style.setCurrentIndex(max(0, style.findData(event.get("style", "normal"))))
            attackers = QtWidgets.QLineEdit(", ".join(map(str, event.get("attackers", []))))
            defenders = QtWidgets.QLineEdit(", ".join(map(str, event.get("defenders", []))))
            mutual = QtWidgets.QCheckBox("Defenders fight back")
            mutual.setChecked(bool(event.get("mutual", True)))
            form.addRow("Duration", duration)
            form.addRow("Style", style)
            form.addRow("Attackers", attackers)
            form.addRow("Defenders", defenders)
            form.addRow("", mutual)
            widgets.update(duration=duration, style=style, attackers=attackers,
                           defenders=defenders, mutual=mutual)

        else:
            raw = QtWidgets.QPlainTextEdit(json.dumps(
                {key: value for key, value in event.items() if key != "type"},
                indent=2,
                ensure_ascii=False,
            ))
            form.addRow("Data", raw)
            widgets["raw"] = raw

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return

        event["time"] = float(time.value())
        if kind == "message":
            event["line"] = widgets["line"].currentText()
            event["text"] = widgets["text"].text()
        elif kind == "io":
            event["target_name"] = widgets["target"].text().strip()
            event["input"] = widgets["input_name"].text().strip()
            event.pop("source_name", None)
            event.pop("output", None)
            if widgets["parameter"].text():
                event["parameter"] = widgets["parameter"].text()
            else:
                event.pop("parameter", None)
        elif kind in ("say", "think"):
            event["text"] = widgets["text"].text().strip()
            event["duration"] = float(widgets["seconds"].value())
        elif kind == "fight":
            event["mutual"] = widgets["mutual"].isChecked()
            event["duration"] = float(widgets["duration"].value())
            event["style"] = widgets["style"].currentData()
            event["attackers"] = [x.strip() for x in widgets["attackers"].text().split(",") if x.strip()]
            event["defenders"] = [x.strip() for x in widgets["defenders"].text().split(",") if x.strip()]
        else:
            try:
                raw_data = json.loads(widgets["raw"].toPlainText())
                if isinstance(raw_data, dict):
                    event.clear()
                    event["type"] = kind
                    event.update(raw_data)
                    event["time"] = float(time.value())
            except (TypeError, ValueError):
                QtWidgets.QMessageBox.warning(self, "Invalid event", "The event data is not valid JSON.")
                return

        self.events.sort(key=lambda x: x.get("time", 0))
        self._refresh_event_list()
        self._refresh_summary()

    def _refresh_event_list(self):
        self.event_list.clear()
        for event in sorted(self.events, key=lambda x: x.get("time", 0)):
            kind = event["type"]
            label = f"{event['time']:.2f}s — {kind}"
            if kind == "fight":
                label += f" ({len(event.get('attackers', []))} vs {len(event.get('defenders', []))})"
            elif kind == "message":
                label += f" — {event.get('line', 'message')}: {str(event.get('text', ''))[:45]}"
            elif kind in ("say", "think"):
                who = self.actor_meta.get(str(event.get("actor", "")), {}).get("name", "?")
                label += f" — {who}: {str(event.get('text', ''))[:45]}"
            elif kind == "io":
                label += f" — {event.get('target_name', event.get('target_id', ''))}.{event.get('input', event.get('output', ''))}"
            self.event_list.addItem(label)

    # ------------------------------------------------------------------
    # Refresh / save / cleanup.
    # ------------------------------------------------------------------
    def _refresh_summary(self):
        self.summary.setText(
            f"Actors {len(self.actor_meta)}  |  "
            f"Moves {sum(len(v) for v in self.actor_tracks.values())}  |  "
            f"Lines {sum(1 for e in self.events if e.get('type') in ('say', 'think'))}  |  "
            f"Battles {sum(1 for e in self.events if e.get('type') == 'fight')}  |  "
            f"Camera {len(self.camera_keys)}  |  Events {len(self.events)}"
        )

    def _filename(self):
        name = self.filename.text().strip() or self.name.text().strip() or "cutscene"
        if not name.lower().endswith(".json"):
            name += ".json"
        return name.split("/")[-1].split("\\")[-1]

    def _refresh_actor_objects_from_state(self):
        """Rebind actor references after EditorState undo/redo reconstruction."""
        for aid in list(self.actor_meta):
            actor = self._find_map_actor(aid)
            if actor is not None:
                self.actor_objects[aid] = actor

    def _actor_definition(self, aid):
        self._refresh_actor_objects_from_state()
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
            "type": str(props.get("type") or "monster"),
            "pos": _v3(actor.pos),
            "yaw": _facing(actor),
            "properties": props,
        }

    def _delete_temporary_actors(self):
        if self._cleaned:
            return
        state = self.main_window.state
        ids = set(self.temporary_actor_ids)
        state.things[:] = [
            actor for actor in state.things
            if not (
                getattr(actor, "properties", {}).get("_cutscene_temporary")
                and str(getattr(actor, "properties", {}).get("id", "")) in ids
            )
        ]
        self.temporary_actor_ids.clear()
        self._cleaned = True
        self.main_window.state.selected_objects = [
            obj for obj in self.main_window.state.selected_objects
            if str(getattr(obj, "properties", {}).get("id", "")) not in ids
        ]
        try:
            self.main_window.update_all_ui()
        except Exception:
            pass

    def _cleanup_after_cancel(self):
        # Temporary actors are authoring state, not a map edit.  Do not touch
        # the editor's dirty flag here: the user may have made unrelated map
        # edits while this modeless panel was open.
        self._delete_temporary_actors()

    def _current_map_name(self):
        path = self.main_window.file_path or ""
        return Path(path).name if path else ""

    def _find_map_actor(self, aid):
        aid = str(aid or "")
        if not aid:
            return None
        for obj in self.main_window.state.things:
            if str(getattr(obj, "properties", {}).get("id", "")) == aid:
                return obj
        return None

    def _existing_logic_camera(self, cutscene_file):
        wanted = str(cutscene_file or "").replace("\\", "/")
        for obj in self.main_window.state.things:
            if obj.__class__.__name__ != "LogicCamera":
                continue
            current = str(getattr(obj, "properties", {}).get("cutscene_file", "") or "").replace("\\", "/")
            if current == wanted:
                return obj
        return None

    def _current_map_cutscene_files(self):
        """Return cutscene files referenced by LogicCamera entities in the loaded map."""
        root_dir = Path(self.main_window.root_dir)
        seen = set()
        candidates = []

        for obj in self.main_window.state.things:
            if obj.__class__.__name__ != "LogicCamera":
                continue
            reference = str(
                getattr(obj, "properties", {}).get("cutscene_file", "") or ""
            ).replace("\\", "/").strip()
            if not reference:
                continue

            path = root_dir / reference
            try:
                key = str(path.resolve()).casefold()
            except OSError:
                key = str(path).casefold()
            if key in seen:
                continue
            seen.add(key)
            if path.is_file():
                candidates.append(path)

        return candidates

    def _load_current_map_cutscene(self):
        """Load a cutscene already attached to the currently loaded map, if any."""
        candidates = self._current_map_cutscene_files()
        if candidates:
            # The wizard edits one cutscene at a time. Map order supplies a
            # deterministic active cutscene; the Load button can switch to
            # another LogicCamera-referenced cutscene explicitly.
            self._load_cutscene(str(candidates[0]))

    def _load_cutscene(self, filename=None):
        if filename is None:
            start_dir = Path(self.main_window.root_dir) / CUTSCENE_DIR
            filename, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Load Cutscene", str(start_dir),
                "Cutscene JSON (*.json);;All files (*)",
            )
            if not filename:
                return
        try:
            data = json.loads(Path(filename).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(self, "Load failed", f"The cutscene could not be read:\n{exc}")
            return
        if not isinstance(data, dict) or not isinstance(data.get("camera"), list):
            QtWidgets.QMessageBox.warning(
                self, "Invalid cutscene",
                "This file is not a valid Fio cutscene (keyframes are missing).",
            )
            return

        saved_map = str((data.get("map") or {}).get("file", "") or "")
        current_map = self._current_map_name()
        if saved_map and current_map and saved_map.lower() != current_map.lower():
            result = QtWidgets.QMessageBox.question(
                self, "Different map",
                f"This cutscene was created for '{saved_map}', but the current map is "
                f"'{current_map}'.\n\nLoad it into the current map anyway?",
            )
            if result != QtWidgets.QMessageBox.Yes:
                return

        self._preview_stop_and_restore()
        self._delete_temporary_actors()
        # _delete_temporary_actors() marks the previous authoring session as
        # cleaned. Loading a new cutscene starts a fresh authoring session, so
        # its recreated spawn actors must be eligible for cleanup on Apply/Cancel.
        self._cleaned = False
        self.actor_meta.clear()
        self.actor_objects.clear()
        self.temporary_actor_ids.clear()
        self.actor_tracks = {
            str(aid): list(rows or [])
            for aid, rows in (data.get("actor_tracks") or {}).items()
            if isinstance(rows, list)
        }
        self.camera_keys = list(data.get("camera") or [])
        self.events = list(data.get("events") or [])
        self.name.setText(str(data.get("name") or "Cutscene"))
        self.filename.setText(Path(filename).name)

        settings = data.get("settings") or {}
        self.restore.setChecked(bool(settings.get("restore_actors", True)))
        self.stop_escape.setChecked(bool(settings.get("stop_on_escape", True)))
        trigger = self.trigger_mode.findData(settings.get("trigger_mode", "manual"))
        self.trigger_mode.setCurrentIndex(trigger if trigger >= 0 else 0)
        self.radius.setValue(float(settings.get("trigger_radius", 180.0)))
        self.once.setChecked(bool(settings.get("trigger_once", True)))

        for row in data.get("actors") or []:
            if not isinstance(row, dict):
                continue
            aid = str(row.get("id", "") or "")
            if not aid:
                continue
            name = str(row.get("name") or aid)
            definition = row.get("definition") if row.get("spawn") else None
            actor = self._find_map_actor(aid)
            if actor is None and isinstance(definition, dict):
                try:
                    cls = _entity_class(definition.get("type") or "monster")
                    actor_props = dict(definition.get("properties") or {})
                    actor_props["id"] = aid
                    actor_props["_cutscene_temporary"] = True
                    actor = cls(
                        pos=definition.get("pos") or [0.0, 0.0, 0.0],
                        properties=actor_props,
                    )
                    _set_facing(actor, float(definition.get("yaw", 0.0)))
                    self.main_window.state.things.append(actor)
                    self.actor_objects[aid] = actor
                    self.temporary_actor_ids.add(aid)
                except Exception as exc:
                    QtWidgets.QMessageBox.warning(
                        self, "Actor load failed",
                        f"Could not recreate actor '{name}': {exc}",
                    )
                    actor = None
            if actor is not None:
                self.actor_objects[aid] = actor
                if aid in self.temporary_actor_ids:
                    actor.properties["_cutscene_temporary"] = True
            self.actor_meta[aid] = {
                "id": aid, "name": name, "spawn": bool(row.get("spawn")),
            }

        self._refresh_actor_lists()
        self._rebuild_actor_panel()
        self._refresh_actor_keys_list()
        self._refresh_key_list()
        self._refresh_camera_list()
        self._refresh_event_list()
        self._refresh_summary()
        self._saved = True
        self._saved_signature = self._cutscene_signature()
        self.main_window.update_all_ui()
        self.main_window.show_toast(f"Loaded cutscene {Path(filename).name}", level='success')

    def _apply_logic_camera(self, filename):
        from .things import LogicCamera
        cutscene_file = str(Path(CUTSCENE_DIR) / Path(filename).name).replace("\\", "/")
        camera = self._existing_logic_camera(cutscene_file)
        if self.camera_keys:
            pos = list(self.camera_keys[0].get("pos", [0.0, 0.0, 0.0]))
        else:
            pos = _v3(self.main_window.view_3d.camera.pos)
        props = {
            "type": "logic_camera",
            "id": str(camera.properties.get("id")) if camera is not None else str(uuid.uuid4()),
            "name": self.name.text().strip() or "Cutscene Camera",
            "cutscene_file": cutscene_file,
            "cutscene_trigger_mode": self.trigger_mode.currentData(),
            "cutscene_trigger_radius": float(self.radius.value()),
            "cutscene_once": self.once.isChecked(),
            "cutscene_restore_actors": self.restore.isChecked(),
            "cutscene_stop_on_escape": self.stop_escape.isChecked(),
            "cutscene_io_events": [dict(e) for e in self.events if e.get("type") == "io"],
        }
        self.main_window.save_state()
        if camera is None:
            camera = LogicCamera(pos=pos, properties=props)
            self.main_window.state.things.append(camera)
        else:
            camera.pos = [float(v) for v in pos]
            camera.properties.update(props)
        self._delete_temporary_actors()
        self.main_window.set_selected_objects([camera])
        self.main_window.update_all_ui()
        self._saved = True
        self.main_window.show_toast(f"Applied cutscene {Path(filename).name} to current map")
        return camera

    def _build_cutscene_data(self):
        actors = []
        for aid, meta in self.actor_meta.items():
            row = {"id": aid, "name": meta["name"]}
            if meta.get("spawn") or aid in self.temporary_actor_ids:
                definition = self._actor_definition(aid)
                if definition is not None:
                    row["spawn"] = True
                    row["definition"] = definition
            actors.append(row)
        return {
            "version": 2,
            "id": str(uuid.uuid4()),
            "name": self.name.text().strip() or "Cutscene",
            "actors": actors,
            "camera": self.camera_keys,
            "actor_tracks": self.actor_tracks,
            "events": sorted(self.events, key=lambda x: x.get("time", 0)),
            "map": {"file": self._current_map_name()},
            "settings": {
                **({"camera": "top_down"} if TOP_DOWN_CAMERA else {}),
                "restore_actors": self.restore.isChecked(),
                "stop_on_escape": self.stop_escape.isChecked(),
                "trigger_mode": self.trigger_mode.currentData(),
                "trigger_radius": float(self.radius.value()),
                "trigger_once": self.once.isChecked(),
            },
        }

    def _validate_for_save(self):
        self._preview_stop_and_restore()
        if not self.camera_keys:
            QtWidgets.QMessageBox.warning(
                self, "No keyframes", "Capture at least one camera position."
            )
            return None
        if not self.actor_meta and not self.events:
            QtWidgets.QMessageBox.warning(
                self, "Empty cutscene",
                "Create/capture at least one actor or add a timed event."
            )
            return None
        return self._filename()

    def _write_cutscene(self, filename, prompt_overwrite=False):
        path = Path(self.main_window.root_dir) / CUTSCENE_DIR / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        if prompt_overwrite and path.exists():
            result = QtWidgets.QMessageBox.question(
                self, "Overwrite cutscene",
                f"{filename} already exists. Replace it?"
            )
            if result != QtWidgets.QMessageBox.Yes:
                return False
        try:
            # Written aside and swapped in: a full disk or a crash mid-write
            # must not leave the existing cutscene truncated.
            from engine.fileio import write_text_atomic
            write_text_atomic(
                str(path),
                # Minified, as every cutscene in cutscenes/ is stored.
                json.dumps(self._build_cutscene_data(), separators=(",", ":"),
                           ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            QtWidgets.QMessageBox.warning(
                self, "Save failed", f"The cutscene JSON could not be written:\n{exc}"
            )
            return False
        return True

    def _save_and_close(self):
        filename = self._validate_for_save()
        if not filename:
            return
        if not self._write_cutscene(filename, prompt_overwrite=True):
            return
        self._saved = True
        self._saved_signature = self._cutscene_signature()
        self._delete_temporary_actors()
        self.main_window.show_toast(f"Saved cutscene {filename}", level='success')
        super().accept()

    def _apply_to_map(self):
        filename = self._validate_for_save()
        if not filename:
            return
        # Apply must update the JSON as well: LogicCamera stores a filename,
        # so applying stale on-disk data would make the map reference an older
        # version of the cutscene being authored.
        if not self._write_cutscene(filename, prompt_overwrite=False):
            return
        self._apply_logic_camera(filename)
        self._saved = True
        self._saved_signature = self._cutscene_signature()

    def reject(self):
        if not self._confirm_close():
            return
        self._preview_stop_and_restore()
        self._cleanup_after_cancel()
        super().reject()

    def closeEvent(self, event):
        if not self._confirm_close():
            event.ignore()
            return
        self._preview_stop_and_restore()
        self._cleanup_after_cancel()
        event.accept()


# Backwards-compatible class name retained for MainWindow.open_cutscene_wizard.
CutsceneWizard = CutsceneWizard
