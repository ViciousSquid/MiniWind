# MiniWind — The Rules

The definitive description of how MiniWind plays: every rule here is what the
game actually does, with its numbers. Where a number lives in code, the file
is named so it can be found and tuned. If the game and this document ever
disagree, that is a bug in one of them — fix whichever is wrong.

---

## 1. Dice

Every chance in MiniWind is rolled on dice, and every roll is shown honestly.

* **The d20 check.** A chance *p* becomes "need N or higher" on a d20:
  `threshold = round(p × 20)`, held between 1 and 19; `N = 21 − threshold`.
  So chances move in 5% steps, and anything that is possible at all is
  between 5% and 95% (`game/diceroll.py`).
* **Randomness.** Every die — yours, every NPC's and every animal's — draws
  from the operating system's cryptographic random source
  (`random.SystemRandom`), which the OS feeds from hardware randomness.
  Nothing can predict or replay a roll (`game/dice_rng.py`).
  *For developers:* setting `dice_seed` under `[GAME]` in `settings.ini` makes
  the dice repeat exactly, roll for roll, to reproduce a bug. Empty (the
  default) is truly random.
* **Roll boxes.** A roll shows in a small box: the roller's name in their side's colour (gold you, green an ally,
  red a foe), what the roll is for, the real dice tumbling, the verdict, and —
  for a hit — the damage. Your own rolls sit on a black box; everyone else's
  (allies, foes, fights between NPCs) on a blue-slate one. In co-op each
  player's rolls are in **their own colour** -- the border of their party
  card: the box's border, their name and the line to them. The verdict sits
  right under the dice (a line is left only for a die's role label).
  Your own roll sits over you, even beside someone else's. Everyone else's line up in one column down
  the right edge of the screen, under the weapon panel and above the
  shortcut bar, all one narrow width (the roller's name on one line, what
  they roll for on the next), attacks first, so the fight itself stays in
  view; a thin, half-transparent line in the roller's colour joins each box
  to its roller; when more are rolling than the column holds, the ones that don't
  fit aren't shown. (With the column turned off, each box sits over its
  roller: boxes that overlap more than their margins lock into one stack,
  the attacker's roll on top — Settings › Game › *Stack dialogs* — and a
  stack that would cover another moves to the nearest clear place, so no
  box ever hides another's words.) A character
  with a roll box over its head says nothing (speech bubbles, barks and
  thoughts wait).
* **Who rolls where it can be seen.** Only actors in the NEAR simulation tier
  roll dice on screen; anyone further out (ACTIVE, DISTANT, DORMANT), and
  anyone Big World has parked, never does.
* **Dice colours.** Your dice are always in colour, everyone else's never.
  * *Yours:* each die a random finish, any die any finish — white with navy
    numbers, white with orange numbers, ivory with dark numbers, blue with
    pale-orange numbers, pale orange with blue numbers, ember with ice-blue
    numbers, or red with gold numbers.
  * *Everyone else's:* always greyscale, each die a random finish — black with
    white numbers, charcoal, slate, light grey, or white with black numbers.
  * The dice of one roll are never the same colour.
* **Co-op.** "You" is whoever plays on your machine (the local client). Your
  rolls are in colour under YOU; every other client's player is a party
  member, and their rolls show on your screen too — under their name in
  green, with greyscale dice. An NPC's roll against a party member names
  them, not "you".
* **One roll for everyone.** In co-op the host rolls every die. Every client
  shows that same roll: the same numbers, the same tumble and the same dice
  colours, all built from the roll's own seed. Rolls travel inside the world
  update the host already sends (no extra messages), carrying only the
  result, the seed and the clock; each client builds the dice once and only
  keeps the clock in step after that.
* **Honesty.** A box only ever shows what was rolled and what was used: the
  die's real face, the real target number, and the damage actually dealt —
  the same number that floats over the target.
* **Anticipation.** No result is told before its die lands (plus a 0.08 s
  beat): HIT / MISS / Crit! when the to-hit die lands; the damage number, the
  blood, the screen shake and the target's health bar when the damage die
  lands. The rules themselves happen at the blow — only what you see waits.
* **Never waiting on dice.** Attacking again before your last roll has landed
  (mashing the attack button or clicking fast) tells that roll's results at
  once — its HIT / MISS / Crit!, damage, blood, shake and health bar — and
  the new roll replaces it straight away. Dice never slow your attacks; only
  your weapon does.
* **Timing.** A die tumbles 0.45–0.68 s; the damage die is thrown 0.10 s
  after the to-hit die; each roll runs ±10% faster or slower than the last.
  The result and damage are always shown within **1.0 s** of the blow. About
  one roll in four keeps rattling after it lands (the rolled face staying
  up), but no roll lasts longer than **1.2 s** (`game/ui/dice3d.py`).

---

## 2. Attributes

Six attributes, base **40**, range 0–100 (`game/rpg/attributes.py`):

| Attribute | What it does |
|---|---|
| **Strength** | melee damage (×(0.7 + STR/100)); melee attack bonus; carry weight (STR × 5); a creature's blows (×(0.7 + STR × 0.006)) |
| **Endurance** | health (END × 2); stamina; Armour Class (lightly armoured); magicka regeneration; casting; magic resistance |
| **Intelligence** | magicka (INT × 1.5) |
| **Speed** | your pace (§5); governs Light Armor, Athletics and Acrobatics |
| **Personality** (shown as *Charisma*) | prices, disposition, how strangers react to your face |
| **Luck** | critical hits; attack bonus (both ways); saving throws at the extremes (the fate die); loot; skill learning; casting |

Everyone in the world has Strength, Endurance, Charisma and **Luck** — every
NPC and every animal: rolled once on 3d6 around a baseline for their kind (a
bear is strong, a hen is not), at half the swing of the player's roll, and
kept for good (`game/rpg/charisma.py`). Luck's baseline is 40, except: beggar
and crab 25, skeletons 20, sheep 30, merchant 50, bandit chief 55, hen 55,
dragon 60. An authored value always wins.

---

## 3. Making a character

Attributes are built in this order: base 40 → race → +10 to each of the
class's two favoured attributes → birthsign → your dice. You roll **3d6** each
for Strength, Endurance and Charisma; each roll moves the attribute by
`round((total − 10.5) × 4)` (−30 at 3, +30 at 18). Reroll as often as you
like (`game/rpg/character.py`).

**Tutorial (experimental).** With `[developer] enable_tutorial = true` in
settings.ini, the last step of making a character has a "Show tutorial"
checkbox (ticked; T toggles it). Begin then opens four short pages: moving,
your two hands (a mouse button or trigger each), quick slots, the inventory.
Every control named is the one in use: keyboard and mouse or gamepad,
whichever was used last, switching at once, by your own bindings. Enter / A
next, ← / D-pad ← back, Esc / B skip. Without the setting none of it appears.

### Classes

Thirteen classes; the character creator offers six (★). A class sets your
specialisation (+5 to every skill in it), two favoured attributes and seven
**major skills** (start at 25; minors at 5).

| Class | Spec. | Magic | Notes |
|---|---|---|---|
| Warrior ★ | Combat | **none** | every attack +10% damage |
| Knight | Combat | yes | |
| Barbarian | Combat | **none** | every attack +10% damage |
| Scout | Combat | yes | |
| Archer ★ | Combat | yes | |
| Mage ★ | Magic | yes | starts with Flare, Minor Healing |
| Sorcerer | Magic | yes | starts with Flare |
| Healer ★ | Magic | yes | starts with Minor Healing, Flare |
| Necromancer ★ | Magic | yes | starts with Flare, Resurrection |
| Thief ★ | Stealth | yes | |
| Assassin | Stealth | yes | |
| Rogue | Stealth | yes | |
| Bard | Stealth | yes | |

A class with no magic has no magicka, cannot learn or cast spells, is never
offered Magicka on levelling, and gets no spells from race or birthsign.

**Starting gear**, by specialisation (the first weapon, armour and ammo are
equipped):

* **Combat:** Iron Longsword, Iron Shield, Leather Cuirass, Short Bow,
  20 Iron Arrows, 2 Minor Healing Potions.
* **Magic:** Iron Dagger, Apprentice's Staff, 2 Potions of Magicka,
  1 Minor Healing Potion.
* **Stealth:** Iron Shortsword, Hunting Bow, 15 Iron Arrows, Leather Cuirass,
  5 Lockpicks, 1 Minor Healing Potion.

**Starting spells** are your class's, your race's and your birthsign's. A
magic class that would start with none is given Flare. Whenever you are
given Flare, there is a **15%** chance it is Wisp instead (unless you already
know Wisp).

### Races (`game/rpg/races.py`)

| Race | Attributes | Skills | Resistances | Power / spells |
|---|---|---|---|---|
| Highlander | STR+10 END+15 INT−10 PER−5 | Blunt+10 Blade+5 Heavy+10 Block+5 | frost 50%, shock 25% | Woad |
| Valian | END+5 PER+10 | Blade/Blunt/Heavy +5, Speechcraft/Mercantile +10 | — | Silver Tongue |
| Wyrfolk | INT+10 END+5 STR−10 | Offensive/Defensive +10, Occult/Alchemy +5 | magic 50% | Dragon Skin; Minor Healing |
| Ashfolk | SPD+10 STR+5 PER−5 | Blade/Offensive +10; Light/Marksman/Occult/Athletics +5 | fire 75% | Ancestor's Wrath |
| Woodkin | SPD+10 STR−10 PER+5 | Marksman+15 Sneak+10; Light/Alchemy/Acrobatics +5 | disease, poison 75% | Beast Tongue |
| Highkin | INT+10 END+5 STR−5 SPD−5 | Offensive/Defensive +10, Alchemy+5 | disease 75%; fire/frost/shock −25% | Highborn; Flare, Minor Healing |
| Orc | STR+5 END+15 PER−10 INT−5 | Heavy+15 Blunt+10 Block/Blade +5 | magic 25% | Berserk |
| Sunborn | STR+5 END+10 INT−10 | Blade/Athletics +10; Blunt/Heavy/Light +5 | poison 75%, disease 50% | Adrenaline Rush |
| Tehani | SPD+5 PER+5 | Light Fingers+10; Sneak/Acrobatics/Security/Light/Blade +5 | — | Eye of Night |
| Marshborn | SPD+5 INT+5 STR−5 | Alchemy/Defensive/Sneak/Security/Blade/Speechcraft +5 | poison 100%, disease 75% | Histskin |

Racial powers are spells that cost nothing and never fizzle.

### Birthsigns (`game/rpg/birthsigns.py`)

Warrior (STR+10 END+5) · Mage (INT+10, +50 magicka) · Thief (END+10 SPD+5
LUCK+5) · Lady (END+10 PER+10) · Steed (SPD+15) · Lord (+25 health, Minor
Healing) · Apprentice (INT+5, +100 magicka) · Golem (+150 magicka; magicka
never regenerates) · Shadow (END+5, Minor Invisibility) · None. The creator
offers Warrior, Mage, Thief, Lord and Shadow.

---

## 4. Skills and levelling

**Skills** (`game/rpg/skills.py`): Combat — Blade, Blunt, Marksman, Block,
Heavy Armor, Light Armor, Athletics. Magic — Offensive, Defensive, Occult,
Alchemy. Stealth — Sneak, Security, Light Fingers, Mercantile, Speechcraft,
Acrobatics. Ranks: Novice 0, Apprentice 25, Journeyman 50, Expert 75,
Master 100.

**Skills rise with use.** Each use earns `difficulty × (1 + (LUCK − 40) ×
0.002)` skill XP; a point costs `1 + 0.05 L² + 0.5 L` at level *L*.

| Use | Difficulty |
|---|---|
| Weapon hit | 1 + target's health / 120 |
| Weapon **miss** | 0.25 — using a weapon is how you get better with it |
| Sneak attack | +1.5 Sneak |
| Block | 1.0 |
| Armour struck | heavy 1.0 · light 1.0 · medium 0.5 to each |
| Sprinting | Athletics 0.08 per second |
| Spell cast / fizzle | 1.5 + cost/30 · 1 + cost/60 |
| Staff | Offensive 1.0 |
| Lockpicking | 1 + 0.5 × pins |
| Trading | Mercantile 0.5 |
| Persuading | Speechcraft 1.0 |
| Skill book | 5.0 (first read only) |

**Levelling.** You may level when either track is full: **10 major-skill
increases**, or **XP ≥ 100 × level** (spent on levelling). XP comes from kills
(the creature's own value: wolf 8, boar 10, crab 4, bear 25, bandit 14,
bandit archer 16, bandit chief 45, cultist 18, skeleton 16, skeleton archer
18, wraith 40, monster 30; townsfolk and farm animals 0) and from quests.

The **level-up page** is the only way to level. A level-up raises your two
favoured attributes and the one you trained most this level by +1 to +5 each
(1 + half the skill rises it governed, rounded down; at most 5); you choose
one more for +5 (Strength, Endurance, Charisma, or — for magic users —
Magicka, which raises Intelligence); health rises by END × 0.1 for good; all
pools refill. No level grows a pool directly (a save from before the page
keeps any magicka or stamina its older level-ups gave).

**Spell levels** are bought with the same XP: `xp_per_level × current level`
(common 30, uncommon 45, rare 60, epic 80, legendary 120), up to level 5.
Each level adds +25% magnitude, +12.5% duration and +10% cost.

---

## 5. Health, magicka, stamina and burden

* **Max health** = END × 2 + level gains + birthsign.
* **Max magicka** = INT × 1.5 + birthsign (0 for a class with no magic).
* **Max stamina** = (STR + 3 × END) × 0.5 + Athletics gains + birthsign.
  Every point of Athletics you gain (by use or from a trainer) adds **+1**
  max stamina for good.
* **Regeneration per second:** magicka `max × 0.02 × (0.5 + END/100)` (none
  under the Golem); stamina `max × 0.15` (not while sprinting). Health does
  not regenerate — only spells, potions, food (bread and flour, 8 each) and
  levelling restore it. The quick-heal key (**H**) drinks the strongest
  healing potion carried, or, with none left, eats the cheapest food that
  heals (never while unhurt).
* **Sprinting** costs 12 stamina a second; at 0 you are **winded** and cannot
  sprint again until back to 30%. Winded fighters take −2 to hit.
* **Stamina costs:** a swing or an arrow 6; a shield bash its own cost.
* **Pace:** you move at `1 + (SPD − 40) × 0.0025` of the usual speed —
  ×0.90 at Speed 0, ×1.00 at 40, ×1.15 at 100, walking or sprinting.
* **Carry weight** = STR × 5. Over it you are encumbered: movement × 0.33
  (on top of your pace).

---

## 6. Armour Class

Every living thing has an **Armour Class** — the player, every NPC, every
monster and every animal (`game/rpg/armour_class.py`).

* **Yours** = 10 + one per 4 points of each worn piece's skill-scaled armour
  rating (never less than 1 a piece) + Endurance (one per 10 above 40: all of
  it in light armour, at most 2 in medium, none in heavy) + rings and amulets.
* **Anyone else's** = an authored `armour_class`, or 10 + the natural armour
  of its kind + its shield + Endurance (one per 10 above 40, at most 4) + one
  per 3 levels above the first. Natural armour: hen, sheep 0 · cow, deer,
  wolf 1 · boar 2 · bear 3 · crab 5 · skeleton 2 · skeleton archer 1 ·
  wraith, monster 3 · dragon 8 · guard 4 · guard archer 3 · bandit, bandit
  archer 1 · bandit chief 4 · blacksmith 1 · other townsfolk 0.

---

## 7. Combat

### To hit

**Every attack is a d20 + the attacker's bonus against the target's Armour
Class** — 5% to 95%. This decides your swings, shots, staff bolts and shield
bashes (a close, faced melee swing rolls too), every blow on you, and every
fight between NPCs and creatures.

* **Your attack bonus** = 3 + weapon skill ÷ 10 + Luck + Strength in melee
  (one per 15 above 40) − 2 if winded − 2 with two weapons.
* **Anyone else's** = an authored `attack_bonus`, or 6 + level + Strength (one
  per 15 above 40) + Luck. An unknown attacker (a trap) counts as +7.
