# The Last Sheaf: MiniWind's main storyline

Status: **design, for review**. Nothing below is implemented yet. Chapter one
gets a beat-by-beat plan here; chapters two to five are outlines and get their
own beat plans once chapter one has shipped and been played.

The aim is a vertical slice. The first hour runs from the launcher's PLAY,
through character creation and Millbrook, to the end of "Trouble at the Old
Mill". It should be good, it should hang together, and it should be the
template every later chapter follows.

---

## 1. The first hour today: a headless walkthrough

Played on CANARY at `5e66370` with the real map (`maps/miniwind_world.json`),
the real game session and real dialogue. I used `FioTestSession` under Xvfb
with Mesa, the same setup the `fio_session` fixture uses, and kept
screenshots. The character was a Warrior made through the creator's own keys.
Travel was done by teleporting. The walking time, at 200 units/s with no
sprint, is estimated from the distances.

North is world −Z. All distances are straight lines in world units.

| Place | Where | From Millbrook |
|---|---|---|
| Millbrook (spawn, `PlayerStart_1`) | 0, 0 | — |
| Millbrook windmill (the only working mill) | 3,312, 704 | 3,400 E (~17 s) |
| Old Mill (bandit camp, static mill model) | 8,856, −5,600 | 10,500 NE (~55 s) |
| Hollin's Cross (Aldric) | 8,432, 6,560 | 10,700 SE (~55 s) |
| Old Mill → Hollin's Cross | | 12,200 (~60 s) |

### Step by step: what a new player actually sees

1. **PLAY** (launcher) loads `[Startup] default_map` in kiosk mode and goes
   straight to character creation. **There is no Continue.** PLAY always
   starts a new game, even with `saves/autosave.fiosave` on disk. The only way
   back to a save is pause menu › GAME › LOAD GAME, or the death screen.
