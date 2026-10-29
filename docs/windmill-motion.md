# Windmill blade motion

A game-ready windmill: tapered brick tower, gray metal bonnet, red timber
lattice sails, timber door and small windows. The placed world mill has
rotating sails controlled by its production state.

## Production and sail motion

The placed mill in `maps/miniwind_world.json` uses two ordinary Props:
`windmill_body.glb` at ground center and `windmill_rotor.glb` at the hub.
The rotor's `mill_rotor_for` property references the tower's
stable entity id. Ready-to-use paired records are in `windmill_props.json`.

The tower owns an ordinary item inventory. **The blades turn while that
inventory contains wheat.** The placed mill starts empty and stationary.
Receiving the first wheat starts the rotor; removing the last wheat stops it.
Other items do not power the mill.

- Starting takes **3 seconds** to reach **45 degrees/second** (7.5 rpm).
- Stopping coasts to a complete halt over **3 seconds** from full speed.
- Interrupting either transition continues from the current speed and angle.
- A stopped rotor keeps its angle; restarting never resets its pose.
- World pause freezes the motion. Durations use real seconds, independently
  of the game calendar's time scale.

## Discovery and inventory

Approaching the placed mill announces **Windmill discovered**, records
`visited.windmill`, and adds Windmill to the world map. Discovery is remembered
across map visits.

Press the normal interaction key beside the mill to open **Windmill** and
store or take items using the existing container screen. The editor's
**Contents** tab also edits its stock. Inventory travels with ordinary saves
and is remembered when leaving and returning to the map.

The placed mill belongs to **Bram the Farmer and the villagers**. Taking its
wheat is theft: the goods are marked stolen and witnesses can report it to
the watch. The inventory screen labels taking stock as **Steal all**.
Depositing wheat is allowed. The owner can be edited through the
normal **Ownership & Production** tab.

The old manual production flag is replaced by the inventory rule. Wheat stays
in stock until taken or used by future milling recipes.

## Farmer deliveries

Working farmers gather wheat with their scythes as before. At **five wheat**
they put the tool away, walk to the nearest available mill's door and deposit
all the wheat they carry. They also deliver a smaller final harvest when their
reaping period ends. Milk, tools and other belongings stay with the farmer.

Delivery uses the normal NPC movement and navigation. Stock moves only after
the farmer reaches the door; then the farmer resumes reaping or tending.
The **Delivering wheat to the mill** state and short thoughts identify the
errand. Threats, personal needs and the working day still take precedence;
an interrupted farmer keeps the wheat for a later delivery. With no usable
mill, farmers keep harvesting and retain their wheat.

Batch size and drop-off distance are constants in `game/farm_work.py`; speed
and transition durations are constants in `game/windmills.py`.

## Model placement

The rotor's local origin is its axle, with pivot **[0, 550, 170]** in tower
coordinates and rotation about **+Z**. Its placement follows the tower's
position and rotation; use a uniform scale for the assembly. Stopping Play
restores the rotor's authored transform. The complete `windmill.glb`,
`windmill.obj` and the rendered PNG sprites are also supplied as static assets.

Rebuild the full and split models from the same Blender source with:

```sh
blender -b -t 4 -P game/tools/make_windmill.py -- --export-only
```
