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

Debug view: small sans text, not the game's display faces.
"""

from __future__ import annotations

import math
import time

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPen

from engine.floating_windows import FloatingWindow

#: Colours given to inspector windows in turn (title stripe, line, rings).
COLOURS = (QColor(80, 200, 255), QColor(255, 170, 60), QColor(160, 255, 120),
           QColor(255, 110, 200), QColor(250, 240, 110), QColor(170, 140, 255))

#: How often the text refreshes (s); the world line follows every frame.
REFRESH_SECONDS = 0.25

_TEXT = QColor(220, 220, 220)
_MUTED = QColor(150, 150, 160)
_HEAD = QColor(240, 200, 120)
_HILITE = QColor(90, 130, 128, 120)

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
    for t in getattr(logic, "things", None) or ():
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
    if mstate.get("in_sight") and getattr(logic, "player", None) is not None:
        p = logic.player.pos
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
        self._fm = QFontMetrics(self.font)
        self._rows = []          # [(kind, text, value)] kind: head/row/sched/sched_now
        self._refreshed = 0.0

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

        head("Actor")
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
                text = "{}  {:<14} @ {}".format(_fmt_hour(entry.get("hour", 0)),
                                                str(entry.get("state", "?")),
                                                entry.get("location", "-"))
                rows.append(("sched_now" if entry is current else "sched", text, ""))

        snap = None
        try:
            from .. import mental_state
            snap = mental_state.snapshot(thing, monster_state=_monster_state(logic, thing),
                                         session=session)
        except Exception:
            snap = None
        if snap:
            for title, items in snap.get("sections", []):
                if title not in ("Why", "AI State"):
                    continue
                head(title)
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
    def content_height(self):
        self.refresh()
        return 10 + self.LINE_H * max(1, len(self._rows))

    def draw(self, painter, focused=False):
        super().draw(painter, focused)
        # The window's colour on its title bar ties it to its line in the world.
        rect = self._full_rect()
        painter.fillRect(QRectF(rect.x(), rect.y(), 5, self.HEADER_H), self.colour)

    def draw_body(self, painter, x, y, w):
        self.refresh()
        painter.save()
        ty = y + 6
        label_w = 112
        for kind, text, value in self._rows:
            base = ty + self.LINE_H - 3
            if kind == "head":
                painter.setFont(self.bold)
                painter.setPen(_HEAD)
                painter.drawText(x + 8, base, text)
            elif kind in ("sched", "sched_now"):
                if kind == "sched_now":
                    painter.fillRect(QRectF(x + 4, ty, w - 8, self.LINE_H), _HILITE)
                painter.setFont(self.bold if kind == "sched_now" else self.font)
                painter.setPen(_TEXT if kind == "sched_now" else _MUTED)
                painter.drawText(x + 14, base, ("▶ " if kind == "sched_now" else "  ") + text)
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
    x = max(10, view.width() - 400 - (n % 4) * 26)
    win = ActorInspectorWindow(view, thing, x=x, y=70 + (n % 4) * 26)
    manager.add(win)
    view.update()
    return win


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


def draw_world_lines(painter, viewport, width, height):
    """For every open inspector: a ring round its actor and a line to where it
    is heading, ending in a ring there."""
    windows = open_windows(viewport)
    if not windows:
        return
    try:
        import glm
        proj = viewport.projection_matrix
        view_m = viewport.view_matrix
    except Exception:
        return
    logic = getattr(viewport, "logic_thread", None)
    session = getattr(logic, "_miniwind", None)
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    painter.setBrush(Qt.NoBrush)
    for win in windows:
        thing = win.thing
        start = _project(glm, proj, view_m, thing.pos, width, height)
        if start is None:
            continue
        colour = QColor(win.colour)
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
