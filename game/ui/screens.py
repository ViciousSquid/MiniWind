"""
Full-screen RPG menus: character creation, inventory & equipment, the character
sheet, the quest journal, the spellbook, the merchant trade screen and the
level-up allocator.

Each screen is a pair of pure functions — ``draw(painter, session, w, h)`` and
``handle_key(session, key)`` — navigated with the arrow keys, Enter and Esc, so
they need nothing beyond a QPainter and the session. Selection lives in
``session.sel`` (a plain dict), which persists across frames.
"""

from __future__ import annotations

from PyQt5.QtCore import QRect, QRectF, Qt
from PyQt5.QtGui import QColor, QFontMetrics, QPen

from . import drag, fonts, hits, trade_anim
from . import theme as T
from ..rpg import (races, classes, birthsigns, attributes as attr, skills as sk,
                   items as rpg_items, inventory as inv, equipment as eq,
                   magic as rpg_magic, guilds, quests, heads)
from ..rpg import charisma as _cha


def _sel(session):
    if not hasattr(session, "sel"):
        session.sel = {}
    return session.sel


# ===========================================================================
# Dispatch
# ===========================================================================
def draw(painter, session, w, h):
    screen = session.open_screen
    T.dim_screen(painter, w, h, alpha=180 if screen != "charcreate" else 235)
    fn = _DRAW.get(screen)
    if fn:
        fn(painter, session, w, h)


def handle_key(session, key):
    """Return True if the key was consumed by the open screen."""
    screen = session.open_screen
    fn = _HANDLE.get(screen)
    if fn:
        return fn(session, key)
    return False


# When set (x, y, w, h), every screen draws its panel into this rect instead of a
# centred full-screen panel — used when a screen is hosted inside a draggable
# floating window (see ``draw_in_rect``). Kept as a module global so no screen
# body needs to thread a rect through its layout: they all route through
# ``_panel_rect``.
_PANEL_OVERRIDE = None

#: Suggested floating-window body size (px) per screen.
_SCREEN_BODY_SIZE = {
    "charcreate": (1000, 700),
    "inventory": (720, 500),
    "character": (720, 520),
    "journal": (700, 470),
    "spells": (700, 470),
    "levelup": (820, 600),
    "trade": (760, 520),
    "container": (760, 500),
    "quest": (880, 540),
    "lockpicking": (820, 560),
}


def window_body_size(screen):
    return _SCREEN_BODY_SIZE.get(screen, (700, 480))


#: Clickable regions recorded by :func:`_draw_quest` each frame and hit-tested
#: by :func:`handle_click` (the quest journal is mouse-driven — see the host's
#: overlay wiring). ``rows`` is [(QRect, known-index)]; ``toggle`` is the
#: "make active quest" box rect for ``toggle_qid``.
_QUEST_HITS = {"rows": [], "toggle": None, "toggle_qid": None,
               "map": None, "map_focus": None}


def button(painter, rect, label, action, enabled=True, primary=False):
    """A clickable button: gilded frame, MedievalSharp label, lit on hover.

    *action(session)* runs (from the game tick) when it is clicked; a disabled
    button draws dimmed and does nothing.
    """
    hot = enabled and hits.hovered(rect)
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    fill = (QColor(96, 70, 34, 240) if hot else
            QColor(62, 48, 30, 235) if primary else QColor(34, 30, 44, 235))
    painter.setBrush(fill if enabled else QColor(24, 22, 30, 200))
    painter.setPen(QPen(T.GOLD_BRIGHT if hot else T.GILD if enabled else T.DIM, 1.5))
    painter.drawRoundedRect(rect, 5, 5)
    painter.setFont(fonts.dialogue_font(12))
    painter.setPen(T.GOLD_BRIGHT if (hot or primary) and enabled
                   else T.INK if enabled else T.DIM)
    painter.drawText(rect, T.ALIGN_CENTER, label)
    painter.restore()
    if enabled:
        hits.add(QRect(rect), action, label)


def _row_target(painter, rect, action, label=None):
    """Make a list row clickable, with a faint glow under the pointer."""
    if hits.hovered(rect):
        painter.fillRect(rect, QColor(255, 220, 150, 22))
    hits.add(QRect(rect), action, label)


def handle_click(session, x, y):
    """Route a body click inside the open screen. Returns True if consumed.

    The screen is hosted in a floating window, and that window swallows
    every click on its body, so a click must be handed on from here or the
    screen's buttons (a merchant's *Buy* and *Leave*, the level-up choices)
    could never be pressed. The quest journal keeps its own hit areas — a
    quest row, or the tracked/active toggle; every other screen goes through
    the targets it published while painting (:mod:`game.ui.hits`)."""
    if getattr(session, "open_screen", None) != "quest":
        return hits.click(x, y)
    from PyQt5.QtCore import QPoint
    p = QPoint(int(x), int(y))
    shown = _QUEST_HITS.get("map")
    if shown is not None and shown.contains(p):
        session.map_request = _QUEST_HITS.get("map_focus")
        return True
    tog = _QUEST_HITS.get("toggle")
    if tog is not None and tog.contains(p):
        qid = _QUEST_HITS.get("toggle_qid")
        if qid:
            session.set_tracked_quest(qid)
        return True
    for r, idx in _QUEST_HITS.get("rows", []):
        if r.contains(p):
            _sel(session).setdefault("quest", {"row": 0})["row"] = idx
            return True
    return hits.click(x, y)


def draw_in_rect(painter, session, x, y, w, h):
    """Draw the open screen's panel inside (x, y, w, h) with no full-screen dim.

    Used when the screen is presented in a floating window; the window supplies
    the chrome, so the screen fills the given body rect."""
    global _PANEL_OVERRIDE
    fn = _DRAW.get(session.open_screen)
    if fn is None:
        return
    _PANEL_OVERRIDE = (int(x), int(y), int(w), int(h))
    try:
        fn(painter, session, int(w), int(h))
    finally:
        _PANEL_OVERRIDE = None


def _panel_rect(w, h, pw=0.8, ph=0.82):
    if _PANEL_OVERRIDE is not None:
        return _PANEL_OVERRIDE
    bw, bh = int(w * pw), int(h * ph)
    return (w - bw) // 2, (h - bh) // 2, bw, bh


# ===========================================================================
# Character creation
_CC_STEPS = ["identity", "fortune", "class", "birthsign", "confirm"]
#: How long one die tumbles before it settles, and the stagger between dice.
_ROLL_TUMBLE = 0.85
_ROLL_STAGGER = 0.14
_DEFAULT_RACE = "imperial"          # simplified creator asks no race / gender
_MAX_NAME = 18
_HEAD_PIXMAP_CACHE = {}


def _cc(session):
    return _sel(session).setdefault("cc", {"step": 0, "name": "", "head": 0,
                                           "class": 0, "birthsign": 0,
                                           "handed": "right"})


def _head_pixmap(head_index):
    import os
    from PyQt5.QtGui import QPixmap
    hid = heads.head_at(head_index)
    if hid in _HEAD_PIXMAP_CACHE:
        return _HEAD_PIXMAP_CACHE[hid]
    pm = None
    try:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        p = os.path.join(root, heads.head_path(hid))
        if os.path.exists(p):
            q = QPixmap(p)
            if not q.isNull():
                pm = q
    except Exception:
        pm = None
    _HEAD_PIXMAP_CACHE[hid] = pm
    return pm


