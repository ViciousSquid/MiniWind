"""Who will do what in a cutscene, drawn over the editor's views.

While the cutscene editor is open (editor/cutscene_wizard.py) every keyframe
of the cutscene being authored is an arrow in the 2D and 3D views, from the
actor to what it acts on, in the colour of the action and labelled with what
and when:

* **ATTACK** (red): attacker to target -- a battle between companies is one
  thick arrow between the two companies' outlines, double-headed when the
  defenders fight back, rather than a line per pair;
* **MOVE** (green): the actor's route, step by step, numbered;
* **SAY** (blue) and **THINK** (purple): to whom, when the line has a
  listener; otherwise a label over the actor.

The lines are the dice roll box's leader (game/ui/hud.py ``_draw_leader``):
a thick line in the action's colour on a dark edge, a dot on the actor --
with an arrowhead into the target. With actors selected in the cast, their
arrows are bright and everyone else's fade back.

They are an authoring aid: drawn only in the editor while the cutscene editor
is open, never in Play nor while its preview plays.
"""

from __future__ import annotations

import math

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPen, QPolygonF

ATTACK = (238, 104, 88)
MOVE = (120, 214, 130)
SAY = (110, 170, 255)
THINK = (196, 146, 255)
COLOURS = {"attack": ATTACK, "move": MOVE, "say": SAY, "think": THINK}
#: More pairs than this in one battle and it is drawn company to company.
PAIRS_DRAWN = 6
LINE_W = 3.0
ALPHA = 0.62        # as the roll box's leader (ROLL_LEADER_ALPHA), a touch firmer
ALPHA_FOCUS = 0.9   # the selected actors' own
ALPHA_FADED = 0.16  # everyone else's while some are selected
ACTOR_GAP = 22      # px kept clear of an actor's centre


class Intent:
    """One thing to draw: ``kind`` (attack/move/say/think), world points
    ``src`` and ``dst`` (or a company's points ``src_group`` / ``dst_group``),
    a ``label``, the actor ids it involves, and drawing hints."""

    def __init__(self, kind, src=None, dst=None, label="", actors=(), *, both=False,
                 src_group=None, dst_group=None, src_gap=ACTOR_GAP, dst_gap=ACTOR_GAP,
                 step=None, head=True):
        self.kind = kind
        self.src, self.dst = src, dst
        self.label = label
        self.actors = set(actors)
        self.both = both
        self.src_group, self.dst_group = src_group, dst_group
        self.src_gap, self.dst_gap = src_gap, dst_gap
        self.step = step
        self.head = head
        self.ghosts = ()


def _pos(actor):
    p = getattr(actor, "pos", None)
    if p is None:
        return None
    try:
        return (float(p[0]), float(p[1]), float(p[2]))
    except (TypeError, IndexError):
        return (float(p.x), float(p.y), float(p.z))


def _t(value):
    return f"{float(value):g}s"


