"""
Debug inspector for NPCs, creatures and monsters (console ``inspect``).

``inspect`` arms Fio's Play Mode actor pick; clicking an actor opens an
:class:`ActorInspectorWindow` on the view's floating window manager (SysMon's
chrome: drag it by the title bar, fold it, close it with [X]). It shows, live:

* who the actor is and where it stands;
* what it is doing (its schedule state) and its whole schedule, the entry in
  effect highlighted with the hours it holds for;
* where it is heading and why (a chase, its schedule, a target, a sound);
* the AI's view of it (:func:`game.mental_state.snapshot`): what it wants
  and the tasks it weighs.

While a window is open, :func:`draw_world_lines` draws a line in the world from
the actor to where it is heading, ending in a ring, in the window's own colour,
and circles the actor so it is clear which window is whose. Several actors can
be inspected at once.

The places in the schedule ("@ work", "@ home", "@ thalen_bed") and the
"Heading to" point are links: clicking one swings the play camera there
(``LogicThread.set_camera_focus``) and puts a beacon on the spot, with the
place's marker sprite, which play otherwise hides. Clicking it again, the
"Back to player" link, walking, HOME or closing the window brings the camera
back.

Debug view: small sans text, not the game's display faces.
"""

from __future__ import annotations

import math
import time

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPen

from engine.floating_windows import FloatingWindow

from .. import fio

#: Colours given to inspector windows in turn (title stripe, line, rings).
COLOURS = (QColor(80, 200, 255), QColor(255, 170, 60), QColor(160, 255, 120),
           QColor(255, 110, 200), QColor(250, 240, 110), QColor(170, 140, 255))

#: How often the text refreshes (s); the world line follows every frame.
REFRESH_SECONDS = 0.25

_TEXT = QColor(220, 220, 220)
_MUTED = QColor(150, 150, 160)
_HEAD = QColor(240, 200, 120)
#: Strength, Endurance and Charisma letters in the inspector.
_STAT_COLOURS = (QColor(230, 120, 100), QColor(120, 200, 120), QColor(150, 170, 255))
_HILITE = QColor(90, 130, 128, 120)
_LINK = QColor(120, 190, 255)
_LINK_HOT = QColor(190, 230, 255)

#: The place the camera is showing for an inspector window, or None:
#: {"pos", "label", "entity", "window", "key"}.
_focus = None

#: Keys that, held, mean the player wants the camera back on them.
_MOVE_KEYS = ("w", "a", "s", "d", "up", "down", "left", "right")

_next_colour = 0


def _fmt_hour(h) -> str:
    try:
        h = float(h) % 24.0
    except (TypeError, ValueError):
        return "?"
    return f"{int(h):02d}:{int(round((h - int(h)) * 60)) % 60:02d}"


def _fmt_pos(p) -> str:
    try:
        return f"{p[0]:.0f}, {p[2]:.0f}"
    except Exception:
        return "?"


def _name(thing) -> str:
    props = getattr(thing, "properties", {}) or {}
    return str(props.get("display_name") or props.get("name")
               or props.get("type") or "actor")


def _monster_state(logic, thing) -> dict:
    states = getattr(getattr(logic, "monster_ai", None), "monster_states", None)
    if isinstance(states, dict):
        return states.get(id(thing), {}) or {}
    return {}


def _actor_by_id(logic, actor_id):
    for t in fio.things(logic):
        if id(t) == actor_id:
            return t
    return None


