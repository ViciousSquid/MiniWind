"""
The heads-up display: health/magicka/stamina, clock, gold, level, active
weapon/spell, the quest tracker, a compass, target nameplates, notifications and
floating combat text. Drawn every frame via the plugin's ``render.overlay`` hook.
"""

from __future__ import annotations

import math
import os
from types import SimpleNamespace

from PyQt5.QtCore import QRect, QRectF, Qt
from PyQt5.QtGui import QColor, QFontMetrics, QPixmap, QPolygon, QPolygonF, QPen, QConicalGradient
from PyQt5.QtCore import QPoint, QPointF

from .. import controls, fio
from ..diceroll import check_target, describe_roll
from . import hud_layout as layout
from . import spell_lock
from . import theme as T
from ..rpg import equipment as eq
from ..rpg import items as rpg_items
from ..rpg import magic as rpg_magic
from ..runtime import (DICE_ANIMATION_SHAKE, DICE_ANIMATION_ROLL, DICE_ANIMATION_FADE,
                        ESCORT_BREAKAWAY_DISTANCE)

DICE_RESULT_HOLD_DURATION = 1.0

#: Rough world-units-per-metre used only to render friendly quest distances
#: (TALK_RADIUS ~140u reads as arm's reach; BOW_REACH ~2400u as a long bowshot).
WORLD_UNITS_PER_METRE = 64.0

#: Distinct arrow colours, one taken per active quest (see _draw_quest_arrow).
#: The first is the classic gold so a single-quest HUD looks unchanged; the
#: rest are picked so several arrows read apart at a glance.
_QUEST_ARROW_COLORS = [
    QColor(255, 214, 130),   # gold
    QColor(120, 200, 255),   # sky blue
    QColor(150, 230, 150),   # green
    QColor(240, 150, 220),   # pink
    QColor(110, 220, 210),   # teal (orange is the waypoint's: theme.WAYPOINT)
    QColor(190, 175, 255),   # lavender
]


def _fmt_distance(world_units):
    """A short, friendly distance label for a quest objective."""
    if world_units is None:
        return ""
    m = world_units / WORLD_UNITS_PER_METRE
    if m < 3:
        return "here"
    if m < 1000:
        return f"{int(round(m))} m"
    return f"{m / 1000:.1f} km"


def draw(painter, session, width, height):
    game = session.game
    c = game.character

    # A modal menu or an open conversation covers the play view; the world-space
    # navigation cues (the orbiting quest arrow, the compass, the quest tracker
    # and target nameplates) are meaningless there and must not bleed on top of
    # the dialogue box or a menu window, so they are suppressed while one is open.
    menu_open = session.open_screen is not None or session.dialogue is not None

    # Name, health, magicka and the minimap, in the bronze frame top left.
    import game.ui.hud_frame as hud_frame
    hud_frame.draw(painter, session, c, width, height)
    # Every other panel can be moved and folded away (game/ui/hud_layout.py).
    layout.begin_frame()

    def panel(pid, draw):
        layout.panel(painter, pid, draw, width, height)

    panel("clock", lambda: _draw_clock(painter, session, width))
    panel("law", lambda: _draw_law(painter, session, width))
    panel("active", lambda: _draw_active(painter, session, c, width, height))
    if not menu_open:
        panel("quest", lambda: _draw_quest_tracker(painter, session, width))
        _draw_quest_arrow(painter, session, width, height)
        panel("compass", lambda: _draw_compass(painter, session, width, height))
        _draw_target_panel(painter, session, width, height)
    panel("status", lambda: _draw_status_flags(painter, session, c, width, height))
    # Dice rolls float in small boxes over whoever rolls (draw_roll_boxes),
    # not in a corner panel.
    panel("rolls", lambda: _draw_roll_log(painter, session, width, height))
    panel("toasts", lambda: _draw_notifications(painter, session, width, height))
    _draw_floaters(painter, session, width, height)
    if not menu_open:
        _draw_interact_prompt(painter, session, width, height)


#: The bow-draw pie's radius, and how far it sits out from the player's head:
#: tucked against its upper right edge, this fraction of the pie outside it.
BOW_PIE_RADIUS = 14
BOW_PIE_OUTSIDE = 0.35
#: The player's head is drawn this many world units across (the overhead
#: sprite size), which is how big it is on screen at any zoom.
PLAYER_HEAD_SIZE = 128.0


def draw_bow_charge(painter, session, viewport, width, height):
    """While left mouse draws the bow: a pie tucked against the upper right
    of the player's head that fills as the draw lengthens (a fuller pie, a
    longer shot). Gone once the arrow is loosed or the draw is lowered.

    Placed from the player's head as drawn -- projected through the live
    camera -- so it stays against the head however far the camera is zoomed.
    """
    charge = getattr(session, "bow_charge", None)
    if charge is None or session.open_screen is not None or session.dialogue is not None:
        return
    charge = max(0.0, min(1.0, float(charge)))
    import game.fio as fio
    player = fio.player(getattr(viewport, "logic_thread", None))
    centre = edge = None
    if player is not None:
        try:
            import glm
            proj, view = viewport.projection_matrix, viewport.view_matrix
            x, y, z = (float(v) for v in player.pos)
            centre = _world_to_screen(glm, proj, view, x, y, z, width, height)
            edge = _world_to_screen(glm, proj, view, x + PLAYER_HEAD_SIZE / 2, y, z,
                                    width, height)
        except Exception:
            centre = edge = None
    if centre is None or edge is None:
        centre, head_r = (width / 2.0, height / 2.0), 30.0
    else:
        head_r = max(8.0, math.hypot(edge[0] - centre[0], edge[1] - centre[1]))
    _draw_charge_pie(painter, centre, head_r, charge)


def _draw_charge_pie(painter, centre, head_r, charge):
    """The bow-draw pie, tucked against the upper right of a head of radius
    *head_r* centred on *centre* (screen pixels): one look for every archer."""
    r = BOW_PIE_RADIUS
    out = head_r + r * (2.0 * BOW_PIE_OUTSIDE - 1.0)
    cx = int(round(centre[0] + out * math.cos(math.radians(45))))
    cy = int(round(centre[1] - out * math.sin(math.radians(45))))
    box = QRect(cx - r, cy - r, 2 * r, 2 * r)
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(10, 10, 14, 170))
    painter.drawEllipse(box)
    full = charge >= 1.0
    painter.setBrush(QColor(255, 214, 90, 235) if full else QColor(235, 225, 200, 220))
    # Qt measures pie angles in 1/16 degree, anticlockwise from 3 o'clock:
    # start at 12 o'clock and fill clockwise.
    painter.drawPie(box, 90 * 16, -int(round(charge * 360 * 16)))
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(QColor(255, 214, 90) if full else QColor(30, 26, 20), 2))
    painter.drawEllipse(box)
    painter.restore()


def draw_npc_bow_charges(painter, session, viewport, width, height):
    """The same charge pie beside every NPC or creature drawing a bow, so the
    player can read an archer winding up a power shot and get out of the way.
    Only archers on screen are drawn."""
    archery = getattr(session, "archery", None)
    if archery is None or session.open_screen is not None or session.dialogue is not None:
        return
    archers = archery.archers()
    if not archers:
        return
    try:
        import glm
        proj, view = viewport.projection_matrix, viewport.view_matrix
    except Exception:
        return
    for thing in archers:
        p = getattr(thing, "properties", {}) or {}
        charge = p.get("_bow_charge")
        if charge is None:
            continue
        try:
            x, y, z = (float(v) for v in thing.pos)
            size = float(p.get("sprite_width", PLAYER_HEAD_SIZE) or PLAYER_HEAD_SIZE)
            centre = _world_to_screen(glm, proj, view, x, y, z, width, height)
            edge = _world_to_screen(glm, proj, view, x + size / 2, y, z, width, height)
        except Exception:
            continue
        if centre is None or edge is None:
            continue
        if not (-40 <= centre[0] <= width + 40 and -40 <= centre[1] <= height + 40):
            continue
        head_r = max(8.0, math.hypot(edge[0] - centre[0], edge[1] - centre[1]))
        _draw_charge_pie(painter, centre, head_r, max(0.0, min(1.0, float(charge))))


#: The interact prompt's size, in points.
PROMPT_FONT_PT = 16


def _draw_interact_prompt(painter, session, width, height):
    """The 'Press E to talk to …' prompt, centred low on screen. MiniWind draws
    it itself because it suppresses the engine's default HUD."""
    text = getattr(session, "interact_prompt", "")
    if not text or session.dialogue is not None or session.open_screen is not None:
        return
    painter.save()
    # The game's medieval face (MedievalSharp; Georgia where it is missing).
    # It has one upright weight, so it is not asked for bold.
    import game.ui.fonts as fonts
    painter.setFont(fonts.dialogue_font(PROMPT_FONT_PT))
    rect = QRect(0, int(height * 0.72), width, 34)
    # soft shadow for legibility over any terrain
    painter.setPen(QColor(0, 0, 0, 200))
    painter.drawText(rect.translated(1, 1), Qt.AlignCenter, text)
    painter.setPen(QColor(245, 240, 220))
    painter.drawText(rect, Qt.AlignCenter, text)
    painter.restore()


def _world_to_screen(glm, proj, view, x, y, z, width, height):
    """Project a world point to screen pixels using the live render matrices,
    or None if it is behind the camera / well off-screen."""
    clip = proj * view * glm.vec4(float(x), float(y), float(z), 1.0)
    w = clip.w
    if w <= 1e-4:
        return None
    nx, ny = clip.x / w, clip.y / w
    if nx < -1.3 or nx > 1.3 or ny < -1.3 or ny > 1.3:
        return None
    return ((nx * 0.5 + 0.5) * width, (1.0 - (ny * 0.5 + 0.5)) * height)


def _has_roll_box(session, thing) -> bool:
    """Whether *thing* has a roll box -- or a "Crit!" -- over its head: its
    speech bubble, bark and thought give way to it."""
    for ask in ("has_roll_box", "shows_crit"):
        has = getattr(session, ask, None)
        try:
            if has is not None and has(thing):
                return True
        except Exception:
            pass
    return False


