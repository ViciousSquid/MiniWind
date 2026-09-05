# Quests

Every quest in MiniWind lives here as its own **`.quest` file** — human-readable
JSON you can open, hand-edit, diff and version-control. This folder is the single
source of truth: the **MiniWind Quest Editor** writes these files, and the
running game loads them at play start. Quests are *no longer* stored inside the
map's `Game Settings` entity (a map that still carries the old in-entity list is
migrated into this folder the first time you open it in the Quest Editor).

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

### Stage conditions

A stage auto-advances when its `condition` is met (leave `kind` as `none` for a
stage advanced only by dialogue `advance_quest`):

- `talk`  — `target` = NPC name/role
- `fetch` — `target` = item id, `count` = how many to hold
- `kill`  — `target` = monster_type / role / name, `count` = how many
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
