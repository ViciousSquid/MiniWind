"""
The heads-up display: health/magicka/stamina, clock, gold, level, active
weapon/spell, the quest tracker, a compass, target nameplates, notifications and
floating combat text. Drawn every frame via the plugin's ``render.overlay`` hook.
"""

from __future__ import annotations

import math

from PyQt5.QtCore import QRect, QRectF, Qt
from PyQt5.QtGui import QColor, QPolygon, QPen, QConicalGradient
from PyQt5.QtCore import QPoint, QPointF

from . import theme as T
from ..rpg import equipment as eq
from ..rpg import items as rpg_items
from ..rpg import magic as rpg_magic


def draw(painter, session, width, height):
    game = session.game
    c = game.character

    _draw_orbs(painter, c, width, height)
    _draw_clock(painter, session, width)
    _draw_topleft(painter, session, c)
    _draw_active(painter, session, c, width, height)
    _draw_quest_tracker(painter, session, width)
    _draw_compass(painter, session, width, height)
    _draw_target(painter, session, width, height)
    _draw_status_flags(painter, session, c, width, height)
    _draw_notifications(painter, session, width, height)
    _draw_floaters(painter, session, width, height)
    _draw_interact_prompt(painter, session, width, height)


def _draw_interact_prompt(painter, session, width, height):
    """The 'Press E to talk to …' prompt, centred low on screen. MiniWind draws
    it itself because it suppresses the engine's default HUD."""
    text = getattr(session, "interact_prompt", "")
    if not text or session.dialogue is not None or session.open_screen is not None:
        return
    painter.save()
    f = painter.font()
    f.setPointSize(13)
    f.setBold(True)
    painter.setFont(f)
    rect = QRect(0, int(height * 0.72), width, 30)
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
    player = getattr(logic, "player", None) if logic is not None else None
    if player is None:
        return
    ppos = [float(player.pos[0]), float(player.pos[1]), float(player.pos[2])]
    for npc, kind in session.bubble_npcs(ppos)[:10]:
        head_y = npc.pos[1] + float(npc.properties.get("sprite_height", 112)) * 0.5 + 26.0
        sp = _world_to_screen(glm, proj, view, npc.pos[0], head_y, npc.pos[2], width, height)
        if sp is not None:
            _draw_bubble(painter, int(sp[0]), int(sp[1]), kind)


