"""
The teacher's pages: a trainer's training sheet and a tutor's list of spells.

Both are parchment pages, like the level-up page. The training sheet follows
the old tomes: the skill's name between flourishes, what it governs, its
emblem, then *Trainer skill* (the teacher's rank), *Current skill* (yours),
and *Times trained this level* as five stars -- with what a lesson costs and
the button to buy one. The tutor's page lists the spells for sale down the
left, with the chosen one's school, power and price on the right.

Each page is a ``draw(painter, session, w, h)`` / ``handle_key(session, key)``
pair, dispatched from :mod:`game.ui.screens` as ``"training"`` and
``"tutor"``. The rules are :mod:`game.rpg.training`'s; buying goes through the
session (``train_with_teacher`` / ``learn_from_teacher``).
"""

from __future__ import annotations

import math
import os

from PyQt5.QtCore import QPointF, QRect, QRectF, Qt
from PyQt5.QtGui import QColor, QPen, QPixmap, QPolygonF

from . import fonts
from . import theme as T
from ..rpg import guilds, magic as rpg_magic, skills as sk, training

#: The page's inks (as the level-up page's).
_INK = QColor(64, 34, 22)
_INK_SOFT = QColor(110, 86, 60)
_INK_BLUE = QColor(36, 40, 104)
_INK_RED = QColor(122, 40, 30)
_RULE = QColor(120, 92, 54, 160)
_STAR_ON = QColor(52, 92, 168)
_STAR_OFF = QColor(176, 160, 128)

_ICON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir,
                                         os.pardir, "assets", "sprites", "spells"))
_PIXMAPS = {}


def _screens():
    from . import screens
    return screens


def _teacher(session):
    npc = getattr(session, "trainer_npc", None)
    return npc, (getattr(npc, "properties", None) or {})


def _state(session, key):
    return _screens()._sel(session).setdefault(key, {"row": 0})


def _icon(name):
    """A spell / school icon from assets/sprites/spells, or None."""
    if name not in _PIXMAPS:
        pm = None
        for fn in (f"{name}.png", f"{name}.jpg"):
            path = os.path.join(_ICON_DIR, fn)
            if os.path.isfile(path):
                pm = QPixmap(path)
                break
        _PIXMAPS[name] = pm if pm is not None and not pm.isNull() else None
    return _PIXMAPS[name]


def _flourish(painter, cx, cy, half, flip):
    """A little scroll of ink beside a title: a rule ending in a curl."""
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    painter.setPen(QPen(_INK_SOFT, 1.6))
    sign = -1 if flip else 1
    painter.drawLine(QPointF(cx, cy), QPointF(cx + sign * half, cy))
    painter.drawEllipse(QPointF(cx + sign * (half + 5), cy), 4.5, 4.5)
    painter.drawArc(QRectF(cx + sign * half * 0.35 - 6, cy - 12, 12, 12), 200 * 16, 220 * 16)
    painter.drawArc(QRectF(cx + sign * half * 0.35 - 6, cy, 12, 12), -20 * 16, -220 * 16)
    painter.restore()


def _title(painter, rect, text):
    """*text* centred between flourishes."""
    T.text_in(painter, rect, text, size=22, color=_INK, align=T.ALIGN_CENTER,
              family=fonts.dialogue_family())
    painter.save()
    painter.setFont(T.font(22, family=fonts.dialogue_family()))
    half_w = painter.fontMetrics().horizontalAdvance(text) // 2
    painter.restore()
    cy = rect.center().y()
    _flourish(painter, rect.center().x() - half_w - 18, cy, 70, True)
    _flourish(painter, rect.center().x() + half_w + 18, cy, 70, False)


def _star(painter, cx, cy, r, on):
    pts = []
    for i in range(8):
        rr = r if i % 2 == 0 else r * 0.38
        a = math.radians(i * 45 - 90)
        pts.append(QPointF(cx + math.cos(a) * rr, cy + math.sin(a) * rr))
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    painter.setPen(QPen(QColor(30, 40, 70) if on else _STAR_OFF.darker(130), 1))
    painter.setBrush(_STAR_ON if on else _STAR_OFF)
    painter.drawPolygon(QPolygonF(pts))
    painter.restore()


