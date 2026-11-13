# Multiplayer and local co-op

Choose **MULTIPLAYER** in the launcher. A party contains up to four characters
across any combination of computers and controllers: keyboard plus gamepad,
two or more gamepads, four network players, or mixed parties such as two plus
two. Every computer shows the whole party in one shared overhead view.

The host can also add **AI companions** to fill unused slots, including one
human with three bots. Normal **Play** still starts a single-player game with its existing character
creator, controls, quest rules and save slots.

## Form a party

1. For one computer, choose **Local co-op on this computer**. For network play,
   choose **Host LAN / Internet game**, select a port and name the party.
2. Other computers can **Refresh LAN games** and join a discovered host, or
   enter an IP address/hostname and TCP port with **Join by address**.
3. On each computer, choose a name, **head appearance**, race, class, birthsign,
   handedness and control device; press **Add local player** for each person.
   Each character needs a different head and each local player needs a different
   device. Use **Refresh controllers** after connecting pads.
4. Select an existing local character and **Apply changes** to edit it. Ready
   applies to all characters on that computer. A selection change clears lobby
   readiness. The host chooses **Start adventure** once everyone connected is
   ready. Characters enter with these appearances; there is no in-game co-op
   character-creation screen.

The host can resume a campaign before adding characters. Saved characters keep
their race, class and birthsign, while their name, head and controller assignment
can be changed in the lobby. Offline friends remain in the roster and do not
prevent the host from continuing alone. Rejoining from the same game installation
reclaims that installation's characters instead of creating replacements.
Keep `saves/.multiplayer-identity` on a joining machine to retain that identity.

## Play with bots

Host a local or network party, add your own character, then choose **Add AI
companion** for each empty slot you want filled. Bots count toward the four
character limit and require no keyboard, gamepad or other computer. Select a
bot in the roster to change its name, head, race, class and birthsign, or remove
it before starting. Their readiness is automatic; ready your human characters
and start as usual. A party still needs a human host character.

Companions follow a human leader in formation, use the game's navigator and
player collision, defend the nearby party with their own equipment, drink
their healing potions and help revive downed companions. They choose blades
at close range and bows or staves at a distance, taking clear shots, ammunition,
magicka, weapon quality and skills into account. They select a suitable healing
dose from their own inventory when injured, with individual preferences rather
than perfect efficiency. When every human is
down, rescue takes priority. They automatically consent to party map travel.
Humans choose conversations and quests; bots participate in the shared
adventure, receive their own rewards and advance their characters. Bot choices
and character progress persist in the campaign save, including when it is
resumed. All companion decisions run on the host. Normal single-player Play
keeps its existing behavior; use the local Multiplayer lobby for a bot party.

Each new campaign gives companions a fresh mix of courage, concentration,
thrift, sociability and fighting preferences. They react at different speeds,
occasionally miss an opening, aim imperfectly, and fall back when hurt or
exhausted. They notice enemies in their own vicinity with clear sight; when an
attacker disappears, they briefly search its last seen position. Familiar
weapons and spells, different following distances and occasional pauses give
each teammate habits. These choices vary as play continues. Campaign saves
keep their personalities and the progress of their random decisions, including
across map travel. Older campaigns acquire stable personalities when resumed.

To see a companion's personality, enter **`inspect`** in the console and click
the companion. The **Overview** shows **Companion personality**, including the
traits and preferences driving its decisions, healing and fallback habits,
typical reaction time and current task. Inspecting does not reroll its traits.

NPCs and companions with an available shield raise it during combat. Each
physical hit against a raised block makes a **d20 saving throw**, using Block,
Endurance and current stamina. Success reduces the hit; failure gives no block
reduction. A bow, torch or spell occupying that hand prevents shield use.
Spell and fire damage do not trigger a shield save. Companions put their
shields back on when changing from a bow to a one-handed weapon.

