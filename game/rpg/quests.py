"""
Quests & the journal.

A quest is a static definition with an ordered list of **stages**; each stage
carries a journal entry and, optionally, marks the quest finished. Live quest
state (which stage you're on, whether it's complete) lives in the persistent
key/value store as plain strings — the same store dialogue and map logic use —
so it round-trips through Fio's save/load with no new format and can be read by
map I/O (`TestValue`) to open gates, spawn enemies, etc.

Keys used per quest ``q``:
    quest.<q>.stage   integer, current stage index (-1 = not started)
    quest.<q>.state   "" | "active" | "complete" | "failed"
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional


#: Condition kinds a stage can require before it auto-advances. ``none`` means
#: the stage advances only when scripted (dialogue ``advance_quest`` etc.).
COND_NONE = "none"
COND_FETCH = "fetch"     # target = item id, count = how many to hold
COND_TALK = "talk"       # target = NPC name/role
COND_KILL = "kill"       # target = monster_type / npc_role / name, count = how many
COND_VISIT = "visit"     # target = location id/name (a discoverable Marker)
COND_ROLL = "roll"       # notation = dice expression, target = minimum total
COND_KINDS = [COND_NONE, COND_FETCH, COND_TALK, COND_KILL, COND_VISIT, COND_ROLL]


class Stage:
    def __init__(self, index: int, journal: str, finishes: bool = False,
                 objective: str = "", condition=None, waypoint: str = ""):
        self.index = index
        self.journal = journal
        self.finishes = finishes
        self.objective = objective or journal
        # Optional completion condition: {"kind","target","count"}. When set and
        # its kind is not ``none``, the runtime auto-advances this stage once the
        # condition is met (see game.runtime._tick_quests).
        self.condition = dict(condition) if isinstance(condition, dict) else None
        # Optional purely-navigational hint: the name of a world thing (marker
        # place, NPC name/role, monster type or item id) the quest arrow should
        # point at while on this stage. Unlike ``condition`` this NEVER advances
        # the quest — it only gives the on-screen arrow a destination when the
        # stage has no machine-readable condition (e.g. "clear the mill"). When
        # empty, the arrow falls back to the quest giver.
        self.waypoint = str(waypoint or "").strip()

    def condition_kind(self) -> str:
        c = self.condition or {}
        k = str(c.get("kind", COND_NONE)).lower()
        return k if k in COND_KINDS else COND_NONE

    def condition_target(self) -> str:
        return str((self.condition or {}).get("target", "")).strip()

    def condition_count(self) -> int:
        try:
            return max(1, int((self.condition or {}).get("count", 1)))
        except (TypeError, ValueError):
            return 1

    def condition_notation(self) -> str:
        """Return the dice expression required by a roll objective."""
        return str((self.condition or {}).get("notation", "1d20")).strip() or "1d20"

    def condition_target_value(self) -> Optional[int]:
        """Return a roll objective's threshold, when one is authored."""
        try:
            value = (self.condition or {}).get("target")
            return None if value in (None, "") else int(value)
        except (TypeError, ValueError):
            return None


class Quest:
    def __init__(self, qid, name, stages, giver="", desc="", rewards=None,
                 faction="", xp=0):
        self.id = qid
        self.name = name
        self.stages: List[Stage] = stages
        self.giver = giver
        self.desc = desc
        self.rewards = rewards or {}   # {"gold": n, "items": [(id,qty)], "rep": (faction, n)}
        self.faction = faction
        self.xp = xp

    def stage(self, index: int) -> Optional[Stage]:
        for s in self.stages:
            if s.index == index:
                return s
        return None


QUESTS: Dict[str, Quest] = {}


def register(quest: Quest) -> Quest:
    QUESTS[quest.id] = quest
    return quest


def get(qid: str) -> Optional[Quest]:
    return QUESTS.get(str(qid))


# ---------------------------------------------------------------------------
# Data-driven quests (authored in the editor on the GameSettings entity)
# ---------------------------------------------------------------------------
def quest_from_dict(data: Dict) -> Optional[Quest]:
    """Build a :class:`Quest` from a plain, editor-authored dict.

    Shape::

        {"id": "my_quest", "name": "My Quest", "giver": "Bob", "faction": "town",
         "desc": "...", "xp": 20,
         "rewards": {"gold": 100, "items": [["iron_sword", 1]], "rep": ["town", 10]},
         "stages": [
             {"index": 0, "journal": "Do the thing.", "objective": "Do the thing",
              "finishes": false},
             {"index": 10, "journal": "It is done.", "finishes": true}]}
    """
    if not isinstance(data, dict) or not data.get("id"):
        return None
    stages = []
    for i, s in enumerate(data.get("stages", []) or []):
        stages.append(Stage(int(s.get("index", i * 10)), s.get("journal", ""),
                            bool(s.get("finishes", False)), s.get("objective", ""),
                            condition=s.get("condition"),
                            waypoint=s.get("waypoint", "")))
    if not stages:
        stages = [Stage(0, data.get("desc", "A new quest."))]
    rewards = dict(data.get("rewards", {}) or {})
    # normalise rep/items to the tuple/list shapes complete_quest expects
    if isinstance(rewards.get("rep"), list) and len(rewards["rep"]) == 2:
        rewards["rep"] = (rewards["rep"][0], int(rewards["rep"][1]))
    rewards["items"] = [tuple(it) for it in rewards.get("items", []) if len(it) == 2]
    return Quest(str(data["id"]), data.get("name", data["id"]), stages,
                 giver=data.get("giver", ""), desc=data.get("desc", ""),
                 rewards=rewards, faction=data.get("faction", ""),
                 xp=int(data.get("xp", 0)))


