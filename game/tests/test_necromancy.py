"""Necromancers raise the fallen to fight for them -- in any fight, and when a
cutscene orders a cast; cutscene rules' FLEE and spawned actors' arming."""
from .test_corpse_loot import _Thing, _Logic
from .test_sim import _FakeGlobals


def _session(*things):
    from ..runtime import MiniwindSession
    logic = _Logic(list(things))
    logic.player = _Thing("You", (5000.0, 0.0, 5000.0), is_player=True)
    s = MiniwindSession(logic, cfg={}, globals_store=_FakeGlobals())
    s.needs_char_creation = False
    s.game.dice = None
    s.rng.seed(1)
    return s


def _necromancer(**props):
    base = dict(type="npc", id="necro", npc_role="cultist", team="cultists", faction="cultists",
                spells=[{"id": "resurrection"}, {"id": "firebolt"}], magicka=500,
                max_magicka=500, health=60, max_health=60)
    base.update(props)
    return _Thing("Morwen", (0.0, 0.0, 0.0), **base)


def _body(x=200.0, **props):
    base = dict(type="creature", id=f"body{x}", npc_role="bandit", team="bandits",
                faction="bandits", dead=True, health=0, max_health=50)
    base.update(props)
    return _Thing("Brigand", (x, 0.0, 0.0), **base)


def test_a_necromancer_raises_the_nearest_fallen_to_fight_for_it(monkeypatch):
    import game.npc_magic as npc_magic
    monkeypatch.setattr(npc_magic.NpcMagic, "_fizzles", lambda self, t, s: False)
    necro, near, far = _necromancer(_aggro_target=12345), _body(200.0), _body(5000.0)
    s = _session(necro, near, far)
    assert s.npc_magic.try_raise(necro)
    p = near.properties
    assert not p["dead"] and p["health"] == 50
    assert p["team"] == "cultists" and p["resurrection_used"] and p["resurrected_by"] == "necro"
    assert p["_aggro_target"] == 12345                   # straight at its master's foe
    assert far.properties["dead"]                        # out of reach
    assert not s.npc_magic.try_raise(necro)              # nothing else within reach


def test_only_a_necromancer_raises_and_never_a_body_raised_once(monkeypatch):
    import game.npc_magic as npc_magic
    monkeypatch.setattr(npc_magic.NpcMagic, "_fizzles", lambda self, t, s: False)
    plain = _necromancer(spells=[{"id": "firebolt"}])
    used = _body(100.0, resurrection_used=True)
    s = _session(plain, used)
    assert not s.npc_magic.try_raise(plain)
    necro = _necromancer(id="necro2")
    s.logic.things.append(necro)
    assert not s.npc_magic.try_raise(necro)              # that body had its second life


def test_an_ordered_cast_flies_the_named_spell_at_its_target(monkeypatch):
    import game.npc_magic as npc_magic
    monkeypatch.setattr(npc_magic.NpcMagic, "_fizzles", lambda self, t, s: False)
    flown = []
    monkeypatch.setattr(npc_magic.NpcMagic, "_loose",
                        lambda self, thing, target, pos, spell, *a: flown.append((thing, target, spell.id)))
    necro = _necromancer()
    foe = _Thing("Guard", (300.0, 0.0, 0.0), type="npc", id="g", health=100)
    s = _session(necro, foe)
    assert s.cutscene_cast(necro, "firebolt", foe) == []
    assert flown == [(necro, foe, "firebolt")]
    assert s.cutscene_cast(necro, "lightning", foe) == [] and len(flown) == 1   # not its spell


def test_a_cutscene_flee_runs_for_refuge_on_the_games_own_legs(monkeypatch):
    from ..rpg import schedule as sched
    actor = _Thing("Coward", (0.0, 0.0, 0.0), type="npc", id="c", home=[900.0, 0.0, 0.0],
                   _aggro_target=99, awake=True, triggered=False)
    threat = _Thing("Ogre", (50.0, 0.0, 0.0), type="creature", id="o")
    s = _session(actor, threat)
    s.cutscene_flee(actor, threat)
    p = actor.properties
    assert p["sched_state"] == sched.FLEE and p["_flee"] and p["triggered"] and "_aggro_target" not in p
    moved = []
    monkeypatch.setattr(s, "_move", lambda npc, dt: moved.append(npc))
    s.cutscene_tick(0.1)
    assert moved == [actor]


def test_actors_a_cutscene_spawns_are_armed_as_a_maps_are(monkeypatch):
    s = _session()
    ran = []
    monkeypatch.setattr(s, "_arm_fighters", lambda: ran.append("arm"))
    monkeypatch.setattr(s, "_assign_npc_handedness", lambda: ran.append("hand"))
    monkeypatch.setattr(s, "_assign_npc_stats", lambda: ran.append("stats"))
    s.prepare_cutscene_actors([])
    assert set(ran) == {"arm", "hand", "stats"}
