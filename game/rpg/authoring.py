"""
A tiny human-writable grammar for dialogue conditions & actions, so the
Property-Manager Dialogue editor can author branching, quest-driving conversations
as plain text that round-trips to the exact JSON the :class:`DialogueRunner`
consumes. Pure and unit-tested — no Qt.

Response line grammar (in the editor's "Responses" box, one per line)::

    Some response text -> GOTO_NODE | if <condition> | do <actions>

* ``-> GOTO_NODE`` — the node to go to (``END`` closes the conversation).
* ``| if <condition>`` — only show this option when the condition holds.
* ``| do <actions>`` — run these when the option is chosen.

Node "on-enter actions" box: one ``<action>`` per line.

Conditions::  key == value | key != value | has item_id | lacks item_id
Actions   ::  set key=value ; start_quest qid ; complete_quest qid ;
              advance_quest qid ; give item_id[,qty] ; take item_id[,qty] ;
              open_trade ; persuade ; join_guild guild_id
"""

from __future__ import annotations

from typing import Dict, List, Optional


# ------------------------------------------------------------------ conditions
def parse_condition(text: str) -> Optional[Dict]:
    text = (text or "").strip()
    if not text:
        return None
    low = text.lower()
    if low.startswith("has "):
        return {"has_item": text[4:].strip()}
    if low.startswith("lacks "):
        return {"lacks_item": text[6:].strip()}
    for op, key in (("!=", "not_equals"), ("==", "equals"), ("=", "equals")):
        if op in text:
            k, v = text.split(op, 1)
            return {"key": k.strip(), key: v.strip()}
    return None


def format_condition(cond: Dict) -> str:
    if not cond:
        return ""
    if "has_item" in cond:
        return f"has {cond['has_item']}"
    if "lacks_item" in cond:
        return f"lacks {cond['lacks_item']}"
    key = cond.get("key", "")
    if "equals" in cond:
        return f"{key} == {cond['equals']}"
    if "not_equals" in cond:
        return f"{key} != {cond['not_equals']}"
    return ""


# --------------------------------------------------------------------- actions
def parse_action(text: str) -> Optional[Dict]:
    text = (text or "").strip()
    if not text:
        return None
    parts = text.split(None, 1)
    op = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    if op == "set":
        if "=" in arg:
            k, v = arg.split("=", 1)
            return {"op": "set", "key": k.strip(), "value": v.strip()}
        return None
    if op in ("start_quest", "complete_quest", "advance_quest"):
        return {"op": op, "quest": arg}
    if op in ("give", "give_item"):
        iid, qty = _id_qty(arg)
        return {"op": "give_item", "item": {"id": iid, "qty": qty}}
    if op in ("take", "take_item"):
        iid, qty = _id_qty(arg)
        return {"op": "take_item", "item_id": iid, "qty": qty}
    if op == "join_guild":
        return {"op": "join_guild", "guild": arg}
    if op in ("open_trade", "persuade"):
        return {"op": op}
    # unknown op: keep it verbatim so nothing is silently lost
    return {"op": op, "arg": arg} if op else None


def _id_qty(arg: str):
    if "," in arg:
        iid, q = arg.split(",", 1)
        try:
            return iid.strip(), int(q.strip())
        except ValueError:
            return iid.strip(), 1
    return arg.strip(), 1


def format_action(action: Dict) -> str:
    op = action.get("op", "")
    if op == "set":
        return f"set {action.get('key','')}={action.get('value','')}"
    if op in ("start_quest", "complete_quest", "advance_quest"):
        return f"{op} {action.get('quest', action.get('value',''))}"
    if op == "give_item":
        it = action.get("item", {})
        q = it.get("qty", 1)
        return f"give {it.get('id','')}" + (f",{q}" if q and q != 1 else "")
    if op == "take_item":
        q = action.get("qty", 1)
        return f"take {action.get('item_id','')}" + (f",{q}" if q and q != 1 else "")
    if op == "join_guild":
        return f"join_guild {action.get('guild','')}"
    if op in ("open_trade", "persuade"):
        return op
    return (op + (" " + action.get("arg", "") if action.get("arg") else "")).strip()


def parse_actions(text: str) -> List[Dict]:
    """Parse a ';'- or newline-separated action list."""
    out = []
    for chunk in str(text or "").replace("\n", ";").split(";"):
        a = parse_action(chunk)
        if a:
            out.append(a)
    return out


def format_actions(actions: List[Dict]) -> str:
    return " ; ".join(format_action(a) for a in (actions or []))


# ------------------------------------------------------------------- responses
def parse_response_line(line: str) -> Optional[Dict]:
    line = (line or "").strip()
    if not line:
        return None
    # split off pipes first: text->goto | if COND | do ACTIONS
    segs = [s.strip() for s in line.split("|")]
    head = segs[0]
    if "->" in head:
        text, goto = head.rsplit("->", 1)
        text, goto = text.strip(), goto.strip() or "END"
    else:
        text, goto = head, "END"
    resp = {"text": text, "goto": goto}
    for seg in segs[1:]:
        low = seg.lower()
        if low.startswith("if "):
            cond = parse_condition(seg[3:])
            if cond:
                resp["condition"] = cond
        elif low.startswith("do "):
            acts = parse_actions(seg[3:])
            if acts:
                resp["actions"] = acts
    return resp


def format_response(resp: Dict) -> str:
    line = f"{resp.get('text','')} -> {resp.get('goto','END')}"
    if resp.get("condition"):
        line += f" | if {format_condition(resp['condition'])}"
    if resp.get("actions"):
        line += f" | do {format_actions(resp['actions'])}"
    return line
