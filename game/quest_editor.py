"""
Quest Editor & Quest Wizard — a first-class, card-based popup for authoring the
RPG's quests without touching JSON.

Quests are plain dicts stored as human-readable ``.quest`` files in the
project's ``quests/`` folder (see :mod:`game.rpg.quest_files`) — not on the
``GameSettings`` entity — so the same files the editor writes are the ones the
running game loads, and a designer can hand-edit or version-control them. A map
that still carries the old ``properties['quests']`` list is migrated into the
folder the first time the editor opens it. This module adds:

* :func:`make_quests_launcher` — the small panel that lives in the GameSettings
  *Quests* property tab: a live summary of the map's quests plus buttons that
  open the full editor or jump straight into the wizard.
* :func:`open_quest_editor` — opens :class:`QuestEditorDialog`, a large popup
  where quests and their stages are shown as **cards** and edited in a tidy,
  visual detail panel.
* The **Quest Wizard** — a guided QWizard that asks who gives the quest, what
  the goal is, and the rewards, then builds the quest *and its supporting map
  logic*: a location Marker for "visit" goals, and a dialogue branch on the
  giver NPC so talking to them offers and starts the quest.

All Qt imports are local/lazy so a headless player process never imports PyQt5;
each entry point degrades to a plain "not available" label if Qt is missing.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Shared vocabulary (kept in step with game.rpg.quests COND_* kinds)
# ---------------------------------------------------------------------------
#: (kind, short label, one-line description, emoji) for each completion goal.
GOAL_KINDS = [
    ("talk",  "Talk to someone", "The stage completes when the player speaks "
                                 "to a named NPC or role.", "💬"),
    ("fetch", "Fetch an item",   "The stage completes once the player is "
                                 "holding enough of an item.", "🎒"),
    ("kill",  "Kill targets",    "The stage completes after enough monsters "
                                 "of a type/role are slain.", "⚔️"),
    ("visit", "Visit a place",   "The stage completes when the player reaches "
                                 "a location marker on the map.", "📍"),
    ("roll",  "Pass a dice check", "The stage completes when the shared dice "
                                  "service meets a target total.", "🎲"),

    ("none",  "Scripted",        "The stage only advances when your dialogue "
                                 "runs 'advance_quest'.", "📜"),
]
GOAL_LABEL = {k: lbl for k, lbl, _d, _e in GOAL_KINDS}
GOAL_EMOJI = {k: e for k, _l, _d, e in GOAL_KINDS}
GOAL_DESC = {k: d for k, _l, d, _e in GOAL_KINDS}

#: Placeholder guidance for the goal target field, per kind.
GOAL_TARGET_HINT = {
    "none":  "(no target — advanced by a dialogue 'advance_quest')",
    "talk":  "NPC name or role, e.g. Bob  /  blacksmith",
    "roll":  "dice notation, e.g. 1d20  (minimum target is set below)",

    "fetch": "item id, e.g. iron_sword",
    "kill":  "monster_type / npc_role / name, e.g. wolf",
    "visit": "location name, e.g. Old Cave",
}


# ---------------------------------------------------------------------------
# Qt / editor plumbing
# ---------------------------------------------------------------------------
def _qt():
    from PyQt5 import QtWidgets, QtCore, QtGui
    return QtWidgets, QtCore, QtGui


def _find_editor(widget):
    """Return the main editor window (the object that owns ``state.things``),
    found by walking up from *widget* and then scanning top-level widgets.
    Returns ``None`` when it can't be located (e.g. a detached test harness)."""
    try:
        w = widget
        seen = 0
        while w is not None and seen < 20:
            state = getattr(w, "state", None)
            if state is not None and hasattr(state, "things"):
                return w
            w = w.parent() if hasattr(w, "parent") else None
            seen += 1
    except Exception:
        pass
    try:
        QtWidgets, _c, _g = _qt()
        for top in QtWidgets.QApplication.topLevelWidgets():
            state = getattr(top, "state", None)
            if state is not None and hasattr(state, "things"):
                return top
    except Exception:
        pass
    return None


def _scene_things(editor):
    try:
        return list(editor.state.things)
    except Exception:
        return []


def _npc_names(editor):
    """Names of NPCs and monsters that can give a quest in the scene."""
    names = set()
    for t in _scene_things(editor):
        props = getattr(t, "properties", None)
        kind = str(props.get("type", "")).lower() if isinstance(props, dict) else ""
        if kind in ("npc", "monster", "creature"):
            n = str(props.get("name", "")).strip()
            if n:
                names.add(n)
    return sorted(names)


def _thing_id(thing):
    """The entity's stable UUID (``properties['id']``), or ``''``."""
    props = getattr(thing, "properties", None)
    if isinstance(props, dict) and props.get("id"):
        return str(props.get("id"))
    return str(getattr(thing, "id", "") or "")


def _npc_giver_entries(editor):
    """(label, value) pairs for every quest-giver candidate in the scene.

    The *value* stored on the quest is the NPC's **name** when that name is
    unique, or its **entity id (UUID)** when the name is shared (e.g. two
    "Guard" NPCs), so the giver always resolves to exactly one entity at play
    start. The *label* stays human-readable ("Name — role" or "Name — role · id
    abc123") so the author can still tell who they picked.
    """
    candidates = []
    name_counts = {}
    for t in _scene_things(editor):
        props = getattr(t, "properties", None)
        kind = str(props.get("type", "")).lower() if isinstance(props, dict) else ""
        if kind not in ("npc", "monster", "creature"):
            continue
        name = str(props.get("name", "")).strip()
        if not name:
            continue
        candidates.append(t)
        name_counts[name] = name_counts.get(name, 0) + 1
    entries = []
    for t in candidates:
        props = t.properties
        name = str(props.get("name", "")).strip()
        role = str(props.get("npc_role", "")).strip()
        eid = _thing_id(t)
        ambiguous = name_counts.get(name, 0) > 1
        value = eid if (ambiguous and eid) else name
        label = f"{name} — {role}" if role else name
        if ambiguous and eid:
            label += f" · id {eid[:8]}"
        entries.append((label, value))
    entries.sort(key=lambda e: e[0].lower())
    return entries


def _find_thing_by_name(editor, name):
    """Find a scene thing by giver value — its entity id first, then its name."""
    if not name:
        return None
    for t in _scene_things(editor):
        if _thing_id(t) == name:
            return t
    for t in _scene_things(editor):
        props = getattr(t, "properties", None)
        if isinstance(props, dict) and props.get("name") == name:
            return t
    return None