2. **Character creation**, in five steps: name and head, then 3d6 fortune for
   STR/END/CHA, then class (six offered), then birthsign (five), then
   confirm. It reads well, and the fortune step's dice and short bio are
   charming. Problems:
   * Pieces of the engine's stock HUD show through around the panel: a large
     orange **"80"** (Fio's own health readout) at bottom left, and the
     brass weapon frame at bottom centre.
   * **"FPS: 0/1"** sits top right. The shipped `settings.ini` has
     `show_fps = True`, and `qt_game_view` draws the counter in kiosk mode
     too.
3. **Spawn**: Millbrook market square, 08:00, day 1. The only text is a toast,
   *"Welcome to The Vale of Miniwind, Tamsin."* There is no objective, no
   tracked quest, and nothing to say what this place is. Three NPCs within
   ~700 units carry a "!" quest offer:
   * Mara: *A Word with Wick*. A two-line errand.
   * Elowen: *The Lost Amulet*. The amulet is at Greywood, 16 km away.
   * Thalen: *The Ember Tome*. It sits on an altar at the Emberpeak Shrine,
     ~37 km north-east past Frostcap Tor. A new character dies on the way.

   Nobody in Millbrook mentions the Old Mill, Aldric or Hollin's Cross. The
   game's named opening quest is invisible from where the player starts.
4. **Journal** (J): *"Your journal is empty. Talk to the folk of Miniwind to
   find work."* The village is called Millbrook. The README also says "the
   village of Miniwind" and "Borin the smith" (he is Thalen).
5. **Talking**: greetings are good (*"I keep the peace, the books and the
   tolls at Hollin's Cross. Mostly the tolls."*). Wick's *"What's the word
   around town?"* is fixed flavour text, not the rumour layer. There are
   **no notice boards anywhere in the world**: the map has 0 things of type
   `notice_board`. Half of what docs/rumours.md describes therefore can't be
   seen at all.
6. **Aldric** (Hollin's Cross) offers *Trouble at the Old Mill* through his
   hand-written map dialogue: *"Bandits hold the old mill north-east of
   Millbrook — the grain for three villages sits under their boots."*
   Accepting it starts the **wrong quest definition** (see 7).
7. **BREAK: the quest that runs is not `quests/mill_bandits.quest`.**
   `begin_new_character` → `GameState.new_game` → `GameState.__init__` calls
   `quests_content.load()`. That re-registers the hard-coded built-ins
   *after* the session has loaded the `.quest` files, so every new game plays
   the old built-ins.
   * The built-in Old Mill quest's first stage has **no condition**.
   * I killed 8 bandits and 6 bandit archers (`kills.bandit = 8`). The quest
     never advanced, and Aldric never offered a turn-in.
   * **The first hour cannot be finished.** The same happens to every quest
     that exists both as a built-in and as a file (wolves, fighters_join,
     lost_amulet, …).
   * The quest target is also wrong. The built-in names the mill as "east of
     Miniwind" and gives `target_pos = None`, so there is no arrow to it.
8. **With the `.quest` files re-applied by hand** (to see the intended
   version), the quest works:
   * Stage 0 is "Find the Old Mill", with an arrow (12.3 km).
   * Discovery advances it to "Kill 4 bandits" (0/4, with an arrow to the
     nearest bandit).
   * Then "Return to Aldric", and he pays 150 gold and a steel longsword.

   Remaining problems:
   * **"Return to Aldric" has no arrow.** It is 12 km away and stages with
     no condition have no target.
   * **Difficulty spike.** The camp has the `BanditSpawner` (4 bandits,
     `respawn: true`) plus 3 placed bandits, 2 of them archers. A level-1
     Warrior lost 45–58 of 124 HP in four seconds just standing at the edge.
     Because the spawner respawns, "clearing the mill" never really clears
     it. My fight took ~2,400 ticks and 12 emergency heals.
   * **Raw names on screen.** The spawned bandits are *Creature_21–24*, and
     the roll box reads **"CREATURE_22: ROLL TO HIT FOLK1014 THE
     WAYFARER"**. Generated folk show as "Folk908 the Farmer".
   * After the fight a bystander barked *"The watch had better hear of
     this."* It reads as if killing bandits were a crime. I'll confirm who
     was reporting whom in Phase 1.
   * The level-up prompt appears (Level up! (press L)). That's good, but the
     player is never told what L does.
9. **The mills.** The Old Mill is a static model with still sails and is not
   part of `game/windmills.py`. The Millbrook windmill has 0 wheat and 0
   flour at 08:00 on day 1.
   * All five flour shops (Elowen, Old Maud, Hollin Brewer, Wynn, Nell) start
     with 0 flour and report *"No collection route fits before opening;
     awaiting a supplier."*
   * The economy the game is named after is empty at the start, and the
     player has no way to know it.
10. **Dice outside combat.** Persuade, Charm & Luck and loot finds go through
    `dice_animation`, the old **corner panel** above the weapon chips.
    RULES.md §1 says a roll "shows in a small box over whoever rolls it
    (never a corner panel)". The loot rolls also flood the log with "Roll to
    find …: FAILED" lines.
11. **Editor exposure in PLAY.** I found three:
    * the FPS counter (item 2);
    * the **EDITOR** button on the pause menu's top row;
    * game windows with editor-style title bars (`▼ [X]`).

    The last is minor and may be intended.

---

## 2. The story

### The threat

The Vale lives on bread. Its wheat goes to the mills, its flour to the
shelves, and its people eat what the shelves hold. That is all simulated
already (`farm_work.py` → `windmills.py` → `flour_supply.py`): finite
stock, real couriers, and real shortages.

**The Ashen Circle** wants the Vale hungry. It is a hedge-cult of ruined
tenant farmers led by a preacher, **Sister Cinder**. They lost their land to
the Cross's tolls and believe a hungry winter, the *Ash Winter*, will burn
the Vale clean. They don't march on towns. They starve them:

* they pay bandits to seize a mill;
* they buy the stolen flour through smugglers and burn it as offerings;
* they drive boar into the barley;
* in the end they carry off the Vale's seed grain, so that nothing can be
  sown in spring.

Each chapter takes one of these away from them. The player follows the money
and the flour, one ledger, manifest or token at a time.

The grievance is real (Aldric does mostly do the tolls), which lets the ending
be something other than a body count.

### Chapters

Each chapter is an existing quest file, recast. "Changes" lists what each file
needs.

| # | Chapter | From | Where | What it takes from the Circle |
|---|---|---|---|---|
| 1 | **Trouble at the Old Mill** | `mill_bandits.quest` | Millbrook → Old Mill → Hollin's Cross | The mill they had seized |
| 2 | **The Mirrormere Smugglers** | `mirrormere_smugglers.quest` | Reedhollow → Smugglers' Cove | The route the stolen flour leaves by |
| 3 | **Blight in the Barley** | `blight_in_the_barley.quest` | Oakridge Farm (feeds Millbrook's mill) | Their sabotage of the harvest |
| 4 | **The Ashen Circle** | `ashen_circle.quest` | Hollin's Cross → the stone circle | Their altar, and their secret |
| 5 | **The Last Sheaf** (finale) | new: `last_sheaf.quest` | Shrine of the Last Sheaf (8,179, −27,488), far north | The Vale's seed grain |

**Chapter 2: The Mirrormere Smugglers.** Aldric reads the bandit chief's
ledger: *silver paid at the south shore*. He sends the player to Old Maud at
Reedhollow, who sees every boat on Mirrormere. The smugglers aren't bringing
contraband in. They're taking flour out, in sacks marked with a smear of ash.
Their manifest names the buyer only as "the Circle".
*Changes:*
* a new first stage, *talk Old Maud*, reached through Aldric's referral (the
  quest is still Maud's to hand over);
* the kill stage stays;
* a new fetch stage for the ash-marked manifest;
* new journal text;
* the turn-in names Oakridge Farm, the next delivery's source.

**Chapter 3: Blight in the Barley.** The manifest's next pickup is Oakridge
Farm, whose wheat feeds Millbrook's windmill. Hobb thinks the boar are bad
luck, but the fences were cut and a burnt circle was left in the stubble.
*Changes:*
* giver stays Hobb, with an opening visit to the burnt field (an authored
  marker);
* boar kill stays;
* a new fetch stage for an ash token from the field;
* the reward bread becomes flour from Hobb's own sack;
* the turn-in sends the player to Brother Ansel, who knows the token.

**Chapter 4: The Ashen Circle.** Ansel recognises the token: a hedge-cult
that meets at the stone circle north-east of the Cross. Breaking the circle
turns up Sister Cinder's letters. The Circle has gone north with the Vale's
seed grain, *"to the last sheaf"*. Among the letters is a toll receipt in
Aldric's hand, for the farm that was hers.
*Changes:*
* giver stays Ansel;
* visit and kill stay;
* a new fetch stage for Cinder's letters;
* the turn-in to Ansel starts the finale.

**Chapter 5: The Last Sheaf (finale).** A new quest. The Shrine of the Last
Sheaf is far to the north, a real journey. Sister Cinder holds the seed grain
in the shrine and means to burn it at dawn (`burning.py` already burns
things).
*Stages:*
* reach the shrine;
* get past her followers;
* face Cinder;
* bring the seed grain home to Mara's windmill at Millbrook.

At the shrine there is one confrontation with two ways through, both
resolved on the same roll box:
* **Fight** her.
* **Persuade** her (a Speechcraft check). The player can show her the toll
  receipt from chapter 4 and give their word that the toll will be lifted.
  Holding the receipt makes the check easier.

### The ending (one ending)

The seed grain is sown, and Aldric reduces the mill toll. That second part is
a store flag. There is no toll in the flour code today. The finale chapter
would add one: a markup on flour bought at the Cross's mill, which the flag
lowers. That is the only new rule in the plan, and it is chapter five's, not
chapter one's.

The closing scene is at the Millbrook windmill. **It reads the world as it
actually is, not a script:**
* it names every mill whose sails are turning;
* it names every shop with flour on its shelf, with today's real counts;
* if a shop is still empty (a runner killed on the road, say), Mara says so
  by name.

If Cinder was persuaded, she is at the mill queue with a sack of her own. If
not, she isn't.

That's the ending. The Vale is fed for now, and the player can see exactly
how well.

### Side quests

The others stay side quests: Wick, the amulet, wolves, Nettle, the Fighters
Guild, the yeti, the spiders, the greenskins and the Ember Tome. Rumours can
point at them. None of them is required.

---

## 3. Chapter one, beat by beat

**"Trouble at the Old Mill"**: about 45–60 minutes including character
creation.

**Changes to the mill story itself:**
* The quest's giver moves from Aldric to **Elowen in Millbrook**, so it
  starts where the player starts.
* Aldric becomes the turn-in, and the way into chapter two.
* His hand-written map dialogue keeps its good greeting. Its offer branch
  becomes the turn-in.

| Beat | Where | What happens | Systems it shows |
|---|---|---|---|
| 0 | Launcher | **PLAY**: with no save it goes straight to creation; with an autosave it asks **Continue / New game** (fix). | autosave |
| 1 | Creation | Unchanged apart from the fixes in §1.2. The fortune step's bio is the first piece of writing in the tone below. | dice, charisma |
| 2 | Millbrook square, 08:00 | The welcome toast gives way to Elowen calling across the square: *"You — new face. Have you got a minute?"*. A real bark, once. The quest is **started at new game** with stage 0 *Talk to Elowen* (arrow on her stall). It is the only quest in the journal, so the player always knows the first step. | barks, quest arrow |
| 3 | Elowen's stall | Her trade window shows **Flour — sold out**: the real shelf, which is truly empty. She explains: since bandits took the Old Mill, Hollin's Cross sends its runner to Mara's windmill. The queue is out the door and Millbrook gets what's left. *Stage 10: Ask Mara at the windmill.* | flour shelf, price |
| 4 | Road east (~17 s) | Villagers who couldn't buy flour say so (the existing `_food_reason`: *"The local shop has run out of flour."*) as thoughts and barks. | needs, chatter |
| 5 | Millbrook windmill | The sails turn only if there's wheat in the hopper (real). In the queue at the door stands **Hollin's Cross Flour Runner** (real, if he's been sent). Mara reads her own stock aloud from the mill's inventory: *"Twelve measures of wheat in the hopper. That's one sack, and the Cross's man is first in line for it."* She points north-east. *Stage 20: Find the Old Mill* (arrow). | windmills, flour queue |
| 6 | Road NE (~45 s) | A wayfarer on the road volunteers the rumour that the Old Mill lot robbed a cart. It is a real fact if the board's encounters made one; if not, a seeded opening fact the knowledge store holds like any other. The player is warned before arriving. | rumours |
| 7 | Old Mill: approach | Discovery. **Stage 30: Drive the bandits from the Old Mill.** Kill their leader, **Hal Corbin** (a named bandit chief), and 3 of his men. The camp is retuned for a level-1–2 character: the spawner doesn't respawn (`respawn: false`), there is one archer, and every bandit has a real name. Sneaking up, now with a working Sneak skill (Phase 3), is a real option: a sneak attack, and the archer posts on the far side. | combat, sneak |
| 8 | Old Mill: the strongbox | Inside the mill is a locked strongbox holding the mill's stolen toll takings. It's a lockpicking check **on the roll box** (Phase 4). Opening it is a theft from the Cross unless the player returns the money to Aldric. That is an existing ownership/law rule, so the player chooses. | lockpicking, law |
| 9 | Old Mill: the ledger | Corbin carries **Corbin's Ledger**, a book: *silver paid "for mill-work" at the south shore; the flour sacks "to the boat"; one line, "the Ash-men's price, settled"*. **Stage 40: fetch the ledger.** | books, loot |
| 10 | Old Mill: the mill wakes | With Corbin dead, the Old Mill becomes a working windmill again: its authored mill and rotor are enabled (format extension, §6). From then on it is ordinary simulation: the farmers at Fox Croft carry wheat to the nearest mill (now this one), and the sails start turning when the first delivery lands. Hollin's Cross buys from its own mill again (`flour_mill`, §6), so Mara's queue shortens. | windmills, farm work |
| 11 | Road S (~60 s) | **Stage 50: Take the ledger to Aldric at Hollin's Cross** (arrow, which is fixed for talk stages). People who saw the fight know who did it, and the rumour layer carries it. | knowledge, rumours |
| 12 | Hollin's Cross | Residents asked *"Heard any news?"* tell the player what they know about the Old Mill, and about the player. Aldric has a different first line if word has reached him: *"Word got here before you did."* He reads the ledger, pays the reward, and if the player brought the strongbox money back he says so and adds to the pay. He names the next lead: *"South shore means Mirrormere. Old Maud at Reedhollow sees every boat on that water."* **Chapter one is complete.** A chapter card appears, and chapter two's first objective goes into the journal. | dialogue, rep |
| 13 | Coda: the warning | Hal Corbin's brother **Rook** lives at Cutthroat Ridge (an authored `relationships` entry on an existing bandit there). When word of Hal's death reaches him, the storyteller can send him on a **vendetta**, and it is announced before he arrives: the notice board in Hollin's Cross and the residents' departures news say *"Rook Corbin set out from Cutthroat Ridge — swore to find whoever killed Hal."* The storyteller's state rises, and when Rook arrives he says once, *"You killed Hal. I've walked a long road to find you."* All of these lines and steps exist already (`justification()`, `departures()`, `chatter.justified_line`); chapter one only gives them a name the player knows. | vendettas, storyteller, notice board |
| 14 | Next morning | Elowen's shelf has flour again, and the count is real. If the Hollin's runner was killed on the road, it doesn't, and Elowen says why. | flour supply |

**Why the player wants chapter two.** The ledger raises a question chapter
one doesn't answer: who pays bandits in silver to stop a mill, and who are
the "Ash-men"? Rook's vendetta also shows the player that the world
remembers what they did. Aldric hands over a name and a place.

**Phase 5 hook (optional).** The ledger's last page reads *"the rest of the
sacks are in the cellar at Thornback"*. That is cave20 (15,665, −7,294),
~7 km east of the Old Mill, renamed **Thornback Cellar**. It is authored as
the bandits' stash: stolen flour sacks (finite stock the player can return to
Elowen's shelf) and Rook's hideout if he hasn't come for the player yet. It
is the one cave chapter one uses, and it gets a name, a reason and a link.

---

## 4. Simulation loops chapter one makes visible

I recommend these three. Each is wired to systems that already exist, and
each can be read on screen: the player can tell what happened and why.

1. **Mill trouble shows up as flour shortages.**
   * *Already exists:* finite mill and shop stock, couriers, queues,
     `_food_reason`, `shelf_price`, and the shop's `sync_shelf` row.
   * *Chapter one adds:*
     * the Old Mill as a second working mill, disabled while the bandits
       hold it;
     * an authored preferred mill per shop (`flour_mill`), so Hollin's Cross
       truly depends on the Old Mill and falls back to Mara's when it's
       held;
     * `_food_reason` said aloud as barks and thoughts;
     * "sold out" and the live price on the trade row;
     * Mara reading her real stock aloud.
   * *How the player reads it:* an empty shelf, the Cross's runner in
     Mara's queue, sails that stop and start, and a shelf that refills the
     morning after.
2. **What the player does reaches rumours, and NPCs react.**
   * *Already exists:* witnesses, knowledge facts, gossip, `rumours.line`,
     "Heard any news?", volunteering, and departures.
   * *Chapter one adds:*
     * notice boards in Millbrook and Hollin's Cross (the system exists; the
       map has none);
     * real names for the bandits, so facts read "Hal Corbin" and not
       "Creature_22";
     * Aldric's alternative first line when he holds the fact.
3. **A threat is warned about before it arrives.**
   * *Already exists:* kin vendettas, justified journeys, departures news,
     the storyteller's RISING state, and `justified_line`.
   * *Chapter one adds:* one authored kin link (Hal ↔ Rook) and the notice
     board to read it on.
   * *Risk:* the storyteller's timing is emergent, so Rook may take days to
     come. The warning is guaranteed (it is news of a real departure). The
     arrival is not, and that is honest.

---

## 5. Known gaps chapter one runs into

These come from RULES.md "Known gaps". Phase 3 fixes or removes each one, and
moves it out of Known gaps.

| Gap | Where chapter one hits it |
|---|---|
| **Speed** is described as movement speed but read by nothing | Three long walks. The creator and sheet show Speed. |
| **Sneak** is trained but read by no rule | Beat 7 offers a sneak approach. Sneak should affect how far observers see you, as sneaking does (§11). |
| Sneak-attack damage applies even if the target has already seen you | Beat 7's sneak attack must only work on a target that hasn't seen you. |
| **Charisma counts twice in prices** | Beat 3 (Elowen's trade window and the flour price), and any shopping in Millbrook. |
| An **Athletics** rise adds +1 max stamina that the next recalculation removes | Sprinting the long roads trains Athletics. |
| **Acrobatics**, **Light Fingers**, **Alchemy** are neither trained nor read | Not used by chapter one, but shown on the sheet every time it opens. Phase 3 decides: implement simply, or hide until they do something. |
| The older pool-based level-up option is unused | The player levels up after the mill. Remove the dead option so the level-up page is the only path. |
| **Apprentice** birthsign's "weaker to magic"; descriptions missing bonuses | Apprentice isn't offered in the creator, but the five that are have their descriptions checked against what they give. |

---

## 6. Quest-format extensions chapter one needs

The current format (quests/README.md) can't express four of the beats. I'll
add these four and nothing else, and document each in quests/README.md:

1. **`"starts_on_new_game": true`**. The quest starts when the character is
   created (beat 2), so the journal is never empty and stage 0 always has an
   arrow.
2. **Stage `"on_enter"` actions**, using the dialogue grammar's ops
   (`set key=value`, `give`), plus one new op, **`enable <entity id>`**. It
   wakes the Old Mill's mill (beat 10) and sets flags such as Aldric's toll
   in the finale.
3. **`"chapter": {"number": 1, "next": "mirrormere_smugglers"}`**. This
   marks main-storyline quests. The journal groups them under *The Last
   Sheaf*, completing one shows the chapter card, and it starts or points to
   the next.
4. **Arrows for `talk` stages.** This is a fix, not a format change: a stage
   whose condition is `talk` points at that NPC, like `kill` and `fetch`
   already point at their targets.

Separately, the `.quest` files must win over the built-ins after character
creation (§1.7). Either `quests_content.load()` stops overwriting registered
quests, or the session re-applies the files after `GameState.new_game`. A
regression test will start a new game and assert that the file's stages are
the ones that run.

---

## 7. Tone: grounded

I've chosen **grounded**:
* People are tired, practical and short of bread.
* Any wit is dry and comes from who is speaking. The game never winks.
* Nobody explains the plot; they talk about their own work, their stock and
  their worries.
* Numbers in dialogue are the real numbers.

The existing comic flavour stays where it already lives: the fate die's
*"Tripped over a hen"* and the goat in the water-stained ledger. Main-quest
writing doesn't borrow it.

Two sample lines:

> **Elowen:** "Eight sacks a week, I sell. This week I've sold none, and it
> isn't for want of asking."

> **Mara the Mill Farmer:** "Sails don't turn on wind alone. They turn on
> wheat, and nobody's bringing me any."

---

## 8. Plan after approval

* **Phase 1.** Implement chapter one as in §3:
  * the format extensions in §6, documented in quests/README.md;
  * the quest-precedence fix and its test;
  * Old Mill retuning, real names, Continue on PLAY;
  * no FPS counter or stock HUD in PLAY;
  * the journal and README place names.
* **Phase 2.** Make the three loops in §4 visible, wired only to existing
  systems.
* **Phase 3.** Fix the gaps in §5. Each fix moves out of RULES.md "Known gaps"
  into its proper section, in the same commit.
* **Phase 4.** Move the non-combat checks onto the roll box and 3D dice:
  * lockpicking (beat 8);
  * persuasion, Charm & Luck and haggling;
  * being noticed while sneaking (beat 7).

  Today these use the corner `dice_animation` panel, or no dice at all. They
  must follow every rule in RULES.md §1.
* **Phase 5.** Thornback Cellar, if time allows.

Every visual change is verified with offscreen screenshots and sent for
review.