def destination(session, logic, thing):
    """Where *thing* is heading now: ``(position, why)``, or None.

    In order: a walk target the game set (``_dest``: a chase, an errand, a
    flight), the actor it is fighting, a sound it is investigating, then the
    place its schedule sends it to.
    """
    props = getattr(thing, "properties", {}) or {}
    if props.get("dead"):
        return None
    state = str(props.get("sched_state", "") or "").lower()
    dest = props.get("_dest")
    if isinstance(dest, (list, tuple)) and len(dest) == 3:
        return list(dest), (state or "walking")
    aggro = props.get("_aggro_target")
    if aggro is not None:
        target = _actor_by_id(logic, aggro)
        if target is not None:
            return list(target.pos), f"fighting {_name(target)}"
    mstate = _monster_state(logic, thing)
    if mstate.get("in_sight") and fio.player(logic) is not None:
        p = fio.player(logic).pos
        return [float(p[0]), float(p[1]), float(p[2])], "hunting the player"
    sound = mstate.get("investigating_sound")
    if sound:
        try:
            pos = sound[0]
            return [float(pos[0]), float(pos[1]), float(pos[2])], "investigating a sound"
        except Exception:
            pass
    if session is not None and props.get("schedule"):
        try:
            entry = session._schedule_entry(thing)
        except Exception:
            entry = None
        if entry and entry.get("location"):
            where = session._resolve_location(thing, entry.get("location"))
            if where is not None:
                return list(where), f"schedule: {entry.get('location')}"
    return None


def resolve_place(session, thing, key):
    """``(position, entity or None, label)`` for a schedule place, or None.

    "home" is the NPC's home position; "work" / "market" its workplace (a
    position, or the name of the marker it works at); anything else names a
    marker or thing.
    """
    props = getattr(thing, "properties", {}) or {}
    key = str(key or "").strip()
    low = key.lower()
    if not key or session is None:
        return None
    if low == "home":
        home = props.get("home")
        if isinstance(home, (list, tuple)) and len(home) == 3:
            return list(home), None, "home"
        return None
    target = props.get("work_location") if low in ("work", "market") else key
    if isinstance(target, (list, tuple)) and len(target) == 3:
        return list(target), None, low
    if isinstance(target, str) and target:
        try:
            ent = session._find_named(target)
        except Exception:
            ent = None
        if ent is not None:
            label = target if target == key else f"{low} ({target})"
            return list(ent.pos), ent, label
    return None


def focused_place(logic=None):
    """The place the camera shows for an inspector, or None.

    Dropped as soon as the engine's focus has gone elsewhere (HOME, a new
    session, another tool), so the beacon never outlives the view of it.
    """
    global _focus
    if _focus is not None and logic is not None:
        held = getattr(fio.camera(logic), "camera_focus", None)
        pos = _focus["pos"]
        if held is None or any(abs(float(a) - float(b)) > 1e-3
                               for a, b in zip(held, pos)):
            _focus = None
    return _focus


def show_place(window, key, pos, label, entity=None):
    """Swing the camera to *pos* and mark it; the same place again goes back."""
    global _focus
    logic = window._logic()
    camera = fio.camera(logic)
    if camera is None:
        return
    current = focused_place(logic)
    if current is not None and current["window"] is window and current["key"] == key:
        clear_focus(logic)
        return
    _focus = {"pos": [float(pos[0]), float(pos[1]), float(pos[2])], "label": label,
              "entity": entity, "window": window, "key": key,
              "since": time.monotonic()}
    camera.set_camera_focus(_focus["pos"])


def clear_focus(logic=None, glide=True):
    """Bring the camera back to the player (gliding, or at once)."""
    global _focus
    _focus = None
    camera = fio.camera(logic)
    if camera is not None:
        camera.set_camera_focus(None, glide=glide)


def cancel_focus_on_move(logic, ctx):
    """From the game tick: the player walking brings the camera back."""
    if _focus is None or ctx is None:
        return
    try:
        moving = any(ctx.key_down(k) for k in _MOVE_KEYS)
    except Exception:
        moving = False
    if moving:
        clear_focus(logic)