def _resolve_entity_ref(editor, raw):
    """Normalise a quest reference to a scene entity's stable **id (UUID)**.

    Names change; ids do not. Given whatever the author typed or picked — an
    id, or a name / display name / role — return the matching entity's id so
    the quest keeps pointing at the same NPC even after it is renamed. Returns
    *raw* unchanged when it is already an id, when it matches no single entity,
    or when the name is shared by several (the combo offers ids for those, so an
    ambiguous name only survives for hand-typed input). Empty in, empty out.
    """
    raw = str(raw or "").strip()
    if not raw:
        return ""
    things = _scene_things(editor)
    for t in things:                     # already an id?
        if _thing_id(t) == raw:
            return raw
    rl = raw.lower()
    matches = []
    for t in things:
        p = getattr(t, "properties", None) or {}
        vals = {str(p.get("name", "")).strip().lower(),
                str(p.get("display_name", "")).strip().lower(),
                str(p.get("npc_role", "")).strip().lower()}
        vals.discard("")
        if rl in vals:
            matches.append(t)
    ids = [_thing_id(t) for t in matches if _thing_id(t)]
    if len(matches) == 1 and ids and ids[0]:
        return ids[0]
    return raw


def _entity_display_name(editor, ref):
    """A human-readable name for a quest reference (id or name), for journal /
    objective text. An id resolves to its entity's display name / name / role;
    a plain name is returned as-is. Falls back to *ref* when nothing matches."""
    ref = str(ref or "").strip()
    if not ref:
        return ""
    for t in _scene_things(editor):
        if _thing_id(t) == ref:
            p = getattr(t, "properties", None) or {}
            return str(p.get("display_name") or p.get("name")
                       or p.get("npc_role") or ref)
    return ref


