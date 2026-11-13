"""
MiniWind's meadow: the odd tuft of grass all over the land.

The terrain grows three kinds of vegetation: wheat fields and tundra heath
where the biome map paints them, and meadow grass over ordinary ground
(:attr:`engine.terrain.Terrain.meadow_grass`). MiniWind keeps the meadow
sparse -- scattered tufts, thinned further by the terrain's own clearings and
kept off steep ground, the high rock and snow, and painted paths -- so the
land is dotted with grass, not a lawn.

Seen from MiniWind's overhead camera (some 800 units up, past the grass's
detail distance) a meadow blade at the map's own size and the colour of its
ground is a dark speck: only its shaded root shows. So the tufts are fuller,
taller and a fresh green of their own, and read as grass.

The player's grass setting (``[Renderer] grass_quality``: high, medium, low,
off) thins the meadow and the heath with it; at Off there is no grass at all.
Wheat is a crop, not grass: its fields always grow in full, since the farms'
produce and the seasons depend on them.
"""

from __future__ import annotations

#: Meadow tufts per square world unit (a chunk is 256 units square): a few
#: hundred tufts to a chunk before the clearings -- occasional, against the
#: heath's tens of thousands.
MEADOW_DENSITY = 0.004
#: Blades to a tuft, and how far they spread (world units).
BLADES_PER_TUFT = 10
TUFT_RADIUS = 5.0
#: Blade size, times the map's blade height.
BLADE_SCALE = 3.5
#: The tufts' own green.
COLOUR = (0.62, 0.85, 0.34)


def apply(terrain) -> bool:
    """Grow MiniWind's meadow on *terrain* (at the start of Play). Regrows
    its grass only when that changes anything; returns whether it did."""
    if terrain is None:
        return False
    wanted = {
        "meadow_grass": True,
        "meadow_density": MEADOW_DENSITY,
        "meadow_blade_scale": BLADE_SCALE,
        "meadow_colour": COLOUR,
        "GRASS_BLADES_PER_TUFT": BLADES_PER_TUFT,
        "GRASS_TUFT_RADIUS": TUFT_RADIUS,
    }
    if all(getattr(terrain, name, None) == value for name, value in wanted.items()):
        return False
    for name, value in wanted.items():
        setattr(terrain, name, value)
    table = getattr(terrain, "table", None)
    if table is not None:
        table.mark_grass_dirty()
    return True
