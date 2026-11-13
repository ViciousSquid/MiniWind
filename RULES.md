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
* **Roll boxes.** A roll shows in a small box over whoever rolls it (never a
  corner panel): their name in their side's colour (gold you, green an ally,
  red a foe), what the roll is for, the real dice tumbling, the verdict, and —
  for a hit — the damage. Your own rolls sit on a black box; everyone else's
  (allies, foes, fights between NPCs) on a blue-slate one.
  Boxes that overlap more than slightly lock into one stack, the attacker's
  roll on top (Settings › Game › *Stack dialogs*, on by default). A character
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
| **Speed** | governs Light Armor, Athletics and Acrobatics |
| **Personality** (shown as *Charisma*) | prices, disposition, how strangers react to your face |
| **Luck** | critical hits; attack bonus (both ways); saving throws at the extremes (the fate die); loot; skill learning; casting |

Everyone in the world has Strength, Endurance, Charisma and **Luck** — every
NPC and every animal: rolled once on 3d6 around a baseline for their kind (a
bear is strong, a hen is not), at half the swing of the player's roll, and
kept for good (`game/rpg/charisma.py`). Luck's baseline is 40, except: beggar
and mudcrab 25, skeletons 20, sheep 30, merchant 50, bandit chief 55, hen 55,
dragon 60. An authored value always wins.

---

## 3. Making a character

Attributes are built in this order: base 40 → race → +10 to each of the
class's two favoured attributes → birthsign → your dice. You roll **3d6** each
for Strength, Endurance and Charisma; each roll moves the attribute by
`round((total − 10.5) × 4)` (−30 at 3, +30 at 18). Reroll as often as you
like (`game/rpg/character.py`).

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
(the creature's own value: wolf 8, boar 10, mudcrab 4, bear 25, bandit 14,
bandit archer 16, bandit chief 45, cultist 18, skeleton 16, skeleton archer
18, wraith 40, monster 30; townsfolk and farm animals 0) and from quests.

A level-up raises your two favoured attributes and the one you trained most
this level by +1 to +5 each; you choose one more for +5 (Strength, Endurance,
Charisma, or — for magic users — Magicka, which raises Intelligence); health
rises by END × 0.1 for good; all pools refill.

**Spell levels** are bought with the same XP: `xp_per_level × current level`
(common 30, uncommon 45, rare 60, epic 80, legendary 120), up to level 5.
Each level adds +25% magnitude, +12.5% duration and +10% cost.

---

## 5. Health, magicka, stamina and burden

* **Max health** = END × 2 + level gains + birthsign.
* **Max magicka** = INT × 1.5 + gains + birthsign (0 for a class with no magic).
* **Max stamina** = (STR + 3 × END) × 0.5 + gains + birthsign.
* **Regeneration per second:** magicka `max × 0.02 × (0.5 + END/100)` (none
  under the Golem); stamina `max × 0.15` (not while sprinting). Health does
  not regenerate — only spells, potions and levelling restore it.
* **Sprinting** costs 12 stamina a second; at 0 you are **winded** and cannot
  sprint again until back to 30%. Winded fighters take −2 to hit.
* **Stamina costs:** a swing or an arrow 6; a shield bash its own cost.
* **Carry weight** = STR × 5. Over it you are encumbered: movement × 0.33.

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
  wolf 1 · boar 2 · bear 3 · mudcrab 5 · skeleton 2 · skeleton archer 1 ·
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
  critical killing blow** — blows the body apart. A critical kill adds extra
  gore and the hardest screen shake.
* A body blown apart can never be resurrected, and Death (the reaper, who
  otherwise attends one death in eight) never comes for it.

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

## 14. Trade, talk and charm

* **Prices:** `factor = 1 − (Mercantile + PER − 40) / 300`; buying costs
  `base × (2 − factor) × like × face`, selling pays `base × factor × 0.8 ÷
  like × face`. *Like* is `1 − (disposition − 50) × 0.0035` (0.85–1.15);
  *face* by Charisma: repulsive (under 15) 1.5, ugly (under 30) 1.22, plain
  (under 55) 1.0, fair (under 72) 0.96, striking 0.9 (inverted when selling).
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

## 15. The screen

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
* **Fonts:** MedievalSharp for names and headings; Texturina Light for small
  text, never under 11 px.

---

## Known gaps

Places where the code does not yet do what something in the game describes:

* **Speed** is described as how fast you move, but nothing reads it for
  movement.
* The **Apprentice** birthsign's "weaker to magic" is not implemented, and
  some birthsign descriptions leave out bonuses they give.
* **Sneak** is trained but read by no rule; **Acrobatics**, **Light Fingers**
  and **Alchemy** are neither trained nor read.
* An **Athletics** rise adds +1 max stamina that the next recalculation
  removes.
* Sneak-attack damage applies whenever sneaking is on, even if the target has
  already seen you.
* **Charisma** counts twice in prices.
* The older pool-based level-up option is unused.