def intents(wizard):
    """Every keyframe of *wizard*'s cutscene as :class:`Intent` s."""
    wizard._refresh_actor_objects_from_state()
    objects = wizard.actor_objects
    names = {aid: meta["name"] for aid, meta in wizard.actor_meta.items()}
    out = []
    # A company's MOVE (one order to many): one arrow from where they stand to
    # its pin, with where each will stand ghosted round it.
    orders = {}
    for aid, rows in wizard.actor_tracks.items():
        for row in rows:
            if row.get("order") and aid in objects:
                orders.setdefault(row["order"], []).append((aid, row))
    for members in orders.values():
        here = [_pos(objects[aid]) for aid, _row in members]
        here = [p for p in here if p is not None]
        if not here:
            continue
        centre = tuple(sum(p[i] for p in here) / len(here) for i in range(3))
        first = members[0][1]
        pin = first.get("pin") or first.get("pos")
        pin = (float(pin[0]), float(pin[1]), float(pin[2]))
        intent = Intent("move", centre, pin,
                        f"MOVE · {len(members)} actors · at {_t(first.get('time', 0.0))}",
                        [aid for aid, _row in members], src_gap=10, dst_gap=12, step=1)
        intent.ghosts = [tuple(float(v) for v in row.get("pos", pin)) for _aid, row in members]
        out.append(intent)
    # MOVE: each actor's own route from where it stands, step by step.
    for aid, rows in wizard.actor_tracks.items():
        actor = objects.get(aid)
        here = _pos(actor) if actor is not None else None
        if here is None:
            continue
        rows = sorted(rows, key=lambda r: float(r.get("time", 0.0)))
        prev, prev_t, first = here, None, True
        for n, row in enumerate(rows, 1):
            if row.get("order"):
                # Drawn with its company; the route carries on from there.
                dest = row.get("pos")
                if dest is not None:
                    prev = (float(dest[0]), float(dest[1]), float(dest[2]))
                    prev_t, first = float(row.get("time", 0.0)), False
                continue
            dest = row.get("pos")
            target = objects.get(str(row.get("target_id", "") or ""))
            if target is not None:
                dest = _pos(target)
            if dest is None:
                continue
            dest = (float(dest[0]), float(dest[1]), float(dest[2]))
            if math.dist(prev, dest) < 1.0:
                prev, prev_t = dest, float(row.get("time", 0.0))
                continue
            when = f"{_t(prev_t)}–{_t(row.get('time', 0.0))}" if prev_t is not None else \
                f"at {_t(row.get('time', 0.0))}"
            cut = " (cut)" if row.get("teleport") else ""
            out.append(Intent("move", prev, dest, f"MOVE · {when}{cut}", [aid],
                              src_gap=ACTOR_GAP if first else 12, dst_gap=12, step=n))
            prev, prev_t, first = dest, float(row.get("time", 0.0)), False
    for event in wizard.events:
        kind = event.get("type")
        if kind in ("say", "think"):
            aid = str(event.get("actor", ""))
            actor = objects.get(aid)
            if actor is None:
                continue
            text = str(event.get("text", ""))
            short = text if len(text) <= 28 else text[:27] + "…"
            label = f"{kind.upper()} “{short}” · {_t(event.get('time', 0.0))}"
            listener = objects.get(str(event.get("to", "") or ""))
            if listener is not None:
                out.append(Intent(kind, _pos(actor), _pos(listener), label,
                                  [aid, str(event.get("to"))]))
            else:
                here = _pos(actor)
                out.append(Intent(kind, here, here, label, [aid], head=False))
        elif kind == "fight":
            attackers = [a for a in map(str, event.get("attackers", [])) if a in objects]
            defenders = [d for d in map(str, event.get("defenders", [])) if d in objects]
            if not attackers or not defenders:
                continue
            mutual = bool(event.get("mutual", True))
            start = float(event.get("time", 0.0))
            end = start + float(event.get("duration", 0.0))
            back = " · fights back" if mutual else ""
            if len(attackers) * len(defenders) <= PAIRS_DRAWN:
                for a in attackers:
                    for d in defenders:
                        label = f"ATTACK {names.get(d, '')} · {_t(start)}–{_t(end)}{back}"
                        out.append(Intent("attack", _pos(objects[a]), _pos(objects[d]),
                                          label, [a, d], both=mutual))
            else:
                out.append(Intent(
                    "attack", label=f"ATTACK · {len(attackers)} vs {len(defenders)} · "
                                    f"{_t(start)}–{_t(end)}{back}",
                    actors=attackers + defenders, both=mutual,
                    src_group=[_pos(objects[a]) for a in attackers],
                    dst_group=[_pos(objects[d]) for d in defenders]))
    return out


# ---------------------------------------------------------------------------
# Drawing.
# ---------------------------------------------------------------------------
def _font(size, bold=True):
    f = QFont()
    f.setPointSizeF(size)
    f.setBold(bold)
    return f


