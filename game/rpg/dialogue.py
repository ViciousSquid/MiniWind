"""
Dialogue trees with conditions & actions (§8, §9, §10).

A dialogue tree is plain JSON-friendly data stored on an NPC under
``properties['dialogue']``::

    {
        "start": "greeting",
        "nodes": {
            "greeting": {
                "text": "Welcome to the village, traveller.",
                "responses": [
                    {"text": "Who are you?", "goto": "about"},
                    {"text": "I could use some work.",
                     "goto": "quest",
                     "condition": {"key": "village_quest", "equals": "false"}},
                    {"text": "Goodbye.", "goto": "END"}
                ]
            },
            "quest": {
                "text": "Bandits have taken the old mill. Deal with them.",
                "on_enter": [{"op": "set", "key": "village_quest", "value": "started"}],
                "responses": [
                    {"text": "I'll take a blade for the road.",
                     "goto": "END",
                     "actions": [{"op": "give_item",
                                  "item": {"id": "iron_sword", "name": "Iron Sword",
                                           "type": "weapon", "value": 25}}]}
                ]
            }
        }
    }

**Conditions** gate whether a response is shown; **actions** run when a response
is chosen; ``on_enter`` actions run when a node is displayed. Both read and
write persistent world state through a small ``store`` interface — in the plugin
that store is backed by Fio's :class:`LogicKeyValueStore` registry via the
plugin ``GlobalStore`` (§9), so quest flags set in dialogue are the *same*
values map logic and other plugins see, and they persist through save/load.

Values are strings (matching the KV store). ``give_item`` / ``take_item`` defer
to a caller-supplied callback so this module never imports inventory ownership
rules — it just describes intent.

Pure Python — safe everywhere.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

END = "END"


class DictStore:
    """A minimal string key/value store — the interface the runner needs.

    In the plugin this is replaced by an adapter over the engine
    ``GlobalStore`` / ``LogicKeyValueStore``; here it doubles as the test double
    and a safe fallback.
    """

    def __init__(self, data: Dict[str, str] = None):
        self._data = dict(data or {})

    def get(self, key, default="false"):
        return self._data.get(str(key), default)

    def set(self, key, value):
        self._data[str(key)] = str(value)

    def all(self):
        return dict(self._data)


def _truthy(value) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "started", "done", "on")


class DialogueRunner:
    """Walks a dialogue tree, evaluating conditions and firing actions.

    Stateless with respect to the tree (it just reads it); the only mutable
    thing it touches is the *store* and, via callbacks, the world. Construct one
    per conversation; it is cheap.
    """

    def __init__(self, tree: Dict, store=None,
                 give_item: Callable[[Dict], None] = None,
                 take_item: Callable[[str, int], bool] = None,
                 has_item: Callable[[str, int], bool] = None,
                 on_action: Callable[[Dict], None] = None):
        self.tree = tree or {}
        self.store = store if store is not None else DictStore()
        self._give_item = give_item
        self._take_item = take_item
        self._has_item = has_item
        self._on_action = on_action
        self.node_id: Optional[str] = None

    # --- navigation --------------------------------------------------------
    def start(self) -> Optional[Dict]:
        """Enter the tree's start node and return its display view."""
        start = self.tree.get("start")
        nodes = self.tree.get("nodes", {})
        if not start or start not in nodes:
            # fall back to any first node so a half-authored tree still opens
            start = next(iter(nodes), None)
        return self.goto(start)

    def goto(self, node_id: Optional[str]) -> Optional[Dict]:
        """Move to *node_id*, run its ``on_enter`` actions, return its view."""
        if not node_id or node_id == END:
            self.node_id = None
            return None
        node = self.tree.get("nodes", {}).get(node_id)
        if node is None:
            self.node_id = None
            return None
        self.node_id = node_id
        for action in node.get("on_enter", []) or []:
            self._run_action(action)
        return self.view()

    def choose(self, index: int) -> Optional[Dict]:
        """Pick the *index*-th currently-visible response and advance."""
        view = self.view()
        if view is None:
            return None
        responses = view["responses"]
        if index < 0 or index >= len(responses):
            return None
        chosen = responses[index]
        for action in chosen.get("actions", []) or []:
            self._run_action(action)
        return self.goto(chosen.get("goto", END))

    # --- presentation ------------------------------------------------------
    def view(self) -> Optional[Dict]:
        """Return ``{"text", "responses"}`` for the current node.

        ``responses`` is filtered to only those whose ``condition`` passes; each
        keeps its original list for :meth:`choose` — the returned indices line
        up with the visible options.
        """
        if not self.node_id:
            return None
        node = self.tree.get("nodes", {}).get(self.node_id)
        if node is None:
            return None
        visible = [r for r in node.get("responses", [])
                   if self._condition_passes(r.get("condition"))]
        return {"text": node.get("text", ""), "responses": visible}

    # --- conditions & actions ---------------------------------------------
    def _condition_passes(self, cond) -> bool:
        if not cond:
            return True
        # has_item / lacks_item are resolved via callback when available.
        if "has_item" in cond:
            if self._has_item is None:
                return True
            return self._has_item(cond["has_item"], int(cond.get("qty", 1)))
        if "lacks_item" in cond:
            if self._has_item is None:
                return True
            return not self._has_item(cond["lacks_item"], int(cond.get("qty", 1)))
        key = cond.get("key")
        if key is None:
            return True
        current = self.store.get(key, "false")
        if "equals" in cond:
            return str(current) == str(cond["equals"])
        if "not_equals" in cond:
            return str(current) != str(cond["not_equals"])
        if "is_true" in cond:
            return _truthy(current) == bool(cond["is_true"])
        return True

    def _run_action(self, action) -> None:
        if not action:
            return
        op = action.get("op")
        if op == "set":
            self.store.set(action.get("key"), action.get("value"))
        elif op == "start_quest":
            self.store.set(action.get("key"), action.get("value", "started"))
        elif op == "give_item":
            if self._give_item is not None and action.get("item"):
                self._give_item(action["item"])
        elif op == "take_item":
            if self._take_item is not None:
                self._take_item(action.get("item_id"), int(action.get("qty", 1)))
        # Any other op is forwarded to a caller-supplied sink (teleport, fire
        # I/O event, change faction, …) so the vocabulary can grow outside this
        # module (§8).
        if self._on_action is not None:
            self._on_action(action)
