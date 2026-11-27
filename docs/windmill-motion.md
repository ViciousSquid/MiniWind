# Windmill blade motion

A low-poly game-ready windmill: tapered 12-sided brick tower, gray metal
bonnet, and a small attached brick mill house with a pitched terracotta tile
roof, chimney, porch and timber entrance. Four pale timber lattice sails remain
separate geometry and rotate whenever the mill itself is operational.

## Production and sail motion

The placed mill in `maps/miniwind_world.json` uses two ordinary Props:
`windmill_body.obj` at ground center and `windmill_rotor.obj` at the hub.
The rotor's `mill_rotor_for` property references the tower's
stable entity id. Ready-to-use paired records are in `windmill_props.json`.

The tower owns an ordinary item inventory. **The sails turn whenever the mill
is operational, even when its inventory is empty.** The placed mill starts
empty but its rotor spins from the start of play. Wheat controls flour
production, not blade motion: delivering wheat enables flour production;
removing the last wheat stops production but does not stop the sails. Other
items do not produce flour.

- Starting takes **3 seconds** to reach **45 degrees/second** (7.5 rpm).
- A mill that is disabled, destroyed or held by a living holder coasts to a
  complete halt over **3 seconds** from full speed.
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
delivery; the sails continue turning independently of stock. Flour and collected payments stay
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

The placed tower and rotor Props both use `no_collision: true`: they are
rendered scenery, not navigation obstacles. The windmill discovery marker can
therefore remain at the tower centre without placing an NPC goal inside a
solid model footprint.

The original overhead-style mill keeps its historical rotor anchor
**[0, 550, 170]** and ground-plane XZ sail disk, rotating about local **+Y**.
Existing maps and saves therefore retain their established silhouette.

The Chesterton landmark uses a dedicated `chesterton_windmill_rotor.obj`:
its four sails lie in a vertical XY plane facing the body's **+Z** front, with
a forged axle extending back along **-Z** into the stone tower. Its hub is
anchored at body-local **[0, 700, 130]** and it rotates about local **+Z**.
`mill_rotor_axis` and `mill_rotor_anchor` are per-instance properties, so
the two windmills can share the same motion system without sharing the same
orientation. Both body and rotor are separate Wavefront OBJ models with
companion MTL files; the brick body MTL references
`windmill_brick_albedo.png`.

The combined `windmill.obj` and PNG sprites remain static previews. The live
world uses `windmill_body.obj` and `windmill_rotor.obj` so only the sails rotate.

Rebuild the OBJ/MTL models and metadata from the Blender source:

```sh
blender -b -t 4 -P game/tools/make_windmill.py -- --export-only
python tools/pack_assets.py models
```

## Chesterton Windmill landmark

The main world gains a second Chesterton-inspired stone landmark through
`maps/miniwind_chesterton_additions.json`. It has a round upper drum above
four open masonry arches, a circular grass-capped plinth and a dark slate cap.
Its four pale lattice sails use a vertical, side-mounted rotor with an
axle that meets the tower face, and run through the normal per-instance motion
system. The separate **Chesterton Windmill**
discovery marker sits at the base. The body and sails are non-solid; the
landmark does not obstruct NPC navigation. The sidecar is merged after the
main world loads so the large embedded terrain payload remains untouched.
