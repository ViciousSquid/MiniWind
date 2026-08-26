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
from PyQt5.QtGui import QColor

from . import theme as T
from ..rpg import (races, classes, birthsigns, attributes as attr, skills as sk,
                   items as rpg_items, inventory as inv, equipment as eq,
                   magic as rpg_magic, guilds, quests)


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


def _panel_rect(w, h, pw=0.8, ph=0.82):
    bw, bh = int(w * pw), int(h * ph)
    return (w - bw) // 2, (h - bh) // 2, bw, bh


# ===========================================================================
# Character creation
# ===========================================================================
_CC_STEPS = ["gender", "race", "class", "birthsign", "confirm"]
_CC_GENDERS = ["male", "female"]


def _cc(session):
    s = _sel(session).setdefault("cc", {"step": 0, "gender": 0, "race": 0,
                                        "class": 0, "birthsign": 0})
    return s


def _draw_charcreate(painter, session, w, h):
    s = _cc(session)
    x, y, bw, bh = _panel_rect(w, h, 0.82, 0.86)
    inner = T.panel(painter, x, y, bw, bh)
    step = _CC_STEPS[s["step"]]
    ty = T.heading(painter, inner, "Create Your Character",
                   f"The Vale of Miniwind awaits — step {s['step']+1} of {len(_CC_STEPS)}")

    col_x = inner.x()
    list_w = int(inner.width() * 0.42)
    detail_x = col_x + list_w + 24
    detail_w = inner.width() - list_w - 24

    if step == "gender":
        _cc_list(painter, col_x, ty, list_w, _CC_GENDERS, s["gender"],
                 lambda g: g.title())
        _cc_detail(painter, detail_x, ty, detail_w,
                   "Sex", "Choose your character's sex. It affects nothing but "
                   "how the world addresses you.")
    elif step == "race":
        rid = races.RACE_IDS[s["race"]]
        r = races.get(rid)
        _cc_list(painter, col_x, ty, list_w, races.RACE_IDS, s["race"],
                 lambda i: races.get(i).label)
        bonuses = ", ".join(f"+{v} {attr.label(k)}" if v > 0 else f"{v} {attr.label(k)}"
                            for k, v in r.attr_bonuses.items())
        pw = r.power["name"] if r.power else "—"
        _cc_detail(painter, detail_x, ty, detail_w, r.label,
                   r.desc + "\n\nAttributes: " + (bonuses or "balanced") +
                   f"\nPower: {pw}")
    elif step == "class":
        cid = classes.CLASS_IDS[s["class"]]
        k = classes.get(cid)
        _cc_list(painter, col_x, ty, list_w, classes.CLASS_IDS, s["class"],
                 lambda i: classes.get(i).label)
        majors = ", ".join(sk.label(m) for m in k.major_skills)
        favs = ", ".join(attr.label(a) for a in k.favored_attrs)
        _cc_detail(painter, detail_x, ty, detail_w, k.label,
                   k.desc + f"\n\nSpecialisation: {k.specialisation}" +
                   f"\nFavoured: {favs}\nMajor skills: {majors}")
    elif step == "birthsign":
        bid = birthsigns.BIRTHSIGN_IDS[s["birthsign"]]
        b = birthsigns.get(bid)
        _cc_list(painter, col_x, ty, list_w, birthsigns.BIRTHSIGN_IDS, s["birthsign"],
                 lambda i: birthsigns.get(i).label)
        _cc_detail(painter, detail_x, ty, detail_w, b.label, b.desc)
    elif step == "confirm":
        r = races.get(races.RACE_IDS[s["race"]])
        k = classes.get(classes.CLASS_IDS[s["class"]])
        b = birthsigns.get(birthsigns.BIRTHSIGN_IDS[s["birthsign"]])
        summary = (f"Sex: {_CC_GENDERS[s['gender']].title()}\n"
                   f"Race: {r.label}\nClass: {k.label}\nBirthsign: {b.label}\n\n"
                   "Press Enter to begin your adventure, or Esc to go back.")
        _cc_detail(painter, col_x, ty, inner.width(), "Ready?", summary)

    T.text_in(painter, QRect(inner.x(), inner.bottom() - 16, inner.width(), 16),
              "↑/↓ choose    Enter next    Esc back", size=9, color=T.DIM,
              align=T.ALIGN_CENTER, family="Segoe UI")


