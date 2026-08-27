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

from PyQt5.QtCore import QRect, Qt
from PyQt5.QtGui import QColor, QPen

from . import theme as T
from ..rpg import (races, classes, birthsigns, attributes as attr, skills as sk,
                   items as rpg_items, inventory as inv, equipment as eq,
                   magic as rpg_magic, guilds, quests, heads)


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
    "charcreate": (780, 540),
    "inventory": (720, 500),
    "character": (720, 520),
    "journal": (700, 470),
    "spells": (700, 470),
    "levelup": (560, 430),
    "trade": (760, 520),
    "container": (760, 500),
}


def window_body_size(screen):
    return _SCREEN_BODY_SIZE.get(screen, (700, 480))


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
_CC_STEPS = ["identity", "class", "birthsign", "confirm"]
_DEFAULT_RACE = "imperial"          # simplified creator asks no race / gender
_MAX_NAME = 18
_HEAD_PIXMAP_CACHE = {}


def _cc(session):
    return _sel(session).setdefault("cc", {"step": 0, "name": "", "head": 0,
                                           "class": 0, "birthsign": 0})


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
        hint = "Type a name    ←/→ choose head    Enter next"
    elif step == "class":
        ids = classes.CREATION_CLASS_IDS
        k = classes.get(ids[s["class"]])
        list_w = int(inner.width() * 0.42)
        _cc_list(painter, inner.x(), ty, list_w, ids, s["class"],
                 lambda i: classes.get(i).label)
        favs = ", ".join(attr.label(a) for a in k.favored_attrs)
        majors = ", ".join(sk.label(m) for m in k.major_skills)
        _cc_detail(painter, inner.x() + list_w + 24, ty, inner.width() - list_w - 24,
                   k.label, k.desc + f"\n\nSpecialisation: {k.specialisation}"
                   f"\nFavoured: {favs}\nMajor skills: {majors}")
        hint = "↑/↓ choose class    Enter next    Esc back"
    elif step == "birthsign":
        ids = birthsigns.CREATION_BIRTHSIGN_IDS
        b = birthsigns.get(ids[s["birthsign"]])
        list_w = int(inner.width() * 0.42)
        _cc_list(painter, inner.x(), ty, list_w, ids, s["birthsign"],
                 lambda i: birthsigns.get(i).label)
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
        summary = (f"Name: {name}\nClass: {k.label}\nBirthsign: {b.label}\n\n"
                   "Press Enter to begin your adventure, or Esc to go back.")
        _cc_detail(painter, tx, ty, inner.right() - tx, "Ready?", summary)
        hint = "Enter begin    Esc back"

    T.text_in(painter, QRect(inner.x(), inner.bottom() - 16, inner.width(), 16),
              hint, size=10, color=T.DIM, align=T.ALIGN_CENTER, family="Georgia")


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
    hh = inner.bottom() - 40 - hy
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
    painter.drawText(QRect(box.x() - 56, box.y(), 44, size), T.ALIGN_CENTER, "<")
    painter.drawText(QRect(box.right() + 12, box.y(), 44, size), T.ALIGN_CENTER, ">")
    T.text_in(painter, QRect(box.x(), box.bottom() + 4, size, 18),
              f"Head {s['head'] + 1} / {heads.HEAD_COUNT}", size=10,
              color=T.DIM, align=T.ALIGN_CENTER)