class ActorInspectorWindow(FloatingWindow):
    """Live debug panel for one actor; see the module docstring."""

    wants_cursor = True
    LINE_H = 14

    def __init__(self, view, thing, x=60, y=60):
        global _next_colour
        super().__init__(f"Inspect: {_name(thing)}", x=x, y=y, width=380,
                         body_height=200)
        self.view = view
        self.thing = thing
        self.colour = COLOURS[_next_colour % len(COLOURS)]
        _next_colour += 1
        self.font = QFont("Arial", 8)
        self.bold = QFont("Arial", 8, QFont.Bold)
        self.title_font = QFont("Arial", 9, QFont.Bold)
        #: Strength / Endurance / Charisma stand out from the rest of the data.
        self.stats_font = QFont("Arial", 11, QFont.Bold)
        self._fm = QFontMetrics(self.font)
        self._rows = []          # [(kind, text, value)] kind: head/row/sched/sched_now
        self._refreshed = 0.0
        self._links = []         # [(QRectF, action)] of the last paint
        #: Whether this window holds the world paused (its own pause request,
        #: so several inspectors and the menus never fight over it). Off: the
        #: world runs while you watch.
        self.paused = False

    # -- data ----------------------------------------------------------------
    def _logic(self):
        return getattr(self.view, "logic_thread", None)

    def _session(self):
        return getattr(self._logic(), "_miniwind", None)

    def refresh(self, now=None):
        now = time.monotonic() if now is None else now
        if self._rows and now - self._refreshed < REFRESH_SECONDS:
            return
        self._refreshed = now
        self._rows = self.build_rows()

    def build_rows(self):
        thing, logic, session = self.thing, self._logic(), self._session()
        props = getattr(thing, "properties", {}) or {}
        rows = []

        def head(text):
            rows.append(("head", text, ""))

        def row(label, value):
            rows.append(("row", label, "" if value is None else str(value)))

        rows.append(("pause", "\u23f8 World paused \u2014 click to run" if self.paused
                     else "\u25b6 World running \u2014 click to pause", ""))
        focus = focused_place(logic)
        if focus is not None and focus["window"] is self:
            rows.append(("back", f"\u25c0 Back to player   (showing {focus['label']})", ""))
        head("Actor")
        if all(props.get(k) is not None for k in ("strength", "endurance", "charisma")):
            # The three rolled stats, larger than the rest (see draw_body).
            rows.append(("stats", "", (props.get("strength"), props.get("endurance"),
                                       props.get("charisma"))))
        row("Type", "{} / {}".format(props.get("type", "?"),
                                     props.get("npc_role") or props.get("creature_role")
                                     or props.get("monster_type") or "-"))
        row("Faction", props.get("faction") or props.get("team") or "-")
        hp = props.get("health")
        row("Health", "dead" if props.get("dead") else ("-" if hp is None else hp))
        row("Position", _fmt_pos(thing.pos))
        if session is not None:
            try:
                mark = session.head_mark(thing)
            except Exception:
                mark = None
            if mark:
                row("Head mark", mark)
            if thing is getattr(session, "_arrest_guard", None) and session._arrest_state:
                row("Arrest", session._arrest_state)
            elif thing in getattr(session, "_arrest_pursuers", ()):
                row("Arrest", "pursuing the player")

        head("Doing")
        row("State", props.get("sched_state") or "-")
        dest = destination(session, logic, thing)
        if dest is not None:
            pos, why = dest
            dx, dz = pos[0] - thing.pos[0], pos[2] - thing.pos[2]
            row("Heading to", f"{_fmt_pos(pos)}  ({math.hypot(dx, dz):.0f} away)")
            row("Because", why)
        else:
            row("Heading to", "nowhere (standing)")

        schedule = props.get("schedule") or []
        if schedule:
            head("Schedule" + (f"   (now {_fmt_hour(session.clock.hour)})"
                               if session is not None else ""))
            current = None
            if session is not None:
                try:
                    current = session._schedule_entry(thing)
                except Exception:
                    current = None
            for entry in sorted(schedule, key=lambda e: float(e.get("hour", 0))):
                text = "{}  {:<14}".format(_fmt_hour(entry.get("hour", 0)),
                                           str(entry.get("state", "?")))
                rows.append(("sched_now" if entry is current else "sched", text,
                             str(entry.get("location", "") or "")))

        snap = None
        try:
            from .. import mental_state
            snap = mental_state.snapshot(thing, monster_state=_monster_state(logic, thing),
                                         session=session)
        except Exception:
            snap = None
        if snap:
            # Shown sections, in order, under the window's own headings: the
            # rest (identity, vitals, anchors) is already above or in the
            # schedule.
            shown = {"Why": "Why", "AI State": "AI State",
                     "Intents (ranked)": "Goals", "Needs": "Needs",
                     "Player Standing": "Player Standing",
                     "Knowledge": "Knows"}
            for title, items in snap.get("sections", []):
                if title not in shown:
                    continue
                head(shown[title])
                for item in items:
                    row(item[0], item[1] if len(item) > 1 else "")
            tasks = snap.get("tasks") or []
            if tasks:
                head("Weighing (priority)")
                for pri, label, active in sorted(tasks, key=lambda t: -t[0])[:6]:
                    rows.append(("task", ("▶ " if active else "   ") + str(label),
                                 f"{pri:.0f}" if isinstance(pri, (int, float)) else str(pri)))
        return rows

    # -- window --------------------------------------------------------------
    #: Height of the larger S / E / C row.
    STATS_H = 24

    def _row_h(self, kind):
        return self.STATS_H if kind == "stats" else self.LINE_H

    def content_height(self):
        self.refresh()
        if not self._rows:
            return 10 + self.LINE_H
        return 10 + sum(self._row_h(kind) for kind, _t, _v in self._rows)

    def draw(self, painter, focused=False):
        super().draw(painter, focused)
        # The window's colour on its title bar ties it to its line in the world.
        rect = self._full_rect()
        painter.fillRect(QRectF(rect.x(), rect.y(), 5, self.HEADER_H), self.colour)

    def _link(self, painter, x, base, text, action, active=False):
        """Draw *text* as a link at (x, base); a click on it runs *action*."""
        from . import hits
        fm = self._fm
        rect = QRectF(x - 2, base - fm.ascent() - 1, fm.horizontalAdvance(text) + 4,
                      fm.height() + 2)
        hot = False
        if hits.pointer is not None:
            hot = rect.contains(QPointF(hits.pointer[0], hits.pointer[1]))
        font = QFont(self.font)
        font.setUnderline(hot or active)
        font.setBold(active)
        painter.setFont(font)
        painter.setPen(_LINK_HOT if (hot or active) else _LINK)
        painter.drawText(QPointF(x, base), text)
        self._links.append((rect, action))
        return rect.right()

    def _draw_stats(self, painter, x, ty, values):
        """S / E / C in the larger face: the letter in its colour, the 3..18
        score after it."""
        painter.setFont(self.stats_font)
        fm = QFontMetrics(self.stats_font)
        base = ty + self.STATS_H - 6
        cx = x
        for letter, value, colour in zip("SEC", values, _STAT_COLOURS):
            painter.setPen(colour)
            painter.drawText(QPointF(cx, base), letter)
            cx += fm.horizontalAdvance(letter) + 4
            painter.setPen(_TEXT)
            text = str(value)
            painter.drawText(QPointF(cx, base), text)
            cx += fm.horizontalAdvance(text) + 22

    def _place_action(self, key):
        def action():
            place = resolve_place(self._session(), self.thing, key)
            if place is None:
                return
            pos, entity, label = place
            show_place(self, key, pos, label, entity)
        return action

    def _dest_action(self):
        dest = destination(self._session(), self._logic(), self.thing)
        if dest is None:
            return None
        pos, why = dest

        def action():
            show_place(self, "@dest", pos, f"heading to ({why})")
        return action

    def handle_body_click(self, x, y):
        point = QPointF(x, y)
        for rect, action in reversed(self._links):
            if rect.contains(point):
                action()
                return True
        return False

    def _pause_owner(self):
        return f"inspector:{id(self)}"

    def toggle_pause(self):
        """Hold the world still while reading this window, or let it run."""
        self.set_paused(not self.paused)

    def set_paused(self, paused: bool):
        logic = self._logic()
        runtime = getattr(logic, "session_runtime", None)
        if runtime is not None:
            runtime.set_world_paused(self._pause_owner(), bool(paused))
        self.paused = bool(paused)
        self._rows = []              # redraw the toggle's label now

    def on_close(self):
        if self.paused:
            self.set_paused(False)
        # Closing the window that is showing a place snaps the camera home.
        focus = focused_place(self._logic())
        if focus is not None and focus["window"] is self:
            clear_focus(self._logic(), glide=False)

    def draw_body(self, painter, x, y, w):
        self.refresh()
        painter.save()
        self._links = []
        focus = focused_place(self._logic())
        mine = focus["key"] if focus is not None and focus["window"] is self else None
        ty = y + 6
        label_w = 112
        for kind, text, value in self._rows:
            base = ty + self.LINE_H - 3
            if kind == "stats":
                self._draw_stats(painter, x + 14, ty, value)
                ty += self.STATS_H
                continue
            if kind == "pause":
                self._link(painter, x + 8, base, text, self.toggle_pause,
                           active=self.paused)
                ty += self.LINE_H
                continue
            if kind == "back":
                logic = self._logic()
                self._link(painter, x + 8, base, text,
                           lambda logic=logic: clear_focus(logic))
            elif kind == "head":
                painter.setFont(self.bold)
                painter.setPen(_HEAD)
                painter.drawText(x + 8, base, text)
            elif kind in ("sched", "sched_now"):
                if kind == "sched_now":
                    painter.fillRect(QRectF(x + 4, ty, w - 8, self.LINE_H), _HILITE)
                painter.setFont(self.bold if kind == "sched_now" else self.font)
                painter.setPen(_TEXT if kind == "sched_now" else _MUTED)
                lead = ("▶ " if kind == "sched_now" else "  ") + text + "  @ "
                painter.drawText(x + 14, base, lead)
                lx = x + 14 + QFontMetrics(painter.font()).horizontalAdvance(lead)
                if value:
                    self._link(painter, lx, base, value, self._place_action(value),
                               active=(mine == value))
            elif kind == "task":
                # A task's description runs the whole width; its priority
                # sits at the right.
                painter.setFont(self.font)
                painter.setPen(_TEXT if text.startswith("▶") else _MUTED)
                painter.drawText(x + 14, base, self._fm.elidedText(text, Qt.ElideRight, w - 70))
                painter.drawText(QRectF(x, ty, w - 12, self.LINE_H),
                                 int(Qt.AlignRight | Qt.AlignVCenter), value)
            else:
                painter.setFont(self.font)
                painter.setPen(_MUTED)
                painter.drawText(x + 14, base, self._fm.elidedText(text, Qt.ElideRight, label_w - 8))
                action = self._dest_action() if text == "Heading to" else None
                if action is not None:
                    self._link(painter, x + 14 + label_w, base,
                               self._fm.elidedText(value, Qt.ElideRight, w - label_w - 24),
                               action, active=(mine == "@dest"))
                else:
                    painter.setPen(_TEXT)
                    painter.drawText(x + 14 + label_w, base,
                                     self._fm.elidedText(value, Qt.ElideRight, w - label_w - 24))
            ty += self.LINE_H
        painter.restore()