def _cc_list(painter, x, y, w, ids, sel, labeller):
    row_h = 26
    for i, item in enumerate(ids):
        ry = y + i * row_h
        if i == sel:
            painter.fillRect(QRect(x, ry, w, row_h - 2), T.SELECT)
            painter.setPen(T.GILD)
            painter.drawRect(QRect(x, ry, w, row_h - 2))
        T.text_in(painter, QRect(x + 10, ry, w - 12, row_h - 2), labeller(item),
                  size=11, color=T.GOLD_BRIGHT if i == sel else T.INK,
                  align=T.ALIGN_LEFT)


def _cc_detail(painter, x, y, w, title, body):
    T.text(painter, x, y + 12, title, size=15, color=T.GOLD_BRIGHT, bold=True)
    T.text_in(painter, QRect(x, y + 24, w, 400), body, size=10, color=T.PARCH,
              align=int(Qt.AlignTop | Qt.AlignLeft) | int(Qt.TextWordWrap),
              family="Segoe UI")


def _handle_charcreate(session, key):
    s = _cc(session)
    step = _CC_STEPS[s["step"]]
    lists = {
        "gender": (_CC_GENDERS, "gender"),
        "race": (races.RACE_IDS, "race"),
        "class": (classes.CLASS_IDS, "class"),
        "birthsign": (birthsigns.BIRTHSIGN_IDS, "birthsign"),
    }
    if step in lists:
        ids, field = lists[step]
        if key in ("up", "w"):
            s[field] = (s[field] - 1) % len(ids)
            return True
        if key in ("down", "s"):
            s[field] = (s[field] + 1) % len(ids)
            return True
    if key in ("return", "enter"):
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
    gender = _CC_GENDERS[s["gender"]]
    race = races.RACE_IDS[s["race"]]
    klass = classes.CLASS_IDS[s["class"]]
    sign = birthsigns.BIRTHSIGN_IDS[s["birthsign"]]
    name = _default_name(race, gender)
    session.begin_new_character(name, race, klass, sign, gender)


def _default_name(race, gender):
    names = {
        ("nord", "male"): "Ragnar", ("nord", "female"): "Freya",
        ("imperial", "male"): "Marcus", ("imperial", "female"): "Livia",
        ("breton", "male"): "Alaric", ("breton", "female"): "Elowen",
        ("dunmer", "male"): "Dral", ("dunmer", "female"): "Nadei",
        ("bosmer", "male"): "Faelan", ("bosmer", "female"): "Aerin",
        ("altmer", "male"): "Calen", ("altmer", "female"): "Ithil",
        ("orc", "male"): "Grosh", ("orc", "female"): "Bura",
        ("redguard", "male"): "Kesh", ("redguard", "female"): "Saeda",
        ("khajiit", "male"): "Ra'zin", ("khajiit", "female"): "Sonatta",
        ("argonian", "male"): "Keen-Eye", ("argonian", "female"): "Sees-Far",
    }
    return names.get((race, gender), "Adventurer")


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


# dispatch tables
_DRAW = {
    "charcreate": _draw_charcreate, "inventory": _draw_inventory,
    "character": _draw_character, "journal": _draw_journal,
    "spells": _draw_spells, "trade": _draw_trade, "levelup": _draw_levelup,
}
_HANDLE = {
    "charcreate": _handle_charcreate, "inventory": _handle_inventory,
    "character": _handle_character, "journal": _handle_journal,
    "spells": _handle_spells, "trade": _handle_trade, "levelup": _handle_levelup,
}
