"""
World frames as changes: send only what changed since a frame the peer has.

The host sends the whole world to every peer twenty times a second -- some
770 KB of JSON (125 KB compressed) on the Vale, though only a handful of its
~1,900 entities change from one frame to the next. So a frame travels as a
**patch** against a **baseline**: an earlier frame the peer is known to hold
(over TCP, the last one sent -- TCP delivers it; over UDP, the newest one the
peer has acknowledged). The first frame, or one with no usable baseline,
travels whole.

A patch is plain JSON, tagged so it is never mistaken for a value:

* ``["=", value]`` -- the value is replaced;
* ``["d", {key: patch}, [removed keys]]`` -- a dict, key by key;
* ``["l", {id: patch}, [removed ids], [appended items]]`` -- a list of dicts
  that each carry a unique string ``"id"`` (the world's entities): items by
  id, kept in order (when the order itself changed, the list is replaced).

:func:`apply` never changes the frame it patches, and the receiver hands the
game a private copy (:func:`clone`): frames it keeps as baselines are never
touched by the game. Numbers compare as numbers (``1 == 1.0``), as in JSON.
Pure Python, no I/O; tested headless.
"""

from __future__ import annotations

from collections import OrderedDict

#: Frames a sender remembers (for baselines) and a receiver keeps.
HISTORY = 64


def clone(value):
    """A private copy of a JSON value (dicts and lists copied, the rest shared:
    strings and numbers never change)."""
    if isinstance(value, dict):
        return {k: clone(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clone(v) for v in value]
    return value


def _ids(items):
    """The ids of a list of dicts each with a unique str "id", or None."""
    ids = []
    for item in items:
        if not isinstance(item, dict):
            return None
        key = item.get("id")
        if not isinstance(key, str):
            return None
        ids.append(key)
    return ids if len(set(ids)) == len(ids) else None


def diff(old, new):
    """The patch that turns *old* into *new*, or None when they are equal."""
    if old is new:
        return None
    if type(old) is type(new) or (isinstance(old, (int, float)) and isinstance(new, (int, float))
                                  and not isinstance(old, bool) and not isinstance(new, bool)):
        if old == new:
            return None
    if isinstance(old, dict) and isinstance(new, dict):
        changes = {}
        for key, value in new.items():
            if key in old:
                patch = diff(old[key], value)
                if patch is not None:
                    changes[key] = patch
            else:
                changes[key] = ["=", value]
        removed = [key for key in old if key not in new]
        if not changes and not removed:
            return None
        return ["d", changes, removed]
    if isinstance(old, list) and isinstance(new, list) and old and new:
        old_ids, new_ids = _ids(old), _ids(new)
        if old_ids is not None and new_ids is not None:
            new_set, old_set = set(new_ids), set(old_ids)
            removed = [i for i in old_ids if i not in new_set]
            appended = [item for item, i in zip(new, new_ids) if i not in old_set]
            order = [i for i in old_ids if i in new_set] + [item["id"] for item in appended]
            if order == new_ids:
                by_id = dict(zip(old_ids, old))
                changes = {}
                for item, i in zip(new, new_ids):
                    if i in old_set:
                        patch = diff(by_id[i], item)
                        if patch is not None:
                            changes[i] = patch
                if not changes and not removed and not appended:
                    return None
                return ["l", changes, removed, appended]
    return ["=", new]


def apply(old, patch):
    """*old* with *patch* applied, as a new value (*old* is not changed;
    parts that did not change are shared)."""
    if patch is None:
        return old
    if not isinstance(patch, list) or not patch:
        raise ValueError("Invalid frame patch.")
    tag = patch[0]
    if tag == "=" and len(patch) == 2:
        return patch[1]
    if tag == "d" and len(patch) == 3 and isinstance(old, dict):
        changes, removed = patch[1], patch[2]
        if not isinstance(changes, dict) or not isinstance(removed, list):
            raise ValueError("Invalid frame patch.")
        out = {k: v for k, v in old.items() if k not in set(removed)} if removed else dict(old)
        for key, sub in changes.items():
            out[key] = apply(old.get(key), sub) if key in old else _value(sub)
        return out
    if tag == "l" and len(patch) == 4 and isinstance(old, list):
        changes, removed, appended = patch[1], patch[2], patch[3]
        if not (isinstance(changes, dict) and isinstance(removed, list) and isinstance(appended, list)):
            raise ValueError("Invalid frame patch.")
        gone = set(removed)
        out = []
        for item in old:
            key = item.get("id") if isinstance(item, dict) else None
            if key in gone:
                continue
            out.append(apply(item, changes[key]) if key in changes else item)
        out.extend(appended)
        return out
    raise ValueError("Invalid frame patch.")


def _value(patch):
    if isinstance(patch, list) and len(patch) == 2 and patch[0] == "=":
        return patch[1]
    raise ValueError("Invalid frame patch.")


class PatchCache:
    """One patch per (baseline, frame) pair, shared by every peer: a frame
    broadcast to three peers with the same baseline is diffed once."""

    def __init__(self, size=8):
        self.size = size
        self._entries = []          # (base, frame, patch)

    def patch(self, base, frame):
        for b, f, p in self._entries:
            if b is base and f is frame:
                return p
        p = diff(base, frame)
        self._entries.append((base, frame, p))
        del self._entries[:-self.size]
        return p


class FrameSender:
    """Turns each latest-wins frame into ``{"type": "_frame", ...}``: whole,
    or a patch against the newest frame the peer holds (:meth:`ack`)."""

    def __init__(self, cache=None):
        self.cache = cache or PatchCache()
        self.next_id = 1
        self.sent = OrderedDict()   # id -> frame
        self.acked = 0

    def make(self, frame) -> dict:
        fid = self.next_id
        self.next_id += 1
        base = self.sent.get(self.acked) if self.acked else None
        if base is not None:
            packet = {"type": "_frame", "id": fid, "base": self.acked,
                      "patch": self.cache.patch(base, frame)}
        else:
            packet = {"type": "_frame", "id": fid, "base": 0, "full": frame}
        self.sent[fid] = frame
        while len(self.sent) > HISTORY:
            self.sent.popitem(last=False)
        return packet

    def ack(self, fid) -> None:
        """The peer holds frame *fid* (and so can patch from it)."""
        if isinstance(fid, int) and fid > self.acked and fid in self.sent:
            self.acked = fid

    def reset(self) -> None:
        """Send the next frame whole (the peer lost its baselines)."""
        self.acked = 0


class FrameReceiver:
    """Rebuilds frames from ``_frame`` packets; keeps its own copies as
    baselines and hands out private ones."""

    def __init__(self):
        self.frames = OrderedDict()  # id -> frame (never given out)
        self.newest = 0

    def take(self, packet):
        """``(frame, id)`` for a ``_frame`` packet, or ``(None, id)`` when it
        is older than one already taken or its baseline is unknown."""
        fid = packet.get("id")
        if not isinstance(fid, int) or fid <= self.newest:
            return None, fid
        base_id = packet.get("base", 0)
        if base_id:
            base = self.frames.get(base_id)
            if base is None:
                return None, fid
            frame = apply(base, packet.get("patch"))
        else:
            frame = packet.get("full")
        if not isinstance(frame, dict):
            raise ValueError("Invalid world frame.")
        self.frames[fid] = frame
        while len(self.frames) > HISTORY:
            self.frames.popitem(last=False)
        self.newest = fid
        return clone(frame), fid