def _cc_list(painter, x, y, w, ids, sel, labeller):
    row_h = 26
    for i, item in enumerate(ids):
        ry = y + i * row_h
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
        if key == "backspace":
            s["name"] = s["name"][:-1]; return True
        if key == "space":
            if len(s["name"]) < _MAX_NAME and s["name"]:
                s["name"] += " "
            return True
        if len(key) == 1 and (key.isalpha() or key.isdigit()):
            if len(s["name"]) < _MAX_NAME:
                s["name"] += key
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
        if s["step"] < len(_CC_STEPS) - 1:
            s["step"] += 1
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
    session.begin_new_character(name, _DEFAULT_RACE, klass, sign, "male", head=head)


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
           f"Magicka {int(c.max_magicka)}    Stamina {int(c.max_stamina)}",
           size=11, color=T.PARCH, family="Segoe UI")
    prog = c.xp_progress
    T.bar(painter, inner.x(), ty + 14, 260, 10, prog / 10.0, T.XP,
          label=f"Level progress {prog}/10")

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
# Spellbook
# ===========================================================================
def _draw_spells(painter, session, w, h):
    c = session.game.character
    spells = [rpg_magic.get(s) for s in c.known_spells if rpg_magic.get(s)]
    st = _sel(session).setdefault("spells", {"row": 0})
    st["row"] = max(0, min(st["row"], max(0, len(spells) - 1)))
    x, y, bw, bh = _panel_rect(w, h)
    inner = T.panel(painter, x, y, bw, bh)
    ty = T.heading(painter, inner, "Spellbook",
                   f"{len(spells)} spells known    ·    Magicka {int(c.magicka)}/{int(c.max_magicka)}")

    list_w = int(inner.width() * 0.5)
    for i, spell in enumerate(spells):
        ry = ty + 8 + i * 24
        if i == st["row"]:
            painter.fillRect(QRect(inner.x(), ry - 2, list_w, 22), T.SELECT)
        active = c.active_spell == spell.id
        col = T.GOLD_BRIGHT if i == st["row"] else (T.MAGICKA.lighter(150) if active else T.INK)
        cost = rpg_magic.cast_cost(c, spell)
        T.text(painter, inner.x() + 8, ry + 14, ("✦ " if active else "") + spell.name,
               size=11, color=col, family="Segoe UI")
        T.text_in(painter, QRect(inner.x(), ry - 2, list_w - 8, 22),
                  f"{int(cost)} mp", size=9, color=T.DIM, align=T.ALIGN_RIGHT,
                  family="Segoe UI")

    if spells:
        spell = spells[st["row"]]
        dx = inner.x() + list_w + 20
        T.text(painter, dx, ty + 18, spell.name, size=15, color=T.GOLD_BRIGHT, bold=True)
        info = (f"School: {sk.label(spell.school)}\nDelivery: {spell.delivery}\n"
                f"Element: {spell.element}\nCost: {int(rpg_magic.cast_cost(c, spell))} magicka\n\n{spell.desc}")
        T.text_in(painter, QRect(dx, ty + 34, inner.width() - list_w - 20, 240),
                  info, size=10, color=T.PARCH,
                  align=int(Qt.AlignTop | Qt.AlignLeft) | int(Qt.TextWordWrap),
                  family="Segoe UI")
    else:
        T.text(painter, inner.x() + list_w + 20, ty + 18,
               "You know no spells yet. Buy them from the Mages Guild.",
               size=11, color=T.DIM, family="Segoe UI")

    T.text_in(painter, QRect(inner.x(), inner.bottom() - 16, inner.width(), 16),
              "↑/↓ select   Enter set active   P/Esc close", size=9, color=T.DIM,
              align=T.ALIGN_CENTER, family="Segoe UI")


