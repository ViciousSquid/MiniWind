"""World frames as patches (game/multiplayer/delta.py)."""

from __future__ import annotations

import copy
import json
import random
import zlib

import pytest

from game.multiplayer import delta


def _world(n=2000, seed=1):
    rng = random.Random(seed)
    return {
        "type": "world", "sequence": 1, "map": "maps/miniwind_world.json",
        "players": {f"p{i}": {"pos": [rng.random() * 1000, 0.0, rng.random() * 1000],
                              "character": {"health": 110, "name": f"Player {i}"}} for i in range(4)},
        "entities": [{"id": f"thing{i}", "pos": [rng.random() * 9000, 64.0, rng.random() * 9000],
                      "props": {"name": f"Thing {i}", "health": 20, "sprite": "assets/x.png",
                                "color": [1.0, 0.5, 0.2]}} for i in range(n)],
        "clock": {"hour": 8.0, "day": 1},
    }


def _step(world, rng, moved=10):
    new = copy.deepcopy(world)
    new["sequence"] += 1
    new["clock"]["hour"] += 0.01
    for e in rng.sample(new["entities"], moved):
        e["pos"][0] += rng.uniform(-5, 5)
    return new


def _random_value(rng, depth=0):
    kind = rng.randrange(6 if depth < 4 else 3)
    if kind == 0:
        return rng.choice([None, True, False, 0, 1, 2.5, -7, "a", "bee", ""])
    if kind == 1:
        return rng.uniform(-1e6, 1e6)
    if kind == 2:
        return "".join(rng.choice("abcxyz") for _ in range(rng.randrange(6)))
    if kind == 3:
        return {f"k{rng.randrange(8)}": _random_value(rng, depth + 1) for _ in range(rng.randrange(5))}
    if kind == 4:
        return [_random_value(rng, depth + 1) for _ in range(rng.randrange(5))]
    ids = rng.sample(range(20), rng.randrange(1, 8))
    return [{"id": f"e{i}", "v": _random_value(rng, depth + 1)} for i in ids]


def _mutate(rng, value, depth=0):
    if isinstance(value, dict) and value and depth < 5:
        out = dict(value)
        for key in rng.sample(list(out), max(1, len(out) // 2)):
            choice = rng.randrange(4)
            if choice == 0:
                del out[key]
            elif choice == 1:
                out[key] = _random_value(rng)
            else:
                out[key] = _mutate(rng, out[key], depth + 1)
        if rng.random() < 0.3:
            out[f"new{rng.randrange(9)}"] = _random_value(rng)
        return out
    if isinstance(value, list) and value and depth < 5:
        out = [_mutate(rng, v, depth + 1) if rng.random() < 0.4 else v for v in value]
        if rng.random() < 0.3:
            out.pop(rng.randrange(len(out)))
        if rng.random() < 0.3:
            out.append(_random_value(rng))
        if rng.random() < 0.2:
            rng.shuffle(out)
        return out
    return _random_value(rng)


def test_any_change_round_trips_exactly_and_through_json():
    rng = random.Random(7)
    for _ in range(600):
        old = {"root": _random_value(rng)}
        new = _mutate(rng, old)
        before = copy.deepcopy(old)
        patch = delta.diff(old, new)
        wire = json.loads(json.dumps(patch))                 # it travels as JSON
        rebuilt = delta.apply(json.loads(json.dumps(old)), wire)
        assert rebuilt == json.loads(json.dumps(new))
        assert old == before                                 # never changed
        if old == new:
            assert patch is None


def test_entities_travel_by_id_and_a_world_frame_shrinks_a_thousandfold():
    rng = random.Random(3)
    a = _world()
    b = _step(a, rng)
    patch = delta.diff(a, b)
    assert patch[0] == "d" and patch[1]["entities"][0] == "l"
    assert len(patch[1]["entities"][1]) == 10                # only the ten that moved
    full = len(zlib.compress(json.dumps(b).encode(), 6))
    small = len(zlib.compress(json.dumps(patch).encode(), 6))
    assert small * 50 < full
    assert delta.apply(a, patch) == b


def test_removed_and_new_entities_and_a_reordered_list():
    a = {"entities": [{"id": "a", "v": 1}, {"id": "b", "v": 2}, {"id": "c", "v": 3}]}
    b = {"entities": [{"id": "a", "v": 1}, {"id": "c", "v": 4}, {"id": "d", "v": 5}]}
    patch = delta.diff(a, b)
    assert patch[1]["entities"][2] == ["b"] and patch[1]["entities"][3] == [{"id": "d", "v": 5}]
    assert delta.apply(a, patch) == b
    shuffled = {"entities": [{"id": "c", "v": 3}, {"id": "a", "v": 1}, {"id": "b", "v": 2}]}
    assert delta.diff(a, shuffled) == ["d", {"entities": ["=", shuffled["entities"]]}, []]


def test_a_bad_patch_is_refused():
    with pytest.raises(ValueError):
        delta.apply({"a": 1}, ["?", 1])
    with pytest.raises(ValueError):
        delta.apply([1, 2], ["d", {}, []])


def test_sender_and_receiver_agree_frame_after_frame():
    rng = random.Random(5)
    sender, receiver = delta.FrameSender(), delta.FrameReceiver()
    world = _world(300)
    first = sender.make(world)
    assert first["base"] == 0 and "full" in first
    got, fid = receiver.take(json.loads(json.dumps(first)))
    assert got == world
    sender.ack(fid)
    for _ in range(30):
        world = _step(world, rng, 5)
        packet = json.loads(json.dumps(sender.make(world)))
        assert packet["base"] and "patch" in packet
        got, fid = receiver.take(packet)
        assert got == world
        sender.ack(fid)


def test_the_game_gets_a_private_copy():
    receiver = delta.FrameReceiver()
    got, _fid = receiver.take({"type": "_frame", "id": 1, "base": 0,
                               "full": {"type": "world", "pos": [1, 2, 3]}})
    got["pos"][0] = 99                       # the game moves things about
    assert receiver.frames[1]["pos"][0] == 1


def test_old_frames_and_unknown_baselines_are_ignored():
    receiver = delta.FrameReceiver()
    receiver.take({"type": "_frame", "id": 5, "base": 0, "full": {"type": "world"}})
    assert receiver.take({"type": "_frame", "id": 4, "base": 0, "full": {"type": "world"}}) == (None, 4)
    assert receiver.take({"type": "_frame", "id": 9, "base": 7, "patch": None}) == (None, 9)


def test_one_patch_per_baseline_for_every_peer():
    cache = delta.PatchCache()
    a, b = _world(50), _world(50, seed=2)
    senders = [delta.FrameSender(cache) for _ in range(3)]
    for s in senders:
        s.ack(s.make(a)["id"])
    patches = [s.make(b)["patch"] for s in senders]
    assert patches[0] is patches[1] is patches[2]      # diffed once, shared