def offer_dialogue_branch(dialogue, qid, name, desc=""):
    """Ensure a dialogue tree offers quest *qid*, so the giver hands it out.

    This is the single piece of logic that makes a quest *acceptable in play*:
    it injects a branch on the tree's start node — a "you mentioned a task…"
    response leading to a small offer node with accept / decline choices, where
    accepting runs the ``start_quest`` action the runtime honours. It is what
    makes the '!' available-quest bubble appear and lets the player walk up and
    talk to take the quest.

    Pure and Qt-free so both the editor (wiring a chosen giver) and the runtime
    (auto-wiring every giver at play start) share it. Idempotent: a tree that
    already starts *qid* anywhere is left untouched. Accepts ``None`` / a
    non-dict and builds a fresh greeting tree. Returns ``(dialogue, changed)``.
    """
    if not isinstance(dialogue, dict):
        dialogue = {"start": "", "nodes": {}}
    dialogue.setdefault("nodes", {})
    nodes = dialogue["nodes"]

    # Ensure a start node exists to hang the offer response on.
    start = dialogue.get("start") or ""
    if start not in nodes:
        start = "greet"
        nodes.setdefault(start, {"text": "Greetings, traveller.", "responses": []})
        dialogue["start"] = start
    node = nodes[start]
    node.setdefault("responses", [])

    # Already offers this quest? (scan every node's responses + on-enter actions)
    for n in nodes.values():
        acts = list(n.get("on_enter", []) or [])
        for r in n.get("responses", []) or []:
            acts.extend(r.get("actions", []) or [])
        for a in acts:
            if isinstance(a, dict) and a.get("op") == "start_quest" \
                    and (a.get("quest") or a.get("value")) == qid:
                return dialogue, False

    name = name or qid
    qnode_id = f"offer_{qid}"
    nodes[qnode_id] = {
        "text": desc or f"I have a task for you: {name}.",
        "responses": [
            {"text": "I'll do it.", "goto": "END",
             "actions": [{"op": "start_quest", "quest": qid}]},
            {"text": "Not right now.", "goto": "END"},
        ],
    }
    node["responses"].append(
        {"text": f"You mentioned a task… ({name})", "goto": qnode_id})
    return dialogue, True


def load_definitions(defs) -> int:
    """Register a list of editor-authored quest dicts. Returns how many loaded.

    Map-authored quests override built-ins of the same id, so a level can retune
    or replace a starter quest without touching code.
    """
    n = 0
    for data in defs or []:
        q = quest_from_dict(data)
        if q is not None:
            register(q)
            n += 1
    return n


class QuestLog:
    """A view over quest state in a string key/value ``store``.

    ``store`` needs ``get(key, default)`` and ``set(key, value)`` — the same
    interface dialogue uses. In the game that's the Fio ``GlobalStore`` /
    ``LogicKeyValueStore`` so quests persist and are visible to map logic.
    """

    def __init__(self, store):
        self.store = store

    def _key(self, qid, field):
        return f"quest.{qid}.{field}"

    def stage_of(self, qid: str) -> int:
        try:
            return int(self.store.get(self._key(qid, "stage"), "-1"))
        except (TypeError, ValueError):
            return -1

    def state_of(self, qid: str) -> str:
        v = self.store.get(self._key(qid, "state"), "")
        return "" if v in (None, "false") else str(v)

    def is_active(self, qid: str) -> bool:
        return self.state_of(qid) == "active"

    def is_complete(self, qid: str) -> bool:
        return self.state_of(qid) == "complete"

    def start(self, qid: str) -> bool:
        if self.state_of(qid):
            return False
        q = get(qid)
        if q is None:
            return False
        self.store.set(self._key(qid, "state"), "active")
        self.set_stage(qid, q.stages[0].index if q.stages else 0)
        return True

    def set_stage(self, qid: str, index: int) -> None:
        self.store.set(self._key(qid, "stage"), int(index))
        q = get(qid)
        if q is not None:
            st = q.stage(index)
            if st and st.finishes:
                self.complete(qid)

    def advance(self, qid: str) -> None:
        """Move to the next defined stage after the current one."""
        q = get(qid)
        if q is None:
            return
        cur = self.stage_of(qid)
        nxt = None
        for s in sorted(q.stages, key=lambda s: s.index):
            if s.index > cur:
                nxt = s.index
                break
        if nxt is not None:
            self.set_stage(qid, nxt)

    def complete(self, qid: str) -> None:
        self.store.set(self._key(qid, "state"), "complete")

    def fail(self, qid: str) -> None:
        self.store.set(self._key(qid, "state"), "failed")

    def record_roll(self, qid: str, stage: int, result: Dict) -> None:
        """Persist the latest dice result for a quest stage."""
        self.store.set(self._key(qid, "roll"), json.dumps({
            "stage": int(stage),
            "result": dict(result),
        }, separators=(",", ":")))

    def last_roll(self, qid: str) -> Optional[Dict]:
        """Return the persisted latest quest roll, or ``None`` if absent."""
        raw = self.store.get(self._key(qid, "roll"), "")
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else None
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def current_objective(self, qid: str) -> str:
        q = get(qid)
        if q is None:
            return ""
        st = q.stage(self.stage_of(qid))
        return st.objective if st else ""

    # -- journal presentation ----------------------------------------------
    def active_quests(self) -> List[Quest]:
        return [q for q in QUESTS.values() if self.is_active(q.id)]

    def completed_quests(self) -> List[Quest]:
        return [q for q in QUESTS.values() if self.is_complete(q.id)]

    def journal_entries(self, qid: str) -> List[str]:
        """All journal lines up to and including the current stage."""
        q = get(qid)
        if q is None:
            return []
        cur = self.stage_of(qid)
        return [s.journal for s in sorted(q.stages, key=lambda s: s.index)
                if s.index <= cur]