* **Luck, both ways:** +1 for each full 20 above 40, −1 for each full 20 below
  it — Luck 0 is −2, 20 is −1, 21–59 nothing, 60 is +1, 100 is +3. The lucky
  land more blows; the unlucky fewer.

HIT or MISS floats over the attacker as its die lands.

### Critical hits

After a hit lands, the attacker rolls for a **critical** — everyone the same
way: **5% + Luck × 0.15%** (11% at Luck 40), for **×1.5 damage**. "Crit!"
floats in large white over whoever lands one.

### Damage

1. **The weapon's damage die.** A weapon's damage is one die plus a flat
   amount that averages its listed damage (× its rarity): the largest of
   d4–d12 whose average fits (a d4 at least), or the item's own `damage_die`.
   Unarmed is 2.
2. × skill: `0.4 + skill/110`.
3. Melee × `(0.7 + STR/100)` × a charged blow's power. Ranged: the bow's draw
   (×0.5 at no draw to ×1 at full) plus the arrow's damage. Staff ×
   `(0.7 + Offensive/100)`.
4. × class: Warrior and Barbarian ×1.10.
5. Sneak attack: melee ×3, ranged ×2, any dagger ×6 (while sneaking).
6. Critical ×1.5.
7. The target's raised shield may save (below), then any ward soaks.