def _refresh_editor(editor):
    """Best-effort: push scene changes into the rest of the UI + dirty flag."""
    for meth in ("save_state",):
        fn = getattr(getattr(editor, "state", None), meth, None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass
    for meth in ("mark_dirty", "update_all_ui"):
        fn = getattr(editor, meth, None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# File-backed quest storage (quests/ folder of .quest files) — Qt-free
# ---------------------------------------------------------------------------
def load_quests_for_editor(thing):
    """Return the quest list the editor should edit, from the ``quests/`` folder.

    Quests are stored as external ``.quest`` files, not on the ``GameSettings``
    entity. The first time this runs on a map that still carries the old
    ``properties['quests']`` list, those quests are migrated into the folder so
    nothing is lost. Returns a list of quest dicts (safe to mutate).
    """
    from .rpg import quest_files
    defs = quest_files.load_quest_defs()
    if defs:
        return defs
    # Migrate any legacy quests authored on the entity into the new folder.
    legacy = getattr(thing, "properties", {}).get("quests") if thing is not None else None
    if isinstance(legacy, list) and legacy:
        import copy
        legacy = [copy.deepcopy(q) for q in legacy if isinstance(q, dict) and q.get("id")]
        if legacy:
            try:
                quest_files.sync_quest_files(legacy)
            except Exception:
                pass
            return legacy
    return []


def save_quests_from_editor(thing, quests):
    """Write *quests* to the ``quests/`` folder and clear the legacy entity copy.

    Keeping the quests out of the ``GameSettings`` entity is deliberate: the
    ``.quest`` files are the single source of truth the running game loads.
    """
    from .rpg import quest_files
    try:
        quest_files.sync_quest_files(quests)
    except Exception:
        pass
    # Drop the legacy on-entity copy so quests are no longer stored in the map.
    try:
        if thing is not None and isinstance(getattr(thing, "properties", None), dict):
            if thing.properties.get("quests"):
                thing.properties["quests"] = []
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Pure data helpers (quest dict shape) — unit-testable without Qt
# ---------------------------------------------------------------------------
def new_quest_dict(existing, name="New Quest", giver=""):
    """A blank quest dict with a unique id derived from *existing* quests."""
    ids = {q.get("id") for q in existing if isinstance(q, dict)}
    n = len(existing) + 1
    qid = _slug(name) or f"quest_{n}"
    base = qid
    i = 2
    while qid in ids:
        qid = f"{base}_{i}"
        i += 1
    return {
        "id": qid, "name": name, "giver": giver, "faction": "", "desc": "",
        "xp": 0, "rewards": {"gold": 0},
        "stages": [{"index": 0, "journal": "", "objective": "",
                    "finishes": False,
                    "condition": {"kind": "none", "target": "", "count": 1}}],
    }


def _slug(text):
    out = []
    for ch in str(text).strip().lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in " -_" and out and out[-1] != "_":
            out.append("_")
    return "".join(out).strip("_")


def _cond_phrase(cond):
    kind = str((cond or {}).get("kind", "none")).lower()
    tgt = (cond or {}).get("target", "")
    cnt = (cond or {}).get("count", 1)
    if kind == "kill":
        return f"⚔️ Kill {cnt}× {tgt or '?'}"
    if kind == "fetch":
        return f"🎒 Fetch {cnt}× {tgt or '?'}"
    if kind == "talk":
        return f"💬 Talk to {tgt or '?'}"
    if kind == "roll":
        notation = (cond or {}).get("notation", "1d20")
        return f"🎲 Roll {notation} ≥ {tgt or '?'}"


def goal_summary(quest):
    """One-line human summary of a quest's main goal. Prefers the first
    condition-bearing, non-finishing stage (the real objective) over the
    trailing 'report back' stage; falls back to any goal, then a scripted note."""
    stages = quest.get("stages") or []
    for s in stages:
        if s.get("finishes"):
            continue
        phrase = _cond_phrase(s.get("condition"))
        if phrase:
            return phrase
    for s in stages:
        phrase = _cond_phrase(s.get("condition"))
        if phrase:
            return phrase
    return "📜 Scripted / dialogue-driven"


def build_wizard_quest(existing, *, name, giver, desc, goal_kind, target,
                       count, gold, xp, item, item_qty, faction="",
                       roll_notation="1d20", roll_target=10, giver_name="",
                       target_name=""):
    """Assemble a complete quest dict (identity + two staged journal entries +
    completion condition + rewards) from the wizard's plain answers. Pure — no
    Qt, no scene side effects — so it's easy to test.

    ``giver`` is the stored reference — a scene entity's **id (UUID)** when the
    caller could resolve one, so a rename never breaks the link. ``giver_name``
    is the readable name used only in the journal / objective text; it defaults
    to ``giver`` when not supplied."""
    q = new_quest_dict(existing, name=name or "New Quest", giver=giver or "")
    q["giver"] = giver or ""
    q["desc"] = desc or ""
    q["faction"] = faction or ""
    q["xp"] = int(xp or 0)

    rewards = {"gold": int(gold or 0)}
    if item:
        rewards["items"] = [[str(item), int(item_qty or 1)]]
    q["rewards"] = rewards

    kind = goal_kind if goal_kind in GOAL_LABEL else "none"
    obj = _default_objective(kind, target, count, roll_notation,
                             display=target_name)
    start_journal = desc or f"{name}."
    condition = {"kind": kind, "target": str(target or ""),
                 "count": int(count or 1)}
    if kind == "roll":
        condition["notation"] = str(roll_notation or "1d20").strip()
        condition["target"] = int(roll_target or 1)
    do_stage = {
        "index": 0,
        "journal": start_journal,
        "objective": obj,
        "finishes": False,
        "condition": condition,
    }
    gname = str(giver_name or giver or "").strip()
    done_stage = {
        "index": 10,
        "journal": f"You have completed '{name}'. Return for your reward."
                   if giver else f"You have completed '{name}'.",
        "objective": f"Report to {gname}" if giver else "Quest complete",
        "finishes": True,
        # Target stored as the giver reference (a UUID when resolved) so the
        # "report back" step follows the same NPC even if it is renamed.
        "condition": {"kind": "talk", "target": giver, "count": 1} if giver
                     else {"kind": "none", "target": "", "count": 1},
    }
    q["stages"] = [do_stage, done_stage]
    return q


def _default_objective(kind, target, count, notation="1d20", display=None):
    # *display* is a readable name for the objective line when *target* is a
    # stored id (UUID) — used for a 'talk' NPC. Kill/fetch targets are class /
    # item ids and read fine as-is.
    shown = str(display or target)
    if kind == "kill":
        return f"Kill {count} {target}".strip()
    if kind == "fetch":
        return f"Find {count} {target}".strip()
    if kind == "talk":
        return f"Speak with {shown}".strip()
    if kind == "visit":
        return f"Travel to {target}".strip()
    if kind == "roll":
        return f"Pass a dice check ({notation or '1d20'})"
    return "Follow the quest"


def wire_giver_dialogue(giver_thing, quest):
    """Inject a 'start this quest' branch into *giver_thing*'s dialogue so the
    NPC offers it in play (this is what makes the '!' available-quest cue show).
    Idempotent: a second call for the same quest id does nothing. Returns True
    when the dialogue was created or extended.

    The branch itself is built by :func:`game.rpg.quests.offer_dialogue_branch`,
    the same Qt-free helper the running game uses to auto-wire every giver at
    play start, so hand-wiring in the editor and automatic wiring produce
    identical dialogue."""
    if giver_thing is None:
        return False
    from .rpg.quests import offer_dialogue_branch
    props = giver_thing.properties
    dlg = props.get("dialogue")
    dlg, changed = offer_dialogue_branch(
        dlg if isinstance(dlg, dict) else None,
        quest.get("id", ""), quest.get("name", quest.get("id", "")),
        quest.get("desc", ""))
    props["dialogue"] = dlg
    return changed


# Quest Wizard window sizing. Change these four values to tune its default and
# smallest allowed size without searching through the widget-building code.
QUEST_WIZARD_DEFAULT_WIDTH = 1270
QUEST_WIZARD_DEFAULT_HEIGHT = 1055
QUEST_WIZARD_MIN_WIDTH = 995
QUEST_WIZARD_MIN_HEIGHT = 1013


# ---------------------------------------------------------------------------
# Widgets (lazy-built so PyQt is only needed inside the editor)
# ---------------------------------------------------------------------------
_CLASSES = None


def _classes():
    """Build (and cache) the Qt widget classes. Returns a dict or None if Qt is
    unavailable."""
    global _CLASSES
    if _CLASSES is not None:
        return _CLASSES
    try:
        QtWidgets, QtCore, QtGui = _qt()
    except Exception:
        return None

    Qt = QtCore.Qt
    Signal = QtCore.pyqtSignal

    STYLE = """
    QDialog { background: #1b1b21; color: #e6e6e6; }
    QLabel { color: #d5d5d5; }
    QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
        background: #2a2a33; border: 1px solid #4a4a55; border-radius: 4px;
        color: #f0f0f0; padding: 5px; selection-background-color: #3a5a8a; }
    QComboBox::drop-down { border: none; }
    QComboBox QAbstractItemView { background: #2a2a33; color: #eee;
        selection-background-color: #3a5a8a; }
    QScrollArea { border: none; background: transparent; }
    QPushButton { background: #34343f; border: 1px solid #55555f;
        border-radius: 5px; padding: 7px 15px; color: #e8e8e8; }
    QPushButton:hover { background: #43434f; }
    QPushButton#primary { background: #2f7d4f; border: 1px solid #3ea56a;
        font-weight: bold; }
    QPushButton#primary:hover { background: #379258; }
    QPushButton#danger { background: #7d3030; border: 1px solid #a54a4a; }
    QPushButton#danger:hover { background: #923838; }
    QCheckBox { color: #d5d5d5; spacing: 7px; }
    QGroupBox { color: #b9b9c4; border: 1px solid #3a3a44; border-radius: 6px;
        margin-top: 12px; padding-top: 10px; }
    QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
    """

    # ---- a clickable card frame -------------------------------------------
    class _Card(QtWidgets.QFrame):
        clicked = Signal()

        def __init__(self, selectable=True):
            super().__init__()
            self._selected = False
            self._selectable = selectable
            self.setFrameShape(QtWidgets.QFrame.StyledPanel)
            self._restyle()

        def mousePressEvent(self, ev):
            self.clicked.emit()
            super().mousePressEvent(ev)

        def set_selected(self, on):
            self._selected = bool(on)
            self._restyle()

        def _restyle(self):
            if self._selected:
                border, bg = "#4a90d9", "#26303f"
            else:
                border, bg = "#3a3a44", "#24242c"
            hover = "" if not self._selectable else \
                "_Card:hover { border: 1px solid #5a5a66; }"
            self.setStyleSheet(
                f"_Card {{ background: {bg}; border: 1px solid {border}; "
                f"border-radius: 8px; }} {hover}")

    # ---- goal picker card (used in the wizard) ----------------------------
    class _GoalCard(_Card):
        def __init__(self, kind):
            super().__init__(selectable=True)
            self.kind = kind
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(12, 12, 12, 12)
            title = QtWidgets.QLabel(f"{GOAL_EMOJI.get(kind,'•')}  "
                                     f"{GOAL_LABEL.get(kind, kind)}")
            tf = title.font(); tf.setBold(True); tf.setPointSizeF(tf.pointSizeF() + 1)
            title.setFont(tf)
            desc = QtWidgets.QLabel(GOAL_DESC.get(kind, ""))
            desc.setWordWrap(True)
            desc.setStyleSheet("color:#9a9aa6;")
            lay.addWidget(title)
            lay.addWidget(desc)

    class _LinearWizardPage(QtWidgets.QWizardPage):
        """Wizard page with deterministic sequential navigation."""

        def nextId(self):
            wizard = self.wizard()
            if wizard is None:
                return -1
            page_ids = wizard.pageIds()
            try:
                next_index = page_ids.index(wizard.currentId()) + 1
            except ValueError:
                return -1
            return page_ids[next_index] if next_index < len(page_ids) else -1

    # ===================================================================
    # The Quest Wizard
    # ===================================================================
    class QuestWizard(QtWidgets.QWizard):
        def __init__(self, quests, editor, parent=None):
            super().__init__(parent)
            self.quests = quests
            self.editor = editor
            self.result_quest = None
            self.setWindowTitle("Quest Wizard")
            self.setWizardStyle(QtWidgets.QWizard.ModernStyle)
            self.setOption(QtWidgets.QWizard.NoBackButtonOnStartPage, True)
            self.setOption(QtWidgets.QWizard.HaveHelpButton, False)
            self.setMinimumSize(QUEST_WIZARD_MIN_WIDTH, QUEST_WIZARD_MIN_HEIGHT)
            self.resize(QUEST_WIZARD_DEFAULT_WIDTH, QUEST_WIZARD_DEFAULT_HEIGHT)
            self.setStyleSheet(STYLE + """
                QWizard { background: #1b1b21; }
                QWizardPage { background: #1b1b21; color: #e6e6e6; }
            """)
            self.setButtonText(QtWidgets.QWizard.FinishButton, "Create Quest")
            self._goal_cards = {}
            self.addPage(self._page_basics())
            self.addPage(self._page_goal())
            self.addPage(self._page_reward())
            self._wiring_id = self.addPage(self._page_wiring())
            # Refresh the wiring page's plan when it becomes visible (an
            # instance-assigned initializePage isn't seen by Qt's virtual call).
            self.currentIdChanged.connect(self._on_page)

        def _on_page(self, pid):
            if pid == getattr(self, "_wiring_id", -1):
                self._refresh_plan()

        # -- page 1: basics --------------------------------------------------
        def _page_basics(self):
            p = _LinearWizardPage()
            p.setTitle("Who and what")
            p.setSubTitle("Name the quest and choose who hands it out.")
            f = QtWidgets.QFormLayout(p)
            self.w_name = QtWidgets.QLineEdit("A New Errand")
            self._giver_entries = _npc_giver_entries(self.editor)
            self.w_giver = QtWidgets.QComboBox()
            self.w_giver.setEditable(True)
            self.w_giver.addItem("", "")
            for _label, value in self._giver_entries:
                self.w_giver.addItem(value, value)
            self.w_giver.setToolTip("The NPC or monster who offers the quest. Pick one from "
                                    "the scene, type a name, or paste an entity id (UUID) to "
                                    "target one specific NPC when several share a name.")
            self.w_giver.currentTextChanged.connect(
                lambda _text: self._refresh_plan() if hasattr(self, "w_make_marker") else None)

            self.w_giver_button = QtWidgets.QPushButton("Choose…")
            self.w_giver_button.setToolTip("Choose an available NPC or monster from the scene "
                                           "(shared names are assigned by entity id).")
            self._giver_menu = QtWidgets.QMenu(self.w_giver_button)
            self.w_giver_button.setMenu(self._giver_menu)
            clear_action = self._giver_menu.addAction("(none)")
            clear_action.triggered.connect(lambda: self.w_giver.setEditText(""))
            if self._giver_entries:
                self._giver_menu.addSeparator()
                for label, value in self._giver_entries:
                    action = self._giver_menu.addAction(label)
                    action.triggered.connect(
                        lambda _checked=False, selected=value:
                        self.w_giver.setEditText(selected))
            else:
                empty_action = self._giver_menu.addAction("No NPCs or monsters found")
                empty_action.setEnabled(False)

            giver_row = QtWidgets.QHBoxLayout()
            giver_row.setContentsMargins(0, 0, 0, 0)
            giver_row.addWidget(self.w_giver, 1)
            giver_row.addWidget(self.w_giver_button)
            self.w_desc = QtWidgets.QPlainTextEdit()
            self.w_desc.setPlaceholderText("What the giver tells the player…")
            self.w_desc.setMaximumHeight(90)
            f.addRow("Quest name", self.w_name)
            f.addRow("Given by", giver_row)
            f.addRow("Opening text", self.w_desc)
            return p

        # -- page 2: goal ----------------------------------------------------
        def _page_goal(self):
            p = _LinearWizardPage()
            p.setTitle("The goal")
            p.setSubTitle("How does the player complete this quest?")
            v = QtWidgets.QVBoxLayout(p)
            grid = QtWidgets.QGridLayout()
            grid.setSpacing(8)
            self._goal_kind = "kill"
            for i, (kind, _l, _d, _e) in enumerate(GOAL_KINDS):
                card = _GoalCard(kind)
                card.clicked.connect(lambda k=kind: self._pick_goal(k))
                self._goal_cards[kind] = card
                grid.addWidget(card, i // 2, i % 2)
            v.addLayout(grid)

            box = QtWidgets.QGroupBox("Target")
            bf = QtWidgets.QFormLayout(box)
            self.w_target = QtWidgets.QLineEdit()
            self.w_count = QtWidgets.QSpinBox(); self.w_count.setRange(1, 100000)
            self.w_roll_target = QtWidgets.QSpinBox(); self.w_roll_target.setRange(1, 100000)
            self.w_roll_target.setValue(10)
            bf.addRow("Target", self.w_target)
            bf.addRow("How many", self.w_count)
            bf.addRow("Dice minimum", self.w_roll_target)
            v.addWidget(box)
            self._target_box = box
            self._pick_goal("kill")
            return p

        def _pick_goal(self, kind):
            self._goal_kind = kind
            for k, card in self._goal_cards.items():
                card.set_selected(k == kind)
            self.w_target.setPlaceholderText(GOAL_TARGET_HINT.get(kind, ""))
            self.w_target.setEnabled(kind not in ("none",))
            self.w_count.setEnabled(kind in ("kill", "fetch"))
            self.w_roll_target.setEnabled(kind == "roll")

        # -- page 3: rewards -------------------------------------------------
        def _page_reward(self):
            p = _LinearWizardPage()
            p.setTitle("The reward")
            p.setSubTitle("What the player earns for finishing (all optional).")
            f = QtWidgets.QFormLayout(p)
            self.w_gold = QtWidgets.QSpinBox(); self.w_gold.setRange(0, 1000000)
            self.w_gold.setValue(50)
            self.w_xp = QtWidgets.QSpinBox(); self.w_xp.setRange(0, 1000000)
            self.w_xp.setValue(20)
            self.w_item = QtWidgets.QLineEdit()
            self.w_item.setPlaceholderText("item id, e.g. iron_sword (optional)")
            self.w_item_qty = QtWidgets.QSpinBox(); self.w_item_qty.setRange(1, 999)
            f.addRow("Gold", self.w_gold)
            f.addRow("XP", self.w_xp)
            f.addRow("Reward item", self.w_item)
            f.addRow("Item quantity", self.w_item_qty)
            return p

        # -- page 4: wiring --------------------------------------------------
        def _page_wiring(self):
            p = _LinearWizardPage()
            p.setTitle("Build the logic")
            p.setSubTitle("The wizard can create the supporting map pieces for you.")
            v = QtWidgets.QVBoxLayout(p)
            self.w_make_marker = QtWidgets.QCheckBox(
                "Create a location marker for the 'visit' target")
            self.w_wire_giver = QtWidgets.QCheckBox(
                "Make the giver offer this quest in dialogue")
            self.w_wire_giver.setChecked(True)
            v.addWidget(self.w_make_marker)
            v.addWidget(self.w_wire_giver)
            self._plan = QtWidgets.QLabel()
            self._plan.setWordWrap(True)
            self._plan.setStyleSheet(
                "background:#24242c; border:1px solid #3a3a44; border-radius:6px;"
                "padding:10px; color:#c8c8d0;")
            v.addWidget(self._plan)
            v.addStretch(1)
            return p

        def _refresh_plan(self):
            giver = self.w_giver.currentText().strip()
            kind = self._goal_kind
            in_scene = _find_thing_by_name(self.editor, giver) is not None
            self.w_make_marker.setEnabled(kind == "visit")
            self.w_make_marker.setChecked(kind == "visit")
            self.w_wire_giver.setEnabled(bool(giver) and in_scene)
            if giver and not in_scene:
                self.w_wire_giver.setChecked(False)
            lines = ["<b>On finish this wizard will:</b>",
                     "• Add the quest with a start stage and a finish stage."]
            if kind == "visit" and self.w_make_marker.isChecked():
                lines.append(f"• Drop a location marker named "
                             f"“{self.w_target.text().strip() or 'location'}”.")
            if giver:
                if in_scene and self.w_wire_giver.isChecked():
                    lines.append(f"• Give <b>{giver}</b> a dialogue branch that "
                                 f"offers and starts the quest.")
                elif not in_scene:
                    lines.append(f"• Note: no NPC named “{giver}” is in the "
                                 f"scene yet, so dialogue wiring is skipped.")
            self._plan.setText("<br>".join(lines))

        # -- finish ----------------------------------------------------------
        def accept(self):
            # Store the giver by its stable entity id (UUID) when we can resolve
            # one, so renaming the NPC later never orphans the quest; keep the
            # readable name only for the journal / objective text.
            raw_giver = self.w_giver.currentText().strip()
            giver = _resolve_entity_ref(self.editor, raw_giver)
            giver_name = _entity_display_name(self.editor, giver) or raw_giver
            # A 'talk' goal points at one specific NPC, so store it by id (UUID)
            # too — kill/fetch/visit targets are class / item / place ids and
            # stay as typed (that is how the runtime tracks them).
            raw_target = self.w_target.text().strip()
            goal_target, target_name = raw_target, ""
            if self._goal_kind == "talk":
                goal_target = _resolve_entity_ref(self.editor, raw_target)
                target_name = _entity_display_name(self.editor, goal_target) or raw_target
            quest = build_wizard_quest(
                self.quests,
                name=self.w_name.text().strip(),
                giver=giver,
                giver_name=giver_name,
                desc=self.w_desc.toPlainText().strip(),
                goal_kind=self._goal_kind,
                target=goal_target,
                target_name=target_name,
                count=self.w_count.value(),
                gold=self.w_gold.value(),
                xp=self.w_xp.value(),
                item=self.w_item.text().strip(),
                item_qty=self.w_item_qty.value(),
                roll_notation=self.w_target.text().strip(),
                roll_target=self.w_roll_target.value(),
            )
            # Scene side-effects (guarded — never block quest creation).
            if (self._goal_kind == "visit" and self.w_make_marker.isChecked()
                    and self.editor is not None):
                self._create_location_marker(quest, giver)
            if (giver and self.w_wire_giver.isEnabled()
                    and self.w_wire_giver.isChecked()):
                gthing = _find_thing_by_name(self.editor, giver)
                try:
                    wire_giver_dialogue(gthing, quest)
                except Exception:
                    pass
            if self.editor is not None:
                _refresh_editor(self.editor)
            self.result_quest = quest
            super().accept()

        def _create_location_marker(self, quest, giver):
            try:
                from editor.things import ENTITY_TYPES
            except Exception:
                return
            cls = ENTITY_TYPES.get("Marker")
            if cls is None:
                return
            target = self.w_target.text().strip() or "location"
            # Place next to the giver if we can find them, else near the origin.
            pos = [0.0, 0.0, 0.0]
            g = _find_thing_by_name(self.editor, giver)
            if g is not None:
                try:
                    gp = g.pos
                    pos = [float(gp[0]) + 96.0, float(gp[1]), float(gp[2])]
                except Exception:
                    pass
            try:
                marker = cls(pos=list(pos),
                             properties={"name": target, "marker_kind": "location"})
                self.editor.state.things.append(marker)
            except Exception:
                pass

    # ===================================================================
    # Stage card (one per stage, in the detail panel)
    # ===================================================================
    class _StageCard(_Card):
        changed = Signal()
        removed = Signal()

        def __init__(self, stage, npc_names):
            super().__init__(selectable=False)
            self.stage = stage
            self._loading = False
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(12, 10, 12, 12)
            lay.setSpacing(6)

            head = QtWidgets.QHBoxLayout()
            self.title = QtWidgets.QLabel()
            tf = self.title.font(); tf.setBold(True)
            self.title.setFont(tf)
            head.addWidget(self.title)
            head.addStretch(1)
            self.fin = QtWidgets.QCheckBox("Completes the quest")
            self.fin.stateChanged.connect(self._push)
            head.addWidget(self.fin)
            rm = QtWidgets.QPushButton("✕"); rm.setObjectName("danger")
            rm.setFixedWidth(30)
            rm.clicked.connect(lambda: self.removed.emit())
            head.addWidget(rm)
            lay.addLayout(head)

            self.obj = QtWidgets.QLineEdit()
            self.obj.setPlaceholderText("Objective shown in the HUD tracker")
            self.obj.editingFinished.connect(self._push)
            lay.addWidget(self.obj)

            self.journal = QtWidgets.QPlainTextEdit()
            self.journal.setPlaceholderText("Journal paragraph for this stage…")
            self.journal.setMaximumHeight(70)
            self.journal.textChanged.connect(self._push)
            lay.addWidget(self.journal)

            row = QtWidgets.QHBoxLayout()
            self.cond = QtWidgets.QComboBox()
            for kind, lbl, _d, emoji in GOAL_KINDS:
                self.cond.addItem(f"{emoji} {lbl}", kind)
            self.cond.currentIndexChanged.connect(self._push)
            self.target = QtWidgets.QLineEdit()
            self.count = QtWidgets.QSpinBox(); self.count.setRange(1, 100000)
            self.target.editingFinished.connect(self._push)
            self.count.valueChanged.connect(self._push)
            row.addWidget(QtWidgets.QLabel("Completes by"))
            row.addWidget(self.cond, 2)
            row.addWidget(self.target, 3)
            row.addWidget(self.count, 1)
            lay.addLayout(row)

            self._load()

        def _load(self):
            self._loading = True
            s = self.stage
            self.obj.setText(str(s.get("objective", "")))
            self.journal.setPlainText(str(s.get("journal", "")))
            self.fin.setChecked(bool(s.get("finishes")))
            cond = s.get("condition") or {}
            idx = self.cond.findData(str(cond.get("kind", "none")))
            self.cond.setCurrentIndex(idx if idx >= 0 else 0)
            self.target.setText(str(cond.get("target", "")))
            try:
                self.count.setValue(max(1, int(cond.get("count", 1))))
            except (TypeError, ValueError):
                self.count.setValue(1)
            self._sync()
            self._loading = False

        def _sync(self):
            kind = self.cond.currentData() or "none"
            self.target.setPlaceholderText(GOAL_TARGET_HINT.get(kind, ""))
            self.target.setEnabled(kind != "none")
            self.count.setEnabled(kind in ("kill", "fetch"))
            idx = self.stage.get("index", 0)
            obj = self.obj.text().strip() or "(stage)"
            self.title.setText(f"Stage {idx} — {obj}")

        def _push(self, *_):
            if self._loading:
                return
            s = self.stage
            s["objective"] = self.obj.text().strip()
            s["journal"] = self.journal.toPlainText().strip()
            s["finishes"] = self.fin.isChecked()
            s["condition"] = {"kind": self.cond.currentData() or "none",
                              "target": self.target.text().strip(),
                              "count": self.count.value()}
            self._sync()
            self.changed.emit()

    # ===================================================================
    # Quest summary card (left rail of the editor)
    # ===================================================================
    class _QuestCard(_Card):
        clicked_idx = Signal(int)

        def __init__(self, quest, index):
            super().__init__(selectable=True)
            self.index = index
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(12, 10, 12, 10)
            lay.setSpacing(3)
            name = QtWidgets.QLabel(quest.get("name") or quest.get("id")
                                    or "(unnamed)")
            nf = name.font(); nf.setBold(True); nf.setPointSizeF(nf.pointSizeF() + 0.5)
            name.setFont(nf)
            lay.addWidget(name)
            sub = QtWidgets.QLabel(goal_summary(quest))
            sub.setStyleSheet("color:#9a9aa6;")
            lay.addWidget(sub)
            giver = quest.get("giver", "")
            rw = quest.get("rewards", {}) or {}
            bits = []
            if giver:
                bits.append(f"👤 {giver}")
            if rw.get("gold"):
                bits.append(f"🪙 {rw['gold']}")
            if quest.get("xp"):
                bits.append(f"✨ {quest['xp']}")
            if bits:
                meta = QtWidgets.QLabel("   ".join(bits))
                meta.setStyleSheet("color:#7f7f8a;")
                lay.addWidget(meta)
            self.clicked.connect(lambda: self.clicked_idx.emit(self.index))

    # ===================================================================
    # The big editor dialog
    # ===================================================================
    class QuestEditorDialog(QtWidgets.QDialog):
        def __init__(self, thing, parent=None):
            super().__init__(parent)
            self.thing = thing
            self.editor = _find_editor(self)
            if self.editor is None and parent is not None:
                self.editor = _find_editor(parent)
            # Quests live as human-readable .quest files in the quests/ folder,
            # not on the GameSettings entity. Load them from there (migrating any
            # quests still authored on an old map on first open), edit in memory,
            # and write the folder back on Done.
            self._quest_list = load_quests_for_editor(thing)
            self._cur = -1
            self._stage_cards = []
            self.setWindowTitle("Quest Editor")
            self.setStyleSheet(STYLE)
            self.resize(1040, 720)
            self.setSizeGripEnabled(True)
            self._build()
            self._reload()

        def _quests(self):
            return self._quest_list

        # ---- layout -------------------------------------------------------
        def _build(self):
            root = QtWidgets.QVBoxLayout(self)
            root.setContentsMargins(14, 14, 14, 14)
            root.setSpacing(10)

            header = QtWidgets.QHBoxLayout()
            title = QtWidgets.QLabel("📜  Quest Editor")
            hf = title.font(); hf.setBold(True); hf.setPointSizeF(hf.pointSizeF() + 4)
            title.setFont(hf)
            header.addWidget(title)
            header.addStretch(1)
            wiz = QtWidgets.QPushButton("✨  New Quest Wizard")
            wiz.setObjectName("primary")
            wiz.clicked.connect(self.launch_wizard)
            header.addWidget(wiz)
            root.addLayout(header)

            body = QtWidgets.QHBoxLayout()
            body.setSpacing(12)

            # left rail: quest cards
            left = QtWidgets.QVBoxLayout()
            left.addWidget(QtWidgets.QLabel("Quests in this map"))
            self.card_scroll = QtWidgets.QScrollArea()
            self.card_scroll.setWidgetResizable(True)
            self.card_host = QtWidgets.QWidget()
            self.card_col = QtWidgets.QVBoxLayout(self.card_host)
            self.card_col.setSpacing(8)
            self.card_col.addStretch(1)
            self.card_scroll.setWidget(self.card_host)
            self.card_scroll.setMinimumWidth(300)
            left.addWidget(self.card_scroll, 1)
            lb = QtWidgets.QHBoxLayout()
            add = QtWidgets.QPushButton("＋ Add")
            dup = QtWidgets.QPushButton("⧉ Duplicate")
            rem = QtWidgets.QPushButton("🗑 Remove"); rem.setObjectName("danger")
            add.clicked.connect(self._add)
            dup.clicked.connect(self._duplicate)
            rem.clicked.connect(self._remove)
            for b in (add, dup, rem):
                lb.addWidget(b)
            left.addLayout(lb)
            lw = QtWidgets.QWidget(); lw.setLayout(left)
            lw.setMaximumWidth(340)
            body.addWidget(lw)

            # right: detail
            self.detail_scroll = QtWidgets.QScrollArea()
            self.detail_scroll.setWidgetResizable(True)
            self.detail = QtWidgets.QWidget()
            self._build_detail(self.detail)
            self.detail_scroll.setWidget(self.detail)
            body.addWidget(self.detail_scroll, 1)
            root.addLayout(body, 1)

            foot = QtWidgets.QHBoxLayout()
            hint = QtWidgets.QLabel("Changes save with the map. Enter Play mode "
                                    "to test — stages auto-advance when their "
                                    "condition is met.")
            hint.setStyleSheet("color:#8a8a94;")
            foot.addWidget(hint)
            foot.addStretch(1)
            done = QtWidgets.QPushButton("Done")
            done.clicked.connect(self.accept)
            foot.addWidget(done)
            root.addLayout(foot)

        def _build_detail(self, host):
            v = QtWidgets.QVBoxLayout(host)
            v.setContentsMargins(6, 2, 6, 6)
            v.setSpacing(10)

            self.empty = QtWidgets.QLabel(
                "Select a quest, or press ✨ New Quest Wizard to build one.")
            self.empty.setAlignment(Qt.AlignCenter)
            self.empty.setStyleSheet("color:#8a8a94; padding:40px;")
            v.addWidget(self.empty)

            self.form_host = QtWidgets.QWidget()
            fv = QtWidgets.QVBoxLayout(self.form_host)
            fv.setContentsMargins(0, 0, 0, 0)
            fv.setSpacing(10)

            ident = QtWidgets.QGroupBox("Identity")
            gf = QtWidgets.QFormLayout(ident)
            self.f_name = QtWidgets.QLineEdit()
            self.f_id = QtWidgets.QLineEdit()
            self.f_giver = QtWidgets.QComboBox(); self.f_giver.setEditable(True)
            self.f_faction = QtWidgets.QLineEdit()
            self.f_desc = QtWidgets.QPlainTextEdit()
            self.f_desc.setMaximumHeight(70)
            self.f_desc.setPlaceholderText("Opening / summary paragraph…")
            for w in (self.f_name, self.f_id, self.f_faction):
                w.editingFinished.connect(self._write)
            self.f_giver.currentTextChanged.connect(lambda *_: self._write())
            self.f_desc.textChanged.connect(self._write)
            gf.addRow("Name", self.f_name)
            gf.addRow("Id", self.f_id)
            gf.addRow("Giver", self.f_giver)
            gf.addRow("Faction / guild", self.f_faction)
            gf.addRow("Summary", self.f_desc)
            fv.addWidget(ident)

            reward = QtWidgets.QGroupBox("Rewards")
            rf = QtWidgets.QFormLayout(reward)
            self.f_gold = QtWidgets.QSpinBox(); self.f_gold.setRange(0, 1000000)
            self.f_xp = QtWidgets.QSpinBox(); self.f_xp.setRange(0, 1000000)
            self.f_items = QtWidgets.QLineEdit()
            self.f_items.setPlaceholderText("item_id,qty ; item_id,qty")
            self.f_rep = QtWidgets.QLineEdit()
            self.f_rep.setPlaceholderText("guild_id,amount")
            self.f_gold.valueChanged.connect(self._write)
            self.f_xp.valueChanged.connect(self._write)
            self.f_items.editingFinished.connect(self._write)
            self.f_rep.editingFinished.connect(self._write)
            rf.addRow("Gold", self.f_gold)
            rf.addRow("XP", self.f_xp)
            rf.addRow("Items", self.f_items)
            rf.addRow("Reputation", self.f_rep)
            fv.addWidget(reward)

            stbox = QtWidgets.QGroupBox("Stages")
            sv = QtWidgets.QVBoxLayout(stbox)
            self.stage_col = QtWidgets.QVBoxLayout()
            self.stage_col.setSpacing(8)
            sv.addLayout(self.stage_col)
            addst = QtWidgets.QPushButton("＋ Add stage")
            addst.clicked.connect(self._add_stage)
            sv.addWidget(addst, 0, Qt.AlignLeft)
            fv.addWidget(stbox)
            fv.addStretch(1)

            v.addWidget(self.form_host)
            v.addStretch(1)
            self.form_host.setVisible(False)

        # ---- quest list ---------------------------------------------------
        def _reload(self):
            # clear cards
            while self.card_col.count() > 1:
                item = self.card_col.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()
            quests = self._quests()
            for i, q in enumerate(quests):
                card = _QuestCard(q, i)
                card.clicked_idx.connect(self._select)
                self.card_col.insertWidget(self.card_col.count() - 1, card)
            if quests:
                self._select(min(self._cur, len(quests) - 1) if self._cur >= 0 else 0)
            else:
                self._cur = -1
                self._show_detail(False)
            self._restyle_cards()

        def _restyle_cards(self):
            for i in range(self.card_col.count() - 1):
                w = self.card_col.itemAt(i).widget()
                if isinstance(w, _QuestCard):
                    w.set_selected(w.index == self._cur)

        def _refresh_giver_choices(self, combo):
            cur = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("")
            # Offer each candidate's giver value — a name when unique, an entity
            # id (UUID) when the name is shared — so a giver always resolves to
            # exactly one NPC. An author can still type a name or paste an id.
            combo.setToolTip("NPC who gives this quest — a name, role, or an "
                             "entity id (UUID) to target one specific NPC when "
                             "several share a name.")
            seen = set()
            for _label, value in _npc_giver_entries(self.editor):
                if value in seen:
                    continue
                seen.add(value)
                combo.addItem(value)
            combo.setEditText(cur)
            combo.blockSignals(False)

        def _show_detail(self, on):
            self.empty.setVisible(not on)
            self.form_host.setVisible(on)

        def _select(self, index):
            quests = self._quests()
            if not (0 <= index < len(quests)):
                self._cur = -1
                self._show_detail(False)
                return
            self._cur = index
            q = quests[index]
            self._loading = True
            self._refresh_giver_choices(self.f_giver)
            self.f_name.setText(str(q.get("name", "")))
            self.f_id.setText(str(q.get("id", "")))
            self.f_giver.setEditText(str(q.get("giver", "")))
            self.f_faction.setText(str(q.get("faction", "")))
            self.f_desc.setPlainText(str(q.get("desc", "")))
            rw = q.get("rewards", {}) or {}
            self.f_gold.setValue(int(rw.get("gold", 0) or 0))
            self.f_xp.setValue(int(q.get("xp", 0) or 0))
            self.f_items.setText(" ; ".join(f"{i[0]},{i[1]}"
                                            for i in rw.get("items", [])))
            rep = rw.get("rep")
            self.f_rep.setText(f"{rep[0]},{rep[1]}" if rep else "")
            self._reload_stages(q)
            self._loading = False
            self._show_detail(True)
            self._restyle_cards()

        def _write(self, *_):
            if getattr(self, "_loading", False):
                return
            quests = self._quests()
            if not (0 <= self._cur < len(quests)):
                return
            q = quests[self._cur]
            q["name"] = self.f_name.text().strip()
            q["id"] = self.f_id.text().strip()
            # Persist the giver by stable entity id (UUID) so a later rename of
            # the NPC does not orphan the quest.
            q["giver"] = _resolve_entity_ref(self.editor, self.f_giver.currentText().strip())
            q["faction"] = self.f_faction.text().strip()
            q["desc"] = self.f_desc.toPlainText().strip()
            q["xp"] = self.f_xp.value()
            rewards = {"gold": self.f_gold.value()}
            items = []
            for chunk in self.f_items.text().replace("\n", ";").split(";"):
                chunk = chunk.strip()
                if not chunk:
                    continue
                if "," in chunk:
                    iid, qty = chunk.split(",", 1)
                    try:
                        items.append([iid.strip(), int(qty.strip())])
                    except ValueError:
                        items.append([iid.strip(), 1])
                else:
                    items.append([chunk, 1])
            if items:
                rewards["items"] = items
            rep = self.f_rep.text().strip()
            if "," in rep:
                g, a = rep.split(",", 1)
                try:
                    rewards["rep"] = [g.strip(), int(a.strip())]
                except ValueError:
                    pass
            q["rewards"] = rewards
            # refresh the left card in place
            i = self._cur
            w = self.card_col.itemAt(i).widget() if i < self.card_col.count() - 1 else None
            # simplest: rebuild the card rail labels lazily
            self._refresh_card_text(i, q)

        def _refresh_card_text(self, i, q):
            if not (0 <= i < self.card_col.count() - 1):
                return
            old = self.card_col.itemAt(i).widget()
            if not isinstance(old, _QuestCard):
                return
            card = _QuestCard(q, i)
            card.clicked_idx.connect(self._select)
            card.set_selected(i == self._cur)
            self.card_col.insertWidget(i, card)
            self.card_col.removeWidget(old)
            old.deleteLater()

        # ---- stages -------------------------------------------------------
        def _reload_stages(self, q):
            for c in self._stage_cards:
                c.setParent(None)
                c.deleteLater()
            self._stage_cards = []
            stages = q.get("stages")
            if not isinstance(stages, list):
                stages = []; q["stages"] = stages
            npc = _npc_names(self.editor)
            for s in stages:
                card = _StageCard(s, npc)
                card.changed.connect(lambda i=self._cur: self._on_stage_changed(i))
                card.removed.connect(lambda st=s: self._remove_stage(st))
                self.stage_col.addWidget(card)
                self._stage_cards.append(card)

        def _on_stage_changed(self, quest_index):
            quests = self._quests()
            if 0 <= quest_index < len(quests):
                self._refresh_card_text(quest_index, quests[quest_index])

        def _add_stage(self):
            quests = self._quests()
            if not (0 <= self._cur < len(quests)):
                return
            q = quests[self._cur]
            stages = q.setdefault("stages", [])
            nxt = (max((s.get("index", 0) for s in stages), default=-10) + 10) \
                if stages else 0
            stages.append({"index": nxt, "journal": "", "objective": "",
                           "finishes": False,
                           "condition": {"kind": "none", "target": "", "count": 1}})
            self._reload_stages(q)

        def _remove_stage(self, stage):
            quests = self._quests()
            if not (0 <= self._cur < len(quests)):
                return
            q = quests[self._cur]
            stages = q.get("stages", [])
            if stage in stages:
                stages.remove(stage)
            self._reload_stages(q)

        # ---- quest add/remove --------------------------------------------
        def _add(self):
            quests = self._quests()
            quests.append(new_quest_dict(quests))
            self._cur = len(quests) - 1
            self._reload()

        def _duplicate(self):
            import copy
            quests = self._quests()
            if not (0 <= self._cur < len(quests)):
                return
            clone = copy.deepcopy(quests[self._cur])
            ids = {q.get("id") for q in quests}
            base = clone.get("id", "quest")
            nid = f"{base}_copy"; i = 2
            while nid in ids:
                nid = f"{base}_copy{i}"; i += 1
            clone["id"] = nid
            clone["name"] = f"{clone.get('name','Quest')} (copy)"
            quests.append(clone)
            self._cur = len(quests) - 1
            self._reload()

        def _remove(self):
            quests = self._quests()
            if not (0 <= self._cur < len(quests)):
                return
            del quests[self._cur]
            self._cur = min(self._cur, len(quests) - 1)
            self._reload()

        # ---- wizard -------------------------------------------------------
        def launch_wizard(self):
            wiz = QuestWizard(self._quests(), self.editor, parent=self)
            wiz.setStyleSheet(self.styleSheet() + wiz.styleSheet())
            if wiz.exec_() == QtWidgets.QDialog.Accepted and wiz.result_quest:
                quests = self._quests()
                quests.append(wiz.result_quest)
                self._cur = len(quests) - 1
                self._reload()

        def accept(self):
            save_quests_from_editor(self.thing, self._quest_list)
            if self.editor is not None:
                _refresh_editor(self.editor)
            super().accept()

    _CLASSES = {
        "QuestEditorDialog": QuestEditorDialog,
        "QuestWizard": QuestWizard,
    }
    return _CLASSES


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------
def open_quest_editor(thing, parent=None, start_wizard=False):
    """Open the large card-based quest editor for *thing* (GameSettings)."""
    cls = _classes()
    if not cls:
        return None
    dlg = cls["QuestEditorDialog"](thing, parent)
    if start_wizard:
        dlg.show()
        dlg.launch_wizard()
    dlg.exec_()
    return dlg


def make_quests_launcher(thing):
    """Compact panel for the GameSettings *Quests* property tab: a live summary
    of the map's quests plus buttons that open the full editor / wizard."""
    try:
        QtWidgets, QtCore, _QtGui = _qt()
    except Exception:
        return None

    class Launcher(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.thing = thing
            v = QtWidgets.QVBoxLayout(self)
            v.setSpacing(10)

            intro = QtWidgets.QLabel(
                "Quests are a first-class feature, stored as human-readable "
                ".quest files in the project's quests/ folder (not on this "
                "entity). Author them in the full editor: give each quest a "
                "giver and the giver automatically offers it in play, plus "
                "staged journal text and a completion goal (talk / fetch / kill "
                "/ visit). The wizard can even build the markers and dialogue.")
            intro.setWordWrap(True)
            intro.setStyleSheet("color:#9aa;")
            v.addWidget(intro)

            self.summary = QtWidgets.QLabel()
            self.summary.setWordWrap(True)
            self.summary.setStyleSheet(
                "background:#24242c; border:1px solid #3a3a44; border-radius:6px;"
                "padding:10px; color:#c8c8d0;")
            v.addWidget(self.summary)

            row = QtWidgets.QHBoxLayout()
            openb = QtWidgets.QPushButton("📜  Open Quest Editor")
            wizb = QtWidgets.QPushButton("✨  New Quest Wizard")
            try:
                openb.setStyleSheet(
                    "background:#34343f;border:1px solid #55555f;border-radius:5px;"
                    "padding:8px 14px;")
                wizb.setStyleSheet(
                    "background:#2f7d4f;border:1px solid #3ea56a;border-radius:5px;"
                    "padding:8px 14px;font-weight:bold;color:#fff;")
            except Exception:
                pass
            openb.clicked.connect(self._open)
            wizb.clicked.connect(self._wizard)
            row.addWidget(openb)
            row.addWidget(wizb)
            row.addStretch(1)
            v.addLayout(row)
            v.addStretch(1)
            self._refresh()

        def _quests(self):
            # Summary reflects the .quest files on disk; fall back to any legacy
            # on-entity quests (shown until the editor is opened and migrates them).
            try:
                from .rpg import quest_files
                defs = quest_files.load_quest_defs()
                if defs:
                    return defs
            except Exception:
                pass
            q = self.thing.properties.get("quests")
            return q if isinstance(q, list) else []

        def _refresh(self):
            quests = self._quests()
            if not quests:
                self.summary.setText("<i>No quests yet.</i>")
                return
            lines = [f"<b>{len(quests)} quest(s):</b>"]
            for q in quests[:12]:
                nm = q.get("name") or q.get("id") or "(unnamed)"
                lines.append(f"• {nm} — {goal_summary(q)}")
            if len(quests) > 12:
                lines.append(f"… and {len(quests) - 12} more")
            self.summary.setText("<br>".join(lines))

        def _open(self):
            open_quest_editor(self.thing, parent=self.window())
            self._refresh()

        def _wizard(self):
            open_quest_editor(self.thing, parent=self.window(), start_wizard=True)
            self._refresh()

    return Launcher()