def _draw_bubble(painter, cx, cy, kind):
    painter.save()
    quest = (kind == "quest")
    glyph = "!" if quest else "…"
    fill = QColor(250, 210, 90) if quest else QColor(235, 235, 240)
    edge = QColor(120, 90, 20) if quest else QColor(60, 60, 70)
    text_col = QColor(60, 40, 0) if quest else QColor(40, 40, 50)
    bw, bh = 26, 22
    rect = QRect(cx - bw // 2, cy - bh, bw, bh)
    painter.setPen(edge)
    painter.setBrush(fill)
    painter.drawRoundedRect(rect, 7, 7)
    # little tail pointing down at the head
    tail = QPolygon([QPoint(cx - 4, cy - 1), QPoint(cx + 4, cy - 1), QPoint(cx, cy + 7)])
    painter.drawPolygon(tail)
    painter.setPen(text_col)
    f = painter.font()
    f.setBold(True)
    f.setPointSize(12)
    painter.setFont(f)
    painter.drawText(rect, Qt.AlignCenter, glyph)
    painter.restore()


def _draw_orbs(painter, c, width, height):
    """Three stat bars stacked bottom-left."""
    x = 20
    w = 240
    h = 16
    base_y = height - 28
    T.bar(painter, x, base_y, w, h,
          c.health / c.max_health if c.max_health else 0, T.HEALTH,
          label=f"{int(c.health)} / {int(c.max_health)}")
    T.bar(painter, x, base_y - 22, w, h,
          c.magicka / c.max_magicka if c.max_magicka else 0, T.MAGICKA,
          label=f"{int(c.magicka)} / {int(c.max_magicka)}")
    T.bar(painter, x, base_y - 44, w * 0.7, h * 0.7,
          c.stamina / c.max_stamina if c.max_stamina else 0, T.STAMINA)


def _draw_clock(painter, session, width):
    if not session.show_clock:
        return
    clock = session.clock
    hour = clock.hour
    h_int = int(hour)
    m_int = int((hour - h_int) * 60.0)

    radius = 34
    cx = width - radius - 16
    cy = radius + 16
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

    # hour hand
    h_angle = math.radians((hour % 12) * 30 - 90)
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

    # day label below clock
    day_text = f"Day {clock.day}"
    T.text_in(painter, QRect(int(cx - radius), int(cy + radius + 4),
                             int(radius * 2), 16),
              day_text, size=9, color=T.DIM, align=T.ALIGN_CENTER,
              family="Segoe UI")
    painter.restore()


def _draw_topleft(painter, session, c):
    """Name, level, gold under the stat area — a compact identity chip."""
    x, y = 20, 16
    T.text(painter, x, y + 14, c.name, size=14, color=T.GOLD_BRIGHT, bold=True)
    from ..rpg import races, classes
    sub = f"Level {c.level}  ·  {races.get(c.race_id).label} {classes.get(c.class_id).label}"
    T.text(painter, x, y + 32, sub, size=9, color=T.DIM, family="Segoe UI")
    T.text(painter, x, y + 50, f"⦿ {c.gold} gold", size=10, color=T.GOLD, family="Segoe UI")
    if c.can_level_up:
        T.text(painter, x, y + 68, "Level up! (press L)", size=9,
               color=QColor(120, 220, 130), bold=True, family="Segoe UI")


def _weapon_icon_pixmap(weapon_def, size=26):
    if weapon_def is None:
        return None
    try:
        from .. import item_icons
        return item_icons.icon_pixmap(weapon_def.id, None, size)
    except Exception:
        return None


def _draw_active(painter, session, c, width, height):
    """Bottom-right: active weapon and active spell chips, each with an icon so
    the equipped weapon and readied spell read at a glance."""
    w = eq.weapon(c)
    wname = w.name if w else "Unarmed"
    a = eq.ammo(c)
    if w and w.get("kind") == rpg_items.KIND_BOW and a:
        from ..rpg import inventory as inv
        wname += f"  ({inv.quantity(c.inventory, a.id)} {a.name.split()[0].lower()})"
    spell = rpg_magic.get(c.active_spell) if c.active_spell else None
    sname = spell.name if spell else "—"

    x = width - 250
    y = height - 64
    T.panel(painter, x, y, 232, 52, radius=8, shadow=False)

    # Weapon row: icon + name (left mouse hint).
    tx = x + 14
    pm = _weapon_icon_pixmap(w, 22)
    if pm is not None and not pm.isNull():
        painter.drawPixmap(x + 12, y + 6, pm)
        tx = x + 40
    T.text(painter, tx, y + 21, wname, size=10,
           color=T.GOLD_BRIGHT if w else T.DIM, family="Segoe UI")
    T.text(painter, x + 210, y + 21, "L", size=8, color=T.DIM, family="Segoe UI")

    # Spell row: element-coloured swatch + name (right mouse hint).
    scol = T.MAGICKA.lighter(140) if spell else T.DIM
    if spell is not None:
        col = spell.color
        painter.setBrush(QColor(col[0], col[1], col[2]))
        painter.setPen(QPen(QColor(col[0], col[1], col[2]).darker(160), 1))
        painter.drawEllipse(x + 14, y + 30, 16, 16)
        tx = x + 40
    else:
        tx = x + 14
    T.text(painter, tx, y + 44, sname, size=10, color=scol, family="Segoe UI")
    T.text(painter, x + 210, y + 44, "R", size=8, color=T.DIM, family="Segoe UI")


def _draw_status_flags(painter, session, c, width, height):
    flags = []
    if session.game.sneaking:
        flags.append(("SNEAK", QColor(150, 150, 170)))
    if session._blocking:
        flags.append(("BLOCK", QColor(120, 170, 230)))
    for eff in ("shield", "invisibility", "night_eye", "berserk"):
        if c.effect_magnitude(eff) > 0:
            flags.append((eff.upper().replace("_", " "), QColor(180, 150, 220)))
    cx = width // 2 - len(flags) * 45
    for i, (label, col) in enumerate(flags):
        rx = cx + i * 92
        painter.fillRect(QRect(rx, height - 92, 84, 20), QColor(10, 10, 16, 180))
        T.text_in(painter, QRect(rx, height - 92, 84, 20), label, size=9,
                  color=col, align=T.ALIGN_CENTER, bold=True, family="Segoe UI")


def _draw_quest_tracker(painter, session, width):
    active = session.game.quests.active_quests()
    if not active:
        return
    q = active[0]
    obj = session.game.quests.current_objective(q.id)
    x = width - 300
    y = 48
    T.text(painter, x, y, "◈ " + q.name, size=11, color=T.GOLD_BRIGHT, bold=True)
    if obj:
        T.text(painter, x + 6, y + 18, "• " + obj, size=9, color=T.PARCH, family="Segoe UI")


def _draw_compass(painter, session, width, height):
    """A small heading strip centred at the top (N/E/S/W)."""
    player = getattr(session.logic, "player", None)
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


def _wrap(a):
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


def _draw_target(painter, session, width, height):
    """Nameplate + health bar for the creature under the crosshair."""
    from .. import runtime as rt
    c = session.game.character
    reach = rt.BOW_REACH if c.active_weapon_kind in ("bow", "spell", "staff") else rt.MELEE_REACH * 1.6
    try:
        target = session._acquire_target(reach)
    except Exception:
        target = None
    if target is None:
        return
    tp = target.properties
    name = tp.get("display_name", tp.get("name", "Foe"))
    try:
        hp = int(tp.get("health", 0))
    except (TypeError, ValueError):
        hp = 0
    maxhp = int(tp.get("_max_health", 0)) or max(hp, 1)
    if hp > maxhp:
        tp["_max_health"] = hp
        maxhp = hp
    cx = width // 2
    y = 44
    T.text_in(painter, QRect(cx - 150, y, 300, 18), name, size=12,
              color=T.GOLD_BRIGHT, align=T.ALIGN_CENTER, bold=True)
    T.bar(painter, cx - 110, y + 20, 220, 10, hp / maxhp if maxhp else 0, T.HEALTH)


def _draw_notifications(painter, session, width, height):
    y = height // 2 - 40
    for n in reversed(session.notifications[-4:]):
        alpha = max(0, min(255, int(n["t"] / 3.0 * 255)))
        col = QColor(240, 226, 190, alpha)
        T.text_in(painter, QRect(0, y, width, 22), n["text"], size=13,
                  color=col, align=T.ALIGN_CENTER, bold=True)
        y -= 24


def _draw_floaters(painter, session, width, height):
    cx = width // 2
    colors = {
        "dmg": QColor(240, 230, 200), "crit": QColor(255, 210, 120),
        "sneak": QColor(200, 160, 255), "miss": QColor(160, 160, 170),
        "fire": QColor(255, 140, 60), "frost": QColor(150, 210, 255),
        "shock": QColor(230, 230, 120), "kill": QColor(255, 90, 90),
        "hurt": QColor(255, 80, 80),
    }
    for i, f in enumerate(session.floaters):
        col = QColor(colors.get(f["kind"], QColor(240, 240, 240)))
        col.setAlpha(max(0, min(255, int(f["t"] / 1.2 * 255))))
        fx = cx + ((i * 37) % 120) - 60
        size = 15 if f["kind"] in ("crit", "sneak", "kill") else 12
        T.text(painter, fx, height // 2 + int(f["y"]), f["text"], size=size,
               color=col, bold=True, family="Segoe UI")


def draw_time_tint(painter, session, width, height):
    """Full-screen colour overlay that shifts with game time of day."""
    hour = session.clock.hour
    # Interpolate between time-of-day tint colours:
    #   6-8   dawn     warm gold
    #   8-16  day      clear (no tint)
    #   16-19 evening  amber/orange
    #   19-21 dusk     deep blue-purple
    #   21-5  night    dark blue
    #   5-6   pre-dawn deep blue fading
    if 8.0 <= hour < 16.0:
        return
    if 6.0 <= hour < 8.0:
        t = (hour - 6.0) / 2.0
        r, g, b = 255, 200, 100
        alpha = int(40 * (1.0 - t))
    elif 16.0 <= hour < 19.0:
        t = (hour - 16.0) / 3.0
        r = int(255 - 60 * t)
        g = int(170 - 80 * t)
        b = int(60 + 80 * t)
        alpha = int(20 + 50 * t)
    elif 19.0 <= hour < 21.0:
        t = (hour - 19.0) / 2.0
        r = int(80 - 50 * t)
        g = int(60 - 30 * t)
        b = int(140 + 30 * t)
        alpha = int(70 + 40 * t)
    else:
        # night: 21-24 and 0-5
        r, g, b = 20, 25, 80
        alpha = 110
        if 5.0 <= hour < 6.0:
            t = (hour - 5.0)
            alpha = int(110 * (1.0 - t))
    painter.fillRect(QRect(0, 0, width, height), QColor(r, g, b, alpha))