### Blows on you

In order: the attacker rolls to hit your AC (a miss does nothing) → its
critical roll → your block, if raised → your armour (`rating / (rating +
100)` of the rest) → a Shield effect soaks `min(damage, magnitude × 0.5)` →
resistance (race + effects, plus END × 0.2% against magic, between −100% and
+100%). A creature's blow is scaled by its Strength first.

A blow that would kill you (with more than 1 health) may be escaped once per
game day: a d20 at `(fortune − 40)%`, at most 60%, where fortune is the
average of Charisma and Luck. Escaping leaves you on 1 health less than you
had.

### Blocking

A raised shield (or guard) makes a **saving throw** on a d20 — your Block
skill, Endurance and stamina, and **+2.5% per point of Armour Class above
10**: `(0.2 + Block × 0.006 + END × 0.0015) × (0.5 + stamina × 0.5) + AC
bonus`, held between 5% and 90%. A save blocks `0.2 + Block/200` of the blow
(0.05 + Block/200 without a shield), at most 75%. NPCs with a raised shield
save the same way.

### Luck and saving throws: the fate die

At the extremes, Luck reaches into saving throws. Whoever qualifies rolls a
second d20 — the **fate die** — right after the save. It tumbles beside the
save's die in the roll box (marked SAVE and LUCK) (`game/rpg/luck.py`).
Nobody else ever rolls one.