def _head(painter, tip, ux, uy, ink, dark, w):
    length, half = 12 + w * 1.6, 6 + w
    base = QPointF(tip.x() - ux * length, tip.y() - uy * length)
    painter.setPen(QPen(dark, 1.5))
    painter.setBrush(ink)
    painter.drawPolygon(QPolygonF([
        tip, QPointF(base.x() - uy * half, base.y() + ux * half),
        QPointF(base.x() + uy * half, base.y() - ux * half)]))


#: The labels placed in the paint under way: a new one moves clear of them.
_placed = []


def _label(painter, x, y, text, rgb, alpha):
    painter.setFont(_font(8.5))
    fm = painter.fontMetrics()
    w = fm.horizontalAdvance(text) + 14
    rect = QRectF(x - w / 2, y - 10, w, 20)
    for step in (0, 1, -1, 2, -2, 3, -3, 4, -4):
        trial = rect.translated(0, step * 23)
        if not any(trial.intersects(other) for other in _placed):
            rect = trial
            break
    _placed.append(rect)
    painter.setPen(QPen(QColor(*rgb, int(230 * alpha)), 1.2))
    painter.setBrush(QColor(14, 16, 22, int(215 * min(1.0, alpha + 0.1))))
    painter.drawRoundedRect(rect, 6, 6)
    painter.setPen(QColor(*rgb, int(255 * min(1.0, alpha + 0.1))))
    painter.drawText(rect, int(Qt.AlignCenter), text)


def leader(painter, a, b, rgb, *, alpha=ALPHA, w=LINE_W, start_gap=ACTOR_GAP,
           end_gap=ACTOR_GAP, both=False, dash=False, head=True, label=None):
    """The roll box's leader from screen point *a* to *b*: a thick line in
    *rgb* on a dark edge, a dot at *a*, an arrowhead into *b* (and into *a*
    too, *both*), and a *label* at its middle."""
    ax, ay = a
    bx, by = b
    d = math.hypot(bx - ax, by - ay)
    if d < start_gap + end_gap + 4:
        return
    ux, uy = (bx - ax) / d, (by - ay) / d
    s = QPointF(ax + ux * start_gap, ay + uy * start_gap)
    e = QPointF(bx - ux * end_gap, by - uy * end_gap)
    ink = QColor(*rgb, int(255 * alpha))
    dark = QColor(10, 12, 18, int(255 * alpha * 0.6))
    for pen_w, colour in ((w + 2, dark), (w, ink)):
        pen = QPen(colour, pen_w)
        pen.setCapStyle(Qt.RoundCap)
        if dash:
            pen.setDashPattern([3, 2.2])
        painter.setPen(pen)
        painter.drawLine(s, e)
    if head:
        _head(painter, e, ux, uy, ink, dark, w)
    if both:
        _head(painter, s, -ux, -uy, ink, dark, w)
    else:
        painter.setPen(QPen(dark, 1))
        painter.setBrush(ink)
        painter.drawEllipse(s, w + 2, w + 2)
    if label:
        _label(painter, (s.x() + e.x()) / 2, (s.y() + e.y()) / 2, label, rgb, alpha)