# --------------------------------------------------------------------------- opening

def open_inspector(view, thing):
    """Open (or bring forward) the inspector window for *thing* on *view*."""
    manager = getattr(view, "window_manager", None)
    if manager is None or thing is None:
        return None
    existing = manager.find(lambda w: isinstance(w, ActorInspectorWindow)
                            and w.thing is thing)
    if existing is not None:
        existing.active = True
        manager.raise_(existing)
        view.update()
        return existing
    n = sum(1 for w in manager.windows if isinstance(w, ActorInspectorWindow))
    x, y = _beside(view, thing, n)
    win = ActorInspectorWindow(view, thing, x=x, y=y)
    manager.add(win)
    view.update()
    return win


#: Where a new inspector opens relative to its actor on screen (px), and
#: how far each further window steps so they do not stack exactly.
OPEN_OFFSET = (70, -60)
OPEN_STEP = 22


def _beside(view, thing, n):
    """Top-left for a new inspector window: just beside its actor on screen,
    kept fully inside the view. Falls back to the right-hand side when the
    actor cannot be projected (behind the camera, no frame drawn yet)."""
    width, height = view.width(), view.height()
    win_w, win_h = 380, 260
    point = None
    try:
        import glm
        point = _project(glm, view.projection_matrix, view.view_matrix,
                         thing.pos, width, height)
    except Exception:
        point = None
    if point is None or not (0 <= point.x() <= width and 0 <= point.y() <= height):
        return (max(10, width - 400 - (n % 4) * 26), 70 + (n % 4) * 26)
    x = point.x() + OPEN_OFFSET[0] + (n % 4) * OPEN_STEP
    y = point.y() + OPEN_OFFSET[1] + (n % 4) * OPEN_STEP
    if x + win_w > width - 10:
        # No room to the right: open on the actor's left instead.
        x = point.x() - OPEN_OFFSET[0] - win_w
    x = max(10, min(int(x), width - win_w - 10))
    y = max(10, min(int(y), height - win_h - 10))
    return x, y