| | Who | When | Chance | What happens |
|---|---|---|---|---|
| **Lucky** | Luck 60+, level 10+ | the save **failed** | 5% + 0.4% per Luck above 60 + 0.4% per level above 10, at most 25% | the whole blow is turned aside — no damage at all |
| **Unlucky** | Luck 25 or less, any level | the save **succeeded** | 5% + 0.8% per Luck below 25, at most 25% | the save comes undone — the whole blow lands |

The player is always told what happened. Once the fate die lands:
* **LUCK!** (gold) or **UNLUCKY!** (sickly green) floats big over the
  character, like "Crit!", and hushes their speech.
* The roll box's verdict turns to LUCK! or UNLUCKY!, with the fate die's roll
  and a line saying what happened. For example, *"The blow caught on a belt
  buckle."*, *"The attacker slipped on something unspeakable."*, *"Tripped
  over a hen."* or *"Distracted by a butterfly."*
* The same line appears as a toast and in the log.

When the fate die fails, the save stands, and the box still shows the die
("fate lets it be").

### Kills, gore and the dead

* A killing blow of 120% or more of the victim's health — and **every
  critical killing blow** — blows the body apart: mostly blood (a heavy
  spray, dark chunks, pools), and a few jagged pieces of the body's own
  picture that tumble out, land and lie a few seconds. A critical kill adds extra gore and the
  hardest screen shake.
* How much there is of it follows the **size of the body**, never its
  health (a veteran guard is tougher than a farmer, not bigger). Each kind
  has a size in the bestiary — tiny (a hen), small (a crab, a sheep),
  medium (people, wolves, boars), large (a bear, a cow, a Fiend), huge — and
  a map can give one actor its own (`body_size`). Pieces that fly off: a
  hen 2, a small body 3, a person 4, a bear 6, anything huge 8. Every wound
  and pool of blood is smaller from a smaller body too.
* A body blown apart can never be resurrected, and Death (the reaper, who
  otherwise attends one death in eight) never comes for it.