def _pin(painter, p, n, alpha):
    """A dropped pin where a MOVE goes: its point on the spot, numbered by
    the step it is in the actor's route."""
    from PyQt5.QtGui import QPainterPath
    r = 10.0
    head = QPointF(p.x(), p.y() - 2.2 * r)
    path = QPainterPath()
    path.moveTo(p)
    path.cubicTo(QPointF(p.x() - r * 0.9, p.y() - r * 1.1), QPointF(head.x() - r, head.y() + r * 0.4),
                 QPointF(head.x() - r, head.y()))
    path.arcTo(QRectF(head.x() - r, head.y() - r, 2 * r, 2 * r), 180, -180)
    path.cubicTo(QPointF(head.x() + r, head.y() + r * 0.4), QPointF(p.x() + r * 0.9, p.y() - r * 1.1), p)
    painter.setPen(QPen(QColor(10, 12, 18, int(200 * alpha)), 2))
    painter.setBrush(QColor(*MOVE, int(235 * alpha)))
    painter.drawPath(path)
    painter.setFont(_font(7.5))
    painter.setPen(QColor(12, 30, 14, int(255 * alpha)))
    painter.drawText(QRectF(head.x() - r, head.y() - r, 2 * r, 2 * r), int(Qt.AlignCenter), str(n))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(10, 12, 18, int(120 * alpha)))
    painter.drawEllipse(p, 4, 2)


#: The cast's tints: under the mouse, and selected (firmer).
HOVER_TINT = (255, 214, 120, 70)
SELECT_TINT = (255, 206, 96, 150)
TINT_RADIUS = 26
HOVER_PX = 26


def hovered(wizard, project, cursor):
    """The cast actor under *cursor* (a view point), or None."""
    if cursor is None:
        return None
    best, best_d = None, HOVER_PX
    for aid, actor in wizard.actor_objects.items():
        if aid not in wizard.actor_meta:
            continue
        p = project(_pos(actor))
        if p is None:
            continue
        d = math.hypot(p[0] - cursor[0], p[1] - cursor[1])
        if d <= best_d:
            best, best_d = aid, d
    return best


#: An actor's body on the ground, for sizing its ring on screen (world units).
ACTOR_RADIUS = 34.0


def _screen_radius(project, pos):
    """How big :data:`ACTOR_RADIUS` is on screen at *pos* (kept readable)."""
    a = project(pos)
    b = project((pos[0] + ACTOR_RADIUS, pos[1], pos[2]))
    c = project((pos[0], pos[1], pos[2] + ACTOR_RADIUS))
    if a is None:
        return TINT_RADIUS
    size = max((math.hypot(q[0] - a[0], q[1] - a[1]) for q in (b, c) if q is not None),
               default=TINT_RADIUS)
    return max(9.0, min(40.0, size))


def _facing_rad(actor):
    props = getattr(actor, "properties", {}) or {}
    try:
        return math.radians(float(props.get("angle", 0.0) or 0.0))
    except (TypeError, ValueError):
        return 0.0


