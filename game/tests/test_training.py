"""Trainers and tutors: a trainer's rank caps what it can teach, nobody trains
more than five times a level, spells are bought by rarity and the Arcane
Circle's rarer spells need standing in it (game/rpg/training.py)."""

from ..rpg import guilds, magic, skills as sk, training
from ..rpg.character import Character

JOURNEYMAN_OCCULT = {"trainer": {"skills": ["occult", "conjuration"], "rank": "Journeyman"}}


def _mage(gold=10000):
    c = Character.create("T", "breton", "necromancer", "none")
    c.gold = gold
    return c


def test_what_an_npc_offers():
    assert training.trainer_of(JOURNEYMAN_OCCULT) == {"skills": ["occult"], "rank": 50}
    assert training.trainer_of({"trainer": {"skill": "defensive", "rank": 80}})["rank"] == 80
    assert training.trainer_of({"trainer": {"skills": ["juggling"]}}) is None
    assert not training.is_trainer({}) and not training.is_tutor({})
    tutor = {"teaches_spells": ["frostbite", "sp_woad", "no_such_spell", "frostbite"]}
    assert [s.id for s in training.spells_taught(tutor)] == ["frostbite"]   # no powers


def test_a_session_raises_a_skill_one_point_for_gold_and_counts_as_earned():
    c = _mage()
    c.skills[sk.OCCULT] = 30
    progress, gold = c.xp_progress, c.gold
    r = training.train(c, JOURNEYMAN_OCCULT, sk.OCCULT)
    assert r["ok"] and r["level"] == 31 and c.skills[sk.OCCULT] == 31
    assert c.gold == gold - (training.TRAIN_PRICE_BASE + training.TRAIN_PRICE_PER_POINT * 30)
    assert c.xp_progress == progress + 1           # Occult is a Necromancer's major
    assert c.trained_this_level == 1
    assert c.pop_skill_raises()[-1] == (sk.OCCULT, 31)


def test_a_trainer_cannot_teach_past_its_own_rank():
    c = _mage()
    c.skills[sk.OCCULT] = 49
    assert training.train(c, JOURNEYMAN_OCCULT, sk.OCCULT)["ok"]
    r = training.train(c, JOURNEYMAN_OCCULT, sk.OCCULT)
    assert not r["ok"] and r["reason"] == "beyond" and c.skills[sk.OCCULT] == 50
    assert training.explain("beyond")


def test_five_sessions_a_level_then_none_until_the_next():
    c = _mage()
    c.skills[sk.OCCULT] = 5
    for _ in range(training.SESSIONS_PER_LEVEL):
        assert training.train(c, JOURNEYMAN_OCCULT, sk.OCCULT)["ok"]
    assert training.train(c, JOURNEYMAN_OCCULT, sk.OCCULT)["reason"] == "sessions"
    assert training.sessions_left(c) == 0
    assert Character.from_dict(c.to_dict()).trained_this_level == training.SESSIONS_PER_LEVEL
    c.xp_progress = 10
    c.level_up()
    assert training.sessions_left(c) == training.SESSIONS_PER_LEVEL
    assert training.train(c, JOURNEYMAN_OCCULT, sk.OCCULT)["ok"]


def test_no_gold_no_lesson_and_nothing_is_taken():
    c = _mage(gold=3)
    before = c.skills[sk.OCCULT]
    r = training.train(c, JOURNEYMAN_OCCULT, sk.OCCULT)
    assert r["reason"] == "gold" and c.gold == 3 and c.skills[sk.OCCULT] == before


def test_the_price_function_is_the_merchants():
    c = _mage()
    c.skills[sk.OCCULT] = 10
    r = training.train(c, JOURNEYMAN_OCCULT, sk.OCCULT, price_of=lambda base: base * 2)
    assert r["price"] == 2 * (training.TRAIN_PRICE_BASE + training.TRAIN_PRICE_PER_POINT * 10)


def test_a_warrior_is_turned_away_from_magic_but_not_from_steel():
    w = Character.create("W", "nord", "warrior", "none")
    w.gold = 1000
    assert training.train(w, JOURNEYMAN_OCCULT, sk.OCCULT)["reason"] == "warrior"
    blade = {"trainer": {"skills": ["blade"], "rank": 75}}
    assert training.train(w, blade, sk.BLADE)["ok"]
    tutor = {"teaches_spells": ["flare"]}
    assert training.learn(w, tutor, "flare")["reason"] == "warrior"
    assert "flare" not in w.known_spells


def test_a_spell_is_bought_by_rarity_and_known_at_once():
    c = _mage()
    tutor = {"teaches_spells": ["frostbite", "summon_wolf"]}
    gold = c.gold
    r = training.learn(c, tutor, "frostbite")
    assert r["ok"] and "frostbite" in c.known_spells
    assert c.gold == gold - training.SPELL_PRICES[magic.get("frostbite").rarity]
    assert training.learn(c, tutor, "frostbite")["reason"] == "known"
    assert training.learn(c, tutor, "firebolt")["reason"] == "not_taught"