* **Crabs feed on the dead.** A body blown apart within 650 units of water
  you can see brings crabs out of it -- two for a hen, six for a person, twelve
  for a bear, twenty for anything huge. More bodies blown apart by a feast
  still going join it, up to thirty-two crabs: a nuisance usually, a real
  danger when something huge -- or many -- die by the water together. The
  pieces wait for them instead of fading; the crabs scuttle up (sideways),
  crowd them two to a piece and eat them bite by bite -- chunks gone out of
  each piece, never shrunk -- until nothing is left, then scuttle off out of
  sight and are gone. A save never keeps them.
* **A feeding frenzy bites.** While they feed, crabs attack anything near the
  remains -- you, people, any animal but a crab: whatever comes within 150
  of a crab is swarmed, and never chased more than 150 from where the chase
  began. Each crab nips once a second, at
  its own random moment in it, for 2 damage (armour applies) -- nothing
  alone, a real danger from six; a bitten villager or wolf fights back.
  Crabs leaving the feast no longer bite.

### Screen shake

Your critical hits, killing blows and overkills shake the screen, as does a
critical against you or a heavy blow taken. The shake is a choppy rattle —
about 28 jumps a second, dying away — not a smooth wobble, and only the world
shakes, never the HUD (`game/runtime.py`, `game/host.py`).

| Event | Strength (share of camera height) | Seconds |
|---|---|---|
| Your critical hit | 0.024 | 0.40 |
| Your killing blow | 0.018 | 0.32 |
| Your overkill | 0.032 | 0.48 |
| Your critical killing blow | 0.044 | 0.60 |

---

## 8. Armour and magic

**Metal interferes with magic.** Anyone wearing a piece of metal armour —
iron, steel, chain, scale, plate or mithril, on the head, chest, hands, legs
or feet — cannot cast. The spell fails, no magicka is spent, and "The metal
interferes..." is shown. This stops the cast key, both hands, Resurrection,
Knock and channelling a staff. **Shields never count**: one hand may hold a
shield while the other casts. Leather (studded too), hide, fur, cloth, wood
and elven armour are fine. An item can override its material with `"metal":
true/false` (`game/rpg/equipment.py`).

While metal is worn, your spells are shown greyed out everywhere; they can be
highlighted but not selected or readied, and hovering one (or gamepad focus)
says *Metal armour prevents this*.

---

## 9. Magic

* **Cost** = `base cost × max(0.25, 1 − school skill/150)`; a staff costs half
  that. Magicka is spent before the cast roll, so a fizzle still costs it.
* **Chance to cast** = `0.42 + skill × 0.0065 + (END − 40) × 0.004 + (LUCK −
  40) × 0.002 − base cost × 0.008 + (up to 0.15 for practice)`, between 10%
  and 98%, rolled on a d20.
* **Alignment** strengthens spells: good characters' Defensive spells by up
  to +25%, wicked characters' Offensive and Occult spells by up to +25%.
* **Spell rarity** is authored, or from cost: 90+ legendary, 50+ epic, 30+
  rare, 18+ uncommon, else common.
* **Resurrection** (100 magicka, all of it) raises a fallen body as a
  follower, once a day; each body only once; never one blown apart.

### Ground cover

* Meadow grass grows on ordinary ground only: never in a wheat field (only
  wheat grows there), on sand or on snow, and it thins out under tundra heath.

### Fire

All fire is the engine's FIRE Effect in one look (`[GAME] fire_style` in
settings.ini, a developer option: the engine's fire01–fire04, fire02 by
default; `dragonfire N` changes it for the session). A Flare sets what it
strikes alight; a bolt that misses leaves a small fire on the ground for 8 s.

**Grass fire** (Settings › Game › *Grass fires*, and the pause menu's
Graphics; on by default):

* A fire on the ground, anyone burning who runs through grass, and a dragon's
  breath set long grass alight. The fire then spreads on its own, cell by cell
  (64 units): tall tundra heath and wheat burn hot, plain meadow barely; roads,
  paths and painted ground, swamp, sand and snow don't burn, and ground already
  burnt never burns again.