def _emblem(painter, rect, skill_id=None, spell=None):
    """The card on the left: a framed school icon for magic, a woodcut glyph
    for any other skill."""
    s = _screens()
    painter.save()
    painter.fillRect(rect, QColor(222, 210, 182))
    painter.setPen(QPen(QColor(90, 52, 30), 3))
    painter.drawRect(rect)
    painter.setPen(QPen(QColor(90, 52, 30), 1))
    painter.drawRect(rect.adjusted(7, 7, -7, -7))
    painter.restore()
    pm = None
    if spell is not None:
        pm = _icon(spell.id) or _icon(f"_{spell.school}")
    elif skill_id in sk.SCHOOLS:
        pm = _icon(f"_{skill_id}")
    inner = rect.adjusted(18, 18, -18, -18)
    if pm is not None:
        side = min(inner.width(), inner.height())
        target = QRect(inner.center().x() - side // 2, inner.center().y() - side // 2, side, side)
        painter.drawPixmap(target, pm)
        return
    spec = sk.SKILLS[skill_id].spec if skill_id in sk.SKILLS else sk.MAGIC
    glyph = {sk.COMBAT: "strength", sk.STEALTH: "charisma"}.get(spec, "magicka")
    s._paint_level_icon(painter, inner, glyph)


def _row(painter, rect, label, value, rule=True):
    T.text_in(painter, rect, label, size=15, color=_INK, align=int(Qt.AlignLeft | Qt.AlignVCenter),
              family=fonts.dialogue_family())
    T.text_in(painter, rect, value, size=15, color=_INK_SOFT,
              align=int(Qt.AlignRight | Qt.AlignVCenter), family=fonts.dialogue_family())
    if rule:
        painter.save()
        painter.setPen(QPen(_RULE, 1))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.restore()


def _wrap(painter, rect, text, size=12, color=_INK, family=None):
    painter.save()
    painter.setFont(T.font(size, family=family or fonts.dialogue_family()))
    painter.setPen(color)
    painter.drawText(rect, int(Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap), text)
    painter.restore()


def _close(session):
    session.close_teaching()


# ===========================================================================
# Training
# ===========================================================================
def _taught(session):
    _npc, p = _teacher(session)
    t = training.trainer_of(p)
    return t["skills"] if t else []


def _pick(key, i):
    def action(session):
        _state(session, key)["row"] = i
    return action


def draw_training(painter, session, w, h):
    s = _screens()
    npc, p = _teacher(session)
    t = training.trainer_of(p)
    if t is None:
        return
    c = session.game.character
    st = _state(session, "training")
    taught = t["skills"]
    st["row"] %= len(taught)
    skill_id = taught[st["row"]]
    x, y, bw, bh = s._panel_rect(w, h, 0.66, 0.8)
    page = QRect(x, y, bw, bh)
    s._paint_parchment(painter, page)
    inner = page.adjusted(28, 16, -28, -16)

    name = p.get("display_name") or p.get("name") or "Trainer"
    T.text_in(painter, QRect(inner.x(), inner.y(), inner.width(), 18),
              f"{name} teaches", size=10, color=_INK_SOFT, align=T.ALIGN_CENTER,
              family="Segoe UI")
    top = inner.y() + 18
    # More than one skill: a tab for each, the chosen one inked in.
    if len(taught) > 1:
        tab_w = min(140, (inner.width() - 8 * (len(taught) - 1)) // len(taught))
        tx = inner.center().x() - (tab_w * len(taught) + 8 * (len(taught) - 1)) // 2
        for i, sid in enumerate(taught):
            r = QRect(tx + i * (tab_w + 8), top + 4, tab_w, 24)
            chosen = i == st["row"]
            painter.save()
            painter.setPen(QPen(QColor(90, 52, 30), 1))
            painter.setBrush(QColor(122, 40, 30, 220) if chosen else QColor(214, 196, 158))
            painter.drawRoundedRect(r, 4, 4)
            painter.restore()
            T.text_in(painter, r, sk.label(sid), size=11,
                      color=QColor(244, 232, 206) if chosen else _INK,
                      align=T.ALIGN_CENTER, family=fonts.dialogue_family())
            s._row_target(painter, r, _pick("training", i), f"train:{sid}")
        top += 34
    _title(painter, QRect(inner.x(), top + 4, inner.width(), 40), sk.label(skill_id))
    top += 50
    sd = sk.SKILLS.get(skill_id)
    _wrap(painter, QRect(inner.x() + 20, top, inner.width() - 40, 64), sd.desc if sd else "", 12)
    top += 72

    card_w = min(int(inner.width() * 0.36), 220)
    card = QRect(inner.x() + 12, top, card_w, int(card_w * 1.35))
    _emblem(painter, card, skill_id=skill_id)
    rx = card.right() + 36
    rw = inner.right() - rx - 8
    level = c.skill(skill_id)
    _row(painter, QRect(rx, top + 6, rw, 34), "Trainer skill", sk.rank_name(t["rank"]))
    _row(painter, QRect(rx, top + 46, rw, 34), "Current skill",
         f"{sk.rank_name(level)}  ({level})")
    used = training.SESSIONS_PER_LEVEL - training.sessions_left(c)
    _row(painter, QRect(rx, top + 110, rw, 34), "Times trained this level",
         f"{used}/{training.SESSIONS_PER_LEVEL}")
    for i in range(training.SESSIONS_PER_LEVEL):
        _star(painter, rx + rw - 14 - (training.SESSIONS_PER_LEVEL - 1 - i) * 30,
              top + 166, 11, i < used)

    price = session._teacher_price(training.lesson_price(c, skill_id))
    reason = training.can_train(c, p, skill_id, price)
    _row(painter, QRect(rx, top + 196, rw, 30), "Price", f"{price} gold", rule=False)
    T.text_in(painter, QRect(rx, top + 226, rw, 20), f"You have {c.gold} gold", size=10,
              color=_INK_SOFT, align=int(Qt.AlignRight | Qt.AlignVCenter), family="Segoe UI")
    foot_y = inner.bottom() - 34
    if reason:
        _wrap(painter, QRect(inner.x() + 12, foot_y - 46, inner.width() - 24, 40),
              training.explain(reason), 12, _INK_RED)
    s.button(painter, QRect(inner.right() - 330, foot_y, 180, 32), "Train",
             lambda sess, sid=skill_id: sess.train_with_teacher(sid),
             enabled=not reason, primary=True)
    s.button(painter, QRect(inner.right() - 140, foot_y, 140, 32), "Leave", _close)
    T.text_in(painter, QRect(inner.x(), foot_y, inner.width() - 340, 32),
              "Enter to train   ·   Esc to leave", size=9, color=_INK_SOFT,
              align=int(Qt.AlignLeft | Qt.AlignVCenter), family="Segoe UI")


def handle_training(session, key):
    taught = _taught(session)
    st = _state(session, "training")
    n = max(1, len(taught))
    if key in ("left", "a", "up", "w"):
        st["row"] = (st["row"] - 1) % n; return True
    if key in ("right", "d", "down", "s", "tab"):
        st["row"] = (st["row"] + 1) % n; return True
    if key.isdigit() and 1 <= int(key) <= len(taught):
        st["row"] = int(key) - 1; return True
    if key in ("return", "enter", "space") and taught:
        session.train_with_teacher(taught[st["row"] % n]); return True
    if key in ("escape", "esc", "q"):
        session.close_teaching()
    return True


# ===========================================================================
# Spell tutoring
# ===========================================================================
def _for_sale(session):
    _npc, p = _teacher(session)
    return training.spells_taught(p)


def draw_tutor(painter, session, w, h):
    s = _screens()
    npc, p = _teacher(session)
    spells = training.spells_taught(p)
    if not spells:
        return
    c = session.game.character
    st = _state(session, "tutor")
    st["row"] %= len(spells)
    x, y, bw, bh = s._panel_rect(w, h, 0.72, 0.82)
    page = QRect(x, y, bw, bh)
    s._paint_parchment(painter, page)
    inner = page.adjusted(26, 16, -26, -16)
    name = p.get("display_name") or p.get("name") or "Tutor"
    _title(painter, QRect(inner.x(), inner.y(), inner.width(), 40), "Spells")
    guild = training.guild_of(p)
    sub = f"taught by {name}"
    if guild == training.ARCANE_CIRCLE:
        sub += f"  ·  of the Arcane Circle  ·  you: {guilds.rank_title(c, guild)}"
    T.text_in(painter, QRect(inner.x(), inner.y() + 40, inner.width(), 18), sub, size=10,
              color=_INK_SOFT, align=T.ALIGN_CENTER, family="Segoe UI")
    top = inner.y() + 70

    list_w = int(inner.width() * 0.5)
    row_h = 40
    foot_y = inner.bottom() - 34
    shown = max(1, (foot_y - 10 - top) // row_h)
    first = max(0, min(st["row"] - shown + 1, len(spells) - shown)) if st["row"] >= shown else 0
    for i in range(first, min(len(spells), first + shown)):
        spell = spells[i]
        ry = top + (i - first) * row_h
        r = QRect(inner.x(), ry, list_w, row_h - 4)
        chosen = i == st["row"]
        known = spell.id in c.known_spells
        if chosen:
            painter.fillRect(r, QColor(122, 40, 30, 60))
        painter.fillRect(QRect(r.x(), r.y() + 4, 4, r.height() - 8), s._rarity_color(spell.rarity))
        pm = _icon(spell.id) or _icon(f"_{spell.school}")
        if pm is not None:
            painter.drawPixmap(QRect(r.x() + 10, r.y() + 2, r.height() - 4, r.height() - 4), pm)
        ink = _INK_SOFT if known else _INK
        T.text_in(painter, r.adjusted(r.height() + 12, 0, -70, -r.height() // 2 + 2),
                  spell.name, size=13, color=ink, align=int(Qt.AlignLeft | Qt.AlignBottom),
                  family=fonts.dialogue_family())
        T.text_in(painter, r.adjusted(r.height() + 12, r.height() // 2, -70, 0),
                  f"{sk.label(spell.school)}  ·  {spell.rarity.title()}", size=8,
                  color=_INK_SOFT, align=int(Qt.AlignLeft | Qt.AlignTop), family="Segoe UI")
        price = "known" if known else \
            f"{session._teacher_price(training.spell_price(c, p, spell))} g"
        T.text_in(painter, r.adjusted(0, 0, -6, 0), price, size=11, color=ink,
                  align=int(Qt.AlignRight | Qt.AlignVCenter), family="Segoe UI")
        s._row_target(painter, r, _pick("tutor", i), f"tutor:{spell.id}")

    spell = spells[st["row"]]
    dx = inner.x() + list_w + 24
    dw = inner.right() - dx
    card = QRect(dx + (dw - 120) // 2, top, 120, 120)
    _emblem(painter, card, spell=spell)
    T.text_in(painter, QRect(dx, card.bottom() + 8, dw, 26), spell.name, size=17,
              color=_INK, align=T.ALIGN_CENTER, family=fonts.dialogue_family())
    T.text_in(painter, QRect(dx, card.bottom() + 34, dw, 18),
              f"{sk.label(spell.school)}  ·  {spell.rarity.title()}  ·  {spell.delivery}",
              size=9, color=s._rarity_color(spell.rarity).darker(150), align=T.ALIGN_CENTER,
              bold=True, family="Segoe UI")
    info = (f"{s._spell_power(spell)}{int(rpg_magic.cast_cost(c, spell))} magicka to cast"
            f"\n\n{spell.desc}")
    note = training.standing_note(p, spell)
    if note:
        info += f"\n\nThe Circle sells it to: {note.split(': ', 1)[-1]} and above."
    painter.save()
    painter.setFont(T.font(10, family="Segoe UI"))
    painter.setPen(_INK)
    painter.drawText(QRect(dx, card.bottom() + 58, dw, foot_y - card.bottom() - 110),
                     int(Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap), info)
    painter.restore()
    price = session._teacher_price(training.spell_price(c, p, spell))
    reason = training.can_learn(c, p, spell.id, price)
    if reason:
        _wrap(painter, QRect(dx, foot_y - 44, dw, 40), training.explain(reason), 11, _INK_RED)
    T.text_in(painter, QRect(inner.x(), foot_y, list_w, 32), f"You have {c.gold} gold",
              size=10, color=_INK_SOFT, align=int(Qt.AlignLeft | Qt.AlignVCenter),
              family="Segoe UI")
    s.button(painter, QRect(inner.right() - 330, foot_y, 180, 32), f"Learn  ({price} gold)",
             lambda sess, sid=spell.id: sess.learn_from_teacher(sid),
             enabled=not reason, primary=True)
    s.button(painter, QRect(inner.right() - 140, foot_y, 140, 32), "Leave", _close)


def handle_tutor(session, key):
    spells = _for_sale(session)
    st = _state(session, "tutor")
    n = max(1, len(spells))
    if key in ("up", "w", "left", "a"):
        st["row"] = (st["row"] - 1) % n; return True
    if key in ("down", "s", "right", "d", "tab"):
        st["row"] = (st["row"] + 1) % n; return True
    if key in ("return", "enter", "space") and spells:
        session.learn_from_teacher(spells[st["row"] % n].id); return True
    if key in ("escape", "esc", "q"):
        session.close_teaching()
    return True