def open_windows(view):
    manager = getattr(view, "window_manager", None)
    if manager is None:
        return []
    return [w for w in manager.windows
            if isinstance(w, ActorInspectorWindow) and w.active]


# ------------------------------------------------------------------- world lines

def _project(glm, proj, view_m, pos, width, height):
    """Screen point of a world position, or None behind the camera.

    Unlike the HUD's projection this does not drop points off screen: a line
    to somewhere beyond the edge still leaves the actor in the right direction
    (Qt clips the rest).
    """
    clip = proj * view_m * glm.vec4(float(pos[0]), float(pos[1]), float(pos[2]), 1.0)
    if clip.w <= 1e-4:
        return None
    nx, ny = clip.x / clip.w, clip.y / clip.w
    return QPointF((nx * 0.5 + 0.5) * width, (1.0 - (ny * 0.5 + 0.5)) * height)


def _draw_beacon(painter, glm, proj, view_m, focus, width, height):
    """The place an inspector link is showing: pulsing rings, a cross, its
    marker's own sprite (play hides markers) and its name."""
    centre = _project(glm, proj, view_m, focus["pos"], width, height)
    if centre is None:
        return
    win = focus.get("window")
    colour = QColor(win.colour) if win is not None else QColor(_LINK)
    age = time.monotonic() - focus.get("since", 0.0)
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    painter.setBrush(Qt.NoBrush)
    for i in range(2):
        phase = (age * 0.8 + i * 0.5) % 1.0
        ring = QColor(colour)
        ring.setAlphaF(1.0 - phase)
        painter.setPen(QPen(ring, 2))
        r = 14 + 46 * phase
        painter.drawEllipse(centre, r, r)
    painter.setPen(QPen(colour, 2))
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        painter.drawLine(centre + QPointF(dx * 8, dy * 8), centre + QPointF(dx * 20, dy * 20))
    entity = focus.get("entity")
    pixmap = None
    for getter in ("get_instance_pixmap", "get_icon_pixmap"):
        fn = getattr(entity, getter, None) if entity is not None else None
        if fn is None:
            continue
        try:
            pixmap = fn()
        except Exception:
            pixmap = None
        if pixmap is not None and not pixmap.isNull():
            break
        pixmap = None
    if pixmap is not None:
        size = 48.0
        scale = size / max(1, max(pixmap.width(), pixmap.height()))
        pw, ph = pixmap.width() * scale, pixmap.height() * scale
        painter.drawPixmap(QRectF(centre.x() - pw / 2, centre.y() - ph - 22, pw, ph),
                           pixmap, QRectF(pixmap.rect()))
    painter.setFont(QFont("Arial", 9, QFont.Bold))
    fm = QFontMetrics(painter.font())
    text = str(focus.get("label", ""))
    box = QRectF(centre.x() - fm.horizontalAdvance(text) / 2 - 6, centre.y() + 26,
                 fm.horizontalAdvance(text) + 12, fm.height() + 4)
    painter.fillRect(box, QColor(10, 10, 14, 200))
    painter.setPen(colour)
    painter.drawText(box, int(Qt.AlignCenter), text)
    painter.restore()


