"""
Generate the Miniwind starter world: ``maps/Miniwind.json``.

Builds a small but complete open-world slice on top of the shipped, known-good
top-down demo terrain: the village of Miniwind (quest-givers, a merchant, a
blacksmith who trades, a guard, townsfolk on daily schedules), a wolf-haunted
pasture, the bandit-held Old Mill to the east (melee bandits **and** bow
archers — never guns), and a skeleton barrow. Quest flags, dialogue and the game
clock are all wired so the four starter quests are playable end to end.

Run from the repo root:  python -m game.tools.make_world
"""

from __future__ import annotations

import json
import os
import uuid


def _uid():
    return str(uuid.uuid4())


def _thing(ttype, pos, props, io=None):
    p = {"type": ttype, "name": props.get("name", ttype), "id": _uid()}
    p.update(props)
    return {"type": ttype, "pos": list(pos), "properties": p, "io_connections": io or []}


def _npc(name, role, pos, **extra):
    props = {"name": name, "display_name": name, "npc_role": role}
    props.update(extra)
    return _thing("npc", pos, props)


def build(base_path: str) -> dict:
    with open(base_path) as f:
        base = json.load(f)

    world = {
        "version": base.get("version", 3),
        "brushes": base.get("brushes", []),
        "terrain_data": base.get("terrain_data", {"enabled": True}),
        "things": [],
    }

    # keep player start, lights and the top-down camera command
    keep = {"playerstart", "light", "logiccommand"}
    for t in base.get("things", []):
        if str(t.get("type", "")).replace("_", "") in keep:
            world["things"].append(t)

    px, py, pz = 784.0, 272.0, -784.0  # near the player start

    def at(dx, dz):
        return [px + dx, py, pz + dz]

    # --- game settings + persistent quest store ---
    world["things"].append(_thing("miniwindsettings", at(0, -40), {
        "name": "MiniwindSettings", "start_hour": 8.0, "start_day": 1,
        "minutes_per_day": 16.0, "show_clock": True, "difficulty": "normal",
        "start_scenario": "prompt", "region_name": "The Vale of Miniwind",
        "state_store": "miniwind",
    }))
    world["things"].append(_thing("logic_keyvalue", at(40, -40), {
        "name": "miniwind", "store_name": "miniwind", "initial_data": {},
    }))

    # ================================================================ VILLAGE
    # Aldric — the village elder, gives the mill quest.
    aldric_dialogue = {
        "start": "g",
        "nodes": {
            "g": {"text": "Welcome to Miniwind, traveller. We've little to spare "
                          "and much to fear these days.",
                  "responses": [
                      {"text": "What troubles the village?", "goto": "trouble"},
                      {"text": "I'm looking for work.", "goto": "quest",
                       "condition": {"key": "quest.mill_bandits.state", "not_equals": "active"}},
                      {"text": "The mill is cleared.", "goto": "reward",
                       "condition": {"key": "quest.mill_bandits.stage", "equals": "10"}},
                      {"text": "(Persuade)", "goto": "g", "actions": [{"op": "persuade"}]},
                      {"text": "Farewell.", "goto": "END"},
                  ]},
            "trouble": {"text": "Bandits hold the old mill east of here, and wolves "
                                "harry Bryn's flock. We are afraid to walk our own roads.",
                        "responses": [{"text": "Perhaps I can help.", "goto": "g"}]},
            "quest": {"text": "Then clear the bandits from the old mill, and Miniwind "
                              "will be in your debt — and pay you besides.",
                      "on_enter": [{"op": "start_quest", "quest": "mill_bandits"}],
                      "responses": [{"text": "Consider it done.", "goto": "END"}]},
            "reward": {"text": "You cleared the mill? By the Eight — you have my thanks, "
                               "and your reward. Take this blade and this purse.",
                       "on_enter": [{"op": "complete_quest", "quest": "mill_bandits"}],
                       "responses": [{"text": "A pleasure.", "goto": "END"}]},
        },
    }
    world["things"].append(_npc("Aldric", "villager", at(-40, 120),
                                home=at(-120, 120), work_location=at(0, 40),
                                dialogue=aldric_dialogue, disposition_base=55))

    # Bryn — shepherd, wolves quest.
    bryn_dialogue = {
        "start": "g",
        "nodes": {
            "g": {"text": "Cursed wolves have taken three sheep this week alone!",
                  "responses": [
                      {"text": "I'll thin the pack for you.", "goto": "quest",
                       "condition": {"key": "quest.wolves.state", "not_equals": "active"}},
                      {"text": "The wolves are dealt with.", "goto": "reward",
                       "condition": {"key": "quest.wolves.stage", "equals": "10"}},
                      {"text": "Good luck with that.", "goto": "END"},
                  ]},
            "quest": {"text": "Would you? Kill five of the beasts and I'll see you "
                              "well paid — and lend you my old bow.",
                      "on_enter": [{"op": "start_quest", "quest": "wolves"}],
                      "responses": [{"text": "Five wolves. Done.", "goto": "END"}]},
            "reward": {"text": "My flock can graze in peace again. Here's your coin, "
                               "and keep the bow — you've earned it.",
                       "on_enter": [{"op": "complete_quest", "quest": "wolves"}],
                       "responses": [{"text": "Much obliged.", "goto": "END"}]},
        },
    }
    world["things"].append(_npc("Bryn", "farmer", at(-260, -120),
                                home=at(-320, -120), work_location=at(-420, -260),
                                dialogue=bryn_dialogue, disposition_base=50))

    # Borin — blacksmith / merchant (trade).
    world["things"].append(_npc("Borin", "blacksmith", at(120, 60),
                                home=at(160, 100), work_location=at(120, 60),
                                merchant=True, merchant_gold=400,
                                stock=["iron_longsword", "iron_mace", "steel_longsword",
                                       "iron_shield", "iron_cuirass", "iron_helmet",
                                       "short_bow", "long_bow", "iron_arrow", "steel_arrow",
                                       "repair_hammer"],
                                dialogue={"start": "g", "nodes": {"g": {
                                    "text": "Steel and sweat, friend. Care to trade?",
                                    "responses": [
                                        {"text": "Let's trade.", "goto": "END",
                                         "actions": [{"op": "open_trade"}]},
                                        {"text": "Just looking.", "goto": "END"}]}}}))

    # Elowen — general merchant, lost-amulet quest.
    elowen_dialogue = {
        "start": "g",
        "nodes": {
            "g": {"text": "Potions, provisions, oddments — what do you need?",
                  "responses": [
                      {"text": "Let's trade.", "goto": "END", "actions": [{"op": "open_trade"}]},
                      {"text": "You seem troubled.", "goto": "quest",
                       "condition": {"key": "quest.lost_amulet.state", "not_equals": "active"}},
                      {"text": "I found your amulet.", "goto": "reward",
                       "condition": {"key": "quest.lost_amulet.stage", "equals": "10"}},
                      {"text": "Good day.", "goto": "END"},
                  ]},
            "quest": {"text": "I lost my grandmother's silver amulet gathering herbs in "
                              "the western wood. If you should find it...",
                      "on_enter": [{"op": "start_quest", "quest": "lost_amulet"}],
                      "responses": [{"text": "I'll keep an eye out.", "goto": "END"}]},
            "reward": {"text": "My amulet! Oh, thank you — thank you! Please, take this "
                               "for your trouble.",
                       "on_enter": [{"op": "complete_quest", "quest": "lost_amulet"}],
                       "responses": [{"text": "Take care of it.", "goto": "END"}]},
        },
    }
    world["things"].append(_npc("Elowen", "merchant", at(60, 140),
                                home=at(100, 180), work_location=at(60, 140),
                                merchant=True, merchant_gold=300,
                                stock=["potion_heal_minor", "potion_heal", "potion_magicka",
                                       "potion_stamina", "potion_cure", "lockpick", "torch",
                                       "book_marksman", "book_blade"],
                                dialogue=elowen_dialogue, disposition_base=50))

    # Grunn — Fighters Guild, barrow quest + join.
    grunn_dialogue = {
        "start": "g",
        "nodes": {
            "g": {"text": "The Fighters Guild always needs strong arms. Prove yourself.",
                  "responses": [
                      {"text": "How do I prove myself?", "goto": "quest",
                       "condition": {"key": "quest.fighters_join.state", "not_equals": "active"}},
                      {"text": "The barrow is cleared.", "goto": "reward",
                       "condition": {"key": "quest.fighters_join.stage", "equals": "10"}},
                      {"text": "Later.", "goto": "END"},
                  ]},
            "quest": {"text": "Clear the skeletons from the barrow to the north. Do that, "
                              "and you're one of us.",
                      "on_enter": [{"op": "start_quest", "quest": "fighters_join"}],
                      "responses": [{"text": "I'll clear it.", "goto": "END"}]},
            "reward": {"text": "The barrow's quiet again? Then welcome to the Fighters "
                               "Guild. You've earned your place.",
                       "on_enter": [{"op": "complete_quest", "quest": "fighters_join"},
                                    {"op": "join_guild", "guild": "fighters"}],
                       "responses": [{"text": "An honour.", "goto": "END"}]},
        },
    }
    world["things"].append(_npc("Grunn", "guard", at(200, 20),
                                home=at(220, 20), work_location=at(200, 20),
                                aggression="defensive", display_name="Grunn",
                                dialogue=grunn_dialogue, disposition_base=45))

    # Town guard + a couple of townsfolk with lives.
    world["things"].append(_npc("Gate Guard", "guard", at(20, 300),
                                aggression="defensive", home=at(20, 300),
                                work_location=at(20, 300),
                                dialogue={"start": "g", "nodes": {"g": {
                                    "text": "Keep the peace and we'll have no trouble.",
                                    "responses": [{"text": "Understood.", "goto": "END"}]}}}))
    world["things"].append(_npc("Old Mira", "beggar", at(-60, 200),
                                home=at(-60, 200),
                                dialogue={"start": "g", "nodes": {"g": {
                                    "text": "Spare a coin for an old woman?",
                                    "responses": [{"text": "Here you are.", "goto": "END"},
                                                  {"text": "Not today.", "goto": "END"}]}}}))

    # ============================================================== WILDLIFE
    for i, (dx, dz) in enumerate([(-420, -320), (-500, -260), (-360, -400),
                                  (-540, -360), (-460, -440)]):
        world["things"].append(_npc(f"Wolf {i+1}", "wolf", at(dx, dz),
                                    home=at(dx, dz)))
    world["things"].append(_npc("Bear", "bear", at(-620, -520), home=at(-620, -520)))

    # ============================================================== OLD MILL
    # bandits (melee) + archers (bow) — the fantasy fix for "monsters shooting me".
    mill = (720, 780)
    for i, (dx, dz) in enumerate([(0, 0), (80, 40), (-60, 60), (40, -40)]):
        world["things"].append(_npc(f"Bandit {i+1}", "bandit",
                                    at(mill[0] + dx, mill[1] + dz),
                                    home=at(mill[0] + dx, mill[1] + dz)))
    for i, (dx, dz) in enumerate([(120, 120), (-100, 140)]):
        world["things"].append(_npc(f"Bandit Archer {i+1}", "bandit_archer",
                                    at(mill[0] + dx, mill[1] + dz),
                                    home=at(mill[0] + dx, mill[1] + dz)))
    world["things"].append(_npc("Bandit Chief", "bandit_chief",
                                at(mill[0], mill[1] + 60),
                                home=at(mill[0], mill[1] + 60),
                                # the amulet quest item drops here
                                inventory=[{"id": "silver_amulet", "name": "Silver Amulet",
                                            "type": "quest", "qty": 1, "value": 60, "weight": 0.2,
                                            "description": "Elowen's grandmother's amulet."}]))

    # ================================================================ BARROW
    barrow = (-40, 720)
    for i, (dx, dz) in enumerate([(0, 0), (60, 40), (-60, 40), (30, 90), (-30, 90)]):
        role = "skeleton_archer" if i % 3 == 2 else "skeleton"
        world["things"].append(_npc(f"Skeleton {i+1}", role,
                                    at(barrow[0] + dx, barrow[1] + dz),
                                    home=at(barrow[0] + dx, barrow[1] + dz)))
    world["things"].append(_npc("Barrow Wight", "wraith",
                                at(barrow[0], barrow[1] + 130),
                                home=at(barrow[0], barrow[1] + 130)))

    return world


def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    # Terrain base is bundled with the game (self-contained — no example map
    # dependency), so the RPG branch ships without Fio's demo maps.
    base = os.path.join(os.path.dirname(__file__), "data", "base_terrain.json")
    out = os.path.join(root, "maps", "Miniwind.json")
    world = build(base)
    with open(out, "w") as f:
        json.dump(world, f, indent=2)
    print(f"wrote {out} with {len(world['things'])} things")


if __name__ == "__main__":
    main()
