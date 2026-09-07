"""
The editor's window onto the simulation — construct and *observe*, don't script.

Three surfaces, all built on the same live :class:`~game.sim.director.Director`
the game itself runs, so what a designer sees is the simulation rather than a
report about it:

* :func:`make_simulation_tab` — a per-entity property tab: what this actor
  knows, what it currently intends and **why**, plus the levers to change any of
  it while the game is running.
* :func:`open_world_window` — the World Simulation window: a live actor list, a
  causal event history, and a **Simulate Event** tool that injects an action and
  lets the designer watch the world answer.
* :func:`make_object_tab` — ownership and production for world objects, with a
  live read of what a producer has made and who it belongs to.

Every Qt import is local and every panel degrades to a plain label if PyQt5 is
missing, exactly like :mod:`game.editor_ui` — so a headless or player process
never pulls in Qt.
"""

from __future__ import annotations

from . import editor_ui
from .sim import crime as sim_crime
from .sim import knowledge as sim_knowledge
from .sim import ownership as sim_own
from .sim import production as sim_prod
from .sim.director import actor_key
from .sim.events import EVENT_KINDS

#: How often the live panels re-read the simulation, in milliseconds. Slow
#: enough to be free, fast enough that a designer sees cause and effect.
REFRESH_MS = 500


def _qt():
    """The Qt widget/core modules — but only when there is a live QApplication.

    "Headless" is not just "PyQt5 is missing": Qt can be importable in a process
    that never created a QApplication (a test runner, a build tool), and
    constructing a widget there aborts the process rather than raising. Treating
    that as unavailable is what makes the documented behaviour — a panel or
    wizard degrades instead of crashing — actually true."""
    from PyQt5 import QtWidgets, QtCore
    if QtWidgets.QApplication.instance() is None:
        raise RuntimeError("no QApplication: this process is headless")
    return QtWidgets, QtCore


def _unavailable(text="Qt is not available in this process."):
    try:
        QtWidgets, _ = _qt()
    except Exception:
        return None
    return QtWidgets.QLabel(text)


# ---------------------------------------------------------------------------
# Finding the live simulation
# ---------------------------------------------------------------------------
def active_session(main_window=None):
    """The live :class:`~game.runtime.MiniwindSession`, or None outside Play.

    Walks the same path the Session menu uses (``view_3d.logic_thread._miniwind``)
    and falls back to the module-level current session so a property tab that
    has no handle on the main window still finds it."""
    if main_window is not None:
        view = getattr(main_window, "view_3d", None)
        lt = getattr(view, "logic_thread", None) if view is not None else None
        session = getattr(lt, "_miniwind", None) if lt is not None else None
        if session is not None:
            return session
    try:
        from . import runtime
        return runtime._current_session
    except Exception:
        return None


def _director(main_window=None):
    session = active_session(main_window)
    return getattr(session, "director", None) if session is not None else None


def _main_window():
    """Best-effort handle on the editor main window (for the world window)."""
    try:
        from PyQt5 import QtWidgets
        for w in QtWidgets.QApplication.topLevelWidgets():
            if w.__class__.__name__ in ("MainWindow", "EditorMainWindow"):
                return w
    except Exception:
        pass
    return None


# ===========================================================================
# Per-entity: the Simulation tab (an NPC's knowledge, intents and reasoning)
# ===========================================================================
def make_simulation_tab(thing):
    """Property tab: this actor's live simulation state, editable during Play."""
    try:
        QtWidgets, QtCore = _qt()
    except Exception:  # pragma: no cover - headless
        return None
    return editor_ui.apply_dark(_SimulationTab(thing, QtWidgets, QtCore))


