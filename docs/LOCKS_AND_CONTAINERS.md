# Locks & Containers

*MiniWind player and editor guide · one-page tutorial*

## Open, inspect, take

Stand beside a container and press **E**. An unlocked container shows its
contents. **Looking is free**: opening a container, picking its lock, or
inspecting its contents does not create a theft charge. **Taking somebody
else's contents is theft**, including coin and the **Take all** action.

Containers use the world's existing **Owner** and faction ownership rules.
Your own belongings are free to take. **Owner = None** explicitly makes a
container free for all, even if an owner faction was previously assigned.
Taking from it creates no theft, stolen-goods mark, or bounty. A lock and
ownership are separate: an unowned chest can still need unlocking.

Taking owned goods uses the same witnesses, conversations and watch reports
as other crimes. A witness must get the news to a guard before a named bounty
is imposed. See [Crime & the Settlement Watch](CRIME_AND_THE_WATCH.md).

## Feel the tumblers

A locked container uses its matching key if you carry one; the key is kept.
Otherwise you need a **lockpick** and a lock that allows picking. Interacting
opens a cutaway lock with **one to five spring-loaded tumblers**.

1. **Move the mouse sideways** to put the pick below a tumbler.
2. **Sweep upward** to lift it. Move down and sweep up again for another lift.
3. Feel for the pause at the top: the tumbler **stops, glows gold, and makes a
   metallic contact click**. **Left-click during that pause** to set it.
4. A set tumbler stays raised with a **green check** and a setting sound.
   Set every tumbler to unlock the container and view its contents.

Some lifts give a longer pause. Watch and listen before committing. If a
tumbler drops, you can lift it again without spending a pick. **A mistimed
setting click breaks one pick**: its tip visibly snaps off, turns and falls,
the handle jolts, a snap sounds, and a red message names the failure. The
pick may snap at its tip, split along its shaft, buckle, or fracture into two
falling pieces. Break points and flight paths vary; consecutive breaks use
different styles. The lockpick count updates immediately. The last broken pick remains visible
until you leave; there is no invisible retry or automatic success roll.

Higher **Security** widens the setting window and protects more already-set
tumblers after a break. Harder locks have more tumblers and shorter pauses.
Only successfully opening a lock trains Security. Successful attempts keep
the pick; leaving with **Esc**, **E**, or **Leave** costs nothing. Unlocked
state survives saving and loading; unfinished tumbler progress does not.
The **Lift tumbler** and **Set tumbler** buttons also work; keyboard fallback
is **Left/Right**, **Up**, and **Space/Enter**.

## Author a container in the editor

Select a **Container**. In its **LOCK** group, set:

| Field | Effect |
| --- | --- |
| **Locked** | Start closed behind a lock. Off by default. |
| **Lock difficulty** | **1–100**, from Simple to Masterwork; default **25**. |
| **Key item ID** | Optional inventory item ID that opens this lock. |
| **Can be lockpicked** | On by default. Turn off for a key-only lock. |

In **OWNERSHIP**, put the NPC's identity in the existing **Owner** field, or
enter **None** for free-for-all contents. An empty Owner with an Owner faction
still uses existing shared faction ownership. Fill the **Contents** tab as
usual. Keys must be present in the player's inventory and lockpicks use the
existing **`lockpick`** item. A key-only lock with no key ID cannot be opened.

Example: a merchant's ironbound chest can have **Owner = wick**, **Locked =
true**, and **Lock difficulty = 60**. A communal ruin cache can have **Owner =
None** and the same lock: the mechanical challenge remains, and taking its
contents is lawful.
