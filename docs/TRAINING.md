# Trainers and spell tutors

Some people in the Vale will teach you for gold. Learning by doing is still
how you grow. A teacher only speeds it up, within limits. The rules live in
`game/rpg/training.py`, the two parchment pages in `game/ui/teaching.py`, and
the list of who teaches what in `game/data/teachers.json`.

## The three schools

Magic has three schools and no others. Every spell belongs to one of them,
and each school is a skill that grows as you cast its spells:

| School | Governed by | What it covers |
|--------|-------------|----------------|
| **Offensive** | Intelligence | Fire, frost and shock bolts; Bound Blade. |
| **Defensive** | Endurance | Healing, wards, light, Night Eye, Feather, Knock, Telekinesis, Invisibility, Calm. |
| **Occult** | Charisma | The dark arts: Resurrection, Disintegrate, Summon Wolf, Command Creature, Detect Life. |

Old school names (Destruction, Restoration, Alteration, Illusion,
Conjuration, Mysticism, Necromancy) still load: each folds into its successor
(`skills.FOLDED`). A save from before the Occult school starts its Occult skill
at the lower of its Offensive and Defensive skills. A preset class in such a
save takes up the major skills that class has now. Wickedness empowers
Offensive and Occult magic, and goodness empowers Defensive magic.

## Skill training

Talk to a trainer and choose **"I'd like some training."** The training sheet
shows, for each skill they teach:

* **Trainer skill**: their own rank (Novice 0, Apprentice 25, Journeyman 50,
  Expert 75, Master 100). They cannot teach you past it.
* **Current skill**: your rank and level.
* **Times trained this level**: at most **5** sessions per character level.
  The count resets when you level up.

One session raises one skill by one point. It costs
`10 + 3 × your current skill` gold, before the merchant's adjustments
(Mercantile, Charisma and how much the trainer likes you). A point you buy
counts like a point you earn: it adds to your next level-up's attribute bonus,
and a major skill's point counts toward the next level. Warriors are turned
away from training in the three schools, but not from steel.

## Spell tutors

Choose **"What spells can you teach me?"**. Each spell costs gold by its rarity,
before the merchant's adjustments:

| Rarity | Price | Arcane Circle tutors require |
|--------|------:|------------------------------|
| Common | 40 | nothing |
| Uncommon | 120 | nothing |
| Rare | 450 | membership (Associate) |
| Epic | 1,500 | Journeyman of the Circle |
| Legendary | 5,000 | Conjurer of the Circle |

Tutors of the **Arcane Circle** (`"guild": "mages"`) offer
**"I wish to join the Arcane Circle."** They give members 10% off. Every spell
bought from them earns reputation (2–8 by rarity), and so does every lesson in
a school. Every 10 reputation raises your rank. Independent tutors ask no
standing.

## Who teaches where

| Teacher | Where | Trains (rank) | Sells |
|---------|-------|---------------|-------|
| Mara | Millbrook | Offensive, Defensive, Occult (Apprentice) | Circle basics: Flare, Light, Minor Healing, Night Eye, Detect Life, Feather, Shield, Frostbite |
| Brother Ansel | Hollin's Cross | Offensive, Defensive, Occult (Expert) | The Circle's wider book, Frostbite to Summon Wolf |
| Mother Nettle | Witch's Knoll | Occult, Alchemy (Expert) | The dark arts, with no questions about standing, including Disintegrate and Resurrection |
| Old Maud | Reedhollow | Defensive, Alchemy (Apprentice) | Frostbite, Feather, Night Eye, Minor Healing |
| Grunn | Hollin's Cross | Blade, Blunt, Block, Heavy Armour (Expert) | — |
| Thalen the Smith | Millbrook | Blunt, Heavy Armour (Apprentice) | — |
| Ysolde Steelhand | Hollin's Cross | Blade, Light Armour (Journeyman) | — |
| Fenwick the Hunter | Fenwick's Lodge | Marksman, Sneak (Journeyman) | — |
| Osric the Ferryman | Reedhollow | Athletics, Acrobatics (Journeyman) | — |
| Aldric the Reeve | Hollin's Cross | Speechcraft, Mercantile (Expert) | — |
| Wynn | The Wanderer's Rest | Speechcraft, Light Fingers (Journeyman) | — |
| Nell | The Pilgrim's Lantern | Mercantile, Security (Journeyman) | — |

Every spell the game ships can be learned from someone except Wisp, which only
ever comes in Flare's place.

## Making a teacher

In the editor, an NPC's **TEACHING** group has *Trains skills* (comma-separated
skill ids), *Trainer rank*, *Sells spells* (comma-separated spell ids) and
*Teaches for* (`mages` for the Arcane Circle). Map data may also give a
`trainer` dict (`{"skills": [...], "rank": 50}`) and a `teaches_spells` list.
An NPC's own properties win over its entry in `game/data/teachers.json`. That
file is keyed by the NPC's stable `name`, so an NPC streamed in later by Big
World teaches like any other.