def draw_bubbles(painter, session, viewport, width, height):
    """Draw a small speech bubble above nearby NPCs that have something for the
    player: '!' for an available quest, '…' for dialogue/trade. Overhead only."""
    if viewport is None:
        return
    try:
        import glm
        proj = viewport.projection_matrix
        view = viewport.view_matrix
    except Exception:
        return
    logic = getattr(session, "logic", None)
    player = fio.player(logic) if logic is not None else None
    if player is None:
        return
    ppos = [float(player.pos[0]), float(player.pos[1]), float(player.pos[2])]
    for npc, kind in session.bubble_npcs(ppos)[:10]:
        if _has_roll_box(session, npc):
            continue                    # its roll box is over its head
        head_y = npc.pos[1] + float(npc.properties.get("sprite_height", 112)) * 0.5 + 26.0
        sp = _world_to_screen(glm, proj, view, npc.pos[0], head_y, npc.pos[2], width, height)
        if sp is not None:
            _draw_bubble(painter, int(sp[0]), int(sp[1]), kind)


def draw_barks(painter, session, viewport, width, height):
    """What people are saying aloud, in a small plate over their heads: a
    guard's "Halt!", a traveller's greeting, a brigand's threat."""
    if viewport is None:
        return
    barks = session.live_barks() if hasattr(session, "live_barks") else ()
    if not barks:
        return
    try:
        import glm
        proj, view = viewport.projection_matrix, viewport.view_matrix
    except Exception:
        return
    import game.ui.fonts as fonts
    font = fonts.dialogue_font(11)
    fm = QFontMetrics(font)
    painter.save()
    painter.setFont(font)
    painter.setRenderHint(painter.Antialiasing, True)
    for thing, text, left in barks[:8]:
        if _has_roll_box(session, thing):
            continue                    # its roll box is over its head
        head_y = thing.pos[1] + float(thing.properties.get("sprite_height", 112)) * 0.5 + 40.0
        sp = _world_to_screen(glm, proj, view, thing.pos[0], head_y, thing.pos[2],
                              width, height)
        if sp is None:
            continue
        alpha = int(255 * max(0.0, min(1.0, left / 0.4)))
        lines = _plate_lines(fm, text, PLATE_MAX_W - 16)
        w = max(fm.horizontalAdvance(line) for line in lines) + 16
        h = 6 + fm.height() * len(lines)
        rect = QRect(int(sp[0] - w / 2), int(sp[1] - 4 - h), w, h)
        painter.setPen(QPen(QColor(168, 142, 84, alpha), 1))
        painter.setBrush(QColor(0, 0, 0, int(alpha * 0.72)))
        painter.drawRoundedRect(rect, 6, 6)
        painter.setPen(QColor(247, 238, 214, alpha))
        painter.drawText(rect, int(Qt.AlignCenter), "\n".join(lines))
    painter.restore()


#: A float (an item collected or a fizzled spell) rises this far as it fades.
FLOAT_RISE_PX = 26.0
#: "Crit!" over whoever lands a critical hit: larger, and white.
CRIT_FLOAT_TEXT = "Crit!"
CRIT_FLOAT_SIZE = 18
CRIT_FLOAT_INK = (255, 255, 255)
_FLOAT_INK = (214, 200, 255)


def draw_floats(painter, session, viewport, width, height):
    """Words floating up from a head and fading, such as "+1 wheat" or
    "*fizzled*" over a caster."""
    if viewport is None:
        return
    floats = session.live_floats() if hasattr(session, "live_floats") else ()
    if not floats:
        return
    try:
        import glm
        proj, view = viewport.projection_matrix, viewport.view_matrix
    except Exception:
        return
    import game.ui.fonts as fonts
    font = fonts.dialogue_font(12)
    font.setItalic(True)
    font.setBold(True)
    fm = QFontMetrics(font)
    painter.save()
    painter.setFont(font)
    painter.setRenderHint(painter.Antialiasing, True)
    for thing, text, left, total in floats[:12]:
        pos = thing.pos
        head_y = pos[1] + float(thing.properties.get("sprite_height", 112)) * 0.5 + 24.0
        sp = _world_to_screen(glm, proj, view, pos[0], head_y, pos[2], width, height)
        if sp is None and thing.properties.get("is_player"):
            # Seen from inside the player's own head (first person): over
            # the middle of the view, where their head would be.
            sp = (width * 0.5, height * 0.4)
        if sp is None:
            continue
        age = max(0.0, min(1.0, 1.0 - left / max(0.01, total)))
        alpha = int(255 * max(0.0, min(1.0, left / 0.5)))
        crit = text == CRIT_FLOAT_TEXT
        if crit:
            # "Crit!": bigger and white, popping in a touch over-size. The
            # word in the game's font; the "!" drawn as a shape (the font's
            # own reads like an "l").
            pop = 1.0 + 0.35 * max(0.0, 1.0 - age / 0.15)
            cf = fonts.dialogue_font(int(round(CRIT_FLOAT_SIZE * pop)))
            cf.setItalic(True)
            cf.setBold(True)
            painter.setFont(cf)
            cm = QFontMetrics(cf)
            word = text.rstrip("!")
            # The font's own cap height is unreliable (it reports 2px): measure a capital.
            cap = float(cm.tightBoundingRect("C").height())
            bang_w = cap * 0.42
            ww = cm.horizontalAdvance(word)
            w, fh = ww + bang_w + 10, cm.height()
            left = sp[0] - w / 2 + 5
            base = sp[1] - FLOAT_RISE_PX * age - cm.descent()
            ink = QColor(*CRIT_FLOAT_INK, alpha)
            for dx, dy, colour in ((2, 2, QColor(0, 0, 0, int(alpha * 0.8))),
                                   (1, 1, QColor(0, 0, 0, int(alpha * 0.8))), (0, 0, ink)):
                painter.setPen(colour)
                painter.drawText(QPointF(left + dx, base + dy), word)
                _draw_bang(painter, left + ww + bang_w * 0.25 + dx, base + dy, cap, colour)
            continue
        else:
            painter.setFont(font)
            w, fh = fm.horizontalAdvance(text) + 8, fm.height()
        rect = QRect(int(sp[0] - w / 2), int(sp[1] - FLOAT_RISE_PX * age - fh), w, fh)
        painter.setPen(QColor(0, 0, 0, int(alpha * 0.8)))
        painter.drawText(rect.translated(1, 1), int(Qt.AlignCenter), text)
        if crit:
            painter.drawText(rect.translated(2, 2), int(Qt.AlignCenter), text)
        painter.setPen(QColor(*(CRIT_FLOAT_INK if crit else _FLOAT_INK), alpha))
        painter.drawText(rect, int(Qt.AlignCenter), text)
    painter.restore()


def _draw_bang(painter, x, baseline, height, colour):
    """A bold exclamation mark standing on *baseline* at *x*, *height* tall:
    a wedge tapering down to a point, and a round dot under it, slanted to
    sit with italic text."""
    from PyQt5.QtGui import QPainterPath, QTransform
    w = height * 0.30
    path = QPainterPath()
    path.moveTo(0.0, -height)
    path.lineTo(w, -height)
    path.lineTo(w * 0.62, -height * 0.30)
    path.lineTo(w * 0.38, -height * 0.30)
    path.closeSubpath()
    d = w * 0.78
    path.addEllipse(QRectF(w / 2 - d / 2, -d, d, d))
    slant = QTransform(1, 0, -0.18, 1, 0, 0)          # lean like italic
    path = slant.map(path)
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    painter.translate(x, baseline)
    painter.setPen(Qt.NoPen)
    painter.setBrush(colour)
    painter.drawPath(path)
    painter.restore()


# ------------------------------------------------------------------ roll boxes
#: How a roll box's dice are drawn, and how far above the head its bottom
#: stands: room for "*fizzled*", HIT or MISS to rise between them.
ROLL_BOX_DIE = 40
ROLL_BOX_TITLE_H = 30
ROLL_BOX_GAP_PX = FLOAT_RISE_PX + 24.0
#: Who is rolling, or rolled against, by side: you, an ally, a foe.
ROLL_SIDE_INK = {"you": (255, 206, 96), "ally": (120, 214, 130), "foe": (238, 104, 88)}
#: A roll involving the player or a companion, and a fight between NPCs
#: alone (cooler, a little see-through: other people's business).
ROLL_BOX_BG = {"party": (16, 15, 24, 228), "npc": (18, 34, 44, 200)}
ROLL_BOX_EDGE = {"party": (150, 122, 64, 230), "npc": (80, 120, 140, 220)}


def _box_action(label, against_name):
    """A roll's label as a box's action: "Roll to hit Bandit" -> "ROLL TO
    HIT" (the target is named after it in its own colour), "Bandit rolls to
    hit you" -> "ROLL TO HIT", "Hunter: shield saving throw" -> "SHIELD SAVE"."""
    text = str(label or "Roll")
    low = text.lower()
    if "rolls to hit" in low or low.startswith("roll to hit"):
        return "ROLL TO HIT"
    if ":" in text:
        text = text.split(":", 1)[1].strip()
    text = text.replace("saving throw", "save")
    if against_name and text.lower().endswith(" " + str(against_name).lower()):
        text = text[: -len(str(against_name)) - 1]
    return text.upper()


def _box_verdict(result):
    """The settled line: "14 (need 7+) — HIT", "4 (need 9+) — MISS"."""
    total = result.get("roll_result", 0)
    target = result.get("target")
    if target is None:
        return f"ROLLED {total}", None
    passed = bool(result.get("success"))
    low = str(result.get("label", "")).lower()
    if "to hit" in low:
        word = "HIT" if passed else "MISS"
    elif "save" in low or "saving" in low:
        word = "SAVED" if passed else "FAILED"
    else:
        word = "SUCCESS" if passed else "FAILED"
    return f"{total} (need {target}+) — {word}", passed


def draw_roll_boxes(painter, session, viewport, width, height):
    """Every roll on screen in a small box over the one rolling: the
    player's own (gold name), an ally's (green) or a foe's (red); a fight
    between NPCs alone on a cooler background. The real dice tumble in it
    (game/ui/dice3d.py). Boxes never overlap: a box that would is lifted
    clear above the others, a thin line still pointing to its roller."""
    boxes = session.live_roll_boxes() if hasattr(session, "live_roll_boxes") else ()
    if not boxes or viewport is None:
        return
    try:
        import glm
        proj, view = viewport.projection_matrix, viewport.view_matrix
    except Exception:
        return
    anchored = []
    for box in boxes[:10]:
        actor = box.get("actor")
        pos = getattr(actor, "pos", None)
        props = getattr(actor, "properties", None) or {}
        if pos is None:
            continue
        head_y = pos[1] + float(props.get("sprite_height", 112) or 112) * 0.5 + 24.0
        sp = _world_to_screen(glm, proj, view, pos[0], head_y, pos[2], width, height)
        if sp is None and (props.get("is_player") or box.get("side") == "you"):
            sp = (width * 0.5, height * 0.4)       # first person: over the view's middle
        if sp is None:
            continue
        layout = _roll_box_layout(box, width)
        if layout is not None:
            anchored.append((sp, box, layout))
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    stack = True
    try:
        stack = bool(session.stack_dialogs_enabled())
    except Exception:
        pass
    for group in _stack_roll_boxes(anchored, width, height, stack=stack):
        for bx, by, sp, box, layout, pointer in group:
            _draw_roll_box(painter, box, layout, bx, by, sp, ROLL_BOX_GAP_PX, pointer=pointer)
    painter.restore()