def _handle_spells(session, key):
    c = session.game.character
    spells = [s for s in c.known_spells if rpg_magic.get(s)]
    st = _sel(session).setdefault("spells", {"row": 0})
    if key in ("up", "w"):
        st["row"] = (st["row"] - 1) % max(1, len(spells)); return True
    if key in ("down", "s"):
        st["row"] = (st["row"] + 1) % max(1, len(spells)); return True
    if key in ("return", "enter") and spells:
        c.active_spell = spells[st["row"]]; return True
    if key in ("p", "escape", "esc"):
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
    ty = T.heading(painter, inner, f"Trading with {name}", f"Your gold: {c.gold}")

    # buy list = merchant stock; sell list = player inventory (sellable)
    stock = _merchant_stock(npc)
    sell = [s for s in c.inventory if rpg_items.get(s.get("id")) and
            rpg_items.get(s.get("id")).category != rpg_items.KEY]
    col_w = (inner.width() - 24) // 2

    for side, (title, lst, buying) in enumerate([("Buy", stock, True), ("Sell", sell, False)]):
        cx = inner.x() + side * (col_w + 24)
        T.text(painter, cx, ty + 4, title, size=13,
               color=T.GOLD_BRIGHT if st["side"] == side else T.DIM, bold=True)
        for i, entry in enumerate(lst):
            ry = ty + 24 + i * 22
            if ry > inner.bottom() - 30:
                break
            iid = entry["id"] if isinstance(entry, dict) else entry
            d = rpg_items.get(iid)
            price = session._price(d.value if d else 0, buying)
            selected = st["side"] == side and st["row"] == i
            if selected:
                painter.fillRect(QRect(cx, ry - 2, col_w, 20), T.SELECT)
            nm = (d.name if d else iid)
            if not buying and isinstance(entry, dict) and entry.get("qty", 1) > 1:
                nm += f" ×{entry['qty']}"
            T.text(painter, cx + 8, ry + 12, nm, size=10,
                   color=T.GOLD_BRIGHT if selected else T.INK, family="Segoe UI")
            T.text_in(painter, QRect(cx, ry - 2, col_w - 8, 20), f"{price}g", size=9,
                      color=T.GOLD, align=T.ALIGN_RIGHT, family="Segoe UI")

    T.text_in(painter, QRect(inner.x(), inner.bottom() - 16, inner.width(), 16),
              "↑/↓ select   ←/→ buy|sell   Enter trade   Esc leave", size=9,
              color=T.DIM, align=T.ALIGN_CENTER, family="Segoe UI")


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
                     "iron_arrow", "bread" if rpg_items.get("bread") else "book_lore"],
        "blacksmith": ["iron_longsword", "iron_mace", "steel_longsword", "iron_shield",
                       "iron_cuirass", "iron_helmet", "short_bow", "iron_arrow"],
    }
    return [{"id": i} for i in defaults.get(role, defaults["merchant"])]


def _handle_trade(session, key):
    st = _sel(session).setdefault("trade", {"row": 0, "side": 0})
    c = session.game.character
    npc = session.merchant_npc
    stock = _merchant_stock(npc)
    sell = [s for s in c.inventory if rpg_items.get(s.get("id"))]
    lst = stock if st["side"] == 0 else sell
    if key in ("up", "w"):
        st["row"] = (st["row"] - 1) % max(1, len(lst)); return True
    if key in ("down", "s"):
        st["row"] = (st["row"] + 1) % max(1, len(lst)); return True
    if key in ("left", "a", "right", "d"):
        st["side"] ^= 1; st["row"] = 0; return True
    if key in ("return", "enter") and lst:
        entry = lst[st["row"]]
        iid = entry["id"] if isinstance(entry, dict) else entry
        if st["side"] == 0:
            session.buy(iid)
        else:
            session.sell(iid)
        return True
    if key in ("escape", "esc"):
        session.open_screen = None; session.merchant_npc = None
    return True