def test_the_circle_asks_standing_for_its_rarer_spells_and_rewards_study():
    c = _mage()
    circle = {"guild": "mages",
              "teaches_spells": ["sp_detect", "summon_wolf", "disintegrate"]}
    # A stranger may buy the common spell, but not the rare one.
    assert training.learn(c, circle, "summon_wolf")["reason"] == "standing"
    assert training.standing_note(circle, magic.get("summon_wolf")) == "Circle: Associate"
    full = training.spell_price(c, circle, magic.get("sp_detect"))
    assert training.learn(c, circle, "sp_detect")["ok"]
    assert guilds.join(c, "mages")
    assert training.spell_price(c, circle, magic.get("summon_wolf")) < \
        training.SPELL_PRICES[magic.get("summon_wolf").rarity]
    assert full == training.SPELL_PRICES["common"]
    assert training.learn(c, circle, "summon_wolf")["ok"]
    # Epic needs a Journeyman of the Circle (rank 2): study earns it.
    assert training.learn(c, circle, "disintegrate")["reason"] == "standing"
    st = guilds.standing(c, "mages")
    assert st["reputation"] == training.SPELL_REPUTATION["rare"]
    guilds.add_reputation(c, "mages", 20)
    assert training.learn(c, circle, "disintegrate")["ok"]


def test_an_independent_tutor_asks_no_standing():
    c = _mage()
    witch = {"teaches_spells": ["disintegrate"]}
    assert training.rank_needed(witch, magic.get("disintegrate")) == -1
    assert training.learn(c, witch, "disintegrate")["ok"]


def test_rarer_spells_cost_a_fortune():
    prices = [training.SPELL_PRICES[r] for r in magic.RARITIES]
    assert prices == sorted(prices)
    assert training.SPELL_PRICES["legendary"] >= 2000       # thousands, not hundreds


def test_the_worlds_teachers_come_from_the_data_file_and_authoring_wins():
    mara = {"name": "Mara", "display_name": "Mara"}
    assert training.is_trainer(mara) and training.is_tutor(mara)
    assert training.guild_of(mara) == training.ARCANE_CIRCLE
    # A warrior has somewhere to train too.
    grunn = training.trainer_of({"name": "Grunn"})
    assert sk.BLADE in grunn["skills"] and grunn["rank"] == 75
    authored = {"name": "Mara", "trainer": {"skills": ["sneak"], "rank": 10}}
    assert training.trainer_of(authored) == {"skills": ["sneak"], "rank": 10}
    assert not training.is_trainer({"name": "nobody_at_all"})


def test_every_school_has_a_trainer_and_every_teacher_is_real():
    import json
    import os
    root = os.path.join(os.path.dirname(__file__), "..", "..")
    with open(os.path.join(root, "maps", "miniwind_world.json"), encoding="utf-8") as fh:
        names = {(t.get("properties") or {}).get("name") for t in json.load(fh)["things"]
                 if (t.get("properties") or {}).get("type") == "npc"}
    taught_skills, taught_spells = set(), set()
    for name, entry in training.teachers().items():
        assert name in names, f"{name} teaches but is not in the world"
        props = {"name": name}
        t = training.trainer_of(props)
        if "trainer" in entry:
            assert t is not None and len(t["skills"]) == len(entry["trainer"]["skills"]), name
            taught_skills.update(t["skills"])
        if "teaches_spells" in entry:
            assert len(training.spells_taught(props)) == len(set(entry["teaches_spells"])), name
            taught_spells.update(s.id for s in training.spells_taught(props))
    assert set(sk.SCHOOLS) <= taught_skills
    # Every spell the game ships can be learned from someone -- all but Wisp,
    # which only ever comes in Flare's place, and the racial powers.
    with open(os.path.join(root, "game", "data", "spells.json"), encoding="utf-8") as fh:
        shipped = {r["id"] for r in json.load(fh) if float(r.get("cost", 0)) > 0}
    assert shipped - {"wisp"} <= taught_spells


def test_the_editors_flat_fields_make_a_teacher():
    props = {"name": "new_teacher", "trainer_skills": "occult, Conjuration , block",
             "trainer_rank": "Expert", "teaches_spells": "flare, frostbite", "guild": "mages"}
    assert training.trainer_of(props) == {"skills": [sk.OCCULT, sk.BLOCK], "rank": 75}
    assert [s.id for s in training.spells_taught(props)] == ["flare", "frostbite"]
    assert training.guild_of(props) == training.ARCANE_CIRCLE
    assert training.trainer_of({"trainer_skills": "", "trainer_rank": "Master"}) is None