#: Boxes may overlap this much (a share of the smaller box, across or down)
#: and stay over their rollers; any closer and they become one stack.
ROLL_BOX_OVERLAP_OK = 0.3
ROLL_BOX_STACK_GAP = 1      # stacked boxes sit locked together


def _is_attack(box) -> bool:
    return "to hit" in str((box.get("result") or {}).get("label", "")).lower()


def _stack_roll_boxes(anchored, width, height, stack=True):
    """Lay the boxes out: each right over its roller, a slight overlap
    allowed; boxes closer than that join one stack over their rollers, the
    attacker's roll always at the top (with *stack* off -- Settings > Game >
    "Stack dialogs" -- they stay over their rollers, overlapping).
    Returns groups of ``(x, y, anchor, box, layout, pointer)``, bottom box
    last in a stack."""
    natural = []
    for sp, box, layout in anchored:
        w, h = layout["w"], layout["h"]
        x = int(max(4, min(width - w - 4, sp[0] - w / 2)))
        y = int(sp[1] - ROLL_BOX_GAP_PX - h)
        natural.append((x, y, w, h))
    # Union boxes that overlap more than slightly.
    parent = list(range(len(anchored)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(natural)):
        for j in range(i + 1, len(natural)):
            xi, yi, wi, hi = natural[i]
            xj, yj, wj, hj = natural[j]
            across = min(xi + wi, xj + wj) - max(xi, xj)
            down = min(yi + hi, yj + hj) - max(yi, yj)
            if across <= 0 or down <= 0:
                continue
            if stack and across > ROLL_BOX_OVERLAP_OK * min(wi, wj) and \
                    down > ROLL_BOX_OVERLAP_OK * min(hi, hj):
                parent[find(i)] = find(j)
    clusters = {}
    for i in range(len(anchored)):
        clusters.setdefault(find(i), []).append(i)
    # The player's own box first, then nearest the bottom of the screen;
    # later ones keep clear of what is already placed.
    order = sorted(clusters.values(), key=lambda m: (
        all(anchored[i][1].get("side") != "you" for i in m),
        -max(anchored[i][0][1] for i in m)))
    placed = []

    def heavy(x, y, w, h):
        for (px, py, pw, ph) in placed:
            across = min(x + w, px + pw) - max(x, px)
            down = min(y + h, py + ph) - max(y, py)
            if across > ROLL_BOX_OVERLAP_OK * min(w, pw) and \
                    down > ROLL_BOX_OVERLAP_OK * min(h, ph):
                return True
        return False

    groups = []
    for members in order:
        # Attacks on top, then the rest (saves), each in roll order.
        members.sort(key=lambda i: (not _is_attack(anchored[i][1]), i))
        heights = [natural[i][3] for i in members]
        total = sum(heights) + ROLL_BOX_STACK_GAP * (len(members) - 1)
        widest = max(natural[i][2] for i in members)
        xs = [anchored[i][0][0] for i in members]
        bottom = min(natural[i][1] + natural[i][3] for i in members)
        above = (sum(xs) / len(xs), bottom - total)
        beside = [(min(xs) - 40 - widest / 2, None), (max(xs) + 40 + widest / 2, None)]
        chosen = None
        for centre, top in [above] + beside:
            top = max(4, bottom - total) if top is None else top
            left = centre - widest / 2
            if top < 4 or left < 4 or left + widest > width - 4 or top + total > height - 4:
                continue
            if not heavy(left, top, widest, total):
                chosen = (centre, top)
                break
        if chosen is None:
            chosen = (above[0], max(4, above[1]))
        centre, y = chosen
        group = []
        for k, i in enumerate(members):
            sp, box, layout = anchored[i]
            w, h = layout["w"], layout["h"]
            x = int(max(4, min(width - w - 4, centre - w / 2)))
            group.append((x, int(y), sp, box, layout, k == len(members) - 1))
            y += h + ROLL_BOX_STACK_GAP
        placed.append((int(centre - widest / 2), int(chosen[1]), int(widest), int(total)))
        groups.append(group)
    return groups


def _roll_box_layout(box, width):
    """What a roll box shows and how big it is, or None with nothing to show."""
    result = box.get("result") or {}
    visuals = _prepare_dice_animation(box, result)
    if not visuals:
        return None
    elapsed = float(box.get("elapsed", 0.0))
    settle = max((d["motion"]["delay"] + d["motion"]["duration"] for d in visuals), default=0.0)
    fade_start = max(DICE_ANIMATION_SHAKE + DICE_ANIMATION_ROLL, settle) + DICE_RESULT_HOLD_DURATION
    alpha = 255
    if elapsed > fade_start:
        alpha = max(0, int((fade_start + DICE_ANIMATION_FADE - elapsed) / DICE_ANIMATION_FADE * 255))
    if alpha <= 0:
        return None
    actor = box.get("actor")
    props = getattr(actor, "properties", None) or {}
    side = box.get("side") or "ally"
    against = box.get("against")
    name = "YOU" if side == "you" else str(props.get("display_name")
                                           or props.get("name") or "").upper()
    action = _box_action(result.get("label"), against[0] if against else "")
    parts = [(name, ROLL_SIDE_INK.get(side, (226, 224, 236))),
             (": " + action, (226, 224, 236))]
    if against and against[0]:
        parts.append((" " + str(against[0]).upper(), ROLL_SIDE_INK.get(against[1], (226, 224, 236))))
    details = []
    companion = box.get("companion")
    if companion:
        details.append(str(companion.get("detail") or
                           f"{companion.get('dice_notation', 'die')}: rolled "
                           f"{companion.get('roll_result', '?')}"))
    # (A critical needs no line here: "Crit!" floats just under the box.)
    die = ROLL_BOX_DIE
    # Small text in the small-text face (Texturina Light), never under 11px.
    title_font = T.font(12, bold=True, family="small")
    fm = QFontMetrics(title_font)
    title_w = sum(fm.horizontalAdvance(t) for t, _c in parts)
    detail_font = T.font(11, family="small")
    dm = QFontMetrics(detail_font)
    detail_w = max((dm.horizontalAdvance(t) for t in details), default=0)
    w = int(max(150, title_w + 20, detail_w + 20, len(visuals) * (die + 14) + 26))
    h = int(ROLL_BOX_TITLE_H + die + 20 + 22 + 18 * len(details) + 10)
    return {"visuals": visuals, "elapsed": elapsed, "alpha": alpha, "side": side,
            "parts": parts, "details": details, "title_font": title_font, "fm": fm,
            "title_w": title_w, "w": w, "h": h, "result": result}


def _draw_roll_box(painter, box, layout, bx, by, anchor, gap, pointer=True):
    """One roll box at (*bx*, *by*), pointing down to its roller's head at
    *anchor* (a thin line when it was lifted clear of another box)."""
    from . import dice3d
    visuals, elapsed, alpha = layout["visuals"], layout["elapsed"], layout["alpha"]
    side, parts, details = layout["side"], layout["parts"], layout["details"]
    w, h, fm, result = layout["w"], layout["h"], layout["fm"], layout["result"]
    die = ROLL_BOX_DIE
    count = len(visuals)
    kind = box.get("kind") if box.get("kind") in ROLL_BOX_BG else "party"
    bg = QColor(*ROLL_BOX_BG[kind])
    bg.setAlpha(int(bg.alpha() * alpha / 255))
    edge = QColor(*ROLL_BOX_EDGE[kind])
    edge.setAlpha(int(edge.alpha() * alpha / 255))
    ax, ay = anchor[0], anchor[1] - gap
    tip = max(bx + 10, min(bx + w - 10, ax))
    if pointer and (by + h + 9 < ay - 2 or abs(tip - ax) > 2):
        # The bottom of a stack, lifted above or set beside its roller: a
        # thin line to it.
        painter.setPen(QPen(edge, 1.2))
        painter.drawLine(QPointF(tip, by + h + 9), QPointF(ax, ay))
    painter.setPen(QPen(edge, 1.5))
    painter.setBrush(bg)
    painter.drawRoundedRect(QRectF(bx, by, w, h), 7, 7)
    if pointer:
        painter.drawPolygon(QPolygonF([QPointF(tip - 7, by + h - 1), QPointF(tip + 7, by + h - 1),
                                       QPointF(tip, by + h + 9)]))
    painter.setFont(layout["title_font"])
    x = bx + (w - layout["title_w"]) / 2.0
    for text, ink in parts:
        painter.setPen(QColor(*ink, alpha))
        painter.drawText(QPointF(x, by + 20), text)
        x += fm.horizontalAdvance(text)
    settled = True
    first_done = False           # the roll's own (first) die has landed
    # The player's dice in colour, anyone else's greyscale; never two alike.
    finish = dice3d.finishes(count, side == "you", visuals[0].get("shade", 0) if visuals else 0)
    for index, d in enumerate(visuals):
        cx = bx + w / 2.0 + (index - (count - 1) / 2.0) * (die + 14)
        cy = by + ROLL_BOX_TITLE_H + die / 2.0
        m = d["motion"]
        if elapsed < m["delay"]:
            settled = False
            continue
        local = elapsed - m["delay"]
        rotation, dx, dy, done = dice3d.pose(d["sides"], d["value"], m, local)
        settled = settled and done
        if index == 0:
            first_done = done
        body, ink = finish[index]
        dice3d.draw_die(painter, d["sides"], d["value"], cx + dx * die * 0.5,
                        cy + dy * die * 0.45, die, rotation, alpha=alpha,
                        body=body, ink=ink,
                        tumbling=not done, flicker=int(local * 18.0) + index * 5)
        if d.get("role"):
            T.text_in(painter, QRect(int(cx - 36), int(cy + die / 2 - 1), 72, 13),
                      "TO HIT" if d["role"] == "hit" else "DAMAGE", size=11,
                      color=QColor(170, 166, 184, alpha), align=T.ALIGN_CENTER,
                      bold=True, family="small")
    line_y = by + ROLL_BOX_TITLE_H + die + 20
    # Each line as its die lands: the verdict with the roll's own die, the
    # damage once the damage die has landed too -- never ahead of its dice.
    if first_done:
        verdict, passed = _box_verdict(result)
        ink = (_verdict_color(passed, alpha) if passed is not None
               else QColor(255, 214, 130, alpha))
        if passed is not None and box.get("against") and box["against"][1] == "you" \
                and side != "you":
            ink = _verdict_color(not passed, alpha)       # their hit is bad news
        T.text_in(painter, QRect(bx, line_y, w, 18), verdict, size=13, color=ink,
                  align=T.ALIGN_CENTER, bold=True, family="small")
        for k, text in enumerate(details if settled else ()):
            T.text_in(painter, QRect(bx, line_y + 22 + 18 * k, w, 16), text, size=11,
                      color=QColor(200, 196, 214, alpha), align=T.ALIGN_CENTER,
                      family="small")
    else:
        T.text_in(painter, QRect(bx, line_y, w, 18), "rolling…", size=11,
                  color=QColor(170, 166, 184, alpha), align=T.ALIGN_CENTER,
                  italic=True, family="small")


#: "Block" over the player's head while the block is held: its ink, and how
#: far above the head it stands (clear of a "*fizzled*" rising from there).
BLOCK_TEXT = "Block"
_BLOCK_INK = (150, 200, 255)
BLOCK_LIFT = 44.0


def draw_player_block(painter, session, viewport, width, height):
    """While the player holds a block: "Block" over their head, steady for as
    long as it is held (game.runtime.MiniwindSession.toggle_block)."""
    if viewport is None or not getattr(session, "_blocking", False):
        return
    if session.game.character.is_dead:
        return
    pos = session._player_pos()
    if pos is None:
        return
    try:
        import glm
        proj, view = viewport.projection_matrix, viewport.view_matrix
    except Exception:
        return
    sp = _world_to_screen(glm, proj, view, pos[0], pos[1] + 112 * 0.5 + BLOCK_LIFT, pos[2],
                          width, height)
    if sp is None:
        # Seen from inside the player's own head (first person): over the
        # middle of the view, as the floats are.
        sp = (width * 0.5, height * 0.36)
    import game.ui.fonts as fonts
    font = fonts.dialogue_font(13)
    font.setBold(True)
    fm = QFontMetrics(font)
    w = fm.horizontalAdvance(BLOCK_TEXT) + 10
    rect = QRect(int(sp[0] - w / 2), int(sp[1] - fm.height()), w, fm.height())
    painter.save()
    painter.setFont(font)
    painter.setPen(QColor(0, 0, 0, 200))
    painter.drawText(rect.translated(1, 1), int(Qt.AlignCenter), BLOCK_TEXT)
    painter.setPen(QColor(*_BLOCK_INK))
    painter.drawText(rect, int(Qt.AlignCenter), BLOCK_TEXT)
    painter.restore()


#: The widest a speech plate or thought bubble grows before its text wraps.
PLATE_MAX_W = 340


def _plate_lines(fm, text, max_w, max_lines=2):
    """*text* word-wrapped to *max_w* pixels, at most *max_lines* lines (the
    last elided if it still does not fit)."""
    lines, line = [], ""
    for word in str(text).split():
        trial = f"{line} {word}".strip()
        if line and fm.horizontalAdvance(trial) > max_w:
            lines.append(line)
            line = word
        else:
            line = trial
    lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines - 1] + [" ".join(lines[max_lines - 1:])]
    return [fm.elidedText(l, Qt.ElideRight, max_w) for l in lines]