With **Luck 60 or more**, a blocking shield bearer also has a rare chance to
ricochet an incoming arrow or spell bolt from the front. This is a separate
**2d20 Luck save**: about **0.25%** at Luck 60, up to **5.25%** at Luck 100.
Success bounces the actual missile away before damage or burning effects;
it keeps flying and can hit another actor, including the original shooter.
Ordinary shield block saves still apply to physical hits when the Luck save
fails. The character sheet's Fortune page shows the current ricochet chance.

Only human characters' own rolls animate, when dice animations are enabled.
NPC and companion rolls, including shield saves and NPC casting checks, appear
in the rolling log without replacing the player's roll. Multiplayer clients
receive the log and their character's dice animation from the host.

The host can enable **Respawn at village** in the lobby before starting.
After three seconds downed, an AI companion respawns at the map's starting
location with restored health, stamina and magicka, then follows the road
network back to the human party, navigating around obstacles on each road leg.
Returning companions travel outside the shared camera boundary until they
rejoin. The option and companions still returning are kept in campaign saves.
With the option off, companions use the usual revive and party checkpoint flow.

A running party with a free character slot accepts direct joins. New players
choose their characters and ready up in the lobby before entering. Started games
are no longer advertised in the LAN browser.

## Travelling together

Caves and other map exits move the whole party. When a player uses an exit,
everyone is asked to join; AI companions agree at once. Each human joins by
pressing interact at an exit, or anywhere with nothing else in reach. While the
party gathers, interact still talks to people, loots and revives companions
when one is in reach, so a pending trip never locks a player out of the game.
The party travels once every connected, conscious member has joined.

## Network and firewall setup

| Purpose | Default |
| --- | --- |
| Hosting and game traffic | TCP 39745; configurable when hosting |
| LAN discovery | UDP 39744 |
| Internet joining | A friend code from the host (or a typed host IP[:port]) |

Network services are dormant during launcher construction and ordinary Play.
Showing Multiplayer starts LAN discovery; hosting starts the TCP listener.
Returning to the launcher closes discovery, connections and listening sockets.
Starting an adventure transfers the existing connection to the game.
Local/AI parties and direct joining remain available if LAN discovery cannot
start, including when the computer has no usable LAN connection.

The operating system may ask for firewall access when Multiplayer is first
opened or a network game is hosted. MiniWind does not install firewall rules or
request administrator privileges. Allow the game on the network you use.

**Friend codes.** Host game shows a code (`XXXXX-XXXXX-XXXXX`, Copy code);
friends paste it into Join. The code is the address -- the host's public IPv4
address, the party's TCP port and a random invitation, with a check character
-- so there is no server to look anything up on. To find the address, hosting
asks the router by UPnP (which also forwards the port for the party's
lifetime, and removes it on leaving), then a STUN server (`[Multiplayer]
stun_server`, default `stun.l.google.com:19302`; empty disables it), then
falls back to the LAN address. `[Multiplayer] upnp = false` skips the router
and `[Multiplayer] port` sets the TCP port (default 39745). When the router
does not forward the port, the host forwards TCP 39745 by hand, or uses a VPN.
A joiner from outside the host's network must present the code's invitation;
New code rotates it. There is still no public directory or relay server.

**Late arrival** (host, in the lobby; on by default) lets players join while
the adventure runs. Off, a newcomer after Start is refused with "Game has
already started and does not allow late arrival".