def _SimulationTab(thing, QtWidgets, QtCore):
    class Tab(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.thing = thing
            layout = QtWidgets.QVBoxLayout(self)

            self.status = QtWidgets.QLabel()
            self.status.setWordWrap(True)
            layout.addWidget(self.status)

            # --- Why: the decision's own explanation -----------------------
            box = QtWidgets.QGroupBox("Why it is doing that")
            bl = QtWidgets.QVBoxLayout(box)
            self.why = QtWidgets.QLabel("—")
            self.why.setWordWrap(True)
            self.why.setStyleSheet("font-weight:bold;")
            bl.addWidget(self.why)
            self.intents = QtWidgets.QTableWidget(0, 3)
            self.intents.setHorizontalHeaderLabels(["Pri", "Intent", "Reason"])
            self.intents.horizontalHeader().setStretchLastSection(True)
            self.intents.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            editor_ui.style_table(self.intents, max_rows=6)
            bl.addWidget(self.intents)
            layout.addWidget(box)

            # --- Knowledge -------------------------------------------------
            kbox = QtWidgets.QGroupBox("What it knows")
            kl = QtWidgets.QVBoxLayout(kbox)

            # Actions above the list, so they stay reachable when it is empty —
            # the same rule the I/O editor and the other MiniWind tabs follow.
            teach = QtWidgets.QPushButton("Tell it about an event…")
            teach.setToolTip("Hand this actor a belief about something in the "
                             "world history and watch what it decides to do.")
            teach.clicked.connect(self._teach)
            forget = QtWidgets.QPushButton("Wipe its memory")
            forget.clicked.connect(self._forget)
            kl.addLayout(editor_ui.action_row(QtWidgets, teach, forget))

            self.knowledge = QtWidgets.QTableWidget(0, 4)
            self.knowledge.setHorizontalHeaderLabels(
                ["Event", "Source", "Sure", "Day"])
            self.knowledge.horizontalHeader().setStretchLastSection(True)
            self.knowledge.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            editor_ui.style_table(self.knowledge, max_rows=8)
            kl.addWidget(self.knowledge)
            layout.addWidget(kbox)

            # --- Standing --------------------------------------------------
            sbox = QtWidgets.QGroupBox("Standing toward the player")
            sl = QtWidgets.QFormLayout(sbox)
            self.disp = QtWidgets.QLabel("—")
            self.flags = QtWidgets.QLabel("—")
            self.memlog = QtWidgets.QLabel("—")
            self.memlog.setWordWrap(True)
            sl.addRow("Disposition", self.disp)
            sl.addRow("Flags", self.flags)
            sl.addRow("Remembers", self.memlog)
            layout.addWidget(sbox)

            layout.addStretch(1)

            self._timer = QtCore.QTimer(self)
            self._timer.timeout.connect(self._refresh)
            self._timer.start(REFRESH_MS)
            self._refresh()

        # -- helpers ---------------------------------------------------------
        def _session(self):
            return active_session(_main_window())

        def _refresh(self):
            session = self._session()
            director = getattr(session, "director", None) if session else None
            if director is None:
                self.status.setText(
                    "Not playing. Enter Play mode to watch this actor think — "
                    "its knowledge, its ranked intents and the reason behind "
                    "the one it is acting on all update live.")
                return
            key = actor_key(self.thing)
            self.status.setText(f"Live · identity <b>{key or '?'}</b>")
            try:
                self.why.setText(director.why(self.thing))
            except Exception:
                self.why.setText("—")
            self._fill_intents(director)
            self._fill_knowledge(director)
            self._fill_standing(session)

        def _fill_intents(self, director):
            try:
                intents = director.intents(self.thing)
            except Exception:
                intents = []
            self.intents.setRowCount(len(intents))
            for r, it in enumerate(intents):
                for c, text in enumerate((str(it.priority), it.label, it.reason)):
                    self.intents.setItem(r, c, QtWidgets.QTableWidgetItem(text))
            editor_ui.fit_to_rows(self.intents, max_rows=6)

        def _fill_knowledge(self, director):
            store = getattr(director, "store", None)
            facts = sim_knowledge.facts(store, actor_key(self.thing))
            facts.sort(key=lambda f: -float(f.get("certainty", 0.0)))
            self.knowledge.setRowCount(len(facts))
            for r, f in enumerate(facts):
                from .sim.events import WorldEvent
                ev = WorldEvent(f.get("kind", ""),
                                actor_name=f.get("actor_name", ""),
                                target_name=f.get("target_name", ""),
                                data={"item": f.get("item", "")})
                cells = (ev.describe(),
                         sim_knowledge.SOURCE_PHRASE.get(f.get("source", ""),
                                                         str(f.get("source", ""))),
                         f"{int(float(f.get('certainty', 0)) * 100)}%",
                         str(f.get("day", "")))
                for c, text in enumerate(cells):
                    self.knowledge.setItem(r, c, QtWidgets.QTableWidgetItem(text))
            editor_ui.fit_to_rows(self.knowledge, max_rows=8)

        def _fill_standing(self, session):
            try:
                from .rpg import disposition as disp
                s = disp.summary(session.game.character, self.thing.properties,
                                 session.store)
            except Exception:
                return
            self.disp.setText(f"{s['disposition']} ({s['tier']})")
            marks = [k for k in ("wronged", "befriended") if s.get(k)]
            self.flags.setText(", ".join(marks) or "none")
            self.memlog.setText("; ".join(s.get("log", [])[-4:]) or "nothing yet")

        # -- live edits ------------------------------------------------------
        def _teach(self):
            director = _director(_main_window())
            if director is None:
                return
            events = director.bus.recent(limit=40)
            if not events:
                QtWidgets.QMessageBox.information(
                    self, "Tell it about an event",
                    "Nothing has happened yet. Use the World Simulation "
                    "window's Simulate Event tool to make something happen.")
                return
            labels = [f"#{e.id} [{e.timestamp()}] {e.describe()}" for e in events]
            choice, ok = QtWidgets.QInputDialog.getItem(
                self, "Tell it about an event",
                "Which event should this actor come to believe?", labels, 0, False)
            if not ok:
                return
            event = events[labels.index(choice)]
            fact = sim_knowledge.fact_from_event(event, 0.8,
                                                 sim_knowledge.SOURCE_TOLD)
            if event.kind == "theft":
                fact["value"] = int(event.data.get("value", 0) or 0)
            sim_knowledge.learn(director.store, actor_key(self.thing), fact)
            director.invalidate(self.thing)
            self._refresh()

        def _forget(self):
            director = _director(_main_window())
            if director is None:
                return
            sim_knowledge.forget_all(director.store, actor_key(self.thing))
            director.invalidate(self.thing)
            self._refresh()

    return Tab()


# ===========================================================================
# Per-object: ownership & production
# ===========================================================================
def make_object_tab(thing):
    """Property tab: who owns this object and what it makes."""
    try:
        QtWidgets, QtCore = _qt()
    except Exception:  # pragma: no cover - headless
        return None
    return editor_ui.apply_dark(_ObjectTab(thing, QtWidgets, QtCore))


def _ObjectTab(thing, QtWidgets, QtCore):
    class Tab(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.thing = thing
            layout = QtWidgets.QVBoxLayout(self)
            layout.addWidget(QtWidgets.QLabel(
                "<b>Ownership</b> is the whole of MiniWind's property model. Give "
                "this a owner and taking it becomes a theft — which needs a "
                "witness, produces a bounty when word reaches the watch, and is "
                "remembered by the owner. Nothing here is authored per object."))

            form = QtWidgets.QFormLayout()
            self.owner = QtWidgets.QComboBox()
            self.owner.setEditable(True)
            self.owner.currentTextChanged.connect(self._write)
            form.addRow("Owner", self.owner)
            self.owner_faction = QtWidgets.QComboBox()
            self.owner_faction.setEditable(True)
            self.owner_faction.addItems(["", "villagers", "guards", "bandits",
                                         "cultists", "player"])
            self.owner_faction.currentTextChanged.connect(self._write)
            form.addRow("Owned by faction", self.owner_faction)
            layout.addLayout(form)

            pbox = QtWidgets.QGroupBox("Production")
            pl = QtWidgets.QFormLayout(pbox)
            self.produces = QtWidgets.QLineEdit()
            self.produces.setPlaceholderText("item id, e.g. milk — blank for none")
            self.produces.editingFinished.connect(self._write)
            pl.addRow("Produces", self.produces)
            self.every = QtWidgets.QDoubleSpinBox()
            self.every.setRange(0.05, 1000.0)
            self.every.setSuffix(" game hours")
            self.every.valueChanged.connect(self._write)
            pl.addRow("Every", self.every)
            self.into = QtWidgets.QComboBox()
            self.into.addItems(["world", "self"])
            self.into.currentTextChanged.connect(self._write)
            pl.addRow("Yield goes", self.into)
            self.live = QtWidgets.QLabel("—")
            self.live.setWordWrap(True)
            pl.addRow("Right now", self.live)
            layout.addWidget(pbox)
            layout.addStretch(1)

            self._timer = QtCore.QTimer(self)
            self._timer.timeout.connect(self._refresh_live)
            self._timer.start(REFRESH_MS)
            self._loading = True
            self._reload()
            self._loading = False

        def _reload(self):
            p = self.thing.properties
            self.owner.clear()
            self.owner.addItems([""] + self._npc_names())
            self.owner.setCurrentText(sim_own.owner_of(p))
            self.owner_faction.setCurrentText(sim_own.owner_faction_of(p))
            self.produces.setText(str(p.get("produces", "") or ""))
            self.every.setValue(sim_prod.interval_of(p))
            self.into.setCurrentText(str(p.get("produce_into",
                                                sim_prod.INTO_WORLD)))
            self._refresh_live()

        def _npc_names(self):
            """Every NPC in the open map, so an owner is picked, not typed."""
            names = set()
            win = _main_window()
            things = getattr(getattr(win, "editor_state", None), "things", None) \
                or getattr(win, "things", None) or []
            for t in things:
                props = getattr(t, "properties", {}) or {}
                if str(props.get("type", "")).lower() in ("npc", "creature"):
                    key = actor_key(t)
                    if key:
                        names.add(key)
            return sorted(names)

        def _write(self, *_):
            if getattr(self, "_loading", False):
                return
            p = self.thing.properties
            sim_own.set_owner(p, self.owner.currentText().strip(),
                              self.owner.currentText().strip(),
                              self.owner_faction.currentText().strip())
            produces = self.produces.text().strip()
            if produces:
                p["produces"] = produces
                p["produce_every_hours"] = float(self.every.value())
                p["produce_into"] = self.into.currentText()
            else:
                p.pop("produces", None)

        def _refresh_live(self):
            p = self.thing.properties
            bits = [sim_own.describe(p)]
            if sim_prod.is_producer(p):
                bits.append(sim_prod.describe(p))
            self.live.setText(" · ".join(bits))

    return Tab()


# ===========================================================================
# The World Simulation window
# ===========================================================================
_world_window = None


def open_world_window(main_window=None):
    """Open (or raise) the World Simulation window."""
    global _world_window
    try:
        QtWidgets, QtCore = _qt()
    except Exception:  # pragma: no cover - headless
        return None
    parent = main_window or _main_window()
    if _world_window is None:
        _world_window = editor_ui.apply_dark(_WorldWindow(parent, QtWidgets, QtCore))
    _world_window.show()
    _world_window.raise_()
    _world_window.activateWindow()
    return _world_window


def _WorldWindow(parent, QtWidgets, QtCore):
    class Window(QtWidgets.QWidget):
        def __init__(self):
            super().__init__(parent)
            self.setWindowFlags(QtCore.Qt.Window)
            self.setWindowTitle("MiniWind — World Simulation")
            self.resize(940, 620)
            layout = QtWidgets.QVBoxLayout(self)
            self.banner = QtWidgets.QLabel()
            self.banner.setWordWrap(True)
            layout.addWidget(self.banner)
            tabs = QtWidgets.QTabWidget()
            tabs.addTab(self._actors_tab(), "Actors")
            tabs.addTab(self._history_tab(), "World History")
            tabs.addTab(self._inject_tab(), "Simulate Event")
            layout.addWidget(tabs)
            self._timer = QtCore.QTimer(self)
            self._timer.timeout.connect(self._refresh)
            self._timer.start(REFRESH_MS)
            self._refresh()

        # -- Actors ------------------------------------------------------
        def _actors_tab(self):
            w = QtWidgets.QWidget()
            l = QtWidgets.QVBoxLayout(w)
            l.addWidget(QtWidgets.QLabel(
                "Every living actor, what it is doing, and the reason the "
                "simulation itself gave for it. Select a row and the editor "
                "selects that entity."))
            self.actors = QtWidgets.QTableWidget(0, 5)
            self.actors.setHorizontalHeaderLabels(
                ["Name", "Faction", "State", "Intent", "Why"])
            self.actors.horizontalHeader().setStretchLastSection(True)
            self.actors.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            self.actors.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
            self.actors.setStyleSheet(editor_ui.TABLE_STYLE)
            self.actors.setAlternatingRowColors(True)
            self.actors.verticalHeader().setVisible(False)
            self.actors.itemSelectionChanged.connect(self._select_actor)
            l.addWidget(self.actors)
            return w

        def _select_actor(self):
            row = self.actors.currentRow()
            thing = self._actor_rows[row] if 0 <= row < len(self._actor_rows) else None
            win = parent or _main_window()
            if thing is None or win is None:
                return
            for method in ("select_thing", "select_entity", "set_selected_thing"):
                fn = getattr(win, method, None)
                if callable(fn):
                    try:
                        fn(thing)
                        return
                    except Exception:
                        pass

        # -- History -----------------------------------------------------
        def _history_tab(self):
            w = QtWidgets.QWidget()
            l = QtWidgets.QVBoxLayout(w)
            l.addWidget(QtWidgets.QLabel(
                "Everything significant that has happened, and what each event "
                "caused. A crime with no charge against it is still walking "
                "around inside somebody's head."))
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel("Show:"))
            self.filter = QtWidgets.QComboBox()
            self.filter.addItems(["everything", "crimes", "violence",
                                  "unreported crimes", "social"])
            self.filter.currentTextChanged.connect(self._refresh)
            row.addWidget(self.filter)
            row.addStretch(1)
            l.addLayout(row)
            self.history = QtWidgets.QTreeWidget()
            self.history.setHeaderLabels(["When", "What happened"])
            self.history.setColumnWidth(0, 150)
            self.history.setStyleSheet(editor_ui.TABLE_STYLE)
            l.addWidget(self.history)
            return w

        # -- Simulate Event ----------------------------------------------
        def _inject_tab(self):
            w = QtWidgets.QWidget()
            l = QtWidgets.QVBoxLayout(w)
            l.addWidget(QtWidgets.QLabel(
                "Inject an action and watch the world answer. The event goes "
                "through exactly the same pipeline the game uses — perception, "
                "knowledge, interpretation — so what follows is the simulation "
                "reacting, not a preview of it."))
            form = QtWidgets.QFormLayout()
            self.kind = QtWidgets.QComboBox()
            self.kind.addItems(sorted(EVENT_KINDS))
            form.addRow("Event", self.kind)
            self.actor = QtWidgets.QComboBox()
            self.actor.setEditable(True)
            form.addRow("Actor", self.actor)
            self.target = QtWidgets.QComboBox()
            self.target.setEditable(True)
            form.addRow("Target", self.target)
            self.item = QtWidgets.QLineEdit()
            self.item.setPlaceholderText("item id (for theft / gift / produce)")
            form.addRow("Item", self.item)
            self.value = QtWidgets.QSpinBox()
            self.value.setRange(0, 100000)
            form.addRow("Value", self.value)
            self.as_crime = QtWidgets.QComboBox()
            self.as_crime.addItems(["decide from the event kind",
                                    "force: is a crime",
                                    "force: is not a crime"])
            form.addRow("Offence", self.as_crime)
            l.addLayout(form)
            go = QtWidgets.QPushButton("Simulate it")
            go.clicked.connect(self._inject)
            l.addWidget(go)
            self.outcome = QtWidgets.QTextEdit()
            self.outcome.setReadOnly(True)
            l.addWidget(self.outcome)
            return w

        def _inject(self):
            session = active_session(parent or _main_window())
            if session is None:
                self.outcome.setPlainText(
                    "Enter Play mode first — there is no world to react.")
                return
            actors = {actor_key(a): a for a in session._sim_actors()}
            actor = actors.get(self.actor.currentText().strip())
            target = actors.get(self.target.currentText().strip())
            data = {}
            item = self.item.text().strip()
            if item:
                data["item"] = item
                data["item_name"] = item.replace("_", " ").title()
            if self.value.value():
                data["value"] = int(self.value.value())
            choice = self.as_crime.currentIndex()
            if choice == 1:
                data["crime"] = True
            elif choice == 2:
                data["crime"] = False
            try:
                event = session.emit_event(self.kind.currentText(), actor=actor,
                                           target=target, **data)
            except Exception as exc:
                self.outcome.setPlainText(f"Could not simulate: {exc}")
                return
            # Show what the world made of it, immediately.
            session.director.resolve_reports(session._sim_actors())
            lines = [f"#{event.id} {event.describe()}"]
            lines += [f"    ↳ {c}" for c in event.consequences] or \
                     ["    ↳ (no consequences yet)"]
            lines.append("")
            for thing in session._sim_actors():
                try:
                    intents = session.director.intents(thing)
                except Exception:
                    intents = []
                if intents:
                    name = thing.properties.get("display_name", "?")
                    lines.append(f"{name}: {intents[0].label} — {intents[0].reason}")
            self.outcome.setPlainText("\n".join(lines))
            self._refresh()

        # -- refresh -----------------------------------------------------
        def _refresh(self):
            session = active_session(parent or _main_window())
            director = getattr(session, "director", None) if session else None
            if director is None:
                self.banner.setText(
                    "<b>Not playing.</b> The simulation runs during Play mode — "
                    "press Play and this window fills with the live world.")
                self.actors.setRowCount(0)
                self.history.clear()
                self._actor_rows = []
                return
            clock = session.clock
            self.banner.setText(
                f"<b>Live</b> · Day {int(clock.day)} {int(clock.hour):02d}:00 · "
                f"{len(director.bus.history)} events recorded · bounty "
                f"{int(getattr(session.game.character, 'bounty', 0))}")
            self._refresh_actors(session, director)
            self._refresh_history(session, director)

        def _refresh_actors(self, session, director):
            try:
                actors = session._sim_actors()
            except Exception:
                actors = []
            self._actor_rows = actors
            names = sorted({actor_key(a) for a in actors if actor_key(a)})
            for combo in (self.actor, self.target):
                current = combo.currentText()
                combo.blockSignals(True)
                combo.clear()
                combo.addItems([""] + names)
                combo.setCurrentText(current)
                combo.blockSignals(False)
            self.actors.setRowCount(len(actors))
            for r, a in enumerate(actors):
                p = getattr(a, "properties", {}) or {}
                try:
                    intents = director.intents(a)
                except Exception:
                    intents = []
                top = intents[0] if intents else None
                cells = (str(p.get("display_name", "?")),
                         str(p.get("faction", p.get("team", ""))),
                         str(p.get("sched_state", "")),
                         top.label if top else "—",
                         top.reason if top else "nothing it knows demands a response")
                for c, text in enumerate(cells):
                    self.actors.setItem(r, c, QtWidgets.QTableWidgetItem(text))

        def _refresh_history(self, session, director):
            mode = self.filter.currentText()
            kwargs = {"limit": 120}
            if mode == "crimes":
                kwargs["tag"] = "crime"
            elif mode == "violence":
                kwargs["tag"] = "violence"
            elif mode == "social":
                kwargs["tag"] = "social"
            events = director.bus.recent(**kwargs)
            if mode == "unreported crimes":
                events = [e for e in director.bus.recent(limit=200, tag="crime")
                          if not sim_crime.already_reported(director.store, e.id)]
            self.history.clear()
            for ev in events:
                node = QtWidgets.QTreeWidgetItem(
                    [ev.timestamp(), f"#{ev.id} {ev.describe()}"])
                if ev.is_crime and not sim_crime.already_reported(director.store,
                                                                 ev.id):
                    node.setText(1, node.text(1) + "   [unreported]")
                for c in ev.consequences:
                    node.addChild(QtWidgets.QTreeWidgetItem(["", "↳ " + c]))
                self.history.addTopLevelItem(node)
                node.setExpanded(True)

    return Window()