#: Thought bubbles: a pale cloud trailing two small puffs down to the
#: head, so a thought never reads as something said aloud (draw_barks).
_THOUGHT_FILL = (232, 232, 244)
_THOUGHT_INK = (52, 48, 70)


def draw_thoughts(painter, session, viewport, width, height):
    """What people are thinking, in a thought bubble over their heads: the
    farmer heading home hungry, the witness going to the watch, the coward
    running. Sits above anything the same person is saying aloud."""
    if viewport is None:
        return
    thoughts = session.live_thoughts() if hasattr(session, "live_thoughts") else ()
    if not thoughts:
        return
    try:
        import glm
        proj, view = viewport.projection_matrix, viewport.view_matrix
    except Exception:
        return
    import game.ui.fonts as fonts
    font = fonts.dialogue_font(10)
    fm = QFontMetrics(font)
    speaking = {id(thing) for thing, _t, _l in
                (session.live_barks() if hasattr(session, "live_barks") else ())}
    painter.save()
    painter.setFont(font)
    painter.setRenderHint(painter.Antialiasing, True)
    r, g, b = _THOUGHT_FILL
    for thing, text, left in thoughts[:8]:
        if _has_roll_box(session, thing):
            continue                    # its roll box is over its head
        head_y = thing.pos[1] + float(thing.properties.get("sprite_height", 112)) * 0.5 + 40.0
        sp = _world_to_screen(glm, proj, view, thing.pos[0], head_y, thing.pos[2],
                              width, height)
        if sp is None:
            continue
        alpha = int(255 * max(0.0, min(1.0, left / 0.4)))
        cx, cy = int(sp[0]), int(sp[1]) - (30 if id(thing) in speaking else 0)
        lines = _plate_lines(fm, text, PLATE_MAX_W - 22)
        w = max(fm.horizontalAdvance(line) for line in lines) + 22
        h = 6 + fm.height() * len(lines)
        rect = QRect(cx - w // 2, cy - 16 - h, w, h)
        painter.setPen(QPen(QColor(120, 116, 150, alpha), 1))
        painter.setBrush(QColor(r, g, b, int(alpha * 0.92)))
        painter.drawRoundedRect(rect, 12, 12)
        painter.drawEllipse(QPoint(cx - 6, cy - 10), 5, 4)
        painter.drawEllipse(QPoint(cx - 1, cy - 2), 3, 2)
        painter.setPen(QColor(*_THOUGHT_INK, alpha))
        painter.drawText(rect, int(Qt.AlignCenter), "\n".join(lines))
    painter.restore()


#: Mark images, by mark (assets/sprites/marks); loaded on first use.
_MARK_FILES = {"!": "exclamation.png", "?": "question.png"}
_MARK_PIXMAPS = {}
#: When each NPC's current mark appeared: id(npc) -> (mark, monotonic time),
#: for the pop-in.
_MARK_SINCE = {}
#: On-screen height of a mark (px), its pop-in time (s), and its bob.
MARK_HEIGHT = 34
MARK_POP_SECONDS = 0.22
MARK_BOB_PX = 3.0


def _mark_pixmap(mark):
    if mark not in _MARK_PIXMAPS:
        pm = None
        name = _MARK_FILES.get(mark)
        if name:
            root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            path = os.path.join(root, "assets", "sprites", "marks", name)
            if os.path.exists(path):
                loaded = QPixmap(path)
                if not loaded.isNull():
                    pm = loaded.scaledToHeight(MARK_HEIGHT * 2, Qt.SmoothTransformation)
        _MARK_PIXMAPS[mark] = pm
    return _MARK_PIXMAPS[mark]


def draw_head_marks(painter, session, viewport, width, height, now=None):
    """Draw "!" / "?" above every NPC that has one (session.head_marks()).

    Each mark pops in when it appears and bobs gently while it stays, so a
    guard turning to come for the player catches the eye. Overhead only.
    """
    if viewport is None:
        return
    marks = getattr(session, "head_marks", None)
    if marks is None:
        return
    try:
        import glm
        proj = viewport.projection_matrix
        view = viewport.view_matrix
    except Exception:
        return
    import time as _time
    now = _time.monotonic() if now is None else now
    current = marks()
    live = set()
    painter.save()
    painter.setRenderHint(painter.SmoothPixmapTransform, True)
    for npc, mark in current:
        key = id(npc)
        live.add(key)
        since = _MARK_SINCE.get(key)
        if since is None or since[0] != mark:
            since = (mark, now)
            _MARK_SINCE[key] = since
        pm = _mark_pixmap(mark)
        if pm is None:
            continue
        head_y = npc.pos[1] + float(npc.properties.get("sprite_height", 112)) * 0.5 + 26.0
        sp = _world_to_screen(glm, proj, view, npc.pos[0], head_y, npc.pos[2], width, height)
        if sp is None:
            continue
        age = now - since[1]
        # Pop: grow past full size and settle (a small overshoot).
        t = min(1.0, age / MARK_POP_SECONDS)
        pop = 1.0 + 0.25 * math.sin(math.pi * t) if t < 1.0 else 1.0
        pop *= min(1.0, 0.35 + t)
        bob = MARK_BOB_PX * math.sin(age * 4.0)
        h = MARK_HEIGHT * pop
        w = h * pm.width() / float(pm.height())
        painter.drawPixmap(QRectF(sp[0] - w / 2.0, sp[1] - h - 4.0 + bob, w, h),
                           pm, QRectF(pm.rect()))
    painter.restore()
    for key in [k for k in _MARK_SINCE if k not in live]:
        del _MARK_SINCE[key]


def draw_escort_ring(painter, session, viewport, width, height):
    """While the player is being escorted to prison, ring the escort guard on
    the ground at the breakaway radius, so it's visually obvious how far the
    player may stray before the guard turns hostile."""
    if viewport is None or getattr(session, "_arrest_state", "") != "escorting":
        return
    guard = getattr(session, "_arrest_guard", None)
    if guard is None:
        return
    try:
        import glm
        proj = viewport.projection_matrix
        view = viewport.view_matrix
    except Exception:
        return
    gx, gy, gz = guard.pos[0], guard.pos[1], guard.pos[2]
    segments = 48
    screen_pts = []
    for i in range(segments + 1):
        ang = (i / segments) * 2.0 * math.pi
        wx = gx + math.cos(ang) * ESCORT_BREAKAWAY_DISTANCE
        wz = gz + math.sin(ang) * ESCORT_BREAKAWAY_DISTANCE
        screen_pts.append(_world_to_screen(glm, proj, view, wx, gy, wz, width, height))
    painter.save()
    pen = QPen(QColor(250, 210, 90, 190))
    pen.setWidth(2)
    painter.setPen(pen)
    prev = None
    for sp in screen_pts:
        if sp is not None and prev is not None:
            painter.drawLine(QPointF(prev[0], prev[1]), QPointF(sp[0], sp[1]))
        prev = sp
    painter.restore()


def draw_fade(painter, session, width, height):
    """Full-screen fade-to-black overlay, driven by session.fade_alpha() —
    used to mask a hard teleport cut (e.g. paying off a bounty)."""
    alpha = 0.0
    fade_alpha = getattr(session, "fade_alpha", None)
    if callable(fade_alpha):
        alpha = fade_alpha()
    if alpha <= 0.0:
        return
    painter.save()
    painter.fillRect(QRect(0, 0, int(width), int(height)),
                      QColor(0, 0, 0, int(min(255.0, max(0.0, alpha)))))
    painter.restore()


#: Speech bubble size (px): its body, corner radius, and the tail under it.
BUBBLE_W, BUBBLE_H = 42, 34
BUBBLE_RADIUS = 10
BUBBLE_TAIL_W, BUBBLE_TAIL_H = 7, 11
BUBBLE_FONT_PT = 19


def _paint_bubble(painter, cx, cy, kind):
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    quest = (kind == "quest")
    glyph = "!" if quest else "…"
    fill = QColor(250, 210, 90) if quest else QColor(235, 235, 240)
    edge = QColor(120, 90, 20) if quest else QColor(60, 60, 70)
    text_col = QColor(60, 40, 0) if quest else QColor(40, 40, 50)
    rect = QRect(cx - BUBBLE_W // 2, cy - BUBBLE_H, BUBBLE_W, BUBBLE_H)
    painter.setPen(QPen(edge, 1.5))
    painter.setBrush(fill)
    painter.drawRoundedRect(rect, BUBBLE_RADIUS, BUBBLE_RADIUS)
    # little tail pointing down at the head
    tail = QPolygon([QPoint(cx - BUBBLE_TAIL_W, cy - 1), QPoint(cx + BUBBLE_TAIL_W, cy - 1),
                     QPoint(cx, cy + BUBBLE_TAIL_H)])
    painter.drawPolygon(tail)
    # cover the tail's top edge so body and tail read as one shape
    painter.setPen(Qt.NoPen)
    painter.drawRect(QRect(cx - BUBBLE_TAIL_W + 1, cy - 3, BUBBLE_TAIL_W * 2 - 1, 3))
    painter.setPen(text_col)
    import game.ui.fonts as fonts
    painter.setFont(fonts.dialogue_font(BUBBLE_FONT_PT))
    painter.drawText(rect, Qt.AlignCenter, glyph)
    painter.restore()


def _draw_bubble(painter, cx, cy, kind):
    # The same two pictures over every NPC, every frame: painted once each.
    pad = 2
    w = BUBBLE_W + pad * 2
    h = BUBBLE_H + BUBBLE_TAIL_H + pad * 2
    ox, oy = w // 2, BUBBLE_H + pad
    pm = T.sprite(painter, ("bubble", kind, painter.font().key()), w, h,
                  lambda p: _paint_bubble(p, ox, oy, kind))
    if pm is not None:
        painter.drawPixmap(cx - ox, cy - oy, pm)
    else:
        _paint_bubble(painter, cx, cy, kind)


def _draw_clock(painter, session, width):
    if not session.show_clock:
        return
    clock = session.clock
    hour = clock.hour
    h_int = int(hour)
    m_int = int((hour - h_int) * 60.0)
    day_name = getattr(clock, "day_name", "")
    day_line = f"{day_name} · Day {clock.day}" if day_name else f"Day {clock.day}"

    radius = 34
    cx = width - radius - 16
    cy = radius + 16
    # The face changes once a game minute: painted then, blitted between.
    left, top = cx - radius - 20, cy - radius - 2
    w, h = radius * 2 + 40, radius * 2 + 2 + 3 + 34
    pm = T.sprite(painter, ("clock", h_int, m_int, day_line), w, h,
                  lambda p: _paint_clock(p, radius + 20, radius + 2, radius,
                                         h_int, m_int, day_line))
    if pm is not None:
        painter.drawPixmap(left, top, pm)
    else:
        _paint_clock(painter, cx, cy, radius, h_int, m_int, day_line)
    return QRect(left, top, w, h)


def _paint_clock(painter, cx, cy, radius, h_int, m_int, day_line):
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)

    # face background
    painter.setPen(QPen(T.GILD, 2))
    painter.setBrush(QColor(16, 15, 24, 220))
    painter.drawEllipse(QPointF(cx, cy), radius, radius)

    # hour tick marks
    for i in range(12):
        angle = math.radians(i * 30 - 90)
        inner_r = radius - 6 if i % 3 == 0 else radius - 4
        outer_r = radius - 2
        x1 = cx + math.cos(angle) * inner_r
        y1 = cy + math.sin(angle) * inner_r
        x2 = cx + math.cos(angle) * outer_r
        y2 = cy + math.sin(angle) * outer_r
        pen_w = 2 if i % 3 == 0 else 1
        painter.setPen(QPen(T.GOLD_BRIGHT if i % 3 == 0 else T.GILD, pen_w))
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    # hour hand (to the minute: it turns half a degree a minute)
    h_angle = math.radians(((h_int % 12) + m_int / 60.0) * 30 - 90)
    h_len = radius * 0.5
    painter.setPen(QPen(T.GOLD_BRIGHT, 3, Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(QPointF(cx, cy),
                     QPointF(cx + math.cos(h_angle) * h_len,
                             cy + math.sin(h_angle) * h_len))

    # minute hand
    m_angle = math.radians(m_int * 6 - 90)
    m_len = radius * 0.72
    painter.setPen(QPen(T.PARCH, 2, Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(QPointF(cx, cy),
                     QPointF(cx + math.cos(m_angle) * m_len,
                             cy + math.sin(m_angle) * m_len))

    # centre dot
    painter.setPen(Qt.NoPen)
    painter.setBrush(T.GOLD_BRIGHT)
    painter.drawEllipse(QPointF(cx, cy), 3, 3)

    # digital time + weekday / day below the clock face
    box = QRect(int(cx - radius - 20), int(cy + radius + 3), int(radius * 2 + 40), 34)
    T.text_in(painter, QRect(box.x(), box.y(), box.width(), 16),
              f"{h_int:02d}:{m_int:02d}", size=13, color=T.GOLD_BRIGHT,
              align=T.ALIGN_CENTER, bold=True)
    T.text_in(painter, QRect(box.x(), box.y() + 16, box.width(), 14),
              day_line, size=9, color=T.DIM, align=T.ALIGN_CENTER,
              family="Segoe UI")
    painter.restore()




def _weapon_icon_pixmap(weapon_def, size=26):
    if weapon_def is None:
        return None
    try:
        import game.item_icons as item_icons
        return item_icons.icon_pixmap(weapon_def.id, None, size)
    except Exception:
        return None


def _spell_icon_pixmap(spell, size=26):
    try:
        import game.item_icons as item_icons
        return item_icons.spell_pixmap(spell.id, size)
    except Exception:
        return None


#: The weapon/spell box: top right, under the clock (_draw_clock).
ACTIVE_W, ACTIVE_H = 268, 60
ACTIVE_TOP = 132
ACTIVE_MARGIN = 16
ACTIVE_ICON = 26


def _draw_active(painter, session, c, width, height):
    """The two hands and the mouse button that uses each one: the left
    button the left hand, the right button the right hand."""
    x = width - ACTIVE_W - ACTIVE_MARGIN
    y = ACTIVE_TOP
    rect = QRect(x, y, ACTIVE_W, ACTIVE_H)
    T.panel(painter, x, y, ACTIVE_W, ACTIVE_H, radius=8, shadow=False)
    # Worn metal armour stops every spell: a spell in hand is greyed out.
    locked = spell_lock.locked(c)
    for i, (physical, mouse) in enumerate((("left", "LMB"), ("right", "RMB"))):
        hand = eq.relative_hand(c, physical)
        spell = eq.hand_spell(c, hand)
        item = eq.hand_weapon(c, hand)
        if hand == "off" and item is None:
            item = eq.shield(c) or eq.light_source(c)
            if item is None and eq.is_two_handed(eq.weapon(c)):
                item = eq.weapon(c)                 # both hands on it
        top = y + 5 + i * 27
        tx = x + 14
        if spell is not None:
            icon = spell_lock.grey(_spell_icon_pixmap(spell, 22), locked)
            if icon is not None and not icon.isNull():
                painter.drawPixmap(x + 12, top, icon)
            else:
                orb = spell_lock.colour(spell.color, locked)
                painter.setBrush(orb)
                painter.setPen(QPen(orb.darker(160), 1))
                painter.drawEllipse(x + 14, top + 2, 16, 16)
            tx = x + 40
        else:
            icon = _weapon_icon_pixmap(item, 22)
            if icon is not None and not icon.isNull():
                painter.drawPixmap(x + 12, top, icon)
                tx = x + 40
        label = spell.name if spell else item.name if item else "Unarmed" if hand == "main" else "Empty"
        if item is not None and item.get("kind") in rpg_items.RANGED_KINDS:
            ammo = eq.ammo_for(c, item)
            if ammo is not None:
                import game.rpg.inventory as inv
                label += f" ({inv.quantity(c.inventory, ammo.id)})"
        T.text_in(painter, QRect(tx, top, x + ACTIVE_W - 52 - tx, 21), label, size=10,
                  color=(spell_lock.GREY if spell is not None and locked
                         else T.GOLD_BRIGHT if spell or item else T.DIM),
                  family="Segoe UI", align=int(Qt.AlignLeft | Qt.AlignVCenter))
        T.text(painter, x + ACTIVE_W - 38, top + 16, mouse, size=8, color=T.DIM, family="Segoe UI")
    return rect


def _draw_law(painter, session, width):
    import game.ui.fonts as fonts
    if not hasattr(session, "law_status"):
        return
    status = session.law_status()
    phase = status["phase"]
    if not status["bounty"] and not status["curfew"]:
        return
    labels = {"pursuit": "HUE AND CRY", "search": "THE WATCH IS SEARCHING",
              "writ": "BLOOD WRIT" if status["blood"] else "WANTED BY THE WATCH"}
    label = labels.get(phase, "TOWN CURFEW")
    box = QRect(width // 2 - 170, 56, 340, 49)
    painter.fillRect(box, QColor(28, 18, 22, 225))
    T.text_in(painter, QRect(box.x(), 59, 340, 21), label, size=11,
              color=QColor(245, 130, 92), align=T.ALIGN_CENTER,
              family=fonts.dialogue_family())
    caption = f'{status["region"]} · {status["bounty"]} gold'
    if status["curfew"]:
        caption += " · Curfew"
    T.text_in(painter, QRect(box.x(), 81, 340, 18), caption, size=9,
              color=T.PARCH, align=T.ALIGN_CENTER, family=fonts.dialogue_family())
    if phase == "search":
        painter.fillRect(QRect(box.x(), 103, 340, 3), QColor(70, 42, 38))
        painter.fillRect(QRect(box.x(), 103, int(340 * status["remaining"]), 3),
                         QColor(215, 110, 70))
    return QRect(box.x(), box.y(), box.width(), 51)


def _draw_status_flags(painter, session, c, width, height):
    flags = []
    if session.game.sneaking:
        flags.append(("SNEAK", QColor(150, 150, 170)))
    if session._blocking:
        flags.append(("BLOCK", QColor(120, 170, 230)))
    for eff in ("shield", "invisibility", "night_eye", "berserk"):
        if c.effect_magnitude(eff) > 0:
            flags.append((eff.upper().replace("_", " "), QColor(180, 150, 220)))
    if not flags:
        return None
    cx = width // 2 - len(flags) * 45
    y = height - layout.STATUS_BOTTOM        # clear of the inventory strip
    for i, (label, col) in enumerate(flags):
        rx = cx + i * 92
        painter.fillRect(QRect(rx, y, 84, 20), QColor(10, 10, 16, 180))
        T.text_in(painter, QRect(rx, y, 84, 20), label, size=9,
                  color=col, align=T.ALIGN_CENTER, bold=True, family="Segoe UI")
    return QRect(cx, y, len(flags) * 92 - 8, 20)


def _draw_quest_tracker(painter, session, width):
    try:
        g = session.quest_guidance()
    except Exception:
        g = None
    if not g:
        return
    x = width - 300
    y = 48
    T.text(painter, x, y, "◈ " + g["name"], size=11, color=T.GOLD_BRIGHT, bold=True)
    # The action line is the "what to do now": a short imperative plus any
    # countable progress, so the player can see how to complete the stage.
    action = g.get("action") or g.get("objective")
    if action:
        line = "• " + action
        prog = g.get("progress")
        if prog:
            line += f"   [{prog}]"
        T.text(painter, x + 6, y + 18, line, size=9, color=T.PARCH, family="Segoe UI")
    dist = _fmt_distance(g.get("distance"))
    if dist:
        T.text(painter, x + 6, y + 34,
               f"➤ {dist} away  ·  press {controls.label('quest')} for details",
               size=8, color=T.DIM, family="Segoe UI")
    else:
        T.text(painter, x + 6, y + 34, f"press {controls.label('quest')} for details",
               size=8, color=T.DIM, family="Segoe UI")
    # Up to the clock's left edge (_draw_clock), so its button clears the clock.
    return QRect(x - 4, y - 16, 192, 56)


def _draw_quest_arrow(painter, session, width, height):
    """One GTA1-style arrow per active quest, orbiting the player's head and
    pointing at that quest's objective (location / NPC / foe / item). The
    player can carry several quests at once, so each arrow rings the head on
    its own radius in its own colour (see :data:`_QUEST_ARROW_COLORS`). The
    player sits at screen centre; the bearing is set by the camera, NOT the
    player's facing:
      * Overhead "north" (default, GTA-1 style): map fixed with world -Z up and
        +X right, so spinning in place leaves the arrows put.
      * Overhead "player": the map turns with the player, so 'up' is the
        player's heading.
      * First person: the arrow shows the target relative to where you look.
    """
    try:
        targets = session.quest_arrow_targets()
    except Exception:
        # Fall back to the single-target API for older sessions.
        try:
            one = session.quest_arrow_target()
        except Exception:
            one = None
        targets = [(one[0], "", one[1])] if one else []
    waypoint = session.waypoint() if hasattr(session, "waypoint") else None
    if not targets and waypoint is None:
        return
    logic = getattr(session, "logic", None)
    player = fio.player(logic)
    ppos = getattr(player, "pos", None)
    if ppos is None:
        return

    overhead = False
    try:
        overhead = bool(fio.is_overhead(logic))
    except Exception:
        overhead = False
    hx = hz = 0.0
    if overhead:
        a = fio.navigation_heading(logic)
        hx, hz = math.sin(a), math.cos(a)
    pangle = getattr(player, "angle", 0.0)

    cx, cy = width // 2, height // 2
    for i, entry in enumerate(targets):
        pos = entry[0]
        dx = float(pos[0]) - float(ppos[0])
        dz = float(pos[2]) - float(ppos[2])
        if abs(dx) < 1e-3 and abs(dz) < 1e-3:
            continue
        if overhead:
            # Screen bearing from the camera's ground right/up basis (right =
            # (-hz, hx), up = (hx, hz)); 0 = up, clockwise-positive.
            rel = math.atan2(-dx * hz + dz * hx, dx * hx + dz * hz)
        else:
            rel = _wrap(math.atan2(dx, dz) - pangle)
        color = _QUEST_ARROW_COLORS[i % len(_QUEST_ARROW_COLORS)]
        # Stagger each quest onto its own ring so arrows in the same direction
        # sit as concentric chevrons instead of overlapping.
        orbit = 58.0 + i * 11.0
        _draw_one_quest_arrow(painter, cx, cy, rel, orbit, color,
                              _fmt_distance(math.hypot(dx, dz)), width, height)
    if waypoint is not None:
        # The player's own map waypoint: always orange, on a ring of its own
        # outside the quests'.
        dx = float(waypoint[0]) - float(ppos[0])
        dz = float(waypoint[1]) - float(ppos[2])
        if abs(dx) > 1e-3 or abs(dz) > 1e-3:
            if overhead:
                rel = math.atan2(-dx * hz + dz * hx, dx * hx + dz * hz)
            else:
                rel = _wrap(math.atan2(dx, dz) - pangle)
            _draw_one_quest_arrow(painter, cx, cy, rel, 58.0 + len(targets) * 11.0,
                                  T.WAYPOINT, _fmt_distance(math.hypot(dx, dz)),
                                  width, height)


def _draw_one_quest_arrow(painter, cx, cy, rel, orbit, color, dist, width, height):
    """Draw a single coloured chevron at bearing *rel* on the ring of radius
    *orbit*, captioned with *dist* just beyond it."""
    ax = cx + math.sin(rel) * orbit
    ay = cy - math.cos(rel) * orbit

    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    painter.translate(ax, ay)
    painter.rotate(math.degrees(rel))   # 0 rad points up; +rel rotates clockwise
    # A chunky chevron pointing 'up' (outward from the head toward the target).
    tip, halfw, back = -14.0, 11.0, 6.0
    arrow = QPolygon([
        QPoint(0, int(tip)),
        QPoint(int(halfw), int(back)),
        QPoint(0, int(back - 5)),
        QPoint(-int(halfw), int(back)),
    ])
    painter.setPen(QPen(QColor(40, 30, 0), 2))
    painter.setBrush(color)
    painter.drawPolygon(arrow)
    painter.restore()

    # Caption the arrow with the distance to the objective so the ring reads as
    # "the objective is this way, this far" rather than a bare pointer. Drawn
    # just outside the arrow along the same bearing, clamped to stay on screen,
    # tinted to match the arrow so it reads as belonging to the same quest.
    if dist and dist != "here":
        lx = cx + math.sin(rel) * (orbit + 18)
        ly = cy - math.cos(rel) * (orbit + 18)
        lx = max(24, min(width - 60, lx))
        ly = max(24, min(height - 24, ly))
        painter.save()
        painter.setPen(QColor(20, 16, 8))
        painter.setFont(T.font(9, bold=True, family="Segoe UI"))
        painter.drawText(QRect(int(lx - 39), int(ly - 8), 80, 16),
                         T.ALIGN_CENTER, dist)   # soft shadow
        painter.setPen(color.lighter(115))
        painter.drawText(QRect(int(lx - 40), int(ly - 9), 80, 16),
                         T.ALIGN_CENTER, dist)
        painter.restore()


def _draw_compass(painter, session, width, height):
    """A small heading strip centred at the top (N/E/S/W)."""
    player = fio.player(session.logic)
    if player is None:
        return
    angle = getattr(player, "angle", 0.0)
    cx = width // 2
    cw = 260
    x = cx - cw // 2
    y = 14
    painter.save()
    painter.fillRect(QRect(x, y, cw, 22), QColor(10, 10, 16, 150))
    painter.setPen(T.GILD)
    painter.drawRect(QRect(x, y, cw, 22))
    # marks: N at heading 0
    dirs = [("N", 0), ("E", math.pi / 2), ("S", math.pi), ("W", -math.pi / 2)]
    for label, a in dirs:
        rel = _wrap(a - angle)
        if abs(rel) > math.pi * 0.7:
            continue
        px = cx + int(rel / (math.pi * 0.7) * (cw / 2 - 12))
        T.text(painter, px - 4, y + 16, label, size=10,
               color=T.GOLD_BRIGHT if label == "N" else T.PARCH, bold=True, family="Segoe UI")
    painter.setPen(QColor(255, 230, 160))
    painter.drawLine(cx, y, cx, y + 22)
    painter.restore()
    return QRect(x, y, cw, 23)


def _wrap(a):
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


def _draw_target_panel(painter, session, width, height):
    """Who the player is fighting, bottom right, beside the shortcut bar
    (game/ui/target_panel.py) -- name, Armour Class, chance to hit and the
    health / armour bar. It replaced the crosshair plate at the top."""
    from . import target_panel
    bar = None if layout.collapsed("strip") else layout.screen_rect("strip", width, height)
    target_panel.draw(painter, session, width, height, bar_rect=bar)


def _target_odds(c, target_props):
    """What the player needs to roll against the target under the crosshair,
    before acting: "AC 12  ·  To hit: need 7+ (70%)  ·  Critical: need 18+ (15%)".

    Every attack rolls d20 + the attack bonus against the target's Armour
    Class, shown first; a readied spell shows its cast check instead.
    """
    import game.rpg.combat as combat
    try:
        if c.active_weapon_kind == "spell":
            spell = rpg_magic.get(c.active_spell or "")
            if spell is None or spell.base_cost <= 0:
                return ""
            chance = rpg_magic.cast_chance(c, spell)
            return (f"Cast {spell.name}: need {check_target(chance)}+ "
                    f"({chance * 100:.0f}%)")
        if c.active_weapon_kind == rpg_items.KIND_STAFF:
            return ""                    # a staff looses its bound spell
        odds = combat.attack_odds(c, target_props)
    except (AttributeError, TypeError, ValueError, ZeroDivisionError):
        return ""
    # Every attack rolls d20 + your bonus against the target's Armour Class.
    hit = (f"AC {odds['ac']}  ·  To hit: need {odds['hit_target']}+ "
           f"({odds['hit_chance'] * 100:.0f}%)")
    return (f"{hit}  ·  Critical: need {odds['crit_target']}+ "
            f"({odds['crit_chance'] * 100:.0f}%)")

def draw_dice_preview(painter, animation, width, height):
    """Draw the dice panel for an editor-side preview animation."""
    _draw_dice_roll(painter, SimpleNamespace(dice_animation=animation), width, height)


_DICE_IMAGE_CACHE = {}
_DICE_MAX_COLUMNS = 6


def _dice_image(filename):
    """Load and cache one dice image from the project's dice asset folder."""
    cached = _DICE_IMAGE_CACHE.get(filename)
    if cached is not None:
        return cached
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    path = os.path.join(root, "assets", "dice_imgs", filename)
    image = QPixmap(path)
    if image.isNull():
        return None
    _DICE_IMAGE_CACHE[filename] = image
    return image


def _dice_face_image(value):
    """Return a valid d6 face image, falling back to a known face asset."""
    value = max(1, min(6, int(value)))
    image = _dice_image(f"d6_{value}.png")
    if image is not None:
        return image
    return _dice_image("d6_1.png")


def _dice_entries(result):
    """Expand result components into one visual entry per physical die."""
    entries = []
    for component in result.get("components", []) or []:
        notation = str(component.get("notation", "")).lower().replace(" ", "")
        if "d" not in notation:
            continue
        try:
            sides = int(notation.split("d", 1)[1])
        except (TypeError, ValueError):
            continue
        values = component.get("roll_details") or []
        for value in values:
            entries.append({"sides": max(2, sides), "value": int(value)})
    if entries:
        return entries
    return [{"sides": 20, "value": int(value)}
            for value in result.get("roll_details", [])]


def _prepare_dice_animation(animation, result):
    """Every displayed die's own throw (game/ui/dice3d.py): the roll's dice,
    then a hit's damage die (``animation["companion"]``) thrown a moment
    later, each with its own spin, timing and bounce -- never in step."""
    companion = animation.get("companion")
    key = "companion" if companion else "solo"
    if animation.get("dice_visuals_for") == key:
        return animation["dice_visuals"]
    from . import dice3d
    visuals = []
    entries = [dict(e, role="hit" if companion else "") for e in _dice_entries(result)]
    if companion:
        entries += [dict(e, role="damage") for e in _dice_entries(companion)]
    base = int(animation.get("seed", 0) or 0) or (id(animation) & 0xFFFF)
    speed = dice3d.roll_speed(base)             # this roll's own pace
    long_roll = dice3d.rattles(base)            # now and then, a rattle after landing
    for index, entry in enumerate(entries):
        seed = base * 31 + index * 977 + entry["sides"] * 13 + entry["value"] * 7
        delay = dice3d.SECOND_DIE_DELAY if entry["role"] == "damage" else 0.0
        visuals.append(dict(entry, motion=dice3d.motion(seed, delay=delay, speed=speed,
                                                        rattle=long_roll),
                            shade=dice3d.pick_shade(base)))      # the roll's finishes
    animation["dice_visuals"] = visuals
    animation["dice_visuals_for"] = key
    return visuals


#: ``(face cacheKey, size) -> scaled QPixmap``. Bounded by the six faces times
#: the handful of sizes the screens draw dice at.
_DICE_SCALED_CACHE = {}


def _scaled_dice_image(image, size):
    """*image* scaled to *size*, built once and kept.

    Scaling per draw made a new pixmap for every die of every frame, and on
    the GL paint engine each one is a texture uploaded, drawn once and freed.
    The next die's upload then reused the freed texture name, which the engine
    still took for the texture it had just configured, so it skipped setting
    the new one's filtering: an incomplete texture, sampled as an opaque black
    square. Only the first die after a text draw (a different texture) came
    out. A kept pixmap keeps its texture, so there is nothing to recycle.
    """
    key = (image.cacheKey(), int(size))
    scaled = _DICE_SCALED_CACHE.get(key)
    if scaled is None:
        scaled = image.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        _DICE_SCALED_CACHE[key] = scaled
    return scaled


def _draw_dice_image(painter, image, center_x, center_y, size, angle, alpha):
    """Draw a scaled, independently rotated dice image."""
    if image is None or image.isNull():
        return
    scaled = _scaled_dice_image(image, size)
    painter.save()
    painter.setOpacity(max(0.0, min(1.0, alpha / 255.0)))
    painter.translate(center_x, center_y)
    painter.rotate(angle)
    painter.drawPixmap(-scaled.width() // 2, -scaled.height() // 2, scaled)
    painter.restore()


def _draw_dice_roll(painter, session, width, height):
    """Draw asset-backed dice with staggered timing and independent motion."""
    animation = getattr(session, "dice_animation", None)
    if not animation:
        return
    result = animation.get("result") or {}
    visuals = _prepare_dice_animation(animation, result)
    if not visuals:
        return

    elapsed = float(animation.get("elapsed", 0.0))
    duration = max(0.1, float(animation.get(
        "duration", DICE_ANIMATION_SHAKE + DICE_ANIMATION_ROLL +
        DICE_ANIMATION_FADE + DICE_RESULT_HOLD_DURATION)))
    settle_time = max((d["motion"]["delay"] + d["motion"]["duration"] for d in visuals),
                      default=0.0)
    fade_start = max(DICE_ANIMATION_SHAKE + DICE_ANIMATION_ROLL, settle_time) + DICE_RESULT_HOLD_DURATION
    alpha = 255
    if elapsed > fade_start:
        alpha = max(0, int((fade_start + DICE_ANIMATION_FADE - elapsed) /
                           DICE_ANIMATION_FADE * 255))
    if alpha <= 0:
        return

    notation = str(result.get("dice_notation", "1d20"))
    label = str(result.get("label") or "")
    target = result.get("target")
    followups = [r for r in animation.get("followups", ()) if r.get("label")]
    if animation.get("companion"):
        # The damage die's roll reads first under the hit's verdict.
        followups = [animation["companion"]] + followups
    shown_followups = followups[:DICE_FOLLOWUP_LINES]
    count = len(visuals)
    columns = min(_DICE_MAX_COLUMNS, max(1, count))
    rows = (count + columns - 1) // columns
    die_size = 86 if count <= 4 else 72
    gap = 22 if animation.get("companion") else 12
    panel_w = max(380 if label else 340, columns * die_size + (columns - 1) * gap + 40)
    extra_h = len(shown_followups) * 18 + (18 if len(followups) > len(shown_followups) else 0)
    panel_h = 76 + rows * (die_size + gap) + 34 + extra_h
    # Far right, just above the weapon/spell chips (_draw_active).
    panel_x = width - panel_w - DICE_PANEL_MARGIN
    panel_y = max(58, height - panel_h - DICE_PANEL_BOTTOM)

    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    panel_col = QColor(16, 15, 24, min(244, alpha))
    painter.setPen(QPen(QColor(150, 122, 64, alpha), 2))
    painter.setBrush(panel_col)
    painter.drawRoundedRect(QRect(panel_x, panel_y, panel_w, panel_h), 10, 10)
    # What the roll is for, what it needs, and why the odds are what they are:
    #   ROLL TO HIT BANDIT
    #   d20 — need 14 or higher
    #   Blade 35 vs their Agility 30 — 35%
    title = label.upper() if label else f"DICE  {notation}"
    T.text_in(painter, QRect(panel_x + 12, panel_y + 8, panel_w - 24, 20),
              title, size=10,
              color=QColor(226, 224, 236, alpha), align=T.ALIGN_CENTER,
              bold=True, family="Segoe UI")
    if target is not None:
        need = (f"{notation} — need {target} or higher" if target <= _notation_max(notation)
                else f"{notation} — cannot succeed")
        T.text_in(painter, QRect(panel_x + 12, panel_y + 28, panel_w - 24, 16),
                  need, size=9, color=QColor(255, 214, 130, alpha),
                  align=T.ALIGN_CENTER, family="Segoe UI")
    why = str(result.get("why") or "")
    if why:
        T.text_in(painter, QRect(panel_x + 12, panel_y + 45, panel_w - 24, 16),
                  why, size=8, color=QColor(170, 166, 184, alpha),
                  align=T.ALIGN_CENTER, italic=True, family="Segoe UI")

    settled = True
    start_y = panel_y + 68
    row_left = panel_x + (panel_w - (columns * die_size + (columns - 1) * gap)) // 2
    from . import dice3d
    for index, die in enumerate(visuals):
        row, column = divmod(index, columns)
        center_x = row_left + die_size // 2 + column * (die_size + gap)
        center_y = start_y + die_size // 2 + row * (die_size + gap)
        m = die["motion"]
        if elapsed < m["delay"]:
            settled = False
            continue                    # not thrown yet: it comes in a moment later
        local = elapsed - m["delay"]
        rotation, dx, dy, done = dice3d.pose(die["sides"], die["value"], m, local)
        if not done:
            settled = False
        # It tumbles in from the side and bounces to rest, out of step with
        # its neighbour.
        x = center_x + dx * die_size * 0.6
        y = center_y + dy * die_size * 0.5
        dice3d.draw_die(painter, die["sides"], die["value"], x, y, die_size * 0.92,
                        rotation, alpha=alpha, tumbling=not done,
                        flicker=int(local * 18.0) + index * 5)
        if die.get("role"):
            T.text_in(painter, QRect(center_x - die_size // 2, center_y + die_size // 2 - 2,
                                     die_size, 14),
                      "TO HIT" if die["role"] == "hit" else f"DAMAGE  d{die['sides']}",
                      size=7, color=QColor(170, 166, 184, alpha), align=T.ALIGN_CENTER,
                      bold=True, family="Segoe UI")

    if settled:
        total_y = panel_y + panel_h - 30 - extra_h
        total = result.get("roll_result", 0)
        if target is not None:
            # The verdict, in the colour of the outcome: "Rolled 7 — FAILED".
            passed = bool(result.get("success"))
            T.text_in(painter, QRect(panel_x + 12, total_y, panel_w - 24, 22),
                      f"ROLLED {total}  —  {'SUCCESS' if passed else 'FAILED'}",
                      size=12, color=_verdict_color(passed, alpha),
                      align=T.ALIGN_CENTER, bold=True, family="Segoe UI")
        else:
            T.text_in(painter, QRect(panel_x + 12, total_y, panel_w - 24, 22),
                      f"TOTAL  {total}", size=12,
                      color=QColor(255, 214, 130, alpha), align=T.ALIGN_CENTER,
                      bold=True, family="Segoe UI")
        # The rolls that came with it (a hit's critical, a kill's loot).
        line_y = total_y + 24
        for extra in shown_followups:
            color = (_verdict_color(bool(extra.get("success")), alpha)
                     if extra.get("target") is not None
                     else QColor(226, 224, 236, alpha))
            T.text_in(painter, QRect(panel_x + 12, line_y, panel_w - 24, 18),
                      describe_roll(extra), size=9, color=color,
                      align=T.ALIGN_CENTER, family="Segoe UI")
            line_y += 18
        if len(followups) > len(shown_followups):
            T.text_in(painter, QRect(panel_x + 12, line_y, panel_w - 24, 18),
                      f"+ {len(followups) - len(shown_followups)} more (see roll log)",
                      size=8, color=QColor(170, 166, 184, alpha),
                      align=T.ALIGN_CENTER, family="Segoe UI")
    painter.restore()
    return QRect(panel_x, panel_y, panel_w, panel_h)


#: The dice panel's gap from the right edge, and from the bottom (clear of
#: the inventory strip along the bottom edge).
DICE_PANEL_MARGIN = 18
DICE_PANEL_BOTTOM = 100
#: How many same-instant follow-up rolls the dice panel lists under the main one.
DICE_FOLLOWUP_LINES = 3
_VERDICT_PASS = (130, 220, 130)
_VERDICT_FAIL = (235, 110, 100)


def _verdict_color(passed, alpha=255):
    r, g, b = _VERDICT_PASS if passed else _VERDICT_FAIL
    return QColor(r, g, b, alpha)


def _notation_max(notation):
    """The highest total *notation* can roll (20 for ``1d20``)."""
    try:
        from ..diceroll import parse_dice_notation
        terms, _src = parse_dice_notation(notation)
    except ValueError:
        return 0
    return sum(t.sign * (t.count * t.sides if t.sides else t.modifier) for t in terms)


#: The roll log: bottom-left, above the inventory strip.
ROLL_LOG_LINE = 18
ROLL_LOG_BOTTOM = 128
ROLL_LOG_FADE = 1.0


def _draw_roll_log(painter, session, width, height):
    """The last few explained rolls, newest at the bottom, each one in the
    colour of its outcome: "Roll to hit Bandit: 7 (need 14+) — FAILED"."""
    log = getattr(session, "roll_log", None)
    if not log:
        return
    x = 16
    y = height - ROLL_LOG_BOTTOM - len(log) * ROLL_LOG_LINE
    fm = QFontMetrics(T.font(9, family="Segoe UI"))
    drawn = QRect()
    painter.save()
    for entry in log:
        alpha = int(255 * max(0.0, min(1.0, entry["t"] / ROLL_LOG_FADE)))
        success = entry.get("success")
        color = (QColor(226, 224, 236, alpha) if success is None
                 else _verdict_color(bool(success), alpha))
        rect = QRect(x, y, fm.horizontalAdvance(entry["text"]) + 14, ROLL_LOG_LINE)
        painter.fillRect(rect, QColor(0, 0, 0, int(alpha * 0.55)))
        T.text_in(painter, rect.adjusted(6, 0, -6, 0), entry["text"], size=9,
                  color=color, align=T.ALIGN_LEFT,
                  family="Segoe UI")
        drawn = drawn.united(rect)
        y += ROLL_LOG_LINE
    painter.restore()
    return drawn




#: Toast plate colours: cream on black, so a line like "your bounty has
#: increased" reads instantly over any scene without borrowing the gilded
#: panel chrome the menus use.
_TOAST_CREAM = QColor(247, 238, 214)
_TOAST_PLATE = QColor(0, 0, 0)
_TOAST_EDGE = QColor(168, 142, 84)

#: Where the toast stack starts: clear of the compass strip
#: (_draw_compass draws at y=14, 22 tall) with a little air beneath it.
TOAST_TOP = 46
#: Seconds of fade at the end of a toast's life. Before that it is fully opaque —
#: an announcement should be legible for as long as it is up, not dimming the
#: whole time.
TOAST_FADE = 0.6


def _draw_notifications(painter, session, width, height):
    """The toast stack: announcements pinned top-centre, under the compass.

    Newest first and reading downwards, each on its own black plate with a thin
    gilded edge, so several arriving at once stay separate lines rather than one
    block of text.
    """
    notes = session.notifications[-4:]
    if not notes:
        return
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    import game.ui.fonts as fonts
    font = fonts.dialogue_font(15)
    painter.setFont(font)
    metrics = painter.fontMetrics()
    pad_x, pad_y, gap = 18, 8, 6
    max_w = int(width * 0.7)
    y = TOAST_TOP
    if hasattr(session, "law_status"):
        status = session.law_status()
        if status["bounty"] or status["curfew"]:
            y = 118  # keep the new watch status readable above the notices

    drawn = QRect()
    for n in reversed(notes):
        text = str(n["text"])
        alpha = max(0, min(255, int(255 * min(1.0, float(n["t"]) / TOAST_FADE))))
        if alpha <= 0:
            continue
        shown = metrics.elidedText(text, Qt.ElideRight, max_w - pad_x * 2)
        tw = metrics.horizontalAdvance(shown)
        th = metrics.height()
        w = tw + pad_x * 2
        h = th + pad_y * 2
        x = (width - w) // 2

        plate = QColor(_TOAST_PLATE)
        plate.setAlpha(int(alpha * 0.86))
        edge = QColor(_TOAST_EDGE)
        edge.setAlpha(alpha)
        rect = QRect(x, y, w, h)
        painter.setPen(Qt.NoPen)
        painter.setBrush(plate)
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(QPen(edge, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, 4, 4)

        cream = QColor(_TOAST_CREAM)
        cream.setAlpha(alpha)
        painter.setPen(cream)
        painter.setFont(font)
        painter.drawText(rect, T.ALIGN_CENTER, shown)
        drawn = drawn.united(rect)
        y += h + gap
    painter.restore()
    return drawn


def _draw_floaters(painter, session, width, height):
    cx = width // 2
    colors = {
        "dmg": QColor(240, 230, 200), "crit": QColor(255, 210, 120),
        "sneak": QColor(200, 160, 255), "miss": QColor(160, 160, 170),
        "fire": QColor(255, 140, 60), "frost": QColor(150, 210, 255),
        "shock": QColor(230, 230, 120), "kill": QColor(255, 90, 90),
        "hurt": QColor(255, 80, 80), "xp": QColor(255, 214, 90),
    }
    for i, f in enumerate(session.floaters):
        col = QColor(colors.get(f["kind"], QColor(240, 240, 240)))
        col.setAlpha(max(0, min(255, int(f["t"] / 1.2 * 255))))
        fx = cx + ((i * 37) % 120) - 60
        size = 15 if f["kind"] in ("crit", "sneak", "kill", "xp") else 12
        T.text(painter, fx, height // 2 + int(f["y"]), f["text"], size=size,
               color=col, bold=True, family="Segoe UI")


def draw_time_tint(painter, session, width, height, viewport=None):
    """The hour's light over the world: dawn, day, dusk and a dark night lit
    only where lamps and torches burn (game/ui/daylight.py)."""
    import game.ui.daylight as daylight
    daylight.draw(painter, session, viewport, width, height)


# ------------------------------------------------------------------- gore
#: Blood's colours: fresh and bright in flight, darker where it lies, and the
#: near-black of a chunk.
_BLOOD = (150, 6, 8)
_BLOOD_DARK = (92, 2, 4)
_BLOOD_CHUNK = (70, 6, 8)


def _blob(painter, cx, cy, r, seed, color, alpha):
    """A splash: a rough-edged blot with a few droplets thrown off it."""
    import random as _random
    rng = _random.Random(int(seed * 1e6))
    pts = []
    n = 9
    for i in range(n):
        a = i / n * 2 * math.pi + rng.uniform(-0.2, 0.2)
        rr = r * rng.uniform(0.7, 1.15)
        pts.append(QPointF(cx + math.cos(a) * rr, cy + math.sin(a) * rr * 0.8))
    painter.setBrush(QColor(*color, int(alpha)))
    painter.drawPolygon(QPolygonF(pts))
    for _ in range(rng.randint(2, 5)):
        a = rng.uniform(0, 2 * math.pi)
        d = r * rng.uniform(1.1, 1.9)
        painter.drawEllipse(QPointF(cx + math.cos(a) * d, cy + math.sin(a) * d * 0.8),
                            r * rng.uniform(0.08, 0.22), r * rng.uniform(0.08, 0.2))


def draw_gore(painter, session, viewport, width, height):
    """The blood in the air (game/gore_fx.py), over the world and under the
    HUD: droplets and chunks in flight, the red flash of a kill, and the
    player's own blood on the screen's edge. Blood lying on the ground is not
    drawn here, over everything, but in the 3D pass under the actors standing
    in it (game/ui/blood_gl.py) or stamped into the terrain."""
    gore = getattr(session, "gore", None)
    if gore is None or viewport is None:
        return
    try:
        import glm
        proj, view = viewport.projection_matrix, viewport.view_matrix
    except Exception:
        return
    particles, _splats, screen = gore.snapshot()
    now = gore.clock()

    def to_screen(x, y, z):
        return _world_to_screen(glm, proj, view, x, y, z, width, height)

    def px_per_unit(x, y, z):
        a, b = to_screen(x, y, z), to_screen(x + 100.0, y, z)
        if a is None or b is None:
            return None
        return math.hypot(b[0] - a[0], b[1] - a[1]) / 100.0

    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    for p in particles:
        x, y, z = gore.position(p, now)
        sp = to_screen(x, y, z)
        k = px_per_unit(x, y, z)
        if sp is None or k is None:
            continue
        r = max(1.2, p["size"] * 0.5 * k)
        if p["kind"] == "chunk":
            _blob(painter, sp[0], sp[1], r, p["seed"], _BLOOD_CHUNK, 240)
        else:
            painter.setBrush(QColor(*_BLOOD, 235))
            painter.drawEllipse(QPointF(sp[0], sp[1]), r, r)
    # The player's own blood, on the screen's edge.
    import game.gore_fx as gore_fx
    for b in screen:
        age = now - b["t0"]
        alpha = 200 * max(0.0, 1.0 - age / gore_fx.SCREEN_BLOOD_SECONDS)
        r = b["size"] * min(width, height)
        _blob(painter, b["x"] * width, b["y"] * height, r, b["seed"], _BLOOD_DARK, alpha)
    # The red pulse of a kill or a crit.
    level = gore.flash_level()
    if level > 0:
        from PyQt5.QtGui import QRadialGradient, QBrush
        g = QRadialGradient(QPointF(width / 2, height / 2), max(width, height) * 0.7)
        g.setColorAt(0.55, QColor(140, 0, 0, 0))
        g.setColorAt(1.0, QColor(140, 0, 0, int(170 * level)))
        painter.fillRect(QRect(0, 0, width, height), QBrush(g))
    painter.restore()
