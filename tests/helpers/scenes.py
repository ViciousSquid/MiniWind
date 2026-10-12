"""Small, complete maps built in code, for tests that need a whole level.

Fio's suite drives several of its tests through its example maps
(``_SHOWCASE.json``, ``Portal_Test.json``, ``MonsterTest.json`` ...). MiniWind
ships none of them, so those tests build the level they need here instead:
plain map dicts in the saved-file shape (``{"brushes": [...], "things":
[...]}``), each holding what the test relied on in the map it replaces, and
nothing taken from a file. :func:`write` puts one on disk for a test that
loads a map by path.

Everything is deterministic: names and ids come from
:func:`tests.helpers.worlds.stable_id`, and only assets MiniWind ships are
referenced.
"""

import json

from engine import brush_geometry as bg
from tests.helpers.worlds import angled_brush, box_brush, room, stable_id


def _thing(kind, name, pos, io=(), **props):
    """One saved entity record, as the editor writes it."""
    properties = {"type": kind, "name": name, "id": stable_id(name)}
    properties.update(props)
    return {"type": kind, "pos": [float(v) for v in pos],
            "properties": properties, "io_connections": [dict(c) for c in io]}


def _level(brushes, things, **extra):
    # Only what a saved map holds: runtime caches (``_geo_cache`` on a
    # clipped brush) are not map data.
    data = {"version": 3,
            "brushes": [{k: v for k, v in b.items() if not k.startswith("_")}
                        for b in brushes],
            "things": list(things)}
    data.update(extra)
    return data


def _light(name, pos, colour=(255, 240, 220)):
    return _thing("light", name, pos, color=list(colour), intensity=1.0,
                  radius=1024.0)


def _player_start(pos=(0, 64, 0), angle=0):
    return _thing("playerstart", "PlayerStart_1", pos, angle=angle)


def _path_loop(prefix, corners, y=64.0):
    """PathNodes visiting *corners* in a closed loop."""
    names = ["%s_%d" % (prefix, i + 1) for i in range(len(corners))]
    return [_thing("path_node", name, (x, y, z), radius=64,
                   next_node=names[(i + 1) % len(names)], wait_time=0, speed=1)
            for i, (name, (x, z)) in enumerate(zip(names, corners))]


def _portal(name, target, pos, angle, active=True):
    return _thing("portal", name, pos, portal_target=target, width=200,
                  height=256, rotation=[float(angle), 0.0, 0.0],
                  angle=float(angle), active=active, color=[255, 255, 255],
                  show_rim=False, portal_direction="both")


def _pickup(name, pos, item="gun1"):
    return _thing("prop", name, pos, carry_enabled=False, collect_enabled=True,
                  collect_type="item", collect_value=25,
                  collect_activation="walk_over", collect_collected=False,
                  collect_respawns=False, collect_respawn_time=20,
                  collect_item=item, sprite_path="assets/sprites/%s.png" % item)


# ---------------------------------------------------------------------------
# Scenes
# ---------------------------------------------------------------------------

def simple_room():
    """A closed room with a Player Start and two lights."""
    return _level(room(size=1024.0), [
        _player_start(),
        _light("Light_1", (-256, 192, -256)),
        _light("Light_2", (256, 192, 256)),
    ])


def monster_arena():
    """A room with a patrolling monster, a pickup, a level change and a
    logic_command: the parts of a level a Play session works through."""
    monster = _thing("monster", "Monster_1", (320, 64, 320), monster_type="human",
                     health=50, damage=10, awake=True, wake_on_sight=False,
                     sprite_width=128, sprite_height=192, sight=512,
                     patrol=True, patrol_target="PathNode_2", patrol_mode="loop",
                     variant="variant1")
    return _level(room(size=2048.0), [
        _player_start((0, 64, -640)),
        _light("Light_1", (-512, 192, -512)),
        _light("Light_2", (512, 192, 512)),
        monster,
        *_path_loop("PathNode", [(320, 320), (640, 320), (640, 640), (320, 640)]),
        _pickup("Prop_1", (-320, 32, 640)),
        _thing("levelchanger", "LevelChanger_1", (0, 0, 900), target_map="next",
               delay=0, fade_time=0.5, radius=128, usable=False),
        _thing("logic_command", "LogicCommand_1", (-640, 64, 640),
               command="notarget", disabled=False),
    ])


#: Where :func:`portal_pair` puts its two portals, facing each other's way
#: across an open floor (as Fio's Portal_Test.json does).
PORTAL_1 = (480.0, 224.0, -448.0)
PORTAL_2 = (1072.0, 224.0, -800.0)


def portal_pair():
    """Two linked, active portals, ``Portal_1`` and ``Portal_2``, on a floor."""
    floor = box_brush("floor", (544, -64, -704), (2560, 128, 2560))
    return _level([floor], [
        _player_start((992, 64, -928)),
        _light("Light_1", (544, 384, -704)),
        _portal("Portal_1", "Portal_2", PORTAL_1, 270),
        _portal("Portal_2", "Portal_1", PORTAL_2, 180),
    ])


def spawner_room():
    """A room with a LogicSpawner that sends monsters along a PathNode."""
    return _level(room(size=1024.0), [
        _player_start((0, 64, 320)),
        _light("Light_1", (0, 192, 0)),
        _thing("logic_spawner", "LogicSpawner_1", (-16, 48, -128),
               spawn_type="Monster", target_node="PathNode_1", max_spawn=0,
               spawn_properties={"random": True}),
        *_path_loop("PathNode", [(-256, -256), (256, -256)]),
        _pickup("Prop_1", (-352, 16, 368), item="gun2"),
    ])


