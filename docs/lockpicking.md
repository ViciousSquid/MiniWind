# Lockpicking

Use **E** on a locked container while carrying a lockpick. Lift the highlighted
pin until its gap meets the shear line, apply tension, and follow the binding
point as the mechanism turns. Each pin latches separately. A mistake stops the
turn; it does not reset completed pins or partial progress.

The world continues running. Patrols, monsters, physics and the clock keep
moving. Picking someone else's container is a crime when an awake NPC sees
you: distance, darkness, stealth and solid walls affect detection. A witness
interrupts picking and uses the existing reporting, bounty and reaction system.
Damage or moving out of reach also interrupts. The ordinary pause menu still
pauses both the world and the attempt.

## Controls

| Action | Mouse / keyboard |
| --- | --- |
| Lift or lower the active pin | Hold left button over the mechanism and drag vertically; or arrow keys / WASD |
| Apply / release tension | Hold right button; or toggle with Space / Enter / the button |
| Fine movement | Hold Shift while dragging or using arrow keys |
| Show guide and widen the sweet spot | H or Guide button; optional, no reward penalty |
| Leave | Esc, E, Tab, Leave, or window close |

Mouse positions are Qt logical window coordinates, normalized by the displayed
mechanism size. Windows/macOS, Retina displays and scaled windows use the same
path. A trackpad or one-button mouse uses primary drag plus Space. The tool
resists movement and visibly bends/vibrates while binding; snaps recoil and
split the pick. This is visual motor feedback, not hardware force feedback.
The OS cursor is never warped or given artificial acceleration.

## Difficulty and consequences

| Lock | Pins | Base tolerance | Binding-point travel | Seconds per pin |
| --- | ---: | ---: | ---: | ---: |
| Novice | 3 | 14° | 4° | 0.85 |
| Apprentice | 3 | 11° | 8° | 1.0 |
| Adept | 4 | 8° | 14° | 1.2 |
| Expert | 4 | 5° | 22° | 1.4 |
| Master | 5 | 3.5° | 30° | 1.6 |

Security widens tolerance, reduces travel and slows strain accumulation. There
is no hard skill gate or random success check: a low-skill character can open
a master lock by tracking it precisely. Hard locks require following the
moving binding point; leaving the pick still will bind before the pin sets.

Forcing a binding pin for 0.65 seconds starts accumulating visible strain.
The red overload warning starts at 65%; reaching 100% snaps exactly one pick.
Releasing tension lets strain recover. A stalled frame counts for at most
100ms, so a hitch cannot instantly destroy picks. Success does not consume a
pick. Security practice is awarded once, on opening the lock.

At **Security below 15**, each snap can shear a tip off in the lock. The chance
is `25% × (15 − Security) / 15` (about 17% at Security 5), displayed before
tension is applied. A sheared tip jams the container: keys, further picks,
leaving the map, saving and reloading cannot bypass it.

**Knock** is the sole jam exception. This Defensive touch spell costs 45 base
magicka and uses normal spell knowledge, skill, magicka, fizzle and practice
rules. A successful cast opens the nearest locked/jammed container within its
use radius (capped at interaction reach), clears the obstruction and leaves
its contents/ownership intact. An unsuccessful cast leaves it sealed. An
ordinary matching key opens an unjammed lock without consuming the key.

## Content and authoring

Containers expose **Locked**, **Difficulty** and **Key item id** in the editor.
Existing containers default to unlocked. `lock_jammed` and `lockpick_state` are
runtime properties; save files and map memory preserve them by container id.

The existing cave maps include three examples: the novice Wolfmaw lockbox in
`cave01`, an expert strongbox in `cave04`, and a master strongbox in `cave12`.
The Patient Locksmith, a green spellbook near the entrance of `cave01`, teaches
Knock through the ordinary spellbook pickup path. Existing class restrictions
on magic still apply.

The engraved plate is `assets/ui/lockpicking/escutcheon.png`. Pins, springs,
shear line, pick, tension feedback, recoil and broken-pick segments are drawn
as scalable vectors over it. `assets/sprites/spells/knock.png` is the 100×100
placeholder spell icon.