#: The highlight on the actor under the pointer while ``inspect`` is armed.
PICK_HOVER_COLOUR = QColor(255, 225, 120)


def draw_pick_hover(painter, viewport, width, height):
    """While ``inspect`` is armed: highlight the actor under the pointer -- a
    glowing ring round it and its name -- so it is clear what a click opens."""
    if getattr(viewport, "_actor_pick", None) is None:
        return
    thing = getattr(viewport, "actor_pick_hover", None)
    if thing is None:
        return
    try:
        import glm
        centre = _project(glm, viewport.projection_matrix, viewport.view_matrix,
                          thing.pos, width, height)
    except Exception:
        return
    if centre is None:
        return
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    painter.setBrush(Qt.NoBrush)
    glow = QColor(PICK_HOVER_COLOUR)
    for radius, alpha, pen in ((40, 70, 8), (36, 140, 4), (34, 255, 2)):
        glow.setAlpha(alpha)
        painter.setPen(QPen(glow, pen))
        painter.drawEllipse(centre, radius, radius)
    font = QFont("Segoe UI", 9)
    font.setBold(True)
    painter.setFont(font)
    fm = QFontMetrics(font)
    text = _name(thing)
    box = QRectF(centre.x() - fm.horizontalAdvance(text) / 2 - 6,
                 centre.y() - 40 - fm.height() - 8,
                 fm.horizontalAdvance(text) + 12, fm.height() + 4)
    painter.fillRect(box, QColor(10, 10, 14, 200))
    painter.setPen(PICK_HOVER_COLOUR)
    painter.drawText(box, int(Qt.AlignCenter), text)
    painter.restore()