def paint_cast(painter, wizard, project, cursor=None):
    """Every cast actor's facing (a small wedge on its ring's edge); a tint
    on the actor under the mouse and (firmer) on the selected ones; an actor
    waiting for its target to be clicked pulses."""
    import time
    selected = set(wizard._current_actor_ids())
    over = hovered(wizard, project, cursor)
    pick = getattr(wizard, "_pick", None) or {}
    waiting = set(pick.get("aids") or ())
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    try:
        for aid, actor in wizard.actor_objects.items():
            if aid not in wizard.actor_meta:
                continue
            pos = _pos(actor)
            p = project(pos)
            if p is None:
                continue
            centre = QPointF(*p)
            radius = _screen_radius(project, pos)
            lit = aid in selected or aid == over or aid in waiting
            if lit:
                r, g, b, a = SELECT_TINT if aid in selected else HOVER_TINT
                if aid in waiting:
                    a = int(90 + 80 * (0.5 + 0.5 * math.sin(time.monotonic() * 6.0)))
                painter.setPen(QPen(QColor(r, g, b, min(255, a + 80)), 2.5))
                painter.setBrush(QColor(r, g, b, a // 2))
                painter.drawEllipse(centre, radius, radius)
            # Which way it faces: a wedge on the ring's edge.
            yaw = _facing_rad(actor)
            ahead = project((pos[0] + math.sin(yaw) * ACTOR_RADIUS, pos[1],
                             pos[2] + math.cos(yaw) * ACTOR_RADIUS))
            if ahead is not None:
                dx, dy = ahead[0] - p[0], ahead[1] - p[1]
                d = math.hypot(dx, dy) or 1.0
                ux, uy = dx / d, dy / d
                tip = QPointF(p[0] + ux * (radius + 9), p[1] + uy * (radius + 9))
                base = QPointF(p[0] + ux * (radius - 1), p[1] + uy * (radius - 1))
                half = 6.0
                ink = QColor(255, 236, 190, 235 if lit else 170)
                painter.setPen(QPen(QColor(10, 12, 18, 180), 1.2))
                painter.setBrush(ink)
                painter.drawPolygon(QPolygonF([
                    tip, QPointF(base.x() - uy * half, base.y() + ux * half),
                    QPointF(base.x() + uy * half, base.y() - ux * half)]))
        if pick and over is not None and over not in waiting:
            # What the click would do: the line it will make, ghosted.
            p = project(_pos(wizard.actor_objects.get(over)))
            rgb = COLOURS.get(pick.get("kind"), (255, 236, 190))
            for aid in waiting:
                q = project(_pos(wizard.actor_objects.get(aid)))
                if p is not None and q is not None:
                    leader(painter, q, p, rgb, alpha=0.4)
    finally:
        painter.restore()


def _company(painter, pts, rgb, alpha):
    xs = [p.x() for p in pts]
    ys = [p.y() for p in pts]
    rect = QRectF(min(xs) - 30, min(ys) - 30, max(xs) - min(xs) + 60, max(ys) - min(ys) + 60)
    pen = QPen(QColor(*rgb, int(200 * alpha)), 2)
    pen.setDashPattern([5, 4])
    painter.setPen(pen)
    painter.setBrush(QColor(*rgb, int(26 * alpha)))
    painter.drawRoundedRect(rect, 18, 18)
    return rect


def _edge_towards(rect, other):
    """The point on *rect*'s edge facing the centre of *other*."""
    c, o = rect.center(), other.center()
    dx, dy = o.x() - c.x(), o.y() - c.y()
    if abs(dx) * rect.height() > abs(dy) * rect.width():
        x = rect.right() if dx > 0 else rect.left()
        return (x, c.y() + dy * (abs(x - c.x()) / max(1e-6, abs(dx))))
    y = rect.bottom() if dy > 0 else rect.top()
    return (c.x() + dx * (abs(y - c.y()) / max(1e-6, abs(dy))), y)


def paint(painter, wizard, project, selected=()):
    """Draw *wizard*'s cutscene intents with *project* (world point ->
    ``(x, y)`` screen point, or None off screen). *selected* actor ids
    stand out; everyone else's fade back."""
    selected = set(selected)
    _placed.clear()
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    try:
        for intent in intents(wizard):
            focus = bool(selected & intent.actors)
            alpha = ALPHA if not selected else (ALPHA_FOCUS if focus else ALPHA_FADED)
            labelled = not selected or focus
            rgb = COLOURS[intent.kind]
            if intent.src_group is not None:
                src = [project(p) for p in intent.src_group]
                dst = [project(p) for p in intent.dst_group]
                src = [QPointF(*p) for p in src if p is not None]
                dst = [QPointF(*p) for p in dst if p is not None]
                if not src or not dst:
                    continue
                a = _company(painter, src, (120, 170, 255), alpha)
                b = _company(painter, dst, ATTACK, alpha)
                leader(painter, _edge_towards(a, b), _edge_towards(b, a), rgb, alpha=alpha,
                       w=LINE_W * 2, start_gap=4, end_gap=4, both=intent.both,
                       label=intent.label if labelled else None)
                continue
            a, b = project(intent.src), project(intent.dst)
            if a is None or b is None:
                continue
            if not intent.head:
                # A line said or thought to no one: over the actor's head.
                if labelled:
                    _label(painter, a[0], a[1] - 34, intent.label, rgb, alpha)
                continue
            leader(painter, a, b, rgb, alpha=alpha, start_gap=intent.src_gap,
                   end_gap=intent.dst_gap, both=intent.both, dash=intent.kind == "think",
                   label=intent.label if labelled else None)
            for ghost in getattr(intent, "ghosts", ()) or ():
                g = project(ghost)
                if g is not None:
                    painter.setPen(QPen(QColor(*MOVE, int(150 * alpha)), 1.5))
                    painter.setBrush(QColor(*MOVE, int(50 * alpha)))
                    painter.drawEllipse(QPointF(*g), 8, 8)
            if intent.step is not None:
                _pin(painter, QPointF(*b), intent.step, alpha)
    finally:
        painter.restore()


def projector_3d(view):
    """World -> screen for the 3D view (None behind the camera)."""
    import glm
    mvp = view.projection_matrix * view.view_matrix
    w, h = view.width(), view.height()

    def project(point):
        if point is None:
            return None
        clip = mvp * glm.vec4(float(point[0]), float(point[1]), float(point[2]), 1.0)
        if float(clip.w) <= 1e-6:
            return None
        return ((float(clip.x) / float(clip.w) + 1.0) * 0.5 * w,
                (1.0 - float(clip.y) / float(clip.w)) * 0.5 * h)
    return project


def projector_2d(view):
    """World -> screen for a 2D view (its two axes)."""
    from PyQt5.QtCore import QPointF as _P
    ax = {"x": 0, "y": 1, "z": 2}
    try:
        h_axis, v_axis = view.get_axes()
    except Exception:
        h_axis, v_axis = ("x", "z")

    def project(point):
        if point is None:
            return None
        p = view.world_to_screen(_P(float(point[ax[h_axis]]), float(point[ax[v_axis]])))
        return (p.x(), p.y())
    return project


# ---------------------------------------------------------------------------
# The scrubber: step through the cutscene in the 3D view.
# ---------------------------------------------------------------------------
SCRUB_H = 92
SCRUB_MARGIN = 40
BUTTONS = ("start", "prev", "play", "next")
BUTTON_TEXT = {"start": "|◀", "prev": "◀", "play": "▶", "pause": "❚❚", "next": "▶|"}
BAND = (238, 104, 88, 90)
PLAYHEAD = (255, 206, 96)


def scrubber_rects(width, height):
    """``(bar, timeline, {button: rect})`` for a view *width* x *height*."""
    bar = QRectF(SCRUB_MARGIN, height - SCRUB_H - 28, max(200, width - 2 * SCRUB_MARGIN), SCRUB_H)
    buttons = {name: QRectF(bar.left() + 14 + i * 44, bar.top() + 14, 38, 30)
               for i, name in enumerate(BUTTONS)}
    timeline = QRectF(bar.left() + 20, bar.top() + 54, bar.width() - 40, 26)
    return bar, timeline, buttons


def scrub_duration(wizard):
    return max(1.0, float(wizard._preview_end_time()))


def keyframe_times(wizard):
    """``[(time, kind)]`` of every keyframe, and ``[(start, end)]`` battles."""
    ticks, bands = [], []
    for rows in wizard.actor_tracks.values():
        ticks += [(float(r.get("time", 0.0)), "move") for r in rows]
    for event in wizard.events:
        kind = event.get("type")
        t = float(event.get("time", 0.0))
        if kind in ("say", "think"):
            ticks.append((t, kind))
        elif kind == "fight":
            ticks.append((t, "attack"))
            bands.append((t, t + float(event.get("duration", 0.0))))
    return sorted(set(ticks)), bands


def scrubber_hit(wizard, width, height, pos):
    """What a press at view point *pos* hits: ``("button", name)``,
    ``("time", seconds)`` or None."""
    bar, timeline, buttons = scrubber_rects(width, height)
    if not bar.contains(pos):
        return None
    for name, rect in buttons.items():
        if rect.contains(pos):
            return ("button", name)
    if timeline.adjusted(0, -10, 0, 10).contains(pos):
        return ("time", scrub_time_at(wizard, width, height, pos.x()))
    return ("bar", None)


def scrub_time_at(wizard, width, height, x):
    _bar, timeline, _b = scrubber_rects(width, height)
    frac = (float(x) - timeline.left()) / max(1.0, timeline.width())
    return max(0.0, min(1.0, frac)) * scrub_duration(wizard)


def paint_scrubber(painter, wizard, width, height):
    """The scrubber bar along the bottom of the 3D view."""
    bar, timeline, buttons = scrubber_rects(width, height)
    duration = scrub_duration(wizard)
    now = float(wizard._preview_time if wizard._preview_actor_baseline
                or wizard._preview_rate else wizard.key_time.value())
    playing = bool(wizard._preview_rate)
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    try:
        painter.setPen(QPen(QColor(90, 90, 100), 1))
        painter.setBrush(QColor(20, 21, 26, 235))
        painter.drawRoundedRect(bar, 10, 10)
        painter.setFont(_font(11))
        for name, rect in buttons.items():
            text = BUTTON_TEXT["pause" if name == "play" and playing else name]
            painter.setPen(QPen(QColor(120, 120, 130), 1))
            painter.setBrush(QColor(35, 134, 54) if name == "play" else QColor(50, 52, 60))
            painter.drawRoundedRect(rect, 5, 5)
            painter.setPen(QColor(240, 240, 240))
            painter.drawText(rect, int(Qt.AlignCenter), text)
        painter.setPen(QColor(*PLAYHEAD))
        painter.drawText(QRectF(bar.left() + 200, bar.top() + 14, 170, 30), int(Qt.AlignVCenter),
                         f"{now:.2f}s / {duration:.1f}s")
        painter.setFont(_font(9, bold=False))
        painter.setPen(QColor(170, 170, 180))
        room = QRectF(bar.left() + 370, bar.top() + 14, bar.width() - 390, 30)
        tip = ("Drag or ← → to scrub (Shift: keyframe to keyframe) · "
               "new keyframes go in at the playhead")
        painter.drawText(room, int(Qt.AlignVCenter),
                         painter.fontMetrics().elidedText(tip, Qt.ElideRight, int(room.width())))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(40, 42, 50))
        painter.drawRoundedRect(timeline, 4, 4)

        def x_at(t):
            return timeline.left() + timeline.width() * max(0.0, min(1.0, t / duration))
        ticks, bands = keyframe_times(wizard)
        painter.setBrush(QColor(*BAND))
        for start, end in bands:
            painter.drawRect(QRectF(x_at(start), timeline.top() + 3,
                                    max(2.0, x_at(end) - x_at(start)), timeline.height() - 6))
        for t, kind in ticks:
            painter.setBrush(QColor(*COLOURS[kind]))
            painter.drawRoundedRect(QRectF(x_at(t) - 3, timeline.top() + 4, 6, timeline.height() - 8), 2, 2)
        painter.setFont(_font(7, bold=False))
        step = max(1, int(round(duration / 7.0)))
        for t in range(0, int(duration) + 1, step):
            painter.setPen(QColor(120, 120, 130))
            painter.drawText(QRectF(x_at(t) - 18, timeline.bottom() - 1, 36, 12),
                             int(Qt.AlignCenter), f"{t}s")
        x = x_at(now)
        painter.setPen(QPen(QColor(*PLAYHEAD), 2.5))
        painter.drawLine(QPointF(x, timeline.top() - 6), QPointF(x, timeline.bottom() + 2))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(*PLAYHEAD))
        painter.drawPolygon(QPolygonF([QPointF(x - 7, timeline.top() - 10),
                                       QPointF(x + 7, timeline.top() - 10),
                                       QPointF(x, timeline.top() - 2)]))
    finally:
        painter.restore()
