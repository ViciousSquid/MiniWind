"""
The skill tree: every skill, where it stands and how near its next rise.

A page of the inventory window (I ▸ Skills). Three branches grow from the
character -- Combat, Magic and Stealth -- and each skill on a branch is a node:
its level in the middle, a ring that fills as it is used toward the next
increase, five pips for the mastery ranks it has passed (Novice, Apprentice,
Journeyman, Expert, Master), and a star if it is a major skill, whose rises
count toward the next character level. A strip across the top shows that
count, and the experience toward a level the other way, so the player can see
exactly where the next level is coming from.

Pure drawing: :func:`draw` paints into a rect and returns the node rects so
the window can make them clickable; nothing here changes the character.
"""

from __future__ import annotations

from PyQt5.QtCore import QPointF, QRect, QRectF, Qt
from PyQt5.QtGui import QColor, QPen

from ..rpg import attributes as attr
from ..rpg import skills as sk

#: Mastery ranks: (from level, name), and the one a level has reached.
RANKS = sk.RANKS
rank = sk.rank
#: Each branch's colour.
BRANCH_COLORS = {sk.COMBAT: QColor(222, 112, 88), sk.MAGIC: QColor(120, 150, 245),
                 sk.STEALTH: QColor(110, 200, 130)}
_INK = QColor(226, 228, 232)
_DIM = QColor(140, 144, 150)
_GOLD = QColor(240, 200, 110)
_TRACK = QColor(54, 56, 60)



def progress(character, skill_id: str) -> float:
    """How far *skill_id* is toward its next increase, 0..1 (1 at 100)."""
    level = int(character.skills.get(skill_id, 0))
    if level >= 100:
        return 1.0
    need = sk.xp_to_raise(level)
    have = float(getattr(character, "_skill_xp", {}).get(skill_id, 0.0))
    return max(0.0, min(1.0, have / need)) if need > 0 else 0.0


def _text(painter, font, color, rect, flags, text):
    painter.setFont(font)
    painter.setPen(color)
    painter.drawText(rect, int(flags), text)


