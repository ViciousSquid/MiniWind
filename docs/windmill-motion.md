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

The old manual production flag is replaced by the inventory rule. The mill
converts **10 wheat into 1 `flour`** every **15 game minutes** while a complete
batch is available. `mill_batch_hours` edits the interval; saved `mill_progress`
keeps partially completed work. Wheat left below ten waits for the next
delivery and still keeps the sails turning. Flour and collected payments stay
in the same owned inventory, so taking them is theft too.

## Shops, journeys and food

Elowen, Maud, Hollin, Wynn and Nell stock flour. Their `flour_target` is eight;
zero leaves specialist shops outside the flour trade. The sale row reflects
the shopkeeper's real inventory, shared by player purchases and NPC meals.
Ordinary overnight shelf restocking **never creates flour**.

From **05:00**, shopkeepers plan a collection that allows travel, queue service
and a return buffer before **09:30**. At the mill, arrivals join a physical
FIFO queue with spaced waiting positions. Only its head is served, taking
**two game minutes** per customer. An empty mill makes the head wait for real
production until it is time to return. A disrupted customer loses its place
and rejoins at the back if it resumes.

A long round trip is delegated to an available `flour_runner` resident. Four
ordinary, mortal runners live beside the distant shops. They keep their needs
and reactions to danger, and are not replaced automatically. If no runner can
make the journey, a shopkeeper can buy finite surplus from a closer town's
shop, leaving half that supplier's shelf target for local customers. That
stock carries a **10% import markup**, applied only to flour; mixed deliveries
average the markup. Stock and payment change only on collection. A runner's
cargo reaches the shop only on the return journey.

09:30 is the intended opening time. Each day has a **30% chance of a 2–15
minute opening delay**, sampled once and saved. Physical delays can make a
keeper later still; no schedule teleports anyone home or forces a transaction.
The shop opens once the keeper is present, ready and free to serve. Its food
counter closes when the authored working period ends.

Residents near these shops, including the shopkeepers and guards, depend on
flour. A hungry resident walks to its local shopkeeper, buys one flour with
ordinary coin, and consumes it directly for now. One flour relieves 0.6 hunger.
A household starts with 30 personal coin unless authored otherwise; this is a
finite purse, and there is no new automatic wage system. Closed shops, empty
shelves or insufficient coin leave hunger unresolved. Being idle or returning
home no longer grants a free meal in these settlements. Existing maps without
food shops keep their previous needs behavior.

These are work goals below combat, flight, witness reports, personal intentions,
companionship and urgent rest. The mental-state inspector exposes food and
supply reasons. A robbery, death or delayed runner can leave a shop empty;
residents remain hungry, interrupt work for food, and retain that hunger across
saves and map visits. Player trading or recovering stolen cargo can help restore
supply. No extra scripted punishment or guaranteed rescue is attached.

Outside the active area, the **existing living-world journey board** carries
the same people and finite cargo along its roads. Near the player, its ordinary
actors walk, queue, flee and fight. Dematerialising a party preserves its actual
position, wounds, purse and remaining flour. Off-screen robberies transfer the
flour to the robbers; slain couriers leave their cargo in lootable road remains.
Local meals for parked residents use the existing style of coarse settlement
resolution against the same stocks and purses. Cells are never forced to stay
loaded for a delivery.

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
