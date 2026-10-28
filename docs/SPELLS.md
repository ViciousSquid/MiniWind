# Spell values: `game/data/spells.json`

Every spell in the game, and every number that drives it, lives in
`game/data/spells.json`. Edit it by hand, or in the editor with
**Tools ▸ Spell Editor**, which reads and writes the same file. A spell in the
file overrides the built-in one with the same `id`, and a new `id` adds a spell.

| Field | What it does |
|-------|--------------|
| `id` | Unique name the game, items, races and classes refer to. |
| `name`, `desc` | What the player sees in the spellbook. |
| `school` | One of the three schools, and there are no others: `offensive` (harms), `defensive` (heals, wards, aids) or `occult` (the dark arts: raising the dead, unmaking the living, summoning and binding beasts and spirits, sensing life). The matching skill governs cost and the cast roll, and is trained by casting and by trainers. An old school name (`destruction`, `restoration`, `conjuration`...) is read as the school it was folded into. |
| `cost` | Magicka at level 1, before the caster's skill discount (skill can bring it down to a quarter). |
| `delivery` | `self`, `touch`, `target` or `projectile`. |
| `effects` | A list of `{"kind", "magnitude", "duration"}`. `damage_health` magnitudes are the spell's damage; `restore_health` its healing; `shield`, `fortify_*`, `calm`... their strength. `duration` is in seconds (0: instant). |
| `element` | `fire`, `frost`, `shock` or `magic`: the damage kind resistances apply to, and the default colour. |
| `projectile_speed` | World units per second for a `projectile`. |
| `color`, `visuals` | How the bolt and its impact look (null / `{}`: the element's look). |
| `rarity` | `common`, `uncommon`, `rare`, `epic` or `legendary`: its colour in the spellbook, and the default XP per level. |
| `max_level` | The highest level the player can raise it to. |
| `xp_per_level` | Experience to raise it from level N to N+1 is this × N (so 30 means 30, 60, 90, 120...). Experience spent on spells is not spent on character levels. |
| `level_power` | Extra magnitude per level above the first (0.25 = +25% damage / healing / strength each level). Effects that are on/off switches (knock, invisibility, light...) and instant kills never scale. |
| `level_duration` | Extra duration per level above the first (0.125 = +12.5%). |
| `level_cost` | Extra magicka per level above the first (0.10 = +10%). |

The Spell Editor shows each spell's damage, magicka and XP cost at every
level as you change these.
