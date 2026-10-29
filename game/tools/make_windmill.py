"""Build a Fio-scale windmill and its orthographic overhead sprites.

Run with Blender 4.3+: blender -b -t 4 -P game/tools/make_windmill.py
The game is Y-up; Blender's Z-up scene is converted on export. Geometry is
authored directly in game units, with a 106-unit door for a 100-unit player.
No third-party meshes, textures or add-ons are required.
"""

from __future__ import annotations

import argparse
from array import array
import json
import math
from pathlib import Path
import random
import struct
import sys

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
HUB_HEIGHT = 550.0
DOOR_HEIGHT = 106.0
BODY_RADIUS = 140.0
MODEL_DIR = ROOT / "assets/models/windmill"
SPRITE_DIR = ROOT / "assets/sprites/scenery"
MATERIALS = {}
PARTS = []


def material(name, color, roughness=0.8, metal=0.0):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1.0)
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1.0)
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = metal
    MATERIALS[name] = mat
    return mat


def brick_material(folder):
    """One UV colour texture: individual bricks are painted, not geometry."""
    rng = random.Random(42017)
    size, columns, rows = 1024, 44, 64
    brick_colors = [[rng.choice(((0.48, 0.20, 0.10), (0.58, 0.27, 0.14),
                                (0.62, 0.32, 0.18), (0.44, 0.21, 0.13),
                                (0.67, 0.35, 0.19), (0.54, 0.25, 0.16)))
                     for _ in range(columns)] for _ in range(rows)]
    pixels = array('f')
    for y in range(size):
        row = min(rows - 1, y * rows // size)
        fy = (y * rows / size) % 1.0
        for x in range(size):
            u = x * columns / size + 0.5 * (row % 2)
            col, fx = int(u) % columns, u % 1.0
            mortar = fx < 0.045 or fy < 0.10
            color = (0.48, 0.43, 0.33) if mortar else brick_colors[row][col]
            noise = 0.94 + rng.random() * 0.12
            # Subtle weathering towards the foot of the tower.
            dark = 0.88 + 0.12 * min(1.0, y / 150.0)
            pixels.extend((*[min(1.0, c * noise * dark) for c in color], 1.0))
    image = bpy.data.images.new("windmill_brick", size, size, alpha=False)
    image.pixels.foreach_set(pixels)
    image.filepath_raw = str(folder / "brick_albedo.png")
    image.file_format = 'PNG'
    image.save()
    mat = material("Brick", (1.0, 1.0, 1.0))
    texture = mat.node_tree.nodes.new("ShaderNodeTexImage")
    texture.image = image
    mat.node_tree.links.new(texture.outputs["Color"],
                           mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
    image.pack()


def finish(obj, name, mat, smooth=False):
    obj.name = name
    obj.data.materials.append(MATERIALS[mat])
    for face in obj.data.polygons:
        face.use_smooth = smooth
    PARTS.append(obj)
    return obj


def box(name, center, size, mat, angle=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=center)
    obj = bpy.context.object
    obj.dimensions = size
    obj.rotation_euler[1] = angle
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return finish(obj, name, mat)


def rod(name, a, b, radius, mat, sides=8):
    a, b = Vector(a), Vector(b)
    bpy.ops.mesh.primitive_cylinder_add(vertices=sides, radius=radius,
                                       depth=(b - a).length, location=(a + b) / 2)
    obj = bpy.context.object
    obj.rotation_euler = (b - a).to_track_quat('Z', 'Y').to_euler()
    return finish(obj, name, mat)


def lathe(name, profile, mat, sides=32, uv=False):
    verts = [(r * math.cos(i * math.tau / sides), r * math.sin(i * math.tau / sides), z)
             for z, r in profile for i in range(sides)]
    faces, coords = [], []
    for j in range(len(profile) - 1):
        for i in range(sides):
            faces.append((j * sides + i, j * sides + (i + 1) % sides,
                          (j + 1) * sides + (i + 1) % sides, (j + 1) * sides + i))
            low = (profile[j][0] - profile[0][0]) / (profile[-1][0] - profile[0][0])
            high = (profile[j + 1][0] - profile[0][0]) / (profile[-1][0] - profile[0][0])
            coords.append(((i / sides, low), ((i + 1) / sides, low),
                           ((i + 1) / sides, high), (i / sides, high)))
    faces += [tuple(reversed(range(sides))),
              tuple((len(profile) - 1) * sides + i for i in range(sides))]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    if uv:
        layer = mesh.uv_layers.new(name="UVMap")
        for face, face_uvs in zip(mesh.polygons, coords):
            for loop, coordinate in zip(face.loop_indices, face_uvs):
                layer.data[loop].uv = coordinate
    obj = finish(obj, name, mat, smooth=True)
    obj.data.polygons[-1].use_smooth = obj.data.polygons[-2].use_smooth = False
    return obj


def rotor():
    # Plane of the sails is vertical (XZ), in front of the bonnet, not flat
    # on its roof. Keep a named root/pivot in the editable Blender source.
    pivot = bpy.data.objects.new("Rotor_pivot", None)
    bpy.context.collection.objects.link(pivot)
    pivot.location = (0, -170, HUB_HEIGHT)
    bpy.context.view_layer.update()
    for blade in range(4):
        angle = math.pi / 4 + blade * math.pi / 2
        radial = Vector((math.cos(angle), 0, math.sin(angle)))
        across = Vector((-math.sin(angle), 0, math.cos(angle)))

        def beam(label, lo, hi, offset, width, depth=7):
            center = pivot.location + radial * ((lo + hi) / 2) + across * offset
            obj = box(f"Sail_{blade + 1}_{label}", center, (width, depth, hi - lo),
                      "Sail_red", math.pi / 2 - angle)
            obj.parent = pivot
            obj.matrix_parent_inverse = pivot.matrix_world.inverted()

        beam("main_spar", 22, 350, 0, 13, 10)
        beam("leading_board", 74, 350, -12, 18, 6)
        beam("outer_rail", 74, 350, 60, 4, 5)
        # Rungs make the reference's open lattice silhouette visible at a
        # modest triangle count; no alpha-textured sails are needed.
        for rung in range(10):
            distance = 76 + rung * (274 / 9)
            center = pivot.location + radial * distance + across * 30
            obj = box(f"Sail_{blade + 1}_rung_{rung + 1}", center,
                      (64, 5, 4), "Sail_red", math.pi / 2 - angle)
            obj.parent = pivot
            obj.matrix_parent_inverse = pivot.matrix_world.inverted()
        # Dark iron straps close to the hub.
        for radius in (32, 53):
            center = pivot.location + radial * radius + Vector((0, -7, 0))
            obj = box(f"Sail_{blade + 1}_iron_strap", center, (20, 4, 11),
                      "Iron", math.pi / 2 - angle)
            obj.parent = pivot
            obj.matrix_parent_inverse = pivot.matrix_world.inverted()
    rod("Axle", (0, -65, HUB_HEIGHT), (0, -180, HUB_HEIGHT), 13, "Iron", 12)
    rod("Hub_cap", (0, -179, HUB_HEIGHT), (0, -190, HUB_HEIGHT), 24, "Sail_red", 12)
    rod("Hub_pin", (0, -189, HUB_HEIGHT), (0, -194, HUB_HEIGHT), 7, "Iron", 8)


def build(folder):
    brick_material(folder)
    material("Sail_red", (0.52, 0.085, 0.045))
    material("Bonnet", (0.22, 0.28, 0.30), 0.65, 0.10)
    material("Seams", (0.10, 0.15, 0.17), 0.72, 0.15)
    material("Stone", (0.48, 0.43, 0.34))
    material("Door", (0.11, 0.055, 0.025))
    material("Door_boards", (0.19, 0.10, 0.045))
    material("Iron", (0.055, 0.065, 0.07), 0.55, 0.35)
    material("Glass", (0.035, 0.065, 0.075), 0.3)
    material("Brass", (0.52, 0.36, 0.12), 0.55, 0.45)
    lathe("Foundation", [(0, 144), (10, 144), (16, 140)], "Stone")
    lathe("Brick_tower", [(14, 140), (496, 96)], "Brick", uv=True)
    lathe("Top_collar", [(492, 99), (500, 101), (506, 101)], "Seams")
    bonnet = [(500, 106), (510, 111), (548, 106), (583, 94),
              (612, 73), (634, 44), (643, 14), (645, 0.5)]
    lathe("Bonnet_roof", bonnet, "Bonnet")
    for seam in range(12):
        angle = seam * math.tau / 12
        for (za, ra), (zb, rb) in zip(bonnet, bonnet[1:]):
            rod("Roof_seam", ((ra + 1) * math.cos(angle), (ra + 1) * math.sin(angle), za),
                ((rb + 1) * math.cos(angle), (rb + 1) * math.sin(angle), zb), 0.9, "Seams", 4)
    lathe("Roof_finial", [(644, 6), (651, 9), (665, 11), (679, 7), (685, 3)], "Bonnet", 12)
    rod("Weather_vane_post", (0, 0, 682), (0, 0, 710), 1.5, "Brass", 6)
    rod("Weather_vane_bar", (-18, 0, 702), (21, 0, 702), 1.5, "Brass", 6)
    mesh = bpy.data.meshes.new("Weather_vane_flag")
    mesh.from_pydata([(-21, 0, 693), (-21, 0, 710), (-5, 0, 702)], [], [(0, 1, 2), (2, 1, 0)])
    flag = bpy.data.objects.new("Weather_vane_flag", mesh)
    bpy.context.collection.objects.link(flag)
    finish(flag, "Weather_vane_flag", "Brass")

    # A shallow door recess and dressed stone frame, sized for the player.
    box("Door_frame", (0, -137, 61), (66, 13, 116), "Stone")
    box("Door_leaf", (0, -145, 57), (50, 4, DOOR_HEIGHT), "Door")
    for x in (-20, -10, 0, 10, 20):
        box("Door_plank", (x, -147.5, 57), (8.8, 1.5, 102), "Door_boards")
    for z in (28, 84):
        box("Door_hinge", (-10, -149, z), (25, 2, 3), "Iron")
    box("Door_latch", (15, -150, 55), (3, 3, 7), "Iron")
    box("Threshold", (0, -147, 4), (76, 34, 8), "Stone")
    for z in (245, 393):
        radius = 140 - (z - 14) * 44 / 482
        box("Window_frame", (0, -radius - 1, z), (34, 7, 48), "Stone")
        box("Window_recess", (0, -radius - 5, z), (24, 3, 37), "Glass")
        box("Window_vertical", (0, -radius - 7, z), (2, 2, 37), "Door")
        box("Window_horizontal", (0, -radius - 7, z), (24, 2, 2), "Door")
    rotor()


def setup(samples):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = samples
    scene.cycles.use_denoising = False
    scene.render.resolution_x = scene.render.resolution_y = 1024
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.world = bpy.data.worlds.new("World")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value = (0.65, 0.73, 0.83, 1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value = 0.55
    scene.view_settings.view_transform = 'AgX'
    for location, energy, size in [((-900, -1200, 1800), 4500000, 1100),
                                   ((900, 400, 1100), 1600000, 900)]:
        bpy.ops.object.light_add(type='AREA', location=location)
        lamp = bpy.context.object
        lamp.data.energy = energy
        lamp.data.shape = 'DISK'
        lamp.data.size = size
        lamp.rotation_euler = (Vector((0, 0, 300)) - lamp.location).to_track_quat('-Z', 'Y').to_euler()
    bpy.ops.object.camera_add(location=(0, 0, 2600))
    scene.camera = bpy.context.object
    scene.camera.data.type = 'ORTHO'
    scene.camera.data.clip_end = 10000
    return scene


def render(scene, path, elevation, span, target=(0, 0, 0), azimuth=0):
    target = Vector(target)
    pitch, yaw = math.radians(elevation), math.radians(azimuth)
    offset = Vector((math.sin(yaw) * math.cos(pitch), -math.cos(yaw) * math.cos(pitch), math.sin(pitch)))
    scene.camera.location = target + offset * 3000
    scene.camera.rotation_euler = (-offset).to_track_quat('-Z', 'Y').to_euler()
    scene.camera.data.ortho_scale = span
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def export(folder, work):
    # Fio's current GLB path reads mesh attributes directly. Bake every
    # object's world transform into one identity-transform mesh so neither
    # format depends on a loader applying node/parent transforms.
    copies = []
    for obj in PARTS:
        mesh = obj.data.copy()
        mesh.transform(obj.matrix_world)
        copy = bpy.data.objects.new('Windmill_export', mesh)
        bpy.context.collection.objects.link(copy)
        copies.append(copy)
    bpy.ops.object.select_all(action='DESELECT')
    for obj in copies:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = copies[0]
    bpy.ops.object.join()
    merged = bpy.context.object
    merged.name = 'Windmill'
    bpy.ops.wm.obj_export(filepath=str(folder / 'windmill.obj'), export_selected_objects=True,
                         forward_axis='NEGATIVE_Z', up_axis='Y', global_scale=1.0,
                         export_triangulated_mesh=True, export_materials=True,
                         path_mode='RELATIVE')
    obj = folder / 'windmill.obj'
    obj.write_text('# fio:up=y\n' + obj.read_text())
    mtl = folder / 'windmill.mtl'
    text = mtl.read_text()
    text = '\n'.join('map_Kd brick_albedo.png' if line.startswith('map_Kd ') else line
                     for line in text.splitlines()) + '\n'
    text = text.replace('newmtl Brick\n', 'newmtl Brick\nKd 1.000000 1.000000 1.000000\n')
    mtl.write_text(text)
    temporary_glb = work / 'windmill_export.glb'
    bpy.ops.export_scene.gltf(filepath=str(temporary_glb), export_format='GLB',
                              use_selection=True, export_yup=True, export_apply=True,
                              export_animations=False, export_cameras=False, export_lights=False)
    # Fio resolves GLB texture URIs, but its current renderer does not upload
    # embedded image bufferViews. This standard external URI works in Fio and
    # other glTF viewers. Keep the GLB in assets/models, where both resolve the
    # relative path to the same texture used by the OBJ.
    data = temporary_glb.read_bytes()
    json_length = struct.unpack_from('<I', data, 12)[0]
    document = json.loads(data[20:20 + json_length])
    for image in document.get('images', []):
        image.pop('bufferView', None)
        image.pop('mimeType', None)
        image['uri'] = 'windmill/brick_albedo.png'
    json_chunk = json.dumps(document, separators=(',', ':')).encode()
    json_chunk += b' ' * (-len(json_chunk) % 4)
    binary_chunks = data[20 + json_length:]
    packed = struct.pack('<III', 0x46546C67, 2, 20 + len(json_chunk) + len(binary_chunks))
    packed += struct.pack('<II', len(json_chunk), 0x4E4F534A) + json_chunk + binary_chunks
    (folder.parent / 'windmill.glb').write_bytes(packed)
    (folder / 'windmill.glb').unlink(missing_ok=True)
    bpy.data.objects.remove(merged, do_unlink=True)


def statistics():
    bpy.context.view_layer.update()
    points = [obj.matrix_world @ vertex.co for obj in PARTS for vertex in obj.data.vertices]
    low = [min(p[i] for p in points) for i in range(3)]
    high = [max(p[i] for p in points) for i in range(3)]
    # Native (x,y,z) -> Fio (x,z,-y).
    return {'player_height': 100, 'door_height': DOOR_HEIGHT,
            'base_diameter': 288, 'hub_height': HUB_HEIGHT,
            'bounds_min': [low[0], low[2], -high[1]],
            'bounds_max': [high[0], high[2], -low[1]],
            'triangle_count': sum(sum(len(p.vertices) - 2 for p in obj.data.polygons) for obj in PARTS),
            'up_axis': 'Y', 'front_axis': '+Z', 'origin': 'ground center',
            'model_scale': [1, 1, 1], 'model_rotation': [0, 0, 0],
            'sprites': {'windmill_topdown.png': {'elevation': 90, 'sprite_size': [720, 720]},
                        'windmill_overhead.png': {'elevation': 60, 'sprite_size': [860, 860]}},
            'sprite_ground_anchor': [0.5, 0.5]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--work', type=Path, default=ROOT / 'work/windmill')
    parser.add_argument('--samples', type=int, default=64)
    parser.add_argument('--export-only', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    for path in (MODEL_DIR, SPRITE_DIR, args.work):
        path.mkdir(parents=True, exist_ok=True)
    scene = setup(args.samples)
    build(MODEL_DIR)
    bpy.context.view_layer.update()
    export(MODEL_DIR, args.work)
    stats = statistics()
    (MODEL_DIR / 'windmill.json').write_text(json.dumps(stats, indent=2) + '\n')
    if args.export_only:
        print('WINDMILL_ASSET ' + json.dumps(stats), flush=True)
        return
    render(scene, SPRITE_DIR / 'windmill_topdown.png', 90, 720)
    render(scene, SPRITE_DIR / 'windmill_overhead.png', 60, 860)
    render(scene, args.work / 'windmill_preview.png', 22, 1120, target=(0, 0, 410), azimuth=-18)
    # Add a 100-unit reference only to the scale preview and editable source.
    material('Scale_reference', (0.20, 0.52, 0.54))
    mannequin = box('100_unit_scale_reference', (-255, -95, 40), (30, 18, 80), 'Scale_reference')
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=6, radius=10, location=(-255, -95, 90))
    head = bpy.context.object
    finish(head, 'Scale_reference_head', 'Scale_reference', smooth=True)
    render(scene, args.work / 'windmill_scale.png', 15, 1120, target=(0, 0, 410), azimuth=-18)
    mannequin.hide_render = head.hide_render = True
    bpy.ops.wm.save_as_mainfile(filepath=str(args.work / 'windmill.blend'))
    print('WINDMILL_ASSET ' + json.dumps(stats), flush=True)


if __name__ == '__main__':
    main()
