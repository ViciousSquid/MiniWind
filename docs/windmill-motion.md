# Windmill blade motion

A game-ready windmill: tapered brick tower, gray metal bonnet, red timber
lattice sails, timber door and small windows. The placed world mill has
rotating sails controlled by its production state.

## Production and sail motion

The placed mill in `maps/miniwind_world.json` uses two ordinary Props:
`windmill_body.glb` at ground center and `windmill_rotor.glb` at the hub.
The rotor's `mill_rotor_for` property references the tower's
stable entity id. Ready-to-use paired records are in `windmill_props.json`.

The tower's **Mill producing** (`mill_producing`) flag controls motion during
Play. It currently defaults to `true`, so the placed mill runs immediately.
This is a preliminary control for future production logic; it creates no
items and makes no decisions about workers, ingredients or output capacity.

- Starting takes **3 seconds** to reach **45 degrees/second** (7.5 rpm).
- Stopping coasts to a complete halt over **3 seconds** from full speed.
- Interrupting either transition continues from the current speed and angle.
- A stopped rotor keeps its angle; restarting never resets its pose.
- World pause freezes the motion. Durations use real seconds, independently
  of the game calendar's time scale.

Future production code can call this when the mill starts or stops working:

```python
from game.windmills import set_producing

set_producing(mill, True)    # work starts
set_producing(mill, False)   # work stops; sails coast to rest
```

Map logic can send the tower the **SetMillProducing** input with `true` or
`false`. Changing the production flag in the editor during Play also works.
The speed and transition durations are constants in `game/windmills.py`.

The rotor's local origin is its axle, with pivot **[0, 550, 170]** in tower
coordinates and rotation about **+Z**. Its placement follows the tower's
position and rotation; use a uniform scale for the assembly. Stopping Play
restores the rotor's authored transform. The complete `windmill.glb`,
`windmill.obj` and the rendered PNG sprites are also supplied as static assets.

Rebuild the full and split models from the same Blender source with:

```sh
blender -b -t 4 -P game/tools/make_windmill.py -- --export-only
```