def draw(painter, rect, character, fonts, selected=None, pointer=None):
    """Paint the tree into *rect*. *fonts* is ``(title, body, small)``.
    Returns ``[(QRect, skill_id)]`` of the nodes, for clicks."""
    f_title, f_body, f_small = fonts
    nodes = []
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)

    # The strip: what the next character level is waiting on.
    from ..rpg.character import SKILL_UPS_PER_LEVEL
    strip = QRect(rect.x(), rect.y(), rect.width(), 40)
    painter.fillRect(strip, QColor(26, 25, 24, 230))
    majors = int(getattr(character, "xp_progress", 0))
    xp, need = int(getattr(character, "xp", 0)), int(character.xp_needed)
    _text(painter, f_body, _GOLD, strip.adjusted(12, 0, 0, 0),
          Qt.AlignVCenter | Qt.AlignLeft, f"Level {character.level}")
    bars = (("Major skill rises", majors, SKILL_UPS_PER_LEVEL, _GOLD),
            ("Experience", xp, need, QColor(150, 200, 255)))
    bx = strip.x() + 110
    bw = (strip.width() - 130) // 2 - 16
    for label, have, total, colour in bars:
        frac = max(0.0, min(1.0, have / total)) if total else 0.0
        _text(painter, f_small, _DIM, QRect(bx, strip.y() + 3, bw, 16),
              Qt.AlignLeft, f"{label}  {have} / {total}")
        track = QRect(bx, strip.y() + 23, bw, 8)
        painter.fillRect(track, _TRACK)
        painter.fillRect(QRect(track.x(), track.y(), int(track.width() * frac), 8), colour)
        bx += bw + 24
    _text(painter, f_small, _DIM, QRect(strip.right() - 300, strip.bottom() + 2, 300, 14),
          Qt.AlignRight, "Either bar full: a new level (L)")

    # The branches.
    top = strip.bottom() + 22
    detail_h = 74
    col_w = rect.width() // 3
    specs = (sk.COMBAT, sk.MAGIC, sk.STEALTH)
    for ci, spec in enumerate(specs):
        colour = BRANCH_COLORS[spec]
        cx = rect.x() + ci * col_w
        banner = QRect(cx + 8, top, col_w - 16, 30)
        painter.setPen(QPen(colour, 1.5))
        painter.setBrush(QColor(colour.red(), colour.green(), colour.blue(), 50))
        painter.drawRoundedRect(banner, 6, 6)
        _text(painter, f_title, colour, banner, Qt.AlignCenter, spec)
        skills = sk.BY_SPEC.get(spec, [])
        avail = rect.bottom() - detail_h - (banner.bottom() + 10)
        row_h = max(40, min(56, avail // max(1, len(skills))))
        trunk_x = banner.x() + 18
        first_y = banner.bottom() + 10 + row_h // 2
        last_y = first_y + (len(skills) - 1) * row_h
        painter.setPen(QPen(colour.darker(150), 3))
        painter.drawLine(QPointF(trunk_x, banner.bottom()), QPointF(trunk_x, last_y))
        for i, sid in enumerate(skills):
            ny = first_y + i * row_h
            node_x = trunk_x + 34
            painter.setPen(QPen(colour.darker(150), 3))
            painter.drawLine(QPointF(trunk_x, ny), QPointF(node_x - 18, ny))
            hit = QRect(trunk_x + 10, ny - row_h // 2 + 2, col_w - 40, row_h - 4)
            _node(painter, character, sid, QPointF(node_x, ny), colour, fonts,
                  hit, sid == selected,
                  pointer is not None and hit.contains(int(pointer[0]), int(pointer[1])))
            nodes.append((hit, sid))

    # The detail line for the picked skill.
    pick = selected if selected in sk.SKILLS else None
    detail = QRect(rect.x() + 8, rect.bottom() - detail_h + 6, rect.width() - 16, detail_h - 8)
    painter.setPen(QPen(QColor(90, 92, 98), 1))
    painter.setBrush(QColor(26, 25, 24, 230))
    painter.drawRoundedRect(detail, 6, 6)
    if pick is None:
        _text(painter, f_small, _DIM, detail, Qt.AlignCenter,
              "Click a skill to see what raises it. Skills rise by being used.")
    else:
        sd = sk.SKILLS[pick]
        level = int(character.skills.get(pick, 0))
        _r_i, r_name = rank(level)
        nxt = next((lo for lo, _n in RANKS if lo > level), None)
        major = pick in getattr(character, "major_skills", [])
        head = (f"{sd.label}  ·  {level}  ·  {r_name}"
                + (f" (Rank up at {nxt})" if nxt is not None else "")
                + ("  ·  ★ Major skill" if major else ""))
        _text(painter, f_body, _GOLD, detail.adjusted(12, 4, -12, 0),
              Qt.AlignTop | Qt.AlignLeft, head)
        body = (f"{sd.desc}  Governed by {attr.label(sd.governing_attr)}. "
                f"{int(progress(character, pick) * 100)}% of the way to {level + 1}."
                + ("  Each rise counts toward your next level." if major else ""))
        _text(painter, f_small, _INK, detail.adjusted(12, 26, -12, -4),
              Qt.AlignTop | Qt.AlignLeft | Qt.TextWordWrap, body)
    painter.restore()
    return nodes


def _node(painter, character, sid, centre, colour, fonts, hit, chosen, hot):
    _f_title, f_body, f_small = fonts
    level = int(character.skills.get(sid, 0))
    frac = progress(character, sid)
    major = sid in getattr(character, "major_skills", [])
    r = 17.0
    if chosen or hot:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 26 if hot and not chosen else 40))
        painter.drawRoundedRect(hit, 6, 6)
    # The ring: how near the next rise.
    ring = QRectF(centre.x() - r - 4, centre.y() - r - 4, 2 * r + 8, 2 * r + 8)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(_TRACK, 4))
    painter.drawEllipse(ring)
    painter.setPen(QPen(colour.lighter(120), 4, Qt.SolidLine, Qt.RoundCap))
    painter.drawArc(ring, 90 * 16, -int(360 * 16 * frac))
    # The disc, gilded for a major skill.
    painter.setPen(QPen(_GOLD if major else colour.darker(130), 2))
    painter.setBrush(QColor(30, 31, 34))
    painter.drawEllipse(centre, r, r)
    _text(painter, f_body, _INK, QRectF(centre.x() - r, centre.y() - r, 2 * r, 2 * r).toRect(),
          Qt.AlignCenter, str(level))
    # Name, rank and the five rank pips.
    tx = int(centre.x() + r + 12)
    label = ("★ " if major else "") + sk.label(sid)
    _text(painter, f_body, _GOLD if major else _INK, QRect(tx, int(centre.y()) - 18, 200, 18),
          Qt.AlignLeft | Qt.AlignVCenter, label)
    r_i, r_name = rank(level)
    for i in range(len(RANKS)):
        px = tx + 4 + i * 12
        painter.setPen(QPen(colour.darker(140), 1))
        painter.setBrush(colour if i <= r_i and level >= RANKS[i][0] else _TRACK)
        painter.drawEllipse(QPointF(px, centre.y() + 9), 4, 4)
    _text(painter, f_small, _DIM, QRect(tx + 66, int(centre.y()) + 1, 140, 16),
          Qt.AlignLeft | Qt.AlignVCenter, r_name)