def _draw_charcreate(painter, session, w, h):
    s = _cc(session)
    x, y, bw, bh = _panel_rect(w, h, 0.82, 0.86)
    inner = T.panel(painter, x, y, bw, bh)
    step = _CC_STEPS[s["step"]]
    ty = T.heading(painter, inner, "Create Character",
                   f"Step {s['step'] + 1} of {len(_CC_STEPS)}")

    if step == "identity":
        _draw_identity(painter, inner, ty, s)
        hint = "Type a name    ←/→ head    ↑/↓ switch hand    Enter next"
    elif step == "fortune":
        _draw_fortune(painter, inner, ty, s)
        hint = "R or Space re-roll    Enter next    Esc back"
    elif step == "class":
        ids = classes.CREATION_CLASS_IDS
        k = classes.get(ids[s["class"]])
        list_w = int(inner.width() * 0.42)
        _cc_list(painter, inner.x(), ty, list_w, ids, s["class"],
                 lambda i: classes.get(i).label, field="class")
        favs = ", ".join(attr.label(a) for a in k.favored_attrs)
        majors = ", ".join(sk.label(m) for m in k.major_skills)
        no_magic = "" if k.magic else f"\n\n{classes.NO_MAGIC_NOTE}"
        _cc_detail(painter, inner.x() + list_w + 24, ty, inner.width() - list_w - 24,
                   k.label, k.desc + f"\n\nSpecialisation: {k.specialisation}"
                   f"\nFavoured: {favs}\nMajor skills: {majors}{no_magic}")
        hint = "↑/↓ choose class    Enter next    Esc back"
    elif step == "birthsign":
        ids = birthsigns.CREATION_BIRTHSIGN_IDS
        b = birthsigns.get(ids[s["birthsign"]])
        list_w = int(inner.width() * 0.42)
        _cc_list(painter, inner.x(), ty, list_w, ids, s["birthsign"],
                 lambda i: birthsigns.get(i).label, field="birthsign")
        _cc_detail(painter, inner.x() + list_w + 24, ty, inner.width() - list_w - 24,
                   b.label, b.desc)
        hint = "↑/↓ choose birthsign    Enter next    Esc back"
    else:  # confirm
        name = " ".join(p.capitalize() for p in s["name"].split()) or "Adventurer"
        k = classes.get(classes.CREATION_CLASS_IDS[s["class"]])
        b = birthsigns.get(birthsigns.CREATION_BIRTHSIGN_IDS[s["birthsign"]])
        pm = _head_pixmap(s["head"])
        if pm is not None:
            sz = min(140, inner.width() // 3)
            painter.drawPixmap(QRect(inner.x(), ty + 6, sz, sz),
                               pm.scaled(sz, sz, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            tx = inner.x() + (min(140, inner.width() // 3)) + 20
        else:
            tx = inner.x()
        bio = _cc_bio(s)
        totals = "   ".join(f"{label} {sum(s['rolls'][a])}"
                            for a, label in _cha.ROLLED) if s.get("rolls") else ""
        summary = (f"Name: {name}\nClass: {k.label}"
                   + ("" if k.magic else "  (no magic: it does not reveal itself to you)")
                   + f"\nBirthsign: {b.label}\n"
                   f"{totals}\n\n{bio['title']}\n\n"
                   "Begin your adventure, or go back to change anything.")
        _cc_detail(painter, tx, ty, inner.right() - tx, "Ready?", summary)
        hint = "Enter begin    Esc back"

    # Back / Next (Begin on the last step), above the key hints.
    bw_, bh_ = 128, 32
    by = inner.bottom() - 22 - bh_
    last = s["step"] == len(_CC_STEPS) - 1
    button(painter, QRect(inner.x(), by, bw_, bh_), "Back", _cc_back,
           enabled=s["step"] > 0)
    button(painter, QRect(inner.right() - bw_, by, bw_, bh_),
           "Begin" if last else "Next", _cc_next,
           enabled=bool(s["name"].strip()) or s["step"] > 0, primary=True)

    T.text_in(painter, QRect(inner.x(), inner.bottom() - 16, inner.width(), 16),
              hint, size=10, color=T.DIM, align=T.ALIGN_CENTER, family="Georgia")


def _cc_bio(s):
    from ..rpg import bios
    return bios.bio_from_rolls(s.get("rolls") or {})


def _cc_roll(session):
    """Roll (or re-roll) 3d6 for STRENGTH, ENDURANCE and CHARISMA. The dice
    tumble on screen for a moment before they settle (see _draw_fortune)."""
    import time
    s = _cc(session)
    rng = getattr(session, "rng", None)
    s["rolls"] = {a: _cha.roll_3d6(rng) for a, _label in _cha.ROLLED}
    s["roll_t"] = time.monotonic()
    s["rerolls"] = s.get("rerolls", -1) + 1


def _roll_settled(s) -> bool:
    import time
    t = time.monotonic() - float(s.get("roll_t", 0.0))
    return t >= _ROLL_TUMBLE + _ROLL_STAGGER * 8


def animating(session) -> bool:
    """Whether the open screen has something moving (dice still tumbling), so
    the view keeps repainting it while the world is paused."""
    if getattr(session, "open_screen", None) != "charcreate":
        return False
    s = _cc(session)
    return _CC_STEPS[s["step"]] == "fortune" and not _roll_settled(s)


def _draw_fortune(painter, inner, ty, s):
    """Three rows of 3d6 -- STRENGTH, ENDURANCE, CHARISMA -- tumbling, then
    settled, each with its total and what it does to the attribute; and the
    bio the dice have written so far underneath."""
    import math as _m
    import time
    from . import hud
    from ..rpg import bios
    rolls = s.get("rolls") or {}
    elapsed = time.monotonic() - float(s.get("roll_t", 0.0))
    T.text(painter, inner.x(), ty + 16, "Roll your fortune", size=15,
           color=T.GOLD_BRIGHT, bold=True)
    T.text(painter, inner.x(), ty + 36, "Three six-sided dice for each. Keep what fate "
           "gives you, or tempt it again.", size=10, color=T.DIM, family="Georgia")
    die = 54
    gap = 14
    row_h = die + 18
    top = ty + 52
    # Columns from the text as it is actually drawn: the label font is the
    # game's display face, much wider than a fixed offset allowed for, and
    # the dice were landing on top of the labels.
    label_w = max(QFontMetrics(T.font(14, bold=True)).horizontalAdvance(label)
                  for _a, label in _cha.ROLLED)
    dice_x = inner.x() + label_w + 24
    total_w = QFontMetrics(T.font(20, bold=True)).horizontalAdvance("18")
    all_settled = True
    for r, (attr_id, label) in enumerate(_cha.ROLLED):
        y = top + r * row_h
        T.text(painter, inner.x(), y + die // 2 + 6, label, size=14,
               color=T.GOLD_BRIGHT, bold=True)
        dice = rolls.get(attr_id) or [1, 1, 1]
        for k, value in enumerate(dice):
            idx = r * 3 + k
            local = elapsed - idx * _ROLL_STAGGER
            cx = dice_x + k * (die + gap) + die // 2
            cy = y + die // 2
            if local < _ROLL_TUMBLE:
                all_settled = False
                shown = int(max(0.0, local) * 22 + idx * 3) % 6 + 1
                wob = _m.sin(max(0.0, local) * 26 + idx)
                angle, dy = 22 * wob, -10 * abs(_m.sin(max(0.0, local) * 9 + idx))
            else:
                shown, angle, dy = int(value), 0.0, 0.0
            hud._draw_dice_image(painter, hud._dice_face_image(shown), cx, int(cy + dy),
                                 die, angle, 255)
        tx = dice_x + 3 * (die + gap) + 8
        if all_settled or elapsed - (r * 3 + 2) * _ROLL_STAGGER >= _ROLL_TUMBLE:
            total = sum(int(d) for d in dice)
            delta = _cha.delta_for(total)
            colour = (T.STAMINA.lighter(140) if delta > 0 else
                      T.HEALTH.lighter(140) if delta < 0 else T.PARCH)
            T.text(painter, tx, cy + 4, f"{total}", size=20, color=T.GOLD_BRIGHT, bold=True)
            T.text(painter, tx + total_w + 14, cy + 2,
                   f"{'+' if delta >= 0 else ''}{delta} {attr.label(attr_id)}  ·  "
                   f"{bios.band(total)}", size=11, color=colour, family="Georgia")
    # The bio, once the dice are down.
    by = top + 3 * row_h + 6
    box = QRect(inner.x(), by, inner.width(), inner.bottom() - 70 - by)
    painter.setBrush(QColor(12, 12, 16, 220))
    painter.setPen(QPen(T.GILD, 1))
    painter.drawRect(box)
    if all_settled and rolls:
        bio = bios.bio_from_rolls(rolls)
        T.text(painter, box.x() + 12, box.y() + 24, bio["title"], size=15,
               color=T.GOLD_BRIGHT, bold=True)
        T.text_in(painter, box.adjusted(12, 34, -12, -8), bio["text"], size=11,
                  color=T.PARCH, align=int(Qt.AlignTop | Qt.AlignLeft) | int(Qt.TextWordWrap),
                  family="Georgia")
    else:
        T.text_in(painter, box, "The dice are rolling…", size=12, color=T.DIM,
                  align=T.ALIGN_CENTER)
    n = int(s.get("rerolls", 0) or 0)
    button(painter, QRect(inner.x() + inner.width() // 2 - 90, inner.bottom() - 60, 180, 32),
           "Re-roll" if rolls else "Roll", _cc_roll, enabled=all_settled)
    if n:
        T.text_in(painter, QRect(inner.x(), inner.bottom() - 60, inner.width() // 2 - 100, 32),
                  f"re-rolled {n}×", size=9, color=T.DIM, align=T.ALIGN_RIGHT)


def _cc_next(session):
    _handle_charcreate(session, "return")


def _cc_back(session):
    _handle_charcreate(session, "escape")


def _cc_set(field, value):
    def action(session):
        _cc(session)[field] = value
    return action


def _cc_head_step(delta):
    def action(session):
        s = _cc(session)
        s["head"] = (s["head"] + delta) % heads.HEAD_COUNT
    return action


def _cc_toggle_hand(session):
    s = _cc(session)
    s["handed"] = "left" if s.get("handed", "right") == "right" else "right"


def _draw_identity(painter, inner, ty, s):
    # Name field.
    T.text(painter, inner.x(), ty + 20, "Name:", size=14, color=T.GOLD_BRIGHT, bold=True)
    fx = inner.x() + 90
    fw = inner.width() - 90
    box = QRect(fx, ty + 2, fw, 30)
    painter.setBrush(QColor(12, 12, 16))
    painter.setPen(QPen(T.GILD, 1))
    painter.drawRect(box)
    caret = "_" if (int(__import__("time").time() * 2) % 2 == 0) else " "
    T.text(painter, fx + 8, ty + 23, (s["name"] or "") + caret, size=13, color=T.PARCH,
           family="Georgia")

    # Head chooser: big preview with arrows, centred below the name.
    hy = ty + 52
    hh = inner.bottom() - 100 - hy
    size = min(hh, int(inner.width() * 0.5))
    cx = inner.x() + inner.width() // 2
    box = QRect(cx - size // 2, hy, size, size)
    painter.setBrush(QColor(18, 18, 24))
    painter.setPen(QPen(T.GILD, 1))
    painter.drawRect(box)
    pm = _head_pixmap(s["head"])
    if pm is not None:
        painter.drawPixmap(box.adjusted(6, 6, -6, -6),
                           pm.scaled(size - 12, size - 12, Qt.KeepAspectRatio,
                                     Qt.SmoothTransformation))
    else:
        T.text_in(painter, box, heads.head_at(s["head"]), size=13, color=T.DIM,
                  align=T.ALIGN_CENTER)
    # Arrows.
    painter.setFont(T.font(28, bold=True))
    painter.setPen(T.GOLD_BRIGHT)
    left_arrow = QRect(box.x() - 56, box.y(), 44, size)
    right_arrow = QRect(box.right() + 12, box.y(), 44, size)
    for rect, glyph, delta in ((left_arrow, "<", -1), (right_arrow, ">", 1)):
        painter.setPen(T.PARCH if hits.hovered(rect) else T.GOLD_BRIGHT)
        painter.drawText(rect, T.ALIGN_CENTER, glyph)
        hits.add(QRect(rect), _cc_head_step(delta), glyph)
    # Clicking the face itself shows the next one too.
    hits.add(QRect(box), _cc_head_step(1), "head")
    T.text_in(painter, QRect(box.x(), box.bottom() + 4, size, 18),
              f"Head {s['head'] + 1} / {heads.HEAD_COUNT}", size=10,
              color=T.DIM, align=T.ALIGN_CENTER)
    handed = s.get("handed", "right")
    hand_rect = QRect(inner.x() + inner.width() // 2 - 150, box.bottom() + 24, 300, 28)
    button(painter, hand_rect,
           f"{handed.capitalize()}-handed   (click or ↑/↓ to switch)",
           _cc_toggle_hand)


def _cc_list(painter, x, y, w, ids, sel, labeller, field=None):
    row_h = 26
    for i, item in enumerate(ids):
        ry = y + i * row_h
        if field is not None:
            _row_target(painter, QRect(x, ry, w, row_h - 2), _cc_set(field, i),
                        labeller(item))
        if i == sel:
            painter.fillRect(QRect(x, ry, w, row_h - 2), T.SELECT)
            painter.setPen(T.GILD)
            painter.drawRect(QRect(x, ry, w, row_h - 2))
        T.text_in(painter, QRect(x + 10, ry, w - 12, row_h - 2), labeller(item),
                  size=12, color=T.GOLD_BRIGHT if i == sel else T.INK, align=T.ALIGN_LEFT)


def _cc_detail(painter, x, y, w, title, body):
    T.text(painter, x, y + 14, title, size=16, color=T.GOLD_BRIGHT, bold=True)
    T.text_in(painter, QRect(x, y + 26, w, 400), body, size=11, color=T.PARCH,
              align=int(Qt.AlignTop | Qt.AlignLeft) | int(Qt.TextWordWrap),
              family="Georgia")


def _handle_charcreate(session, key):
    s = _cc(session)
    step = _CC_STEPS[s["step"]]
    if step == "identity":
        if key == "left":
            s["head"] = (s["head"] - 1) % heads.HEAD_COUNT; return True
        if key == "right":
            s["head"] = (s["head"] + 1) % heads.HEAD_COUNT; return True
        if key in ("up", "down"):
            s["handed"] = "left" if s.get("handed", "right") == "right" else "right"
            return True
        if key == "backspace":
            s["name"] = s["name"][:-1]; return True
        if key == "space":
            if len(s["name"]) < _MAX_NAME and s["name"]:
                s["name"] += " "
            return True
        if len(key) == 1 and (key.isalpha() or key.isdigit()):
            if len(s["name"]) < _MAX_NAME:
                s["name"] += key.upper() if not s["name"] else key
            return True
    elif step == "fortune":
        if key in ("r", "space"):
            if _roll_settled(s):
                _cc_roll(session)
            return True
    elif step in ("class", "birthsign"):
        ids = (classes.CREATION_CLASS_IDS if step == "class"
               else birthsigns.CREATION_BIRTHSIGN_IDS)
        if key in ("up", "w"):
            s[step] = (s[step] - 1) % len(ids); return True
        if key in ("down", "s"):
            s[step] = (s[step] + 1) % len(ids); return True
    if key in ("return", "enter"):
        if s["step"] == 0 and not s["name"].strip():
            return True                       # a name is required
        if _CC_STEPS[s["step"]] == "fortune" and not s.get("rolls"):
            _cc_roll(session)
            return True
        if s["step"] < len(_CC_STEPS) - 1:
            s["step"] += 1
            if _CC_STEPS[s["step"]] == "fortune" and not s.get("rolls"):
                _cc_roll(session)               # the dice fall as you arrive
        else:
            _finish_charcreate(session)
        return True
    if key in ("escape", "esc"):
        if s["step"] > 0:
            s["step"] -= 1
        return True
    return True  # consume everything while creating a character


def _finish_charcreate(session):
    s = _cc(session)
    name = " ".join(p.capitalize() for p in s["name"].split()) or "Adventurer"
    klass = classes.CREATION_CLASS_IDS[s["class"]]
    sign = birthsigns.CREATION_BIRTHSIGN_IDS[s["birthsign"]]
    head = heads.head_at(s["head"])
    # Gender is fixed internally and never asked (it changes nothing in play).
    if not s.get("rolls"):
        _cc_roll(session)
    session.begin_new_character(name, _DEFAULT_RACE, klass, sign, "male", head=head,
                                handed=s.get("handed", "right"), rolls=s.get("rolls"))


# ===========================================================================
# Inventory & equipment
# ===========================================================================
_INV_CATS = [("All", None), ("Weapons", rpg_items.WEAPON), ("Armour", rpg_items.ARMOUR),
             ("Potions", rpg_items.POTION), ("Ammo", rpg_items.AMMO),
             ("Books", rpg_items.BOOK), ("Misc", None)]


def _draw_inventory(painter, session, w, h):
    c = session.game.character
    st = _sel(session).setdefault("inv", {"row": 0, "cat": 0})
    x, y, bw, bh = _panel_rect(w, h)
    inner = T.panel(painter, x, y, bw, bh)
    weight = inv.total_weight(c.inventory)
    ty = T.heading(painter, inner, "Inventory",
                   f"{c.gold} gold    ·    {weight:.0f} / {int(c.carry_capacity)} weight"
                   + ("   (OVER-ENCUMBERED)" if c.is_overencumbered else ""))

    cat_label, cat_type = _INV_CATS[st["cat"]]
    items_list = _filtered_items(c, cat_type, cat_label)
    st["row"] = max(0, min(st["row"], max(0, len(items_list) - 1)))

    # category tabs
    tx = inner.x()
    for i, (label, _) in enumerate(_INV_CATS):
        col = T.GOLD_BRIGHT if i == st["cat"] else T.DIM
        T.text(painter, tx, ty + 4, label, size=10, color=col,
               bold=(i == st["cat"]), family="Segoe UI")
        tx += painter.fontMetrics().width(label) + 22 if False else 78

    list_y = ty + 22
    list_w = int(inner.width() * 0.55)
    row_h = 24
    equipped_ids = set(c.equipment.values())
    for i, stack in enumerate(items_list):
        ry = list_y + i * row_h
        if ry > inner.bottom() - 30:
            break
        if i == st["row"]:
            painter.fillRect(QRect(inner.x(), ry, list_w, row_h - 2), T.SELECT)
        name = stack.get("name", stack.get("id"))
        mark = " [E]" if stack.get("id") in equipped_ids else ""
        qty = f" ×{stack['qty']}" if stack.get("qty", 1) > 1 else ""
        if i == st["row"]:
            ncol = T.GOLD_BRIGHT
        elif rpg_items.rarity_of(stack) != rpg_items.COMMON:
            ncol = QColor(*rpg_items.rarity_rgb(stack))
        else:
            ncol = T.INK
        T.text(painter, inner.x() + 8, ry + 16, name + qty, size=11,
               color=ncol, family="Segoe UI")
        T.text_in(painter, QRect(inner.x(), ry, list_w - 8, row_h),
                  mark, size=10, color=QColor(120, 200, 130), align=T.ALIGN_RIGHT,
                  family="Segoe UI")

    # detail + equipment column
    _draw_item_detail(painter, inner.x() + list_w + 20,
                      list_y, inner.width() - list_w - 20,
                      items_list[st["row"]] if items_list else None, c)

    T.text_in(painter, QRect(inner.x(), inner.bottom() - 16, inner.width(), 16),
              "↑/↓ select   ←/→ category   Enter use/equip   X drop   I/Esc close",
              size=9, color=T.DIM, align=T.ALIGN_CENTER, family="Segoe UI")


def _filtered_items(c, cat_type, cat_label):
    out = []
    for stack in c.inventory:
        d = rpg_items.get(stack.get("id"))
        cat = d.category if d else stack.get("type", "misc")
        if cat_label == "All":
            out.append(stack)
        elif cat_label == "Misc":
            if cat in (rpg_items.MISC, rpg_items.INGREDIENT, rpg_items.KEY,
                       rpg_items.SCROLL, "misc", "quest"):
                out.append(stack)
        elif cat == cat_type:
            out.append(stack)
    return out


def _draw_item_detail(painter, x, y, w, stack, c):
    # equipment summary at the top
    T.text(painter, x, y + 12, "Equipped", size=12, color=T.GOLD_BRIGHT, bold=True)
    slot_labels = [("weapon", "Weapon"), ("shield", "Shield"), ("head", "Head"),
                   ("chest", "Body"), ("hands", "Hands"), ("legs", "Legs"),
                   ("feet", "Feet"), ("ammo", "Ammo")]
    yy = y + 30
    for slot, label in slot_labels:
        iid = c.equipment.get(slot)
        d = rpg_items.get(iid) if iid else None
        T.text(painter, x, yy, f"{label}:", size=9, color=T.DIM, family="Segoe UI")
        T.text(painter, x + 70, yy, d.name if d else "—", size=9,
               color=T.INK if d else T.DIM, family="Segoe UI")
        yy += 16
    T.text(painter, x, yy + 6, f"Armour rating: {eq.armor_rating(c):.0f}", size=10,
           color=T.STAMINA.lighter(140), family="Segoe UI")

    if stack is None:
        return
    d = rpg_items.get(stack.get("id"))
    dy = yy + 34
    painter.setPen(T.GILD)
    painter.drawLine(x, dy - 8, x + w, dy - 8)
    T.text(painter, x, dy + 8, stack.get("name", "?"), size=13, color=T.GOLD_BRIGHT, bold=True)
    lines = []
    if d:
        if d.category == rpg_items.WEAPON:
            lines.append(f"{d.get('kind','melee').title()} · {sk.label(d.get('skill','blade'))} · {d.get('damage',0)} dmg")
        elif d.category == rpg_items.ARMOUR:
            lines.append(f"{d.get('armor_class','light').title()} armour · {d.get('armor_rating',0)} rating · {d.get('slot')}")
        elif d.category == rpg_items.AMMO:
            lines.append(f"Ammunition · +{d.get('damage',0)} dmg")
        lines.append(d.desc)
    lines.append(f"Value: {stack.get('value',0)}    Weight: {stack.get('weight',0)}")
    T.text_in(painter, QRect(x, dy + 18, w, 200), "\n".join(l for l in lines if l),
              size=10, color=T.PARCH,
              align=int(Qt.AlignTop | Qt.AlignLeft) | int(Qt.TextWordWrap),
              family="Segoe UI")


def _handle_inventory(session, key):
    c = session.game.character
    st = _sel(session).setdefault("inv", {"row": 0, "cat": 0})
    cat_label, cat_type = _INV_CATS[st["cat"]]
    items_list = _filtered_items(c, cat_type, cat_label)
    if key in ("up", "w"):
        st["row"] = (st["row"] - 1) % max(1, len(items_list)); return True
    if key in ("down", "s"):
        st["row"] = (st["row"] + 1) % max(1, len(items_list)); return True
    if key in ("left", "a"):
        st["cat"] = (st["cat"] - 1) % len(_INV_CATS); st["row"] = 0; return True
    if key in ("right", "d"):
        st["cat"] = (st["cat"] + 1) % len(_INV_CATS); st["row"] = 0; return True
    if key in ("return", "enter") and items_list:
        session.game.use_item(items_list[st["row"]]["id"]); return True
    if key == "x" and items_list:
        session.game.drop(items_list[st["row"]]["id"], 1); return True
    if key in ("i", "escape", "esc"):
        session.open_screen = None; return True
    return True


# ===========================================================================
# Character sheet
# ===========================================================================
def _draw_character(painter, session, w, h):
    c = session.game.character
    x, y, bw, bh = _panel_rect(w, h)
    inner = T.panel(painter, x, y, bw, bh)
    ty = T.heading(painter, inner, c.name,
                   f"Level {c.level} {races.get(c.race_id).label} {classes.get(c.class_id).label}"
                   f"  ·  {birthsigns.get(c.birthsign_id).label}")

    # derived pools
    T.text(painter, inner.x(), ty + 6, f"Health {int(c.max_health)}    "
           f"Magicka {int(c.max_magicka)}    Stamina {int(c.max_stamina)}    "
           f"Armour Class {eq.armour_class(c)}",
           size=11, color=T.PARCH, family="Segoe UI")
    rolls = getattr(c, "rolls", None) or {}
    if rolls:
        from ..rpg import bios
        bio = bios.bio_for(rolls.get("strength", 10), rolls.get("endurance", 10),
                           rolls.get("personality", 10))
        T.text_in(painter, QRect(inner.x() + 280, ty - 6, inner.width() - 280, 18),
                  f"{bio['title']}  ·  STR {rolls.get('strength', '?')}  "
                  f"END {rolls.get('endurance', '?')}  CHA {rolls.get('personality', '?')}",
                  size=10, color=T.GOLD_BRIGHT, align=T.ALIGN_RIGHT, family="Georgia")
    need = max(1, int(c.xp_needed))
    T.bar(painter, inner.x(), ty + 14, 260, 10, min(1.0, c.xp / need), T.XP,
          label=f"XP {c.xp} / {need}  ({max(0, need - c.xp)} to level {c.level + 1})"
                f"  ·  skill rises {c.xp_progress}/10")

    # attributes column
    ax = inner.x()
    ay = ty + 42
    T.text(painter, ax, ay, "Attributes", size=13, color=T.GOLD_BRIGHT, bold=True)
    for i, a in enumerate(attr.ATTRIBUTES):
        row_y = ay + 20 + i * 20
        T.text(painter, ax, row_y, attr.label(a), size=10, color=T.INK, family="Segoe UI")
        T.text_in(painter, QRect(ax, row_y - 12, 200, 14), str(c.attrs[a]), size=10,
                  color=T.GOLD_BRIGHT, align=T.ALIGN_RIGHT, family="Segoe UI")

    # skills columns grouped by spec
    sx = ax + 240
    col_w = (inner.width() - 240) // 3
    for ci, spec in enumerate([sk.COMBAT, sk.MAGIC, sk.STEALTH]):
        cx = sx + ci * col_w
        T.text(painter, cx, ay, spec, size=13, color=T.GOLD_BRIGHT, bold=True)
        for j, sid in enumerate(sk.BY_SPEC[spec]):
            row_y = ay + 20 + j * 17
            major = sid in c.major_skills
            T.text(painter, cx, row_y, ("★ " if major else "") + sk.label(sid),
                   size=9, color=T.GOLD if major else T.INK, family="Segoe UI")
            T.text_in(painter, QRect(cx, row_y - 11, col_w - 16, 12), str(c.skill(sid)),
                      size=9, color=T.PARCH, align=T.ALIGN_RIGHT, family="Segoe UI")

    # guild standing
    gy = inner.bottom() - 54
    mem = [g for g in guilds.GUILDS if guilds.is_member(c, g)]
    if mem:
        line = "   ".join(f"{guilds.get(g).name}: {guilds.rank_title(c, g)}" for g in mem)
        T.text(painter, inner.x(), gy, "Guilds: " + line, size=9, color=T.DIM,
               family="Segoe UI")
    if c.bounty:
        T.text(painter, inner.x(), gy + 16, f"Bounty: {c.bounty} gold", size=10,
               color=QColor(220, 100, 90), family="Segoe UI")
    T.text_in(painter, QRect(inner.x(), inner.bottom() - 16, inner.width(), 16),
              "C/Esc close", size=9, color=T.DIM, align=T.ALIGN_CENTER, family="Segoe UI")


def _handle_character(session, key):
    if key in ("c", "escape", "esc"):
        session.open_screen = None
    return True


# ===========================================================================
# Journal
# ===========================================================================
def _draw_journal(painter, session, w, h):
    log = session.game.quests
    active = log.active_quests()
    done = log.completed_quests()
    allq = active + done
    st = _sel(session).setdefault("journal", {"row": 0})
    st["row"] = max(0, min(st["row"], max(0, len(allq) - 1)))
    x, y, bw, bh = _panel_rect(w, h)
    inner = T.panel(painter, x, y, bw, bh)
    ty = T.heading(painter, inner, "Journal",
                   f"{len(active)} active · {len(done)} completed")

    list_w = int(inner.width() * 0.4)
    for i, q in enumerate(allq):
        ry = ty + 8 + i * 24
        if i == st["row"]:
            painter.fillRect(QRect(inner.x(), ry - 2, list_w, 22), T.SELECT)
        complete = log.is_complete(q.id)
        col = QColor(120, 190, 130) if complete else (T.GOLD_BRIGHT if i == st["row"] else T.INK)
        prefix = "✓ " if complete else "◈ "
        T.text(painter, inner.x() + 8, ry + 14, prefix + q.name, size=11, color=col,
               family="Segoe UI")

    if allq:
        q = allq[st["row"]]
        dx = inner.x() + list_w + 20
        T.text(painter, dx, ty + 18, q.name, size=15, color=T.GOLD_BRIGHT, bold=True)
        entries = log.journal_entries(q.id)
        body = "\n\n".join(f"• {e}" for e in entries) or q.desc
        if log.is_complete(q.id):
            body += "\n\n(Quest complete.)"
        else:
            body += f"\n\nObjective: {log.current_objective(q.id)}"
        T.text_in(painter, QRect(dx, ty + 34, inner.width() - list_w - 20, inner.height() - 80),
                  body, size=10, color=T.PARCH,
                  align=int(Qt.AlignTop | Qt.AlignLeft) | int(Qt.TextWordWrap),
                  family="Segoe UI")
    else:
        T.text(painter, inner.x() + list_w + 20, ty + 18,
               "Your journal is empty. Talk to the folk of Miniwind to find work.",
               size=11, color=T.DIM, family="Segoe UI")

    T.text_in(painter, QRect(inner.x(), inner.bottom() - 16, inner.width(), 16),
              "↑/↓ select   J/Esc close", size=9, color=T.DIM,
              align=T.ALIGN_CENTER, family="Segoe UI")


def _handle_journal(session, key):
    allq = session.game.quests.active_quests() + session.game.quests.completed_quests()
    st = _sel(session).setdefault("journal", {"row": 0})
    if key in ("up", "w"):
        st["row"] = (st["row"] - 1) % max(1, len(allq)); return True
    if key in ("down", "s"):
        st["row"] = (st["row"] + 1) % max(1, len(allq)); return True
    if key in ("j", "escape", "esc"):
        session.open_screen = None
    return True


# ===========================================================================
# Current Quest (Q) — a focused view of the active quest: what to do now, how
# far the objective is and which way it lies, plus the journal detail. Separate
# from the full Journal (J), which lists every quest past and present.
_COMPASS_WORDS = ["north", "north-east", "east", "south-east",
                  "south", "south-west", "west", "north-west"]


def _compass_word(dx, dz):
    """World-direction word for a vector (engine convention: +z is north)."""
    import math
    bearing = math.degrees(math.atan2(dx, dz)) % 360.0   # 0 = north, 90 = east
    return _COMPASS_WORDS[int((bearing + 22.5) // 45) % 8]


def _known_quests(session):
    """(active, completed) quest lists — every quest the player knows about."""
    log = session.game.quests
    return list(log.active_quests()), list(log.completed_quests())


def _objective_rows(session, q):
    """Objective lines for *q*'s detail pane: (text, is_active_step).

    Revealed stages up to and including the current one are shown; the current
    step is the active objective. A completed quest shows every step as done."""
    log = session.game.quests
    cur = log.stage_of(q.id)
    complete = log.is_complete(q.id)
    rows = []
    for s in sorted(q.stages, key=lambda s: s.index):
        obj = (getattr(s, "objective", "") or "").strip()
        if not obj:
            continue
        if complete or s.index < cur:
            rows.append((obj, False))          # done / past
        elif s.index == cur:
            rows.append((obj, True))           # the active step
        # future stages stay hidden until reached
    if not rows:
        rows.append((q.desc or "See your journal.", not complete))
    return rows


def _draw_quest(painter, session, w, h):
    """The quest journal: a clickable list of every quest the player
    knows (active, then completed) down the left, the selected quest's story and
    objectives on the right, and a "Make Active Quest" box that pins the quest
    so only its arrow shows. Mouse-driven (see :func:`handle_click`); the arrow
    keys and Enter still work."""
    from ..ui.hud import _fmt_distance
    active, completed = _known_quests(session)
    known = active + completed
    st = _sel(session).setdefault("quest", {"row": 0})
    st["row"] = max(0, min(st["row"], max(0, len(known) - 1)))
    tracked = session.tracked_quest_id()

    x, y, bw, bh = _panel_rect(w, h)
    inner = T.panel(painter, x, y, bw, bh)
    _QUEST_HITS["rows"] = []
    _QUEST_HITS["toggle"] = None
    _QUEST_HITS["toggle_qid"] = None
    _QUEST_HITS["map"] = None
    _QUEST_HITS["map_focus"] = None
    ty = T.heading(painter, inner, "Quests")

    if not known:
        T.text_in(painter, QRect(inner.x(), inner.y() + 70, inner.width(), 60),
                  "You have no quests yet.\n\nTalk to the folk of Miniwind "
                  "(look for a golden “!”) to find work.",
                  size=11, color=T.DIM,
                  align=int(Qt.AlignTop | Qt.AlignHCenter) | int(Qt.TextWordWrap),
                  family="Segoe UI")
        T.text_in(painter, QRect(inner.x(), inner.bottom() - 16, inner.width(), 16),
                  "Q/Esc close", size=9, color=T.DIM,
                  align=T.ALIGN_CENTER, family="Segoe UI")
        return

    top = ty + 12
    list_w = int(inner.width() * 0.34)
    lx = inner.x() + 6
    col_x = inner.x() + list_w + 18
    col_w = inner.right() - col_x - 6

    # Divider between the list and the detail pane.
    painter.setPen(QPen(T.GILD, 1))
    painter.drawLine(col_x - 9, top, col_x - 9, inner.bottom() - 8)

    # --- left column: the clickable quest list -----------------------------
    row_h = 22
    yy = top
    idx = 0
    for group_title, group, dim in (("ACTIVE", active, False),
                                    ("COMPLETED", completed, True)):
        if not group:
            continue
        T.text(painter, lx, yy + 12, group_title, size=8, color=T.GOLD,
               bold=True, family="Segoe UI")
        yy += 20
        for q in group:
            r = QRect(lx, yy - 2, list_w - 10, row_h)
            selected = (idx == st["row"])
            if selected:
                painter.fillRect(r, T.SELECT)
            is_tracked = bool(tracked) and q.id == tracked
            color = (T.GOLD_BRIGHT if selected else (T.DIM if dim else T.INK))
            label = ("▸ " if is_tracked else "    ") + q.name
            T.text_in(painter, r.adjusted(4, 0, -4, 0), label, size=10,
                      color=color, align=T.ALIGN_LEFT, family="Segoe UI")
            _QUEST_HITS["rows"].append((QRect(r), idx))
            yy += row_h
            idx += 1
        yy += 10

    # --- right column: the selected quest's detail -------------------------
    q = known[max(0, min(st["row"], len(known) - 1))]
    is_active_q = q in active
    is_tracked = bool(tracked) and q.id == tracked

    T.text(painter, col_x, top + 12, q.name, size=16, color=T.GOLD_BRIGHT, bold=True)
    if session.game.quests.is_complete(q.id):
        T.text_in(painter, QRect(col_x, top, col_w, 16), "COMPLETED", size=8,
                  color=T.DIM, align=T.ALIGN_RIGHT, family="Segoe UI")
    elif is_tracked:
        T.text_in(painter, QRect(col_x, top, col_w, 16),
                  "★ ACTIVE — only this quest's arrow shows", size=8,
                  color=T.GOLD_BRIGHT, align=T.ALIGN_RIGHT, family="Segoe UI")
    painter.setPen(QPen(T.GILD, 1))
    painter.drawLine(col_x, top + 22, inner.right() - 6, top + 22)

    entries = session.game.quests.journal_entries(q.id)
    desc = (entries[-1] if entries else "") or q.desc
    T.text_in(painter, QRect(col_x, top + 30, col_w, 92), desc, size=10,
              color=T.PARCH, align=int(Qt.AlignTop | Qt.AlignLeft) | int(Qt.TextWordWrap),
              family="Segoe UI")

    oy = top + 130
    T.text(painter, col_x, oy, "OBJECTIVES", size=9, color=T.GOLD, bold=True,
           family="Segoe UI")
    oy += 20
    for text_line, is_active_step in _objective_rows(session, q):
        marker = "◆" if is_active_step else "◇"
        T.text(painter, col_x, oy, f"{marker}  {text_line}", size=10,
               color=(T.INK if is_active_step else T.DIM), family="Segoe UI")
        oy += 20

    # Where the objective lies (active quests only) — echoes the orbiting arrow.
    if is_active_q:
        g = session.quest_guidance(q) or {}
        dist = _fmt_distance(g.get("distance"))
        pos = g.get("target_pos")
        ppos = session._player_pos()
        if pos is not None and ppos is not None and dist and dist != "here":
            way = _compass_word(float(pos[0]) - float(ppos[0]),
                                float(pos[2]) - float(ppos[2]))
            T.text(painter, col_x, oy + 6,
                   f"➤ About {dist} to the {way} — follow the arrow.",
                   size=9, color=T.PARCH, family="Segoe UI")

    # --- "Make Active Quest" checkbox (active quests only) -----------------
    if is_active_q:
        box = QRect(col_x, inner.bottom() - 34, 16, 16)
        painter.setPen(QPen(T.GILD, 1))
        painter.setBrush(QColor(30, 28, 40))
        painter.drawRect(box)
        if is_tracked:
            painter.setPen(QPen(T.GOLD_BRIGHT, 2))
            painter.drawLine(box.x() + 3, box.y() + 8, box.x() + 6, box.y() + 12)
            painter.drawLine(box.x() + 6, box.y() + 12, box.x() + 13, box.y() + 3)
        label = ("Active quest — click to show all arrows" if is_tracked
                 else "Make Active Quest (show only this arrow)")
        T.text_in(painter, QRect(box.right() + 8, box.y() - 3, col_w - 30, 20),
                  label, size=10, color=T.INK, align=T.ALIGN_LEFT, family="Segoe UI")
        _QUEST_HITS["toggle"] = QRect(box.x(), box.y() - 3, col_w - 140, 22)
        _QUEST_HITS["toggle_qid"] = q.id
        # "Show on map": the full map, centred and ringed on the objective.
        target = session.quest_guidance(q) or {}
        tpos = target.get("target_pos")
        if tpos is not None:
            mrect = QRect(inner.right() - 132, box.y() - 6, 126, 26)
            hot = hits.hovered(mrect)
            painter.setBrush(QColor(96, 70, 34, 240) if hot else QColor(62, 48, 30, 235))
            painter.setPen(QPen(T.GOLD_BRIGHT if hot else T.GILD, 1.5))
            painter.drawRoundedRect(mrect, 5, 5)
            painter.setFont(fonts.dialogue_font(11))
            painter.setPen(T.GOLD_BRIGHT)
            painter.drawText(mrect, T.ALIGN_CENTER, "Show on map")
            _QUEST_HITS["map"] = QRect(mrect)
            _QUEST_HITS["map_focus"] = (float(tpos[0]), float(tpos[2]), q.name)

    T.text_in(painter, QRect(inner.x(), inner.bottom() - 16, inner.width(), 16),
              "Click a quest to read it  ·  click the box to make it active  ·  "
              "M map  ·  Q/Esc close",
              size=9, color=T.DIM, align=T.ALIGN_CENTER, family="Segoe UI")


def _handle_quest(session, key):
    active, completed = _known_quests(session)
    known = active + completed
    st = _sel(session).setdefault("quest", {"row": 0})
    n = max(1, len(known))
    if key in ("up", "w", "left", "a"):
        st["row"] = (st["row"] - 1) % n; return True
    if key in ("down", "s", "right", "d"):
        st["row"] = (st["row"] + 1) % n; return True
    if key in ("return", "enter", "space") and known:
        # Pin the highlighted quest as the active one (only its arrow shows);
        # pressing again on the pinned quest clears it. Only active quests can
        # be tracked.
        q = known[max(0, min(st["row"], len(known) - 1))]
        if session.game.quests.is_active(q.id):
            session.set_tracked_quest(q.id)
        return True
    if key == "m" and known:
        # The full map, on the highlighted quest's objective when it has one.
        q = known[max(0, min(st["row"], len(known) - 1))]
        pos = (session.quest_guidance(q) or {}).get("target_pos") \
            if session.game.quests.is_active(q.id) else None
        session.map_request = ((float(pos[0]), float(pos[2]), q.name)
                               if pos is not None else "player")
        return True
    if key in ("q", "escape", "esc"):
        session.open_screen = None
    return True


# ===========================================================================
# Spellbook
# ===========================================================================
def _spellbook_spells(session):
    return [spell for sid in session.game.character.known_spells
            if (spell := rpg_magic.get(sid)) is not None]


def _spellbook_selection(session, spells):
    active = session.game.character.active_spell
    st = _sel(session).setdefault("spells", {
        "row": next((i for i, spell in enumerate(spells) if spell.id == active), 0)})
    st["row"] = max(0, min(st["row"], max(0, len(spells) - 1)))
    return st


def _ready_spell(session, spell_id):
    spells = _spellbook_spells(session)
    index = next((i for i, spell in enumerate(spells) if spell.id == spell_id), None)
    if index is None:
        return
    _spellbook_selection(session, spells)["row"] = index
    c = session.game.character
    c.active_spell = spell_id
    eq._refresh_weapon_kind(c)
    session.notify(f"Readied {spells[index].name}", 1.5)


def _spellbook_page(session, step, page_size):
    spells = _spellbook_spells(session)
    st = _spellbook_selection(session, spells)
    page = st["row"] // page_size + step
    st["row"] = max(0, min(page * page_size, max(0, len(spells) - 1)))


def _draw_spells(painter, session, w, h):
    from ..host import K_CAST, K_SPELLS

    c = session.game.character
    spells = _spellbook_spells(session)
    st = _spellbook_selection(session, spells)
    x, y, bw, bh = _panel_rect(w, h)
    inner = T.panel(painter, x, y, bw, bh)
    ty = T.heading(painter, inner, "Spellbook",
                   f"{len(spells)} spells known    ·    Magicka {int(c.magicka)}/{int(c.max_magicka)}")

    list_w = int(inner.width() * 0.5)
    top = ty + 8
    nav_y = inner.bottom() - 52
    page_size = max(1, (nav_y - top - 6) // 24)
    page = st["row"] // page_size
    first = page * page_size
    pages = max(1, (len(spells) + page_size - 1) // page_size)
    fm = QFontMetrics(T.font(11, family="Segoe UI"))
    for i in range(first, min(first + page_size, len(spells))):
        spell = spells[i]
        ry = top + (i - first) * 24
        row_rect = QRect(inner.x(), ry - 2, list_w, 22)
        if i == st["row"]:
            painter.fillRect(row_rect, T.SELECT)
        active = c.active_spell == spell.id
        col = T.GOLD_BRIGHT if i == st["row"] else (T.MAGICKA.lighter(150) if active else T.INK)
        cost = rpg_magic.cast_cost(c, rpg_magic.for_caster(c, spell.id) or spell)
        painter.fillRect(QRect(inner.x() + 2, ry + 3, 3, 14), _rarity_color(spell.rarity))
        label = fm.elidedText(("✦ " if active else "") + spell.name,
                              Qt.ElideRight, max(1, list_w - 126))
        T.text(painter, inner.x() + 10, ry + 14, label,
               size=11, color=col, family="Segoe UI")
        T.text_in(painter, QRect(inner.x(), ry - 2, list_w - 60, 22),
                  f"Lv {c.spell_level(spell.id)}", size=9, color=T.GOLD, align=T.ALIGN_RIGHT,
                  family="Segoe UI")
        T.text_in(painter, QRect(inner.x(), ry - 2, list_w - 8, 22),
                  f"{int(cost)} mp", size=9, color=T.DIM, align=T.ALIGN_RIGHT,
                  family="Segoe UI")
        _row_target(painter, row_rect,
                    lambda s, sid=spell.id: _ready_spell(s, sid), f"spell:{spell.id}")

    if pages > 1:
        button(painter, QRect(inner.x(), nav_y, 80, 26), "Previous",
               lambda s, size=page_size: _spellbook_page(s, -1, size), enabled=page > 0)
        button(painter, QRect(inner.x() + list_w - 64, nav_y, 64, 26), "Next",
               lambda s, size=page_size: _spellbook_page(s, 1, size), enabled=page < pages - 1)
        T.text_in(painter, QRect(inner.x() + 82, nav_y, max(1, list_w - 148), 26),
                  f"{page + 1}/{pages}", size=9, color=T.DIM, align=T.ALIGN_CENTER)

    button(painter, QRect(inner.right() - 90, nav_y, 90, 26), "Close",
           lambda s: setattr(s, "open_screen", None))

    if spells:
        spell = spells[st["row"]]
        dx = inner.x() + list_w + 20
        dw = inner.width() - list_w - 20
        level = c.spell_level(spell.id)
        now = spell.at_level(level)
        T.text(painter, dx, ty + 18, spell.name, size=15, color=T.GOLD_BRIGHT, bold=True)
        T.text(painter, dx, ty + 36, f"{spell.rarity.title()}  ·  Level {level} of "
               f"{spell.max_level}", size=10, color=_rarity_color(spell.rarity),
               bold=True, family="Segoe UI")
        info = (f"School: {sk.label(spell.school)}\nDelivery: {spell.delivery}\n"
                f"Element: {spell.element}\n"
                f"Now: {_spell_power(now)}{int(rpg_magic.cast_cost(c, now))} magicka")
        if level < spell.max_level:
            nxt = spell.at_level(level + 1)
            info += (f"\nLevel {level + 1}: {_spell_power(nxt)}"
                     f"{int(rpg_magic.cast_cost(c, nxt))} magicka")
        info += f"\n\n{spell.desc}"
        T.text_in(painter, QRect(dx, ty + 48, dw, max(1, nav_y - ty - 92)),
                  info, size=10, color=T.PARCH,
                  align=int(Qt.AlignTop | Qt.AlignLeft) | int(Qt.TextWordWrap),
                  family="Segoe UI")
        # Raise the spell with experience -- the same pool character levels
        # are paid from, so it is a real choice.
        cost = c.spell_upgrade_cost(spell.id)
        if cost > 0:
            button(painter, QRect(dx, nav_y - 36, min(dw, 260), 28),
                   f"Raise to level {level + 1}  ({cost} XP)",
                   lambda s, sid=spell.id: _upgrade_spell(s, sid),
                   enabled=c.xp >= cost, primary=True)
            T.text_in(painter, QRect(dx, nav_y - 56, dw, 18),
                      f"Experience: {c.xp}  ·  U raises the selected spell", size=8,
                      color=T.DIM, align=T.ALIGN_LEFT, family="Segoe UI")
        else:
            T.text_in(painter, QRect(dx, nav_y - 30, dw, 20),
                      "Mastered: this spell is at its highest level.", size=9,
                      color=T.GOLD, align=T.ALIGN_LEFT, family="Segoe UI")
    else:
        T.text(painter, inner.x() + list_w + 20, ty + 18,
               "You know no spells yet. Buy them from the Mages Guild.",
               size=11, color=T.DIM, family="Segoe UI")

    T.text_in(painter, QRect(inner.x(), inner.bottom() - 16, inner.width(), 16),
              f"Click a spell to ready it · {K_CAST.upper()} cast · {K_SPELLS.upper()}/Esc close",
              size=9, color=T.DIM,
              align=T.ALIGN_CENTER, family="Segoe UI")


#: Rarity colours for spells, commonest first (game.rpg.magic.RARITIES).
_RARITY_COLORS = {"common": QColor(190, 186, 176), "uncommon": QColor(120, 210, 120),
                  "rare": QColor(110, 160, 245), "epic": QColor(190, 120, 240),
                  "legendary": QColor(245, 165, 70)}


def _rarity_color(rarity):
    return _RARITY_COLORS.get(str(rarity), _RARITY_COLORS["common"])


def _spell_power(spell) -> str:
    """The headline amount of a (levelled) spell: "17 damage, 30s, "."""
    for e in spell.effects or []:
        mag = float(e.get("magnitude", 0))
        if 1 < mag < 99999:
            kind = str(e.get("kind", ""))
            what = ("damage" if kind.startswith("damage") else
                    "healing" if kind.startswith("restore") else kind.replace("_", " "))
            dur = float(e.get("duration", 0))
            return f"{mag:g} {what}" + (f" for {dur:g}s" if dur > 0 else "") + ", "
    for e in spell.effects or []:
        dur = float(e.get("duration", 0))
        if dur > 0:
            return f"lasts {dur:g}s, "
    return ""


def _upgrade_spell(session, spell_id):
    c = session.game.character
    spell = rpg_magic.get(spell_id)
    cost = c.spell_upgrade_cost(spell_id)
    if spell is None or cost <= 0:
        return
    if c.upgrade_spell(spell_id):
        session.notify(f"{spell.name} is now level {c.spell_level(spell_id)}.", 3.5)
    else:
        session.notify(f"Not enough experience: {spell.name} needs {cost} XP "
                       f"(you have {c.xp}).", 3.5)


def _handle_spells(session, key):
    from ..host import K_SPELLS

    spells = _spellbook_spells(session)
    st = _spellbook_selection(session, spells)
    if key in ("up", "w"):
        st["row"] = (st["row"] - 1) % max(1, len(spells)); return True
    if key in ("down", "s"):
        st["row"] = (st["row"] + 1) % max(1, len(spells)); return True
    if key in ("return", "enter") and spells:
        _ready_spell(session, spells[st["row"]].id); return True
    if key == "u" and spells:
        _upgrade_spell(session, spells[st["row"]].id); return True
    if key in (K_SPELLS, "escape", "esc"):
        session.open_screen = None
    return True


# ===========================================================================
# Trade
# ===========================================================================
def _draw_trade(painter, session, w, h):
    c = session.game.character
    npc = session.merchant_npc
    st = _sel(session).setdefault("trade", {"row": 0, "side": 0})
    x, y, bw, bh = _panel_rect(w, h)
    inner = T.panel(painter, x, y, bw, bh)
    name = npc.properties.get("display_name", "Merchant") if npc else "Merchant"
    gold_text = f"Your gold: {c.gold}"
    ty = T.heading(painter, inner, f"Trading with {name}", gold_text)
    # Where a price floats up from: just past the gold total (T.heading's
    # subtitle line).
    from PyQt5.QtCore import QPoint
    from PyQt5.QtGui import QFontMetrics
    gold_w = QFontMetrics(T.font(10, italic=True, family="Segoe UI")).horizontalAdvance(gold_text)
    trade_anim.begin_frame()
    trade_anim.record_gold(QPoint(inner.x() + gold_w + 10, inner.y() + 48))

    # buy list = merchant stock; sell list = player inventory (sellable)
    stock = _merchant_stock(npc)
    sell = _sell_list(c)
    col_w = (inner.width() - 24) // 2
    rows_bottom = inner.bottom() - 70          # room for the buttons below

    for side, (title, lst, buying) in enumerate([("Buy", stock, True), ("Sell", sell, False)]):
        cx = inner.x() + side * (col_w + 24)
        T.text(painter, cx, ty + 4, title, size=13,
               color=T.GOLD_BRIGHT if st["side"] == side else T.DIM, bold=True)
        if not lst:
            T.text(painter, cx + 8, ty + 36, "Nothing to sell" if side else
                   "Nothing for sale", size=10, color=T.DIM, family="Segoe UI")
        shown = 0
        for i, entry in enumerate(lst):
            ry = ty + 24 + i * 22
            if ry > rows_bottom - 20:
                break
            shown = i + 1
            iid = entry["id"] if isinstance(entry, dict) else entry
            d = rpg_items.get(iid)
            price = session._price(d.value if d else 0, buying, npc=npc)
            selected = st["side"] == side and st["row"] == i
            row = QRect(cx, ry - 2, col_w, 20)
            trade_anim.record_row(side, iid, row)
            _row_target(painter, row, _trade_select(side, i),
                        f"{'sell' if side else 'buy'}:{iid}")
            if trade_anim.landing_hidden(side, iid):
                continue            # its item is still flying in
            if selected:
                painter.fillRect(row, T.SELECT)
            nm = (d.name if d else iid)
            if not buying and isinstance(entry, dict) and entry.get("qty", 1) > 1:
                nm += f" ×{entry['qty']}"
            left = session.stock_left(entry) if buying else None
            if left == 0:
                nm += "  (sold out)"
            elif left is not None:
                nm += f" ×{left}"
            colour = T.GOLD_BRIGHT if selected else T.INK
            T.text(painter, cx + 8, ry + 12, nm, size=10,
                   color=T.DIM if left == 0 else colour, family="Segoe UI")
            T.text_in(painter, QRect(cx, ry - 2, col_w - 8, 20), f"{price}g", size=9,
                      color=T.GOLD, align=T.ALIGN_RIGHT, family="Segoe UI")
        # Where a new row would appear: a card with no row to land on (an
        # item sold into stock the merchant does not list) lands here.
        trade_anim.record_column(side, QRect(cx, ty + 24 + shown * 22 - 2, col_w, 20))

    # The trade button names what it will do; Leave ends the trade.
    lst = stock if st["side"] == 0 else sell
    label, can = "Choose an item", False
    if lst:
        entry = lst[min(st["row"], len(lst) - 1)]
        d = rpg_items.get(entry["id"] if isinstance(entry, dict) else entry)
        buying = st["side"] == 0
        price = session._price(d.value if d else 0, buying, npc=npc)
        name_ = d.name if d else "item"
        sold_out = buying and session.stock_left(entry) == 0
        can = (c.gold >= price and not sold_out) if buying else True
        label = (f"Buy {name_} for {price}g" if buying
                 else f"Sell {name_} for {price}g")
        if sold_out:
            label = f"{name_}: sold out until tomorrow"
        elif buying and not can:
            label = f"{name_}: {price}g (not enough gold)"
    by = inner.bottom() - 58
    button(painter, QRect(inner.x() + (inner.width() - 360) // 2, by, 360, 34),
           label, lambda sess: _handle_trade(sess, "return"), enabled=can, primary=True)
    button(painter, QRect(inner.right() - 110, by, 110, 34), "Leave",
           lambda sess: _handle_trade(sess, "escape"))

    T.text_in(painter, QRect(inner.x(), inner.bottom() - 16, inner.width(), 16),
              "Click or ↑/↓ select   ←/→ buy|sell   Enter trade   Esc leave", size=9,
              color=T.DIM, align=T.ALIGN_CENTER, family="Segoe UI")

    # Items changing hands, over everything else on the screen.
    trade_anim.draw(painter)


def _sell_list(c):
    """What the player can sell: everything carried but keys."""
    return [s for s in c.inventory if rpg_items.get(s.get("id")) and
            rpg_items.get(s.get("id")).category != rpg_items.KEY
            and not rpg_items.get(s.get("id")).get("innate")]


def _trade_select(side, row):
    def action(session):
        st = _sel(session).setdefault("trade", {"row": 0, "side": 0})
        st["side"], st["row"] = side, row
    return action


def _merchant_stock(npc):
    if npc is None:
        return []
    stock = npc.properties.get("stock")
    if isinstance(stock, list) and stock:
        return [{"id": s} if isinstance(s, str) else s for s in stock]
    # default stock by role
    role = str(npc.properties.get("npc_role", "merchant"))
    defaults = {
        "merchant": ["potion_heal_minor", "potion_magicka", "torch", "lockpick",
                     "cloth_robe", "cloth_hood", "sandals", "hide_boots", "copper_ring",
                     "iron_arrow", "bread" if rpg_items.get("bread") else "book_lore",
                     "book_lore", "book_last_ferryman", "book_lament_greywood",
                     "book_marksman", "book_blade"],
        "blacksmith": ["iron_longsword", "iron_mace", "steel_longsword", "iron_shield",
                       "iron_cuirass", "iron_helmet", "short_bow", "iron_arrow",
                       "crossbow", "iron_bolt",
                       "chain_shirt", "chain_coif", "scale_mail", "kite_shield",
                       "plate_helm", "plate_armour", "tower_shield", "buckler"],
        "armourer": ["leather_cuirass", "hide_armour", "studded_leather",
                     "chain_shirt", "scale_mail", "plate_armour", "plate_helm",
                     "plate_greaves", "round_shield", "kite_shield"],
    }
    return [{"id": i} for i in defaults.get(role, defaults["merchant"])]


def _handle_trade(session, key):
    st = _sel(session).setdefault("trade", {"row": 0, "side": 0})
    c = session.game.character
    npc = session.merchant_npc
    stock = _merchant_stock(npc)
    sell = _sell_list(c)
    lst = stock if st["side"] == 0 else sell
    if key in ("up", "w"):
        st["row"] = (st["row"] - 1) % max(1, len(lst)); return True
    if key in ("down", "s"):
        st["row"] = (st["row"] + 1) % max(1, len(lst)); return True
    if key in ("left", "a", "right", "d"):
        st["side"] ^= 1; st["row"] = 0; return True
    if key in ("return", "enter") and lst:
        st["row"] = min(st["row"], len(lst) - 1)
        entry = lst[st["row"]]
        iid = entry["id"] if isinstance(entry, dict) else entry
        buying = st["side"] == 0
        d = rpg_items.get(iid)
        price = session._price(d.value if d else 0, buying, npc=npc)
        # Whether the item already has a row on the side it is going to: if
        # so it lands on that row, otherwise its new row waits for it.
        to_list = sell if buying else stock
        had_row = any((e["id"] if isinstance(e, dict) else e) == iid for e in to_list)
        done = session.buy(iid) if buying else session.sell(iid)
        if done:
            trade_anim.launch(iid, d.name if d else iid, f"{price}g",
                              from_side=0 if buying else 1,
                              to_side=1 if buying else 0,
                              lands_on_new_row=not had_row,
                              gold_text=f"{'-' if buying else '+'}{price}g",
                              gold_gain=not buying)
        return True
    if key in ("escape", "esc", "e"):
        close_trade(session)
    return True


def close_trade(session):
    """End the trade: the screen closes and the merchant is let go."""
    session.open_screen = None
    session.merchant_npc = None
    trade_anim.reset()


# ===========================================================================
# Level up — a parchment page: a line of encouragement, then STRENGTH,
# ENDURANCE or MAGICKA (MAGICKA only for those who work magic).
# ===========================================================================
#: (choice, label, what it does) in the order the rows are listed.
_LEVEL_ROWS = (
    ("strength", "Strength",
     "How hard you strike with blade, axe and fist, and how much you can "
     "carry. Every creature in the Vale has a Strength; yours decides who is "
     "still standing after the blow."),
    ("endurance", "Endurance",
     "Maximum health and stamina, the health each level brings, and your "
     "Armour Class. It steadies your aim, hastens your magicka's return and "
     "lets you shrug off hostile magic."),
    ("charisma", "Charisma",
     "How the Vale sees you: merchants' prices, how strangers greet you, how "
     "kindly the town's gossip treats you -- and, with Luck, the Charm & Luck "
     "words that open doors."),
    ("magicka", "Magicka",
     "The depth of your well of magic: how many spells you can cast before "
     "you must rest and let it fill again."),
)
#: Parchment and its inks.
_PARCH_LIGHT = QColor(238, 226, 196)
_PARCH_DARK = QColor(208, 188, 146)
_INK = QColor(64, 34, 22)
_INK_BLUE = QColor(36, 40, 104)
_INK_RED = QColor(122, 40, 30)


def _level_rows(c):
    choices = c.level_choices()
    return tuple(r for r in _LEVEL_ROWS if r[0] in choices)


def _levelup_state(session):
    return _sel(session).setdefault("levelup", {"row": 0})


def _quotes_enabled(session) -> bool:
    check = getattr(session, "motivational_quotes_enabled", None)
    return bool(check()) if callable(check) else True


def _level_preview(c, choice):
    """``[(label, before, after)]`` of what *choice* changes, worked out on a
    copy of the character so the page shows real numbers."""
    import copy
    from ..rpg.character import LEVEL_CHOICES, LEVEL_ATTR_GAIN
    a = LEVEL_CHOICES[choice]
    after = copy.deepcopy(c)
    after.attrs[a] = attr.clamp(after.attrs[a] + LEVEL_ATTR_GAIN)
    after.recompute_derived(reset_current=False)
    rows = [(attr.label(a) if choice != "magicka" else "Intelligence",
             c.attrs[a], after.attrs[a])]
    for label, fn in (("Max health", lambda x: x.max_health),
                      ("Max stamina", lambda x: x.max_stamina),
                      ("Max magicka", lambda x: x.max_magicka),
                      ("Armour Class", eq.armour_class)):
        before, now = int(fn(c)), int(fn(after))
        if now != before:
            rows.append((label, before, now))
    if choice == "strength":
        rows.append(("Melee damage", f"x{0.7 + c.attrs[a] / 100.0:.2f}",
                     f"x{0.7 + after.attrs[a] / 100.0:.2f}"))
    if choice == "charisma":
        from ..rpg import fortune
        rows.append(("Prices", f"x{_cha.price_multiplier(c.attrs[a], True):.2f}",
                     f"x{_cha.price_multiplier(after.attrs[a], True):.2f}"))
        rows.append(("Looks", _cha.tier(c.attrs[a]), _cha.tier(after.attrs[a])))
        rows.append(("Fortune (Charm & Luck)", fortune.score(c), fortune.score(after)))
    return rows


def _paint_parchment(painter, rect):
    """An old page: warm in the middle, browning to the edges, flecked."""
    import random as _random
    from PyQt5.QtGui import QRadialGradient, QBrush
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    grad = QRadialGradient(rect.center(), max(rect.width(), rect.height()) * 0.7)
    grad.setColorAt(0.0, _PARCH_LIGHT)
    grad.setColorAt(0.75, _PARCH_LIGHT.darker(104))
    grad.setColorAt(1.0, _PARCH_DARK)
    painter.setPen(QPen(QColor(120, 92, 54), 2))
    painter.setBrush(QBrush(grad))
    painter.drawRoundedRect(rect, 6, 6)
    rng = _random.Random(rect.width() * 31 + rect.height())
    painter.setPen(Qt.NoPen)
    for _ in range(rect.width() * rect.height() // 900):
        painter.setBrush(QColor(120, 90, 50, rng.randint(10, 32)))
        r = rng.uniform(0.6, 2.2)
        painter.drawEllipse(QRectF(rect.x() + rng.uniform(0, rect.width()),
                                   rect.y() + rng.uniform(0, rect.height()), r, r))
    painter.restore()


def _paint_level_icon(painter, rect, choice, ink=_INK_RED):
    """A woodcut-style glyph for a choice: a sword, a shield, a star."""
    from PyQt5.QtGui import QPainterPath, QPolygonF
    from PyQt5.QtCore import QPointF
    import math as _math
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    cx, cy, s = x + w / 2.0, y + h / 2.0, min(w, h) / 2.0
    painter.setPen(QPen(ink.darker(130), max(1.0, s * 0.06)))
    painter.setBrush(ink)
    if choice == "strength":
        blade = QPolygonF([QPointF(cx - s * 0.10, cy + s * 0.25), QPointF(cx - s * 0.10, cy - s * 0.65),
                           QPointF(cx, cy - s * 0.88), QPointF(cx + s * 0.10, cy - s * 0.65),
                           QPointF(cx + s * 0.10, cy + s * 0.25)])
        painter.drawPolygon(blade)
        painter.drawRect(QRectF(cx - s * 0.42, cy + s * 0.25, s * 0.84, s * 0.12))
        painter.drawRect(QRectF(cx - s * 0.07, cy + s * 0.37, s * 0.14, s * 0.36))
        painter.drawEllipse(QPointF(cx, cy + s * 0.80), s * 0.11, s * 0.11)
    elif choice == "endurance":
        path = QPainterPath()
        path.moveTo(cx, cy - s * 0.80)
        path.cubicTo(cx + s * 0.45, cy - s * 0.65, cx + s * 0.70, cy - s * 0.70,
                     cx + s * 0.70, cy - s * 0.70)
        path.cubicTo(cx + s * 0.72, cy + s * 0.10, cx + s * 0.40, cy + s * 0.60, cx, cy + s * 0.85)
        path.cubicTo(cx - s * 0.40, cy + s * 0.60, cx - s * 0.72, cy + s * 0.10,
                     cx - s * 0.70, cy - s * 0.70)
        path.cubicTo(cx - s * 0.70, cy - s * 0.70, cx - s * 0.45, cy - s * 0.65, cx, cy - s * 0.80)
        painter.drawPath(path)
        painter.setPen(QPen(_PARCH_LIGHT, max(1.5, s * 0.08)))
        painter.drawLine(QPointF(cx, cy - s * 0.55), QPointF(cx, cy + s * 0.55))
        painter.drawLine(QPointF(cx - s * 0.42, cy - s * 0.15), QPointF(cx + s * 0.42, cy - s * 0.15))
    elif choice == "charisma":
        # A crown.
        crown = QPolygonF([QPointF(cx - s * 0.75, cy + s * 0.45), QPointF(cx - s * 0.80, cy - s * 0.45),
                           QPointF(cx - s * 0.40, cy - s * 0.05), QPointF(cx, cy - s * 0.70),
                           QPointF(cx + s * 0.40, cy - s * 0.05), QPointF(cx + s * 0.80, cy - s * 0.45),
                           QPointF(cx + s * 0.75, cy + s * 0.45)])
        painter.drawPolygon(crown)
        painter.drawRect(QRectF(cx - s * 0.78, cy + s * 0.50, s * 1.56, s * 0.22))
        painter.setBrush(_PARCH_LIGHT)
        painter.setPen(Qt.NoPen)
        for dx in (-0.80, 0.0, 0.80):
            painter.drawEllipse(QPointF(cx + s * dx, cy - s * (0.70 if dx == 0 else 0.45)),
                                s * 0.09, s * 0.09)
    else:
        pts = []
        for i in range(16):
            r = s * (0.85 if i % 2 == 0 else 0.32)
            ang = _math.radians(i * 22.5 - 90)
            pts.append(QPointF(cx + _math.cos(ang) * r, cy + _math.sin(ang) * r))
        painter.drawPolygon(QPolygonF(pts))
        painter.setBrush(_PARCH_LIGHT)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(cx, cy), s * 0.16, s * 0.16)
    painter.restore()


def _draw_levelup(painter, session, w, h):
    """The level-up page, after the old tomes: "You have ascended to level
    N", a line of encouragement (unless ``[GAME] motivational_quotes`` is off),
    then STRENGTH, ENDURANCE or MAGICKA, with what the highlighted one does
    and what it would change, in real numbers."""
    from ..rpg import quotes
    from ..rpg.character import LEVEL_ATTR_GAIN, LEVEL_CHOICES
    c = session.game.character
    st = _levelup_state(session)
    rows = _level_rows(c)
    st["row"] %= len(rows)
    x, y, bw, bh = _panel_rect(w, h, 0.72, 0.84)
    page = QRect(x, y, bw, bh)
    _paint_parchment(painter, page)
    pad = 24
    inner = page.adjusted(pad, 16, -pad, -14)
    level = c.level + 1

    T.text_in(painter, QRect(inner.x(), inner.y(), inner.width(), 34),
              f"You have ascended to level {level}", size=20, color=_INK_BLUE,
              align=T.ALIGN_CENTER, family=fonts.dialogue_family())
    top = inner.y() + 42
    if _quotes_enabled(session):
        painter.save()
        painter.setFont(fonts.dialogue_font(13))
        painter.setPen(_INK)
        qrect = QRect(inner.x(), top, inner.width(), 78)
        painter.drawText(qrect, int(Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap),
                         quotes.for_level(level))
        used = painter.fontMetrics().boundingRect(
            qrect, int(Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap),
            quotes.for_level(level)).height()
        painter.restore()
        top += min(78, used) + 14
    T.text_in(painter, QRect(inner.x(), top, inner.width(), 20),
              "Choose an attribute to increase", size=11, color=_INK_BLUE,
              bold=True, family="Segoe UI")
    top += 28

    # The choices, down the left.
    list_w = int(inner.width() * 0.52)
    row_h = 58
    tile = row_h - 8
    for i, (choice, label, _desc) in enumerate(rows):
        ry = top + i * (row_h + 6)
        chosen = st["row"] == i
        tile_r = QRect(inner.x(), ry + 4, tile, tile)
        painter.fillRect(tile_r, QColor(122, 40, 30, 230) if chosen else QColor(196, 170, 128))
        painter.setPen(QPen(QColor(90, 52, 30), 1))
        painter.drawRect(tile_r)
        _paint_level_icon(painter, tile_r.adjusted(6, 6, -6, -6), choice,
                          ink=_PARCH_LIGHT if chosen else QColor(150, 110, 80))
        band = QRect(tile_r.right() + 10, ry + 6, list_w - tile - 10, row_h - 12)
        if chosen:
            from PyQt5.QtGui import QLinearGradient, QBrush
            g = QLinearGradient(band.topLeft(), band.bottomLeft())
            g.setColorAt(0.0, QColor(214, 222, 236))
            g.setColorAt(0.5, QColor(150, 170, 204))
            g.setColorAt(1.0, QColor(118, 140, 182))
            painter.save()
            painter.setPen(QPen(QColor(40, 40, 60), 1.5))
            painter.setBrush(QBrush(g))
            painter.drawRect(band)
            painter.restore()
        a = LEVEL_CHOICES[choice]
        ink = _INK if chosen else QColor(120, 98, 84)
        T.text_in(painter, band.adjusted(14, 0, 0, 0), label, size=17, color=ink,
                  align=T.ALIGN_LEFT, family=fonts.dialogue_family())
        value = (f"{int(c.max_magicka)}" if choice == "magicka" else str(c.attrs[a]))
        T.text_in(painter, QRect(band.right() - 120, band.y(), 60, band.height()), value,
                  size=16, color=ink, align=int(Qt.AlignVCenter | Qt.AlignRight),
                  family=fonts.dialogue_family())
        T.text_in(painter, QRect(band.right() - 52, band.y(), 48, band.height()),
                  f"+{LEVEL_ATTR_GAIN}", size=16, color=_INK_RED if chosen else ink,
                  align=T.ALIGN_CENTER, family=fonts.dialogue_family())
        _row_target(painter, QRect(tile_r.x(), ry, list_w, row_h), _levelup_pick(i),
                    f"levelup:{choice}")

    # The highlighted choice, on the right: its picture, what it does, and
    # what it would change.
    choice, label, desc = rows[st["row"]]
    right = QRect(inner.x() + list_w + 24, top - 28, inner.width() - list_w - 24,
                  inner.bottom() - 60 - (top - 28))
    frame = min(right.width(), 150)
    fr = QRect(right.x() + (right.width() - frame) // 2, right.y(), frame, frame)
    painter.fillRect(fr, QColor(190, 196, 206))
    painter.setPen(QPen(QColor(90, 52, 30), 3))
    painter.drawRect(fr)
    painter.setPen(QPen(QColor(90, 52, 30), 1))
    painter.drawRect(fr.adjusted(6, 6, -6, -6))
    _paint_level_icon(painter, fr.adjusted(18, 18, -18, -18), choice)
    painter.save()
    painter.setFont(T.font(10, bold=True, family="Segoe UI"))
    painter.setPen(_INK)
    drect = QRect(right.x(), fr.bottom() + 10, right.width(), 76)
    painter.drawText(drect, int(Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap), desc)
    painter.restore()
    ey = drect.bottom() + 6
    for name, before, after in _level_preview(c, choice):
        if ey > right.bottom() - 14:
            break
        T.text_in(painter, QRect(right.x(), ey, right.width(), 18),
                  f"{name}:  {before}  →  {after}", size=9, color=_INK_BLUE,
                  align=T.ALIGN_LEFT, bold=True, family="Segoe UI")
        ey += 18

    # The foot: what training has already earned, and the confirm button.
    trained = [(a, c._level_attr_gains.get(a, 0)) for a in attr.ATTRIBUTES]
    trained = [f"{attr.label(a)} +{1 + min(4, g // 2)}" for a, g in
               sorted(trained, key=lambda t: -t[1]) if g > 0][:3]
    foot = (f"Every level: health +{int(c.attrs.get(attr.ENDURANCE, 40) * 0.1)} "
            f"and full restoration.")
    if trained:
        foot += "  Your training also raises: " + ",  ".join(trained) + "."
    T.text_in(painter, QRect(inner.x(), inner.bottom() - 54, inner.width(), 18), foot,
              size=9, color=_INK, align=T.ALIGN_LEFT, family="Segoe UI")
    button(painter, QRect(inner.right() - 250, inner.bottom() - 32, 250, 32),
           f"Increase {label}", lambda sess: _handle_levelup(sess, "return"),
           primary=True)
    T.text_in(painter, QRect(inner.x(), inner.bottom() - 26, inner.width() - 260, 20),
              f"Click, 1–{len(rows)} or ↑/↓ to choose   ·   Enter to confirm", size=9,
              color=QColor(110, 86, 60), align=T.ALIGN_LEFT, family="Segoe UI")


def _levelup_pick(i):
    def action(session):
        _levelup_state(session)["row"] = i
    return action


def _handle_levelup(session, key):
    c = session.game.character
    st = _levelup_state(session)
    rows = _level_rows(c)
    n = len(rows)
    if key in ("left", "a", "up", "w"):
        st["row"] = (st["row"] - 1) % n; return True
    if key in ("right", "d", "down", "s", "tab"):
        st["row"] = (st["row"] + 1) % n; return True
    if key in ("1", "2", "3", "4") and int(key) <= n:
        st["row"] = int(key) - 1; return True
    if key in ("return", "enter", "space"):
        choice, label, _desc = rows[st["row"] % n]
        res = c.level_up(choice=choice)
        session.notify(f"Welcome to level {res['level']}!  "
                       f"{label} +{int(res.get('choice_gain', 0))}", 5.0)
        st["row"] = 0
        session.open_screen = None
        session._sync_engine_health(full=True)
        # Another level banked? Offer it straight away.
        if c.can_level_up:
            session.open_screen = "levelup"
        return True
    return True  # must choose; Escape does not skip a level


# ===========================================================================
# Container — a graphical two-column "take / store" inventory for a world
# Container the player opened with E. Separate from the player's own inventory.
# ===========================================================================
def _cont_state(session):
    return _sel(session).setdefault("container",
                                    {"side": 0, "row_c": 0, "row_p": 0})


#: The container screen's draggable rows and its two drop zones, recorded as
#: it paints for the window that hosts it (game/ui/container_window.py):
#: ``cells`` [(QRect, source)], ``zones`` [(QRect, target)].
CONTAINER_DRAG = {"cells": [], "zones": []}


def _draw_container(painter, session, w, h):
    CONTAINER_DRAG["cells"] = []
    CONTAINER_DRAG["zones"] = []
    c = session.game.character
    st = _cont_state(session)
    citems = session.container_inventory()
    pitems = c.inventory
    x, y, bw, bh = _panel_rect(w, h)
    inner = T.panel(painter, x, y, bw, bh)
    ty = T.heading(painter, inner, session.container_name(),
                   f"{c.gold} gold    ·    click or Enter to take / store   ·   E/Esc close")

    st["row_c"] = max(0, min(st["row_c"], max(0, len(citems) - 1)))
    st["row_p"] = max(0, min(st["row_p"], max(0, len(pitems) - 1)))

    col_w = int((inner.width() - 24) / 2)
    # Column titles sit clear below the heading's subtitle line (drawn by
    # T.heading at ty-8); the item list starts below the titles.
    head_y = ty + 20
    list_y = head_y + 24
    row_h = 22

    def _column(cx, title, items, sel_row, active, side):
        zone = QRect(cx, head_y - 16, col_w, inner.bottom() - 40 - (head_y - 16))
        CONTAINER_DRAG["zones"].append((zone, ("container", None) if side == 0
                                        else ("pack", None)))
        if drag.current is not None and hits.hovered(zone):
            painter.save()
            painter.setPen(QPen(T.GOLD_BRIGHT, 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(zone, 5, 5)
            painter.restore()
        head_col = T.GOLD_BRIGHT if active else T.DIM
        T.text(painter, cx + 6, head_y, title, size=12, color=head_col, bold=True,
               family="Segoe UI")
        if not items:
            T.text(painter, cx + 10, list_y + 16, "(empty)", size=10, color=T.DIM,
                   family="Segoe UI")
        for i, stack in enumerate(items):
            ry = list_y + i * row_h
            if ry > inner.bottom() - 58:
                break
            if i == sel_row and active:
                painter.fillRect(QRect(cx, ry, col_w, row_h - 2), T.SELECT)
            name = stack.get("name", stack.get("id"))
            _row_target(painter, QRect(cx, ry, col_w, row_h - 2),
                        _cont_click(side, i), f"{'take' if side == 0 else 'store'}:{i}")
            CONTAINER_DRAG["cells"].append(
                (QRect(cx, ry, col_w, row_h - 2),
                 ("container", i, stack.get("id")) if side == 0
                 else ("pack", None, stack.get("id"))))
            qty = f" ×{stack['qty']}" if stack.get("qty", 1) > 1 else ""
            ncol = T.GOLD_BRIGHT if (i == sel_row and active) else T.INK
            T.text(painter, cx + 8, ry + 15, name + qty, size=11, color=ncol,
                   family="Segoe UI")

    left_x = inner.x()
    right_x = inner.x() + col_w + 24
    _column(left_x, "Contents", citems, st["row_c"], st["side"] == 0, 0)
    _column(right_x, "Your inventory", pitems, st["row_p"], st["side"] == 1, 1)

    # divider
    painter.setPen(T.GILD)
    midx = inner.x() + col_w + 12
    painter.drawLine(midx, list_y - 4, midx, inner.bottom() - 40)

    bw, bh = 120, 30
    by = inner.bottom() - bh
    button(painter, QRect(inner.x(), by, bw, bh), "Take all",
           lambda sess: sess.take_all_from_container(), enabled=bool(citems),
           primary=True)
    button(painter, QRect(inner.right() - bw, by, bw, bh), "Close",
           lambda sess: sess.close_container())
    hint = "Enter: take →" if st["side"] == 0 else "← Enter: store"
    T.text_in(painter, QRect(inner.x() + bw, by, inner.width() - 2 * bw, bh),
              hint, size=9, color=T.DIM, align=T.ALIGN_CENTER, family="Segoe UI")


def _cont_click(side, index):
    """A click on a container row: take it (contents) or store it (yours)."""
    def act(session):
        st = _cont_state(session)
        st["side"] = side
        if side == 0:
            session.take_from_container(index)
        else:
            session.store_in_container(index)
    return act


def _handle_container(session, key):
    st = _cont_state(session)
    citems = session.container_inventory()
    pitems = session.game.character.inventory
    if key in ("left", "a", "right", "d", "tab"):
        st["side"] ^= 1
        return True
    if key in ("up", "w"):
        k = "row_c" if st["side"] == 0 else "row_p"
        n = len(citems) if st["side"] == 0 else len(pitems)
        st[k] = (st[k] - 1) % max(1, n)
        return True
    if key in ("down", "s"):
        k = "row_c" if st["side"] == 0 else "row_p"
        n = len(citems) if st["side"] == 0 else len(pitems)
        st[k] = (st[k] + 1) % max(1, n)
        return True
    if key in ("return", "enter"):
        if st["side"] == 0:
            session.take_from_container(st["row_c"])
        else:
            session.store_in_container(st["row_p"])
        return True
    if key in ("e", "escape", "esc", "i"):
        session.close_container()
        return True
    return True


def _draw_lockpicking(painter, session, w, h):
    from .lockpicking import draw
    draw(painter, session, *_panel_rect(w, h))


def _handle_lockpicking(session, key):
    from .lockpicking import handle_key
    return handle_key(session, key)


# dispatch tables
_DRAW = {
    "charcreate": _draw_charcreate, "inventory": _draw_inventory,
    "character": _draw_character, "journal": _draw_journal,
    "spells": _draw_spells, "trade": _draw_trade, "levelup": _draw_levelup,
    "container": _draw_container, "quest": _draw_quest,
    "lockpicking": _draw_lockpicking,
}
_HANDLE = {
    "charcreate": _handle_charcreate, "inventory": _handle_inventory,
    "character": _handle_character, "journal": _handle_journal,
    "spells": _handle_spells, "trade": _handle_trade, "levelup": _handle_levelup,
    "container": _handle_container, "quest": _handle_quest,
    "lockpicking": _handle_lockpicking,
    "book": lambda session, key: _handle_book(session, key),
}


def _handle_book(session, key):
    """An open book (game/ui/book_window.py): turn pages, or close it."""
    if key in ("left", "a", "pageup", "backspace"):
        session.turn_book(-1)
    elif key in ("right", "d", "pagedown", "space", "return", "enter"):
        session.turn_book(+1)
    elif key in ("escape", "esc", "e", "tab", "i", "b"):
        session.close_book()
    return True
