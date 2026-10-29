"""Persistent, world-wide ownership of NPC head images.

Heads belong to character identities, not to scenes, journeys, or draw calls.
A resident and their travelling stand-in are the *same* identity; any other
two people must never resolve to the same head PNG. The registry survives
streaming, save/load and movement between maps via MiniWind's global store.

Animals are not people: a flock can legitimately share a species sprite.
"""
from __future__ import annotations

import hashlib
import json

from . import heads

STORE_KEY = "heads.identity.v1"


class HeadPoolExhausted(RuntimeError):
    """More distinct people need heads than there are distinct images."""


def identity(props):
    """Stable identity for an authored NPC or a travelling representative."""
    if not isinstance(props, dict):
        return ""
    value = (props.get("_head_identity") or props.get("_memory_identity")
             or props.get("flour_resident") or props.get("resident")
             or props.get("id") or props.get("name"))
    return str(value or "").strip()


def member_identity(member):
    """A board member retains its identity when its transient scene ID changes."""
    return str(member.get("resident") or member.get("_head_identity")
               or member.get("id") or member.get("name") or "").strip()


def npc(props):
    """The rule applies to people; animal/monster species sprites are separate."""
    return (isinstance(props, dict) and
            str(props.get("type", "")).replace("_", "").lower() == "npc")


def image_key(head_id):
    """Canonical picture path, not merely an authoring label."""
    if not heads.is_any_head(head_id):
        return ""
    return heads.any_head_path(head_id).replace("\\", "/").casefold()


class WorldHeadRegistry:
    def __init__(self, store):
        self.store = store
        self.assignments = {}
        self.used = {}
        self.player_head = ""
        self.reload()

    def reload(self):
        raw = self.store.get(STORE_KEY, "")
        try:
            saved = json.loads(raw) if raw and raw != "false" else {}
        except (ValueError, TypeError):
            saved = {}
        self.assignments = {str(k): str(v) for k, v in saved.items()
                            if k and heads.is_any_head(v)} if isinstance(saved, dict) else {}
        self._reindex()

    def reset(self):
        """New game, not a continuation of another world's people."""
        self.assignments.clear()
        self._reindex()
        self.persist()

    def set_player(self, head_id):
        """The player's picture is unavailable to every NPC, even from old saves."""
        self.player_head = str(head_id or "")
        self._reindex()

    def _reindex(self):
        self.used = {}
        picture = image_key(self.player_head)
        if picture:
            self.used[picture] = "__player__"
        # Old saves may already contain collisions. Keep the first legitimate
        # owner deterministically, then let reconciliation repair the rest.
        good = {}
        for owner, head in sorted(self.assignments.items()):
            picture = image_key(head)
            if picture and picture not in self.used:
                good[owner] = head
                self.used[picture] = owner
        self.assignments = good

    @staticmethod
    def _fits(head, guard):
        if guard:
            return heads.is_guard_head(head)
        return heads.is_any_head(head) and not heads.is_guard_head(head)

    def assign(self, owner, requested="", *, guard=False):
        """Get/claim one picture, or *raise* rather than recycle another face."""
        owner = str(owner or "").strip()
        if not owner:
            raise ValueError("An NPC requires a stable identity to own a head")
        assigned = self.assignments.get(owner, "")
        if assigned and self._fits(assigned, guard):
            return assigned
        if assigned:
            self.used.pop(image_key(assigned), None)
            self.assignments.pop(owner, None)
        requested = str(requested or "").strip()
        candidates = []
        if self._fits(requested, guard):
            candidates.append(requested)
        pool = heads.GUARD_HEAD_IDS if guard else heads.HEAD_IDS
        # Stable per-identity starting position; no random re-rolls on reload.
        start = int.from_bytes(hashlib.sha256(owner.encode("utf-8")).digest()[:8],
                               "big") % len(pool)
        candidates.extend(pool[start:] + pool[:start])
        for head in candidates:
            picture = image_key(head)
            if picture and picture not in self.used:
                self.assignments[owner] = head
                self.used[picture] = owner
                self.persist()
                return head
        role = "guard" if guard else "regular"
        raise HeadPoolExhausted(
            f"No unused {role} head for {owner!r}; add more distinct head PNGs "
            "instead of duplicating another character's face")

    def persist(self):
        self.store.set(STORE_KEY, json.dumps(self.assignments, sort_keys=True,
                                           separators=(",", ":")))