def terrain_map(chunks=2, chunk_size=256.0):
    """A procedural terrain (``terrain_data``) with a Player Start above it."""
    terrain = {
        "enabled": True, "solid": True, "seed": 42, "biome": "Alpine Forest",
        "chunk_size": float(chunk_size), "mesh_scale": 1.0,
        "base_resolution": 48, "offset_x": 0.0, "offset_z": 0.0,
        "offset_y": 0.0, "min_chunk_x": -chunks, "max_chunk_x": chunks,
        "min_chunk_z": -chunks, "max_chunk_z": chunks, "use_textures": False,
        "flat_mode": False, "grass_enabled": False,
    }
    return _level([], [_player_start((0, 512, 0)),
                       _light("Light_1", (0, 768, 0))], terrain_data=terrain)


def showcase():
    """One of everything a full level carries, in one room.

    Brushes (room, pillars, a moving platform, and an angled, a water, a
    glass, a glow and a fog brush), lights, a Player Start, a
    monster on a patrol loop whose death opens a pair of portals, pickups,
    a model Prop, a speaker, a fire effect, logic_commands, a LogicCamera
    and a LogicSpawner.
    """
    brushes = room(size=4096.0, height=512.0)
    for ix in range(3):
        for iz in range(3):
            brushes.append(box_brush(
                "pillar_%d_%d" % (ix, iz), ((ix - 1) * 768, 128, (iz - 1) * 768),
                (96, 256, 96), textures={tag: "Dev/256.jpg" for tag in bg.FACE_TAGS}))
    brushes.append(box_brush("platform", (-1536, 32, 1536), (256, 32, 256),
                             is_mover=True, speed=64, distance=192,
                             direction=[0, 1, 0], start_on=True,
                             original_pos=[-1536, 32, 1536]))
    # One brush for each of the renderer's special passes.
    brushes += [
        angled_brush("ramp", (-768, 64, -768), (256, 128, 256),
                     clip_normal=(1.0, 1.0, 0.0)),
        box_brush("water", (1280, 32, -512), (512, 64, 512), shader="Water",
                  water_tint=[0.1, 0.4, 0.5], water_opacity=0.6),
        box_brush("glass", (-256, 128, 512), (32, 256, 384), shader="Glass",
                  glass_color=[0.9, 0.95, 1.0], glass_opacity=0.3,
                  glass_refraction=2.5, glass_fresnel=0.84),
        box_brush("glow", (0, 480, 0), (512, 32, 512), shader="Glow",
                  glow_intensity=10.0, glow_color=[0.02, 0.7, 0.7]),
        box_brush("fog", (-1280, 72, 512), (272, 144, 480), shader="Fog",
                  is_fog=True, fog_density=2.0, fog_color=[0.5, 0.6, 0.7]),
    ]
    monster = _thing(
        "monster", "Monster_1", (1024, 64, 1024), monster_type="human",
        health=50, damage=10, awake=True, sprite_width=128, sprite_height=192,
        sight=512, patrol=True, patrol_target="PathNode_1", patrol_mode="loop",
        variant="variant1",
        io=[{"output": "OnDeath", "target": "Portal_1", "input": "Enable",
             "parameter": "", "delay": 1.0, "fire_once": False,
             "target_id": stable_id("Portal_1")}])
    things = [
        _player_start((0, 64, -1536)),
        *[_light("Light_%d" % (i + 1), pos) for i, pos in enumerate(
            [(-1280, 384, -1280), (1280, 384, -1280), (-1280, 384, 1280),
             (1280, 384, 1280), (0, 448, 0)])],
        monster,
        *_path_loop("PathNode", [(1024, 1024), (1536, 1024), (1536, 1536)]),
        _pickup("Pickup_1", (-1024, 32, -1024), item="gun2"),
        _pickup("Pickup_2", (1024, 32, -1024), item="gun1"),
        # Two models in view of the Player Start, so they draw instanced as
        # a level's models do (one alone takes the single-model path).
        _thing("prop", "Tree_1", (-1024, 0, 512), render_mode="model",
               model_path="assets/models/LowPoly_Tree_v1.obj",
               rotation=[0.0, 0.0, 0.0], scale=[1, 1, 1], no_collision=True),
        _thing("prop", "Tree_2", (-1152, 0, 768), render_mode="model",
               model_path="assets/models/LowPoly_Tree_v1.obj",
               rotation=[0.0, 0.0, 0.0], scale=[1, 1, 1], no_collision=True),
        _thing("speaker", "Speaker_1", (-512, 128, 0),
               sound_file="assets/sounds/fireloop.mp3", radius=1024,
               volume=100, looping=True, play_on_start=True, state="on"),
        _thing("effect", "Effect_1", (512, 96, 0), effect_type="FIRE",
               fire_texture="assets/textures/effects/fire01.gif",
               width=128.0, height=192.0, intensity=1.5,
               colour=[255, 120, 60], light_enabled=True,
               light_radius=480.0),
        _thing("logic_command", "plat_message1", (-1536, 160, 1536),
               command='message "Ride the platform"', disabled=False),
        _thing("logic_camera", "LogicCamera_1", (0, 480, 1536),
               path_target="PathNode_1", speed=200, look_ahead=True),
        _thing("logic_spawner", "endboss_spawner", (0, 64, 1280),
               spawn_type="Monster", target_node="", max_spawn=1,
               spawn_properties={"random": False, "monster_type": "human"}),
        _portal("Portal_1", "Portal_2", (-1792, 128, 0), 90, active=False),
        _portal("Portal_2", "Portal_1", (1792, 128, 0), 270, active=False),
    ]
    return _level(brushes, things)


def write(directory, name, level):
    """Save *level* as ``<directory>/<name>``; returns the path as a string."""
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(level), encoding="utf-8")
    return str(path)