# ===========================================================================
# Level up
# ===========================================================================
def _draw_levelup(painter, session, w, h):
    c = session.game.character
    st = _sel(session).setdefault("levelup", {"row": 0, "picks": []})
    x, y, bw, bh = _panel_rect(w, h, 0.6, 0.7)
    inner = T.panel(painter, x, y, bw, bh)
    ty = T.heading(painter, inner, "Level Up!",
                   f"Choose up to 3 attributes to raise (level {c.level} → {c.level+1})")
    for i, a in enumerate(attr.ATTRIBUTES):
        ry = ty + 8 + i * 24
        picked = a in st["picks"]
        if i == st["row"]:
            painter.fillRect(QRect(inner.x(), ry - 2, inner.width(), 22), T.SELECT)
        mark = "☑ " if picked else "☐ "
        gains = c._level_attr_gains.get(a, 0)
        mult = 1 + min(4, gains // 2)
        T.text(painter, inner.x() + 8, ry + 14, mark + attr.label(a) + f"  ({c.attrs[a]})",
               size=11, color=T.GOLD_BRIGHT if i == st["row"] else T.INK, family="Segoe UI")
        T.text_in(painter, QRect(inner.x(), ry - 2, inner.width() - 8, 22),
                  f"+{mult}", size=10, color=T.STAMINA.lighter(140),
                  align=T.ALIGN_RIGHT, family="Segoe UI")
    T.text_in(painter, QRect(inner.x(), inner.bottom() - 16, inner.width(), 16),
              "↑/↓ move   Space toggle   Enter confirm", size=9, color=T.DIM,
              align=T.ALIGN_CENTER, family="Segoe UI")


def _handle_levelup(session, key):
    c = session.game.character
    st = _sel(session).setdefault("levelup", {"row": 0, "picks": []})
    if key in ("up", "w"):
        st["row"] = (st["row"] - 1) % len(attr.ATTRIBUTES); return True
    if key in ("down", "s"):
        st["row"] = (st["row"] + 1) % len(attr.ATTRIBUTES); return True
    if key == "space":
        a = attr.ATTRIBUTES[st["row"]]
        if a in st["picks"]:
            st["picks"].remove(a)
        elif len(st["picks"]) < 3:
            st["picks"].append(a)
        return True
    if key in ("return", "enter"):
        picks = st["picks"] or None
        res = c.level_up(picks)
        session.notify(f"Welcome to level {res['level']}!", 5.0)
        st["picks"] = []
        session.open_screen = None
        session._sync_engine_health(full=True)
        return True
    if key in ("escape", "esc"):
        return True  # must choose; don't allow escape out
    return True


# ===========================================================================
# Container — a graphical two-column "take / store" inventory for a world
# Container the player opened with E. Separate from the player's own inventory.
# ===========================================================================
def _cont_state(session):
    return _sel(session).setdefault("container",
                                    {"side": 0, "row_c": 0, "row_p": 0})


def _draw_container(painter, session, w, h):
    c = session.game.character
    st = _cont_state(session)
    citems = session.container_inventory()
    pitems = c.inventory
    x, y, bw, bh = _panel_rect(w, h)
    inner = T.panel(painter, x, y, bw, bh)
    ty = T.heading(painter, inner, session.container_name(),
                   f"{c.gold} gold    ·    Tab/←/→ switch side   ·   Enter take/store   ·   E/Esc close")

    st["row_c"] = max(0, min(st["row_c"], max(0, len(citems) - 1)))
    st["row_p"] = max(0, min(st["row_p"], max(0, len(pitems) - 1)))

    col_w = int((inner.width() - 24) / 2)
    list_y = ty + 26
    row_h = 22

    def _column(cx, title, items, sel_row, active):
        head_col = T.GOLD_BRIGHT if active else T.DIM
        T.text(painter, cx + 6, ty + 6, title, size=12, color=head_col, bold=True,
               family="Segoe UI")
        if not items:
            T.text(painter, cx + 10, list_y + 16, "(empty)", size=10, color=T.DIM,
                   family="Segoe UI")
        for i, stack in enumerate(items):
            ry = list_y + i * row_h
            if ry > inner.bottom() - 24:
                break
            if i == sel_row and active:
                painter.fillRect(QRect(cx, ry, col_w, row_h - 2), T.SELECT)
            name = stack.get("name", stack.get("id"))
            qty = f" ×{stack['qty']}" if stack.get("qty", 1) > 1 else ""
            ncol = T.GOLD_BRIGHT if (i == sel_row and active) else T.INK
            T.text(painter, cx + 8, ry + 15, name + qty, size=11, color=ncol,
                   family="Segoe UI")

    left_x = inner.x()
    right_x = inner.x() + col_w + 24
    _column(left_x, "Contents", citems, st["row_c"], st["side"] == 0)
    _column(right_x, "Your inventory", pitems, st["row_p"], st["side"] == 1)

    # divider
    painter.setPen(T.GILD)
    midx = inner.x() + col_w + 12
    painter.drawLine(midx, list_y - 4, midx, inner.bottom() - 20)

    hint = "Enter: take →" if st["side"] == 0 else "← Enter: store"
    T.text_in(painter, QRect(inner.x(), inner.bottom() - 16, inner.width(), 16),
              hint, size=9, color=T.DIM, align=T.ALIGN_CENTER, family="Segoe UI")


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


# dispatch tables
_DRAW = {
    "charcreate": _draw_charcreate, "inventory": _draw_inventory,
    "character": _draw_character, "journal": _draw_journal,
    "spells": _draw_spells, "trade": _draw_trade, "levelup": _draw_levelup,
    "container": _draw_container,
}
_HANDLE = {
    "charcreate": _handle_charcreate, "inventory": _handle_inventory,
    "character": _handle_character, "journal": _handle_journal,
    "spells": _handle_spells, "trade": _handle_trade, "levelup": _handle_levelup,
    "container": _handle_container,
}
