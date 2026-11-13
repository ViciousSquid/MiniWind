"""
The flame spawner: FIRE Effect entities made where grass burns, and taken
away when it has burnt out.

Grass fire (:mod:`game.grass_fire`) is simulated in cells; what the player
sees burning is the engine's FIRE Effect, in the one look every fire has
(:mod:`game.fire_look`). The burning ground is taken in blocks of
:data:`BLOCK` x :data:`BLOCK` cells, and the blocks burning nearest the player
each get a flame, sized by how much burns there and how hot, carrying the
Effect's own light, so the edge of a fire lights the ground around it.

**What it costs.** Adding or removing an entity re-indexes the world's
entities (about 7 ms on the overworld), so the spawner never does it a flame
at a time: flames due and flames spent wait, and are spawned and removed
together, at most every :data:`FLUSH_EVERY` seconds -- one re-index for the
lot. In between, a flame that stays is only resized and moved, which costs
nothing. Never more than :data:`MAX_FLAMES` stand at once.

A flame stays with its block while the block burns, so flames never jump
about, and each starts its animation at its own point, so they never flicker
in step. Spawned flames belong to the session: nothing of them is saved.
"""

from __future__ import annotations

import math
import random

from . import fio, fire_look

#: Most flames standing at once.
MAX_FLAMES = 32
#: Cells per side of the block one flame stands for.
BLOCK = 3
#: Burning blocks further than this from the player get no flame.
SHOW_RADIUS = 2600.0
#: Least seconds between spawning/removing (each time re-indexes the world),
#: and between moving and resizing the flames that stay.
FLUSH_EVERY = 0.5
PLACE_EVERY = 0.1
#: A flame's size at full heat over one burning cell; it grows with the
#: cells burning in its block.
FLAME_W, FLAME_H = 70.0, 105.0
LIGHT = {"light_enabled": True, "light_radius": 300.0, "light_intensity": 2.5}


def _blocks(fire):
    """``{block key: [cells, heat, fuel, x, y, z]}`` of *fire*'s burning
    cells, the position the cells' mean."""
    from .grass_fire import CELL, heat
    blocks = {}
    for (cx, cz), (left, total, fuel, y, _seed) in fire.burning.items():
        key = (cx // BLOCK, cz // BLOCK)
        x, z, h = (cx + 0.5) * CELL, (cz + 0.5) * CELL, heat(left, total)
        b = blocks.get(key)
        if b is None:
            blocks[key] = [1, h, fuel, x, y, z]
        else:
            n = b[0] + 1
            b[3] += (x - b[3]) / n
            b[4] += (y - b[4]) / n
            b[5] += (z - b[5]) / n
            b[0], b[1], b[2] = n, max(b[1], h), max(b[2], fuel)
    return blocks


def flame_size(cells, heat, fuel):
    """``(width, height)`` of the flame over a block with *cells* burning."""
    grow = min(2.2, 0.8 + 0.25 * math.sqrt(cells)) * (0.6 + 0.4 * fuel)
    k = 0.4 + 0.6 * max(0.15, heat)
    return FLAME_W * grow * k, FLAME_H * grow * k


class FlameSpawner:
    def __init__(self, session, clock=None):
        self.session = session
        #: block key -> the flame standing on it.
        self.flames = {}
        self._since_flush = FLUSH_EVERY
        self._since_place = PLACE_EVERY

    # -- each update ---------------------------------------------------------
    def update(self, fire, centre, delta) -> None:
        """Keep the flames on the blocks of *fire* burning nearest *centre*
        (the player's x, z): resize and move those that stay; spawn and
        remove, together, at most every :data:`FLUSH_EVERY` seconds."""
        self._since_flush += float(delta)
        self._since_place += float(delta)
        if self._since_place < PLACE_EVERY:
            return
        self._since_place = 0.0
        blocks = _blocks(fire) if fire.burning and centre is not None else {}
        r2 = SHOW_RADIUS * SHOW_RADIUS
        near = sorted((k for k, b in blocks.items()
                       if (b[3] - centre[0]) ** 2 + (b[5] - centre[1]) ** 2 <= r2),
                      key=lambda k: (blocks[k][3] - centre[0]) ** 2
                      + (blocks[k][5] - centre[1]) ** 2)[:MAX_FLAMES]
        wanted = set(near)
        for key, flame in self.flames.items():
            if key in blocks:
                self._place(flame, blocks[key])
        if self._since_flush < FLUSH_EVERY:
            return
        gone = [k for k in self.flames if k not in wanted]
        due = [k for k in near if k not in self.flames]
        if not gone and not due:
            return
        self._since_flush = 0.0
        self._flush(gone, {k: blocks[k] for k in due})

    def clear(self) -> None:
        """Take every flame away (the fire is out, or a new world)."""
        if self.flames:
            self._flush(list(self.flames), {})

    # -- internals -----------------------------------------------------------
    def _flush(self, gone, due) -> None:
        logic = getattr(self.session, "logic", None)
        things = fio.things(logic) if logic is not None else None
        if things is None:
            self.flames.clear()
            return
        dead = {id(self.flames.pop(k)) for k in gone if k in self.flames}
        if dead:
            things[:] = [t for t in things if id(t) not in dead]
        made = []
        if due:
            try:
                from engine.effect_entity import Effect
            except Exception:
                Effect = None
            texture = fire_look.texture()
            for key, block in due.items():
                if Effect is None:
                    break
                w, h = flame_size(block[0], block[1], block[2])
                props = {"type": "effect", "name": "Grass fire", "effect_type": "FIRE",
                         "fire_texture": texture, "preview": False, "silent": True,
                         "intensity": 1.0, "colour": [255, 110, 25], "grass_fire": True,
                         "width": w, "height": h, **LIGHT,
                         "light_intensity": LIGHT["light_intensity"] * max(0.15, block[1]),
                         "effect_seed": random.getrandbits(31) or 1}
                flame = Effect(pos=[block[3], block[4] + h * 0.42, block[5]], properties=props)
                flame._effect_animation_phase = random.random()
                things.append(flame)
                self.flames[key] = flame
                made.append(flame)
        try:
            fio.rebuild_entity_caches(logic)        # one re-index for the lot
            store = getattr(getattr(logic, "session_runtime", None), "effect_store", None)
            if store is not None:
                for flame in made:
                    store.sync_authored(flame)
        except Exception:
            pass

    @staticmethod
    def _place(flame, block) -> None:
        w, h = flame_size(block[0], block[1], block[2])
        p = flame.properties
        p["width"], p["height"] = w, h
        p["light_intensity"] = LIGHT["light_intensity"] * max(0.15, block[1])
        flame.pos = [block[3], block[4] + h * 0.42, block[5]]
        try:
            from engine.change_journal import touch
            touch(flame)
        except Exception:
            pass
