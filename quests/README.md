# Quests

Every quest in MiniWind lives here as its own **`.quest` file** — human-readable
JSON you can open, hand-edit, diff and version-control. This folder is the single
source of truth: the **MiniWind Quest Editor** writes these files, and the
running game loads them at play start.

## File format

One quest per file, named `<id>.quest`. Example (`a_word_with_wick.quest`):

```json
{
  "id": "a_word_with_wick",
  "name": "A Word with Wick",
  "giver": "Mara",
  "faction": "town",
  "desc": "Mara frets that old Wick hasn't been seen today...",
  "xp": 15,
  "rewards": { "gold": 25, "items": [["potion_heal", 2]], "rep": ["town", 5] },
  "stages": [
    { "index": 0, "journal": "...", "objective": "Speak with Wick",
      "finishes": false,
      "condition": { "kind": "talk", "target": "Wick", "count": 1 } },
    { "index": 10, "journal": "...", "objective": "Report to Mara",
      "finishes": true,
      "condition": { "kind": "talk", "target": "Mara", "count": 1 } }
  ]
}
```

### Fields

| Field      | Meaning                                                              |
|------------|---------------------------------------------------------------------|
| `id`       | Unique quest id (also the file stem). Required.                      |
| `name`     | Display name shown in the journal and offer dialogue.               |
| `giver`    | Name / display name / role of the NPC who hands the quest out.      |
| `faction`  | Optional guild/faction the quest belongs to.                        |
| `desc`     | Opening text the giver speaks when offering the quest.              |
| `xp`       | XP awarded on completion.                                            |
| `rewards`  | `gold`, `items` (`[["item_id", qty], ...]`), `rep` (`["faction", n]`). |
| `stages`   | Ordered stages; each has an `index`, `journal`, `objective`, and an optional completion `condition`. A stage with `"finishes": true` completes the quest. |
| `starts_on_new_game` | Optional. `true` starts the quest for every new character, so the journal and the quest arrow have somewhere to begin. *Trouble at the Old Mill* is the only one. |

### Stage extras

| Field      | Meaning                                                              |
|------------|---------------------------------------------------------------------|
| `waypoint` | Where the quest arrow points on a stage with no machine-readable target (a place, NPC, monster type or item id). Never advances the quest. |
| `say`      | On a `talk` stage: the line the person you were sent to opens the conversation with while you are on that stage ("Go on." then leads to their usual talk). Tokens read the world as it is: `{shelf_flour}` (flour on the speaker's own shelf: "no flour", "one sack of flour", "3 sacks of flour"), `{mill_wheat}` and `{mill_flour}` (in the working windmill nearest the speaker: "no", "12 measures of", "1 sack of"). |

### Stage conditions

A stage auto-advances when its `condition` is met (leave `kind` as `none` for a
stage advanced only by dialogue `advance_quest`):

- `talk`  — `target` = NPC name/role; met by a conversation held *while on
  the stage* (having spoken to them before the quest began does not count)
- `fetch` — `target` = item id, `count` = how many to hold
- `kill`  — `target` = monster_type / role / name / faction, `count` = how many
  (a faction such as `bandits` counts every member: bandits, archers, chiefs)
- `visit` — `target` = a location marker's name
- `roll`  — `notation` = dice expression, `target` = minimum total

## Assigning a quest to its giver

Just set the quest's `giver`. At play start the game finds the matching NPC in
the scene and automatically gives them a dialogue branch that **offers and
starts** the quest — so a `!` bubble appears over them and you can walk up, talk,
and accept. No manual dialogue editing is required. (If you *have* hand-authored
a quest offer in that NPC's dialogue, it is left as-is.)

The `giver` can be the NPC's **name**, **display name**, **role**, or its stable
**entity id (UUID)**. Prefer the id when several NPCs share a name (e.g. two
"Guard" NPCs) so the quest resolves to exactly one entity — the Quest Editor's
giver picker fills in the id automatically for shared names.