**Testing with real instances.** `game/tools/mp_instances.py` runs a host and
up to three clients as separate game processes on one machine: they join by
friend code, make characters, ready up, play and walk, and each writes what it
saw (every member's position) and a screenshot. `--late-client` adds a
player after Start, `--no-late-arrival` closes the party at Start (that player
must be refused), `--bad-code` tries a stale code first:

    xvfb-run -a python -m game.tools.mp_instances --out /tmp/mp --clients 2 --bad-code --late-client

All players need matching gameplay code, quest/data content and installed
destination maps; procedural level-generation exits are unavailable in co-op.
The handshake rejects incompatible builds before joining. Packaged
Windows, macOS and Linux builds generated from the same revision share a
compatibility manifest; a source checkout computes its signature from live files.
When freezing manually, run `python tools/multiplayer_build_manifest.py` first
and include `game/data` in the distribution.

## During play

Each character has separate health, magicka, stamina, equipment, inventory,
skills, spells, factions, crime history and progression. The host runs combat,
AI, loot and quest decisions; other computers send actions for their own
characters. Friendly fire between party characters is disabled.

The camera fits the connected party. Movement at its outer boundary stops so
the group stays on screen. Ordinary menus and conversations keep the world
running; each computer displays one expanded character panel at a time. Opening
another local character's panel transfers that panel's control to its owner.
The host can explicitly pause or resume the party with **F10**, or hold Back
and press Start on a host-assigned gamepad.

With keyboard and mouse, **W/S** move forward/backward relative to the direction
the character faces; **A/D** strafe left/right relative to that facing.
The pointer controls facing. Combat and RPG shortcuts are unchanged. For
gamepads, the left stick moves and the right stick aims; LT/RT operate the two
hands, X attacks, B holds block, A interacts, Y opens the character panel, Back
opens the map and Start opens the local game menu. D-pad navigates menus, A
selects, B returns, and LB/RB switch RPG pages. Bindings remain configurable.
Movement stops for a disconnected controller without taking over another
player's device. Reconnecting the same controller type can reclaim its assignment;
with identical pads, reconnect them one at a time to preserve their order.

Hold interact beside a downed companion for three seconds to revive them with
partial health. If every connected character falls and village respawning is
off, the host restores the last checkpoint. Map exits gather readiness from the
living, connected party; press
interact when ready. Same-map portals carry the party together.

## Quests and saves

Adventure quests share acceptance, stages and objectives. Kills, conversations
and discoveries count once by world identity. Fetch requirements can be met
across the party's inventories; an unsuccessful compound hand-in rolls back
items, quest state and rewards together. Critical authored quest items can live
in the shared quest pouch, so disconnecting their finder does not block progress.

Eligible campaign characters receive their own authored rewards once, including
characters temporarily offline. Late arrivals join active adventures and do not
receive rewards for quests already finished before they arrived. Guild admission
and other personal quests keep separate progress.

The host owns the campaign. Co-op slots, autosaves and the latest exit save use
`saves/coop_<campaign-id>_*.fiosave`; they do not overwrite ordinary single-player
slots. A save retains the whole roster, personal characters, party journal,
reward receipts and world state. The host may load a slot on the current map
with the current roster in place, keeping the connections. To restore a save
with a different map or roster, quit, relaunch and select it in the launcher lobby.

**Copy a solo save** creates a separate campaign, preserving the original
character and quest progress without modifying the source file. Co-op saves use
the version 4 party extension; single-player games continue writing version 3.
Co-op saves reopen through Multiplayer. There is no host migration: if the host
leaves, clients stop and can rejoin when that host resumes the campaign.

## Authoring and verification

`.quest` definitions default to `"coop_scope": "party"`. Mark character-specific
admission quests with `"coop_scope": "personal"`. Use
`"coop_shared_items": ["item_id"]` for critical party-owned items. Ordinary
single-player quest interpretation is unchanged. Existing `quest.*` map-script
values resolve against the active campaign's isolated store during co-op.

Automated coverage includes four-character runtime handoff, independent input,
controller disconnects, AI companion following/combat/revives, live menus, quest transactions/reward receipts,
checkpoint rollback, save/resume, late joins/reconnects, real loopback TCP
ownership checks, bounded framing, content compatibility and lazy launcher
network lifecycle. Actual controllers, rendered OpenGL play and a connection
between separate Internet hosts still require desktop playtesting.