def _draw_leader(painter, win, actor_pt, colour):
    """A line from the inspector window to its actor: from the point of the
    window's outline nearest the actor, so it stays attached wherever the
    window is dragged (read off the live window rect every frame)."""
    rect = win._full_rect()
    x = min(max(actor_pt.x(), rect.left()), rect.right())
    y = min(max(actor_pt.y(), rect.top()), rect.bottom())
    anchor = QPointF(x, y)
    if rect.contains(int(actor_pt.x()), int(actor_pt.y())):
        return                       # the window sits over its actor
    faint = QColor(colour)
    faint.setAlpha(200)
    painter.setPen(QPen(faint, 1.6))
    painter.drawLine(anchor, actor_pt)
    painter.setBrush(faint)
    painter.drawEllipse(anchor, 3.5, 3.5)
    painter.setBrush(Qt.NoBrush)


def draw_world_lines(painter, viewport, width, height):
    """For every open inspector: a ring round its actor and a line to where it
    is heading, ending in a ring there; and the beacon on a place a link is
    showing."""
    logic = getattr(viewport, "logic_thread", None)
    focus = focused_place(logic)
    windows = open_windows(viewport)
    if not windows and focus is None:
        return
    try:
        import glm
        proj = viewport.projection_matrix
        view_m = viewport.view_matrix
    except Exception:
        return
    session = getattr(logic, "_miniwind", None)
    if focus is not None:
        _draw_beacon(painter, glm, proj, view_m, focus, width, height)
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    painter.setBrush(Qt.NoBrush)
    for win in windows:
        thing = win.thing
        start = _project(glm, proj, view_m, thing.pos, width, height)
        if start is None:
            continue
        colour = QColor(win.colour)
        _draw_leader(painter, win, start, colour)
        painter.setPen(QPen(colour, 2))
        painter.drawEllipse(start, 18, 18)
        dest = destination(session, logic, thing)
        if dest is None:
            continue
        end = _project(glm, proj, view_m, dest[0], width, height)
        if end is None:
            continue
        pen = QPen(colour, 2, Qt.DashLine)
        pen.setDashPattern([6, 4])
        painter.setPen(pen)
        painter.drawLine(start, end)
        painter.setPen(QPen(colour, 2))
        painter.drawEllipse(end, 8, 8)
        painter.drawEllipse(end, 2, 2)
        painter.setFont(QFont("Arial", 8))
        painter.drawText(end + QPointF(12, 4), dest[1])
    painter.restore()