* It runs before the wind — about 40 units a second downwind in a fresh wind,
  barely creeping upwind. The wind's direction and strength wander slowly over
  the day (a storm's gale blows far harder, but its rain holds fire back).
* Each cell flares up, burns 3–8 s (longer the more fuel) and dies down.
  Anyone standing in fire that is burning fiercely catches fire (4 damage a
  second for 4 s, through the ordinary burning rules).
* Behind it the ground is scorched black and the grass is gone.
* Never more than 900 cells burn at once. The flames are FIRE Effects spawned
  on the burning ground nearest you (at most 32, spawned and removed in
  batches no more than twice a second), each lighting the ground around it.
  Turned off, a fire on the ground burns where it fell and goes no further.

**After a fire** (`game/fire_aftermath.py`):

* *Everyone knows.* A fire is seen for miles: everyone within 2,500 units
  knows it for certain the moment it starts, and the news loses no certainty
  however often it is retold ("It's true: fire swept through the wheat near
  Millbrook, today."). When it is out, travellers carry it to other towns
  and notice boards post it.
* *The food is lost.* Scorched ground grows no grain: farmers reap nothing
  there and skip its rows, so less wheat reaches the mill, less flour the
  shops, and the hungry go hungrier.
* *The farmers.* A farmer whose field burnt is furious (courage 0.45 or
  more) or terrified for two days, and says so — about the fire and the
  bread it cost — when you are near.
* *The ground recovers, then they sow.* The scorch lies three days. Then heath
  grows back by itself, but a wheat field lies bare, turned earth, and its
  farmer works extra hard for two days — 5:00 to 20:30, a third quicker on
  their feet — sowing it again, row by row: each row sown is wheat once
  more. A field nobody sows grows back on its own after a week. Nothing
  grows on scorched or bare ground.
* Burns are kept with the save, per map.

**Weather** (Settings › Game › *Weather*, on by default; in the console,
`weather sunny`, `weather overcast`, `weather rain` or `weather storm` turns
the sky, fading in as weather does):

* The sky turns by itself: spells of clear sky (6–20 hours), cloud (2–6),
  rain (1–5) and now and then a storm (½–2), each easing into the next. Rain
  soaks the ground; it dries over hours after, twice as fast under clear sky.
  The weather is kept with the save.
* *Rain fights fire.* Burning grass burns out up to six times faster in a
  storm and spreads slower in any rain — heavy rain stops it spreading at
  all. Wet ground barely catches (a soaked field one tenth as readily).
  Someone burning, and a Flare's fire on the ground, go out sooner.
* *Storms.* A storm (it eases in and out as weather does) brings:
  * *a gale* — the wind blows with a whole strongest-ordinary-wind more on
    top of its own, and gusts of up to 0.7 more again (up to 2.7 times the
    strongest ordinary wind), coming every second or two and veering it a
    little;
    the rain leans hard in it and the clouds race; the wind howls (the
    wind ambience loop, heard everywhere from storm level 0.05 until it
    falls below 0.03, louder with the gale and each gust, never restarted);
  * *the grass thrashes* — meadow, wheat and tundra heath sway violently in
    the gusts and lie over before the wind (in ordinary weather they sway
    gently, harder the stronger the wind);
  * *lightning* — about one strike every ten seconds in a full storm (fewer
    while it builds and dies away): three in ten within 1,400 units, seen as
    a jagged bolt to the ground, the rest out to 9,000 units. Each lights the
    sky, the farther the dimmer. Its thunder is
    heard after 1 s per 1,500 units of distance, louder the nearer. A strike
    within 900 units sets the grass alight with chance 35% × how dry the
    ground is — so in a storm's first minutes, before the rain soaks it;
  * *no travel* — fast travel is refused ("No one travels in this storm.")
    and no one sets out on the roads: no new parties or market trips, and
    parties resting at a place wait it out (those already on the road walk
    on). Walking is never stopped.
* *How it looks.* Rain falls past the overhead camera: drops near the lens
  are big soft smears out toward the edges of the view, streaking in toward
  the middle as they fall, small and sharp, to splash on the ground; the
  wind leans them; the world is washed darker under cloud; a storm's
  lightning flashes. The camera gets wet: drops land on the glass (more in a
  storm) and run down it, the bigger the faster — a tiny bead clings and
  barely creeps (0.006 screen heights a second), a drop of radius 0.045
  (screen heights) runs at 0.55, bigger faster still up to 0.9. A drop runs
  in fits and starts (snagging at 0.3 of its pace, then surging), wanders a
  little side to side, is drawn long as it runs, leaves a trail of small
  beads behind (losing water to them) and sweeps up the beads in its way,
  growing heavier and faster. Beads are egg-shaped, wider at the bottom.
  Small beads and trails fade after a few seconds even in the rain (at most
  64 drops on the glass); everything dries off when the rain stops, the
  smallest first. Moving the camera fast pushes the drops back across the
  glass, big ones most. Each drop has no colour of its own: it shows the
  world behind it upside-down, mirrored and much smaller. The camera is
  focused on the world, not its glass, so every drop is out of focus: a
  soft smudge with no outline, fading out from its middle, the view
  through it blurred, lighter below (the sky it turns over) and a little
  darker on top. None of it ever covers the HUD.

**The sky** is only ever seen in water (the camera looks down). Open water
reflects a real one: a layer of clouds high above the world, drifting with
the wind and thickening with the weather, lit from the sun's side by day,
orange at dusk; by night deep blue with stars, moonlit clouds with silver
edges and the moon's light broken by the ripples. It is seen from the camera
as it truly is, so the clouds slide across the water as you move. At least a
third of a calm surface's colour is sky. The clouds are a texture baked once
while the game loads (no extra draw calls; a few texture reads per pixel of
water).

**Reflections of actors.** People and creatures beside or in water are
reflected in it: upside down, fainter and blue-tinted, swaying with the
ripples, laid in the water just below them as the overhead camera sees it --
so someone on the far shore shows in the water, someone on the near shore
does not, and a reflection stops at the water's edge. The player's own head
is reflected too. Further above the water, a fainter reflection. It costs
one extra draw where actors are near water, none elsewhere.

**Water quality** is one graphics setting for all water (Pause → Graphics →
Water; `[Renderer] water_quality`, high by default): high is depth colour,
soft shores, caustics and reflections of the world and the sky; low is plain
water. A water brush's old "High quality" flag no longer lowers it. Only the
patch of screen around the water in view is copied for it (a small pond
copies a small patch; reflective water a little more), and with no water in
view nothing is.

---

## 10. Learning from tutors

* **Skill training:** 5 sessions per level; `10 + 3 × skill` gold a point
  (before the merchant's price). Not past the trainer's rank or 100, and a
  class with no magic cannot train a school of magic.
* **Spells:** common 40, uncommon 120, rare 450, epic 1,500, legendary 5,000
  gold. Arcane Circle tutors need rank 0 for rare, 2 for epic and 4 for
  legendary; members pay ×0.9. Each spell bought earns reputation (2/3/4/6/8
  by rarity); each lesson +1.
* **Guild rank** = reputation ÷ 10 (members only).

---

## 11. Sneaking

Sneaking halves how far others can see you; an observer without a torch at
night sees 45% as far. Sneak attacks multiply damage (see §7).

---

## 12. Loot and rarity

* Each loot entry drops on a d20 at `chance + (LUCK − 40) × 0.2%`.
* A weapon or armour may be special: `6% + level × 1% + (LUCK − 40) × 0.1%`;
  if special, it is Fabled 15%, Rare 35%, Fine 50%.

| Tier | Value | Stats |
|---|---|---|
| Common | ×1.0 | ×1.0 |
| Fine | ×1.6 | ×1.15 |
| Rare | ×3.0 | ×1.35 |
| Fabled | ×6.0 | ×1.7 |

* Luck 60 or more finds 10% more gold.

---

## 13. Law

* **Bounties:** attack 40 · murder 1,000 · theft 25 + the value · trespass
  5 · lockpicking 25 — once a witness at least 30% sure reports it.
  Alignment scales them: saintly ×0.6, good ×0.8, neutral ×1, evil ×1.25,
  villainous ×1.5.
* **Curfew:** three murders within an hour bring a 6-hour curfew; shops will
  not trade during it.
* **Guards** notice a wanted player within 700 units; straying more than 320
  units from your escort is resisting arrest. A search ends 0.25 hours (0.75
  for a blood writ) after you leave 1,000 units of where you were last seen.
* **Paying** clears the bounty in full; **gaol** lasts
  `ceil(bounty ÷ 100)` hours (1 to 72). A *pardon* (a Charm & Luck option)
  forgives half the lesser charges; a blood writ is never forgiven.

---

## 14. Fast travel

* A click on a **discovered** place on the map asks "Fast travel to …?";
  Enter travels, Esc stays. A quest's marker at a place not yet found
  answers "You haven't discovered that location yet." (the waypoint still
  goes there).
* The journey takes the hours walking it would: the road distance at 200
  units a second, on the game's clock (`FAST_TRAVEL_PACE`, `game/runtime.py`).
  The world catches up as it does after a night in the gaol; followers come
  along.
* Not with a hostile within 1,500 units, while the watch is after you, while
  over-encumbered, in a party, within 900 units of the place already, or
  while it storms ("No one travels in this storm."; with the weather on).

## 15. Trade, talk and charm

* **No talking in a fight.** You cannot start a conversation (or trade)
  while you are in combat -- for 6 seconds after any blow struck or taken,
  or while a foe within 900 has its eyes on you -- nor with anyone who is
  fighting or fleeing. The prompt says why instead of offering to talk. A
  fight that starts mid-conversation, or draws your partner in, breaks it
  off. Notice boards can still be read, and a guard's arrest order is
  still given.
* **Prices:** `factor = 1 − Mercantile / 300`; buying costs
  `base × (2 − factor) × like × face`, selling pays `base × factor × 0.8 ÷
  like × face`. *Like* is `1 − (disposition − 50) × 0.0035` (0.85–1.15);
  *face* by Charisma: repulsive (under 15) 1.5, ugly (under 30) 1.22, plain
  (under 55) 1.0, fair (under 72) 0.96, striking 0.9 (inverted when selling).
  Charisma counts once in a price, as the face; *factor* is Mercantile
  alone. (Disposition, which Charisma nudges, is the merchant's liking.)
* **Disposition** = base + (PER − 40) × 0.5 + 15 for faction-mates − the
  bounty's weight.
* **Persuade:** `(Speechcraft + LUCK × 0.2)%`, 5–95%; success +8
  disposition, failure −4.
* **Charm & Luck options** open at fortune 45: `0.45 + (fortune − 45) ×
  0.012 − difficulty` (haggle 0.10, pardon 0.30, rumours 0, favour 0.20),
  each once a day per person.
* A repulsive face: merchants refuse unless disposition is 60+, and hostile
  people may decline to fight (up to 70% at Charisma 0).

---

## 16. The screen

* **Target panel** (bottom right): who you are fighting — portrait, name,
  Armour Class, your chance to hit, and one thin bar: red health, blue armour
  (AC above 10, 3% of the bar a point, at most 30%; display only), gold for
  damage just dealt. It shows the last enemy you attacked, or one attacking
  you once yours has been quiet for 2 s. It fades in over 1 s, swaps in
  0.25 s, and fades out over 1 s when the enemy is slain (SLAIN held 1 s),
  runs beyond 1,500 units, or 6 s pass without fighting. It shares the bottom
  row with the shortcut bar and never overlaps or sits above it: it narrows
  to fit (to 180 px, then a compact form), goes to the bar's other side if
  the bar is dragged into its corner, and only when even its narrowest will
  not fit does the bar move left. Every number is at the top of
  `game/ui/target_panel.py`.
* **Paperdoll:** Head, Torch, L hand and Gloves on the left; Amulet, Ring, R
  hand and Gloves on the right; Chest, Legs and Feet below the head; Armour
  Class on a shield in the title bar, XP top right. The two hand slots are
  the main and off hand by handedness; a torch takes the off hand; the two
  Gloves boxes are one slot. An empty hand slot shows a hand on yellowed
  paper. A worn helmet is drawn over your head — in the paperdoll and in the
  world — with the face showing through the visor; never over a guard's head.
* **Heads:** every actor's head is drawn at the player's head size (128),
  except a chicken's (50) and a crab's (half, 64); a dragon's is set larger
  in the map. Animals wear their own kind's art, spread evenly over a herd.
* **No split screen:** F9 does nothing; players on one computer share the
  overhead view through Multiplayer's local co-op.
* **Fonts:** MedievalSharp for names and headings; Texturina Light for small
  text, never under 11 px.

## 17. Playing together

* **Up to four players** in a party, on any mix of computers and controllers,
  and **up to four AI companions on top** (the host adds them in the lobby;
  they never take a player's place). Each member has their own colour; with
  more than four, the party cards go compact (name, then health).
* **Friend codes** are the main way to play together. Host game gives a
  code such as `7K2QD-M4XA9-0RT3V` (Copy code); a friend pastes it into
  Join, lands in the lobby and makes their character there. The code holds
  the host's Internet address, the party's port and a random invitation,
  with a check character that catches a mistyped letter or two swapped.
  It connects over **UDP**, which gets through home routers: the joiner's
  knocking opens their own router, and the host's opens by UPnP, a
  forwarded UDP port, or -- if a friend still can't get in -- the friend's
  **reply code** (shown to them after a few seconds of knocking), which the
  host pastes into *Let in*. The address comes from the router, else a STUN
  server asked from the game's own socket (`[Multiplayer] stun_server`;
  empty turns it off), else the computer's own network address (LAN or VPN
  only). Nothing is sent until you host or join.
* **TCP still works**: a typed address (`1.2.3.4[:port]`) and games found on
  the local network join over TCP, on the same port.
* **The code is the key.** A joiner from outside the host's own network must
  show the party's invitation; New code makes a fresh one (friends already
  in stay in). Eight different wrong codes in a minute close the door to new
  code joiners for a minute. Players on the host's own network, and members
  rejoining, need no code.
* **Small on the wire.** The world goes to each player 20 times a second as
  only what changed since a frame they hold (a 770 KB world frame becomes
  about 1 KB), over UDP and TCP alike.
* **A bad packet never disconnects anyone.** Every UDP packet carries a
  CRC-32; a damaged one is dropped and recovered like a lost one (resent,
  or replaced by the next frame), and a message that will not decode is
  skipped.
* **Late arrival** (the host's choice in the lobby, on by default): players
  may join while the adventure is running, while there is room. Off, they
  join only in the lobby before Start; anyone new afterwards is told "Game
  has already started and does not allow late arrival".

---

## 18. Mills and flour

* A windmill grinds ten wheat into one flour every quarter hour of game time
  while it has wheat; its sails turn only then. Farmers carry their wheat to
  the nearest working mill; shops send for flour, or walk for it, before
  they open, and a shelf holds only what really reached it.
* A mill can be **held**. The Old Mill's windmill is held by Hal Corbin:
  while anyone of that name lives it is idle (nobody delivers to it or buys
  from it, and its sails stand still). Within 2 seconds of his death,
  however he dies, it is an ordinary working mill.
* A shop can have a mill of its own (`flour_mill`). Hollin's Cross buys from
  the Old Mill while it works, and from the nearest working mill (Mara's, in
  Millbrook) while it is held.
* **Trouble at the Old Mill** ends with Hal Corbin's band: Hal (level 2,
  80 health, 11 damage) and three men with real names, one an archer posted
  on the far side from the Millbrook road. None of them comes back. Hal
  carries *Corbin's Ledger*; Aldric reads it and pays 150 gold, a steel
  longsword and 15 reputation with the town.
* The Old Mill's toll strongbox holds the Cross's stolen tolls, Aldric's by
  right. Taking them is theft from him. Handing them back when the quest
  completes adds 40 gold and 5 reputation; keeping them is the player's
  choice.
* **Talk of the town.** What the mill's trouble does is said aloud:
  * a hungry resident within 600 units of the player says why they cannot
    get bread (the shop has run out, it is shut, it costs too much) -- the
    flour supply's own reason, once for each reason each day;
  * notice boards stand in Millbrook square and at Hollin's Cross's
    crossroads (E to read). Besides the writ on the player's head, the
    watch's appeals, departures and news, each posts the flour on every shop
    shelf within 2,500 units: the real stock and price, or "none today";
  * Aldric, once he knows of Hal Corbin's death (he saw it, or was told),
    opens with "Word got here before you did";
  * Hal's brother **Rook Corbin** lives with the bandits at Cutthroat Ridge.
    When word of Hal's death reaches him, the storyteller can send him on a
    vendetta, announced on the boards and in departures news before he
    arrives;
  * news of a lawful killing or fight (bandits cut down on the road) is met
    with "Good riddance", never "the watch had better hear of this".

## Known gaps

Places where the code does not yet do what something in the game describes:

* The **Apprentice** birthsign's "weaker to magic" is not implemented, and
  some birthsign descriptions leave out bonuses they give.
* **Sneak** is trained but read by no rule; **Acrobatics**, **Light Fingers**
  and **Alchemy** are neither trained nor read.
* Sneak-attack damage applies whenever sneaking is on, even if the target has
  already seen you.
