"""
Who is hostile to whom, as data a game supplies to the monster AI.

Fio's MonsterAI has always had one rule: actors on *different* non-empty
``team``s are enemies, and every awake actor that has no enemy goes for the
player. That makes a village of different teams a battlefield (villagers fight
sheep) and makes every deer hunt the player. A game with factions installs a
:class:`HostilityModel` instead:

* ``groups`` -- the team names it knows about;
* ``hostile`` -- a dense ``(G, G)`` boolean matrix: ``hostile[i, j]`` means
  group *i* attacks group *j* on sight (it need not be symmetric);
* ``hunts_player`` -- a ``(G,)`` boolean mask: does group *i* go for the
  player.

and, optionally, a per-actor override of the player mask: when ``hunts_key``
is set, an actor whose property of that name is present hunts the player
exactly when the value is in ``hunts_values`` (a game marks an angry
individual hostile without moving it to another group).

The AI never asks this per pair in Python. It resolves the table's team codes
to the model's once per distinct team list (:meth:`for_names`, cached), so the
hot path indexes a small matrix with arrays. A team the model does not know
keeps the old rule (hostile to every other team, hunts the player), and so
does a teamless actor's player mask unless ``default_hunts`` says otherwise.

Engine-neutral: plain NumPy and team strings; it knows no game.
"""

from __future__ import annotations

import numpy as np


def _key(name) -> str:
    return str(name or "").strip().lower()


class HostilityModel:
    """Dense, game-supplied hostility; see the module docstring."""

    def __init__(self, groups, hostile, hunts_player, *, hunts_key=None,
                 hunts_values=(True,), default_hunts=True):
        groups = [_key(g) for g in groups]
        hostile = np.asarray(hostile, dtype=bool)
        hunts = np.asarray(hunts_player, dtype=bool)
        g = len(groups)
        if hostile.shape != (g, g):
            raise ValueError(f"hostile must be {g}x{g}, got {hostile.shape}")
        if hunts.shape != (g,):
            raise ValueError(f"hunts_player must have {g} entries, got {hunts.shape}")
        if len(set(groups)) != g:
            raise ValueError("group names must be distinct")
        self.groups = tuple(groups)
        self.code = {name: i for i, name in enumerate(groups)}
        self.hostile = hostile
        self.hunts_player = hunts
        self.hunts_key = hunts_key
        self.hunts_values = frozenset(hunts_values)
        self.default_hunts = bool(default_hunts)
        self._cache = {}

    # -- resolution ---------------------------------------------------------
    def for_names(self, names):
        """``(hostile, hunts)`` for a list of team names, in that order.

        ``hostile[a, b]`` and ``hunts[a]`` are indexed by position in *names*
        -- the team codes the AI's table already uses -- so the caller can
        index with its code arrays directly. A name the model does not know
        is hostile to every other name (the old rule) and hunts the player.
        Cached per distinct tuple of names: the list changes only when a new
        team appears.
        """
        key = tuple(names)
        got = self._cache.get(key)
        if got is not None:
            return got
        n = len(key)
        codes = np.array([self.code.get(_key(name), -1) for name in key], dtype=np.int64)
        known = codes >= 0
        matrix = ~np.eye(n, dtype=bool)                 # the old rule
        if known.any():
            k = np.flatnonzero(known)
            matrix[np.ix_(k, k)] = self.hostile[np.ix_(codes[k], codes[k])]
        hunts = np.ones(n, dtype=bool)
        hunts[known] = self.hunts_player[codes[known]]
        if len(self._cache) > 64:
            self._cache.clear()
        got = self._cache[key] = (matrix, hunts)
        return got

    def is_hostile(self, team_a, team_b) -> bool:
        """The scalar question, for the per-actor path: does *a* attack *b*?"""
        a, b = _key(team_a), _key(team_b)
        if not a or not b:
            return False
        ia, ib = self.code.get(a), self.code.get(b)
        if ia is None or ib is None:
            return a != b
        return bool(self.hostile[ia, ib])

    def hunts(self, props) -> bool:
        """Does the actor with these properties go for the player?"""
        if self.hunts_key is not None and self.hunts_key in props:
            return props.get(self.hunts_key) in self.hunts_values
        team = _key(props.get("team", ""))
        if not team:
            return self.default_hunts
        code = self.code.get(team)
        return True if code is None else bool(self.hunts_player[code])

    def row_hunts(self, props, team_codes, names):
        """``(n,)`` bool: who of these rows goes for the player.

        *team_codes* are the rows' indices into *names* (-1 teamless), as the
        AI's table holds them. The group mask is one gather; the per-actor
        override, when the model has one, is one pass over the property dicts
        (the same cost as each flag the table already reads).
        """
        n = len(team_codes)
        _matrix, hunts = self.for_names(names)
        codes = np.asarray(team_codes)[:n]
        out = np.full(n, self.default_hunts, dtype=bool)
        teamed = codes >= 0
        if teamed.any():
            out[teamed] = hunts[codes[teamed]]
        key = self.hunts_key
        if key is not None:
            values = self.hunts_values
            override = np.fromiter(
                ((-1 if key not in p else (1 if p.get(key) in values else 0))
                 for p in props[:n]), dtype=np.int8, count=n)
            has = override >= 0
            out[has] = override[has] == 1
        return out
