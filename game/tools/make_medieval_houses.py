successfully downloaded text file (SHA: 47f250eb5e4901600ec977883963a694afa03ac6)"""Build a low-poly kit of medieval houses. Blender 4.3+:

    blender -b -t 4 -P game/tools/make_medieval_houses.py

Eight buildings of the Vale, authored like make_castle.py: original meshes,
flat coloured materials (no textures to ship), deterministic from fixed
seeds, and no third-party meshes or add-ons. Author Z-up, export Y-up in Fio
units, a 100-unit player and a 116-unit door (make_windmill's door is 106).
The front wall faces Blender -Y, which is Fio +Z, and every model is an
exterior shell: its ground is closed, so nothing shows the inside.

The kit, written to assets/models:

* house_cottage   -- a one-storey labourer's cottage under a thatch roof.
* house_farmhouse -- a long farmhouse, tiled, with shuttered windows.
* house_townhouse -- two storeys, the upper jettied over the street, gable
  to the street, timber-framed, under a steep slate roof.
* house_inn       -- the inn: two storeys, a lower wing, a painted sign on a
  wrought bracket, and two chimneys.
* house_bakery    -- the baker's: a deep shop window, a canvas awning and a
  wide oven chimney.
* house_smithy    -- the smithy: stone walls, a wide cart door and a forge
  shelter with its anvil and quench trough outside.
* house_barn      -- a big timber barn, cart doors in both gable ends.
* house_chapel    -- a stone chapel with lancets, a round east light and a
  bellcote on the ridge.

Each is exported as OBJ + MTL (flat Kd colours, marked 'fio:up=y') and GLB
(base colour factors, no images), with a kit manifest in
assets/models/medieval_houses.json and preview renders in work/houses when
not run with --export-only. The editable source is saved with the generator,
not among the shipped assets.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / 'assets/models'
PARTS = []
MATS = {}

PLAYER_HEIGHT = 100
DOOR_HEIGHT = 116.0
DOOR_WIDTH = 76.0


# ---------------------------------------------------------------- materials
def material(name, rgb, metal=0):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*rgb, 1)
    mat.use_nodes = True
    mat.use_backface_culling = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (*rgb, 1)
    bsdf.inputs['Roughness'].default_value = .85
    bsdf.inputs['Metallic'].default_value = metal
    MATS[name] = mat
    return mat


def build_materials():
    # Wall renders, one per house, so a street of them does not read as one
    # building repeated; timber, thatch, tile and slate as the kit's rest.
    material('Plaster', (.87, .83, .71))
    material('Plaster_warm', (.86, .78, .63))
    material('Plaster_cool', (.83, .81, .77))
    material('Timber', (.27, .18, .11))
    material('Timber_dark', (.19, .12, .07))
    material('Thatch', (.62, .49, .26))
    material('Tile', (.51, .25, .17))
    material('Slate', (.35, .37, .41))
    material('Stone', (.45, .44, .40))
    material('Oak', (.33, .21, .11))
    material('Iron', (.09, .10, .10), .3)
    material('Recess', (.05, .055, .05))
    material('Shutter', (.45, .29, .16))
    material('Sign_ground', (.16, .30, .22))
    material('Canvas', (.78, .72, .55))


# ----------------------------------------------------------------- geometry
def _consistent_normals(obj):
    """Closed low-poly meshes only: make every face point outward."""
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode='OBJECT')


def mesh(name, verts, faces, mat):
    data = bpy.data.meshes.new(name)
    data.from_pydata(verts, [], faces)
    data.update()
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(MATS[mat])
    layer = data.uv_layers.new(name='UVMap')
    for poly in data.polygons:
        # Planar world-scale mapping; flat colours do not read it, but the
        # export agrees with the castle kit's UV conventions.
        normal = poly.normal
        axes = (1, 2) if abs(normal.x) > .7 else (0, 2) if abs(normal.y) > .7 else (0, 1)
        for li in poly.loop_indices:
            v = data.vertices[data.loops[li].vertex_index].co
            layer.data[li].uv = (v[axes[0]] / 256, v[axes[1]] / 256)
    _consistent_normals(obj)
    PARTS.append(obj)
    return obj


def box(name, center, size, mat='Plaster', yaw=0):
    x, y, z = center
    a, b, c = (s / 2 for s in size)
    co, si = math.cos(yaw), math.sin(yaw)
    verts = [(x + co * i - si * j, y + si * i + co * j, z + k)
             for i, j, k in ((-a, -b, -c), (a, -b, -c), (a, b, -c), (-a, b, -c),
                             (-a, -b, c), (a, -b, c), (a, b, c), (-a, b, c))]
    return mesh(name, verts, [(3, 2, 1, 0), (0, 1, 5, 4), (1, 2, 6, 5),
                              (2, 3, 7, 6), (3, 0, 4, 7), (4, 5, 6, 7)], mat)


def beam(name, start, end, width, thickness, mat):
    """A straight box from *start* to *end*: braces, poles and framing."""
    d = Vector((end[0] - start[0], end[1] - start[1], end[2] - start[2]))
    length = d.length
    if length < 1e-6:
        return box(name, start, (width, thickness, 2), mat)
    d /= length
    up = Vector((0, 0, 1)) if abs(d.z) < .9 else Vector((1, 0, 0))
    u = d.cross(up).normalized()
    v = u.cross(d).normalized()
    center = Vector(((start[0] + end[0]) / 2, (start[1] + end[1]) / 2,
                     (start[2] + end[2]) / 2))
    hw, ht, hl = width / 2, thickness / 2, length / 2
    verts = [tuple(center + d * s * hl + u * a * hw + v * b * ht)
             for s in (-1, 1) for a in (-1, 1) for b in (-1, 1)]
    faces = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4),
             (1, 3, 7, 5), (3, 2, 6, 7), (2, 0, 4, 6)]
    return mesh(name, verts, faces, mat)


def prism(name, profile, span, mat, axis='x', origin=0.0):
    """A closed convex prism: *profile* (a 2D polygon) extruded *span* along
    *axis*. A house's silhouette -- walls and gable in one mesh -- is a
    pentagon profile; its roof slabs are thin ones."""
    a0, a1 = origin - span / 2, origin + span / 2
    n = len(profile)
    verts = []
    for a in (a0, a1):
        for p, q in profile:
            verts.append((a, p, q) if axis == 'x' else (p, a, q))
    faces = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    faces.append(tuple(range(n - 1, -1, -1)))
    faces.append(tuple(range(n, 2 * n)))
    return mesh(name, verts, faces, mat)


def roof_slab(name, axis, lo, hi, p_in, p_out, thickness, mat):
    """One slope of a roof: a slab from the wall line *p_in* down past the
    eave *p_out* (both (across, height) on the roof's cross-section),
    extruded along the ridge *axis* from *lo* to *hi*."""
    dx, dz = p_out[0] - p_in[0], p_out[1] - p_in[1]
    length = math.hypot(dx, dz) or 1.0
    nx, nz = -dz / length, dx / length
    if nz < 0:                              # the outward face is the upper one
        nx, nz = -nx, -nz
    ox, oz = nx * thickness / 2, nz * thickness / 2
    profile = [(p_in[0] - ox, p_in[1] - oz), (p_out[0] - ox, p_out[1] - oz),
               (p_out[0] + ox, p_out[1] + oz), (p_in[0] + ox, p_in[1] + oz)]
    return prism(name, profile, hi - lo, mat, axis, (lo + hi) / 2)


def gable_roof(name, width, depth, wall_top, rise, overhang, thickness, mat,
               gable_front=False):
    """Both slopes of a gabled roof over a *width* x *depth* house whose
    walls top out at *wall_top* and whose ridge rises *rise* above them."""
    if gable_front:
        # The ridge runs front to back; the slopes face the streets aside.
        half = width / 2
        for sign in (-1, 1):
            eave = rise * (half + overhang) / half
            roof_slab(f'{name} slope', 'y', -depth / 2 - overhang,
                      depth / 2 + overhang,
                      (sign * half, wall_top),
                      (sign * (half + overhang), wall_top - eave),
                      thickness, mat)
    else:
        half = depth / 2
        for sign in (-1, 1):
            eave = rise * (half + overhang) / half
            roof_slab(f'{name} slope', 'x', -width / 2 - overhang,
                      width / 2 + overhang,
                      (sign * half, wall_top),
                      (sign * (half + overhang), wall_top - eave),
                      thickness, mat)


def house_shell(name, width, depth, wall_h, rise, wall_mat, roof_mat,
                overhang=100.0, thickness=26.0, gable_front=False):
    """Footing, walls (with the gable in the silhouette) and roof; returns
    (wall_top, ridge_z, half_width, half_depth)."""
    box(f'{name} footing', (0, 0, 10), (width + 48, depth + 48, 20), 'Stone')
    if gable_front:
        profile = [(-width / 2, 0), (width / 2, 0), (width / 2, wall_h),
                   (0, wall_h + rise), (-width / 2, wall_h)]
        prism(f'{name} walls', profile, depth, wall_mat, 'y')
    else:
        profile = [(-depth / 2, 0), (depth / 2, 0), (depth / 2, wall_h),
                   (0, wall_h + rise), (-depth / 2, wall_h)]
        prism(f'{name} walls', profile, width, wall_mat, 'x')
    gable_roof(f'{name} roof', width, depth, wall_h, rise, overhang, thickness,
               roof_mat, gable_front)
    return wall_h, wall_h + rise, width / 2, depth / 2


# ------------------------------------------------------------ door & windows
def doorway(name, x, face_y, *, width=DOOR_WIDTH, height=DOOR_HEIGHT, double=False):
    """An oak door in a frame on a wall whose face is at *face_y*."""
    out = -1.0 if face_y < 0 else 1.0
    y = face_y + out * 3
    planks = 9 if double else 5
    plank_w = (width * (1.3 if double else 1.0)) / planks
    total = plank_w * planks
    box(f'{name} threshold', (x, face_y + out * 4, 12), (total + 44, 14, 24), 'Stone')
    for sign in (-1, 1):
        box(f'{name} door jamb', (x + sign * (total / 2 + 8), y, height / 2 + 12),
            (16, 12, height + 4), 'Timber')
    box(f'{name} door lintel', (x, y, height + 20), (total + 48, 12, 14), 'Timber')
    for i in range(planks):
        px = x - total / 2 + plank_w * (i + .5)
        box(f'{name} door plank', (px, face_y + out * 6, height / 2 + 12),
            (plank_w - 2, 6, height - 6), 'Oak')
    for z in (height * .3 + 12, height * .72 + 12):
        box(f'{name} door strap', (x, face_y + out * 10, z), (total * .7, 3, 5), 'Iron')
    box(f'{name} door latch', (x + total * .28, face_y + out * 10, height * .52 + 12),
        (5, 4, 12), 'Iron')


def window(name, center, normal, *, z, width=96.0, height=112.0, shutters=True,
           frame_mat='Timber'):
    """A mullioned window with a stone sill, in a wall whose face passes
    through *center* -- an '(x, y)' point on the wall -- and looks along the
    unit *normal* '(nx, ny)' (one of the four axis directions, pointing out
    of the wall); *z* is the height of the window's centre. Every part is
    laid out along the wall and offset out of it, so gable and end walls
    take windows the same way the front does."""
    tx, ty = -normal[1], normal[0]          # along the wall
    yaw = math.atan2(ty, tx)

    def at(u, n, dz):
        return (center[0] + tx * u + normal[0] * n,
                center[1] + ty * u + normal[1] * n, z + dz)

    box(f'{name} recess', at(0, 1, 0), (width, 6, height), 'Recess', yaw)
    box(f'{name} mullion', at(0, 3, 0), (9, 4, height), frame_mat, yaw)
    box(f'{name} transom', at(0, 3, 0), (width, 4, 9), frame_mat, yaw)
    for sign in (-1, 1):
        box(f'{name} jamb', at(sign * (width / 2 + 7), 1, 0),
            (14, 10, height + 12), frame_mat, yaw)
    box(f'{name} lintel', at(0, 1, height / 2 + 13), (width + 48, 10, 12),
        frame_mat, yaw)
    box(f'{name} sill', at(0, 1, -height / 2 - 9), (width + 56, 14, 10), 'Stone', yaw)
    if shutters:
        for sign in (-1, 1):
            box(f'{name} shutter', at(sign * (width + 22), 4, 0),
                (30, 5, height + 6), 'Shutter', yaw)


def gable_window(name, center, normal, *, z, width):
    """A small attic light in a gable, narrow enough to stay in the triangle."""
    window(name, center, normal, z=z, width=width, height=88.0, shutters=False)


def chimney_stack(name, x, y, top_z, *, base_z=0.0, size=112.0):
    """A stone stack through the roof, with a cap and a tile pot."""
    h = top_z - base_z
    box(f'{name} stack', (x, y, base_z + h / 2), (size, size, h), 'Stone')
    box(f'{name} cap', (x, y, top_z + 10), (size + 34, size + 34, 18), 'Stone')
    box(f'{name} pot', (x, y, top_z + 44), (46, 46, 46), 'Tile')


def hanging_sign(name, x, face_y, z):
    """The inn's sign: a wrought bracket off the wall and a hanging board."""
    out = -1.0 if face_y < 0 else 1.0
    arm_end = (x, face_y + out * 170, z)
    beam(f'{name} bracket', (x, face_y + out * 6, z), arm_end, 12, 12, 'Iron')
    beam(f'{name} bracket stay', (x, face_y + out * 6, z - 62), arm_end, 10, 10, 'Iron')
    beam(f'{name} sign hook', (arm_end[0], arm_end[1], z - 6),
         (arm_end[0], arm_end[1], z - 42), 6, 6, 'Iron')
    box(f'{name} sign board', (x, face_y + out * 170, z - 88), (10, 120, 74), 'Oak')
    box(f'{name} sign emblem', (x + out * 7, face_y + out * 170, z - 88),
        (4, 62, 44), 'Sign_ground')


def timber_frame(name, x0, x1, z0, z1, face_y, studs=4, rails=1, out=-1.0):
    """Studs and rails on a wall face: low-poly timber framing."""
    y = face_y + out * 5
    for sign in (-1, 1):
        box(f'{name} corner post', (x0 if sign < 0 else x1, y, (z0 + z1) / 2),
            (26, 12, z1 - z0), 'Timber')
    span = (x1 - x0 - 52) / max(1, studs - 1)
    for i in range(studs):
        box(f'{name} stud', (x0 + 26 + span * i, y, (z0 + z1) / 2), (14, 10, z1 - z0 - 8),
            'Timber')
    for r in range(rails):
        z = z0 + (z1 - z0) * (r + 1) / (rails + 1)
        box(f'{name} rail', ((x0 + x1) / 2, y, z), (x1 - x0, 10, 16), 'Timber')


# -------------------------------------------------------------------- houses
def build_cottage():
    name = 'house_cottage'
    start = len(PARTS)
    width, depth, wall_h, rise = 560.0, 440.0, 290.0, 180.0
    wall_top, ridge, w2, d2 = house_shell(name, width, depth, wall_h, rise,
                                          'Plaster', 'Thatch', overhang=110.0)
    doorway(name, 120, -d2)
    window(f'{name} front west', (-140, -d2), (0, -1), z=168)
    window(f'{name} front east', (0, -d2), (0, -1), z=168, shutters=False)
    for sign in (-1, 1):
        window(f'{name} gable light', (sign * (w2 + 2), 40.0), (sign, 0),
               z=170, width=84.0, height=96.0, shutters=False)
    chimney_stack(f'{name} chimney', w2 - 120, 40, ridge - 30)
    return PARTS[start:], dict(width=width, depth=depth, wall_height=wall_h,
                               ridge_height=round(ridge))


def build_farmhouse():
    name = 'house_farmhouse'
    start = len(PARTS)
    width, depth, wall_h, rise = 800.0, 520.0, 330.0, 200.0
    wall_top, ridge, w2, d2 = house_shell(name, width, depth, wall_h, rise,
                                          'Plaster_warm', 'Tile', overhang=120.0)
    doorway(name, 250, -d2)
    window(f'{name} front parlour', (-250, -d2), (0, -1), z=170)
    window(f'{name} front middle', (-40, -d2), (0, -1), z=170, shutters=False)
    for sign in (-1, 1):
        window(f'{name} end light', (sign * (w2 + 2), 60.0), (sign, 0),
               z=180, width=96.0, height=110.0, shutters=False)
    window(f'{name} back kitchen', (150, d2), (0, 1), z=175, shutters=False)
    timber_frame(name, -w2 + 30, w2 - 30, 40, wall_h - 50, -d2, studs=6, rails=1)
    chimney_stack(f'{name} chimney', -w2 + 110, 60, ridge - 20)
    return PARTS[start:], dict(width=width, depth=depth, wall_height=wall_h,
                               ridge_height=round(ridge))


def build_townhouse():
    name = 'house_townhouse'
    start = len(PARTS)
    width, depth, wall_h, rise = 480.0, 560.0, 560.0, 300.0
    wall_top, ridge, w2, d2 = house_shell(name, width, depth, wall_h, rise,
                                          'Plaster_cool', 'Slate', overhang=90.0,
                                          gable_front=True)
    # The upper storey jetties 70 over the street, flush at the back.
    box(f'{name} upper storey', (0, -35, (wall_h / 2 + wall_h) / 2 + 140),
        (width + 70, depth + 70, wall_h / 2 - 140), 'Plaster_cool')
    box(f'{name} jetty beam', (0, -35, wall_h / 2 + 134), (width + 96, 110, 22),
        'Timber')
    timber_frame(name, -w2 - 20, w2 + 20, wall_h / 2 + 40, wall_h - 20, -(d2 + 70),
                 studs=4, rails=1)
    timber_frame(name, -w2, w2, 30, wall_h / 2 - 30, -d2, studs=3, rails=1)
    doorway(name, 0, -d2)
    window(f'{name} parlour', (-w2 + 90, -d2), (0, -1), z=190, shutters=False)
    window(f'{name} chamber west', (-110, -(d2 + 70)), (0, -1), z=wall_h * .72)
    window(f'{name} chamber east', (110, -(d2 + 70)), (0, -1), z=wall_h * .72)
    gable_window(f'{name} attic', (0, -(d2 + 70)), (0, -1),
                 z=wall_h + rise * .34, width=width * .34)
    chimney_stack(f'{name} chimney', 0, d2 - 90, ridge + 60)
    return PARTS[start:], dict(width=width, depth=depth, wall_height=wall_h,
                               ridge_height=round(ridge), jetty=70.0,
                               gable_front=True)


def build_inn():
    name = 'house_inn'
    start = len(PARTS)
    width, depth, wall_h, rise = 940.0, 620.0, 560.0, 230.0
    wall_top, ridge, w2, d2 = house_shell(name, width, depth, wall_h, rise,
                                          'Plaster', 'Tile', overhang=110.0)
    # The lower wing leans on the main block's front-left corner; its own
    # ridge runs the same way, its back slope dying into the main wall.
    wing_w, wing_d, wing_h, wing_rise = 420.0, 380.0, 280.0, 150.0
    wx, wy = -w2 + wing_w / 2 - 30, -d2 - wing_d / 2 + 60
    box(f'{name} wing footing', (wx, wy, 10), (wing_w + 40, wing_d + 40, 20), 'Stone')
    wing_profile = [(-wing_d / 2, 0), (wing_d / 2, 0), (wing_d / 2, wing_h),
                    (0, wing_h + wing_rise), (-wing_d / 2, wing_h)]
    prism(f'{name} wing walls', wing_profile, wing_w, 'Plaster_warm', 'x', wx)
    for sign in (-1, 1):
        eave = wing_rise * (wing_d / 2 + 80) / (wing_d / 2)
        roof_slab(f'{name} wing roof slope', 'x', wx - wing_w / 2 - 70,
                  wx + wing_w / 2 + 70,
                  (wy + sign * wing_d / 2, wing_h),
                  (wy + sign * (wing_d / 2 + 80), wing_h - eave), 24.0, 'Tile')
    doorway(name, 260, -d2, double=True)
    window(f'{name} tap room', (-180, -d2), (0, -1), z=180, width=150.0,
           shutters=False)
    for sign in (-1, 1):
        window(f'{name} chamber', (sign * 220, -d2), (0, -1), z=wall_h * .72,
               width=120.0)
        window(f'{name} end light', (sign * (w2 + 2), 80.0), (sign, 0),
               z=300, width=90.0, height=100.0, shutters=False)
    window(f'{name} wing light', (wx - 90, wy - wing_d / 2), (0, -1),
           z=170, width=90.0, height=100.0, shutters=False)
    hanging_sign(name, 60, -d2, 430)
    chimney_stack(f'{name} kitchen chimney', wx + 60, wy, wing_h + wing_rise - 10)
    chimney_stack(f'{name} chimney', w2 - 140, 80, ridge - 20)
    return PARTS[start:], dict(width=width, depth=depth, wall_height=wall_h,
                               ridge_height=round(ridge), wing=True,
                               door_width=round(76 * 1.3, 1))


def build_bakery():
    name = 'house_bakery'
    start = len(PARTS)
    width, depth, wall_h, rise = 520.0, 460.0, 300.0, 190.0
    wall_top, ridge, w2, d2 = house_shell(name, width, depth, wall_h, rise,
                                          'Plaster_warm', 'Tile', overhang=100.0)
    doorway(name, 140, -d2)
    # The shop window: wide and low, the bread seen from the street.
    window(f'{name} shop', (-130, -d2), (0, -1), z=150, width=230.0,
           height=118.0, shutters=False)
    # The canvas awning: arms from the wall and a cloth sloping out over it.
    for sign in (-1, 1):
        beam(f'{name} awning arm', (-130 + sign * 128, -d2, 232),
             (-130 + sign * 128, -d2 - 158, 196), 9, 9, 'Timber')
    roof_slab(f'{name} awning', 'x', -262, 2, (-d2 - 2, 232), (-d2 - 168, 190),
              14.0, 'Canvas')
    for sign in (-1, 1):
        window(f'{name} side light', (sign * (w2 + 2), 30.0), (sign, 0),
               z=180, width=90.0, height=100.0, shutters=False)
    # The oven chimney, wider than a house's: the ovens live against it.
    chimney_stack(f'{name} oven chimney', -w2 + 110, 30, ridge - 20, size=140.0)
    return PARTS[start:], dict(width=width, depth=depth, wall_height=wall_h,
                               ridge_height=round(ridge), shop_window=True)


def build_smithy():
    name = 'house_smithy'
    start = len(PARTS)
    width, depth, wall_h, rise = 640.0, 520.0, 340.0, 170.0
    wall_top, ridge, w2, d2 = house_shell(name, width, depth, wall_h, rise,
                                          'Stone', 'Tile', overhang=90.0)
    # The cart door: tall and wide, in two leaves that fold back.
    doorway(name, 130, -d2, width=190.0, height=190.0, double=True)
    for sign in (-1, 1):
        window(f'{name} end light', (sign * (w2 + 2), 40.0), (sign, 0),
               z=190, width=84.0, height=96.0, shutters=False)
    # The forge shelter stands in front of the wall, clear of the eave:
    # four posts, a low slope off the wall, the anvil block and quench
    # trough under it.
    sx0, sx1 = -w2 + 20, -w2 + 280
    for px, py in ((sx0, -d2 - 110), (sx1, -d2 - 110), (sx0, -d2 - 320), (sx1, -d2 - 320)):
        beam(f'{name} shelter post', (px, py, 0), (px, py, 200), 22, 22, 'Oak')
    for px in (sx0, sx1):
        beam(f'{name} shelter plate', (px, -d2 - 100, 196), (px, -d2 - 330, 128),
             16, 16, 'Timber')
    roof_slab(f'{name} shelter roof', 'x', sx0 - 40, sx1 + 40,
              (-d2 - 100, 196), (-d2 - 330, 128), 18.0, 'Tile')
    box(f'{name} anvil block', ((sx0 + sx1) / 2 - 60, -d2 - 210, 45), (90, 90, 90), 'Oak')
    box(f'{name} anvil', ((sx0 + sx1) / 2 - 60, -d2 - 210, 108), (120, 44, 30), 'Iron')
    box(f'{name} quench trough', ((sx0 + sx1) / 2 + 60, -d2 - 220, 40), (110, 70, 80), 'Stone')
    # The forge chimney, the widest in the kit.
    chimney_stack(f'{name} forge chimney', w2 - 140, 60, ridge - 10, size=160.0)
    return PARTS[start:], dict(width=width, depth=depth, wall_height=wall_h,
                               ridge_height=round(ridge),
                               door_width=round(190 * 1.3, 1), forge_shelter=True)


def build_barn():
    name = 'house_barn'
    start = len(PARTS)
    width, depth, wall_h, rise = 900.0, 640.0, 360.0, 260.0
    wall_top, ridge, w2, d2 = house_shell(name, width, depth, wall_h, rise,
                                          'Timber', 'Thatch', overhang=120.0,
                                          gable_front=True)
    # Cart doors in both gable ends: wagons go straight through.
    doorway(name, 0, -d2, width=210.0, height=220.0, double=True)
    doorway(name, 0, d2, width=210.0, height=220.0, double=True)
    # Breathing vents high in each gable; a barn has no other openings.
    for sign in (-1, 1):
        box(f'{name} vent', (sign * (width * .18), -(d2 + 2), wall_h + rise * .3),
            (70, 8, 90), 'Recess')
    box(f'{name} vent', (0, d2 + 2, wall_h + rise * .3), (70, 8, 90), 'Recess')
    return PARTS[start:], dict(width=width, depth=depth, wall_height=wall_h,
                               ridge_height=round(ridge),
                               door_width=round(210 * 1.3, 1))


def build_chapel():
    name = 'house_chapel'
    start = len(PARTS)
    width, depth, wall_h, rise = 460.0, 760.0, 400.0, 280.0
    wall_top, ridge, w2, d2 = house_shell(name, width, depth, wall_h, rise,
                                          'Stone', 'Slate', overhang=80.0,
                                          gable_front=True)
    doorway(name, 0, -d2, width=110.0, height=180.0)
    # Lancets down both sides; a round light high in the front gable.
    for sign in (-1, 1):
        for y in (-d2 + 200, -40.0, d2 - 200):
            window(f'{name} lancet', (sign * (w2 + 2), y), (sign, 0),
                   z=250, width=64.0, height=200.0, shutters=False)
    gable_window(f'{name} east light', (0, -(d2 + 2)), (0, -1),
                 z=wall_h + rise * .38, width=120.0)
    # The bellcote on the ridge over the altar end, its bell in the opening.
    bc_w, bc_h = 150.0, 210.0
    bc_y, bc_z = d2 - 150.0, ridge + 6.0
    box(f'{name} bellcote', (0, bc_y, bc_z + bc_h / 2), (bc_w, bc_w, bc_h), 'Stone')
    prism(f'{name} bellcote roof',
          [(-bc_w / 2 - 24, bc_z + bc_h - 2), (bc_w / 2 + 24, bc_z + bc_h - 2),
           (0, bc_z + bc_h + 90)], bc_w + 48, 'Slate', 'y', bc_y)
    box(f'{name} bell', (0, bc_y, bc_z + bc_h - 58), (62, 62, 66), 'Iron')
    for sign in (-1, 1):
        box(f'{name} bellcote opening', (sign * (bc_w / 2 + 1), bc_y, bc_z + bc_h - 58),
            (10, 80, 90), 'Recess')
    return PARTS[start:], dict(width=width, depth=depth, wall_height=wall_h,
                               ridge_height=round(ridge), gable_front=True,
                               bellcote=True)


# -------------------------------------------------------------------- export
def export(name, parts, work):
    bpy.context.view_layer.update()
    copies = []
    for obj in parts:
        data = obj.data.copy()
        data.transform(obj.matrix_world)
        copy = bpy.data.objects.new('Export', data)
        bpy.context.collection.objects.link(copy)
        copies.append(copy)
    bpy.ops.object.select_all(action='DESELECT')
    for obj in copies:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = copies[0]
    bpy.ops.object.join()
    merged = bpy.context.object
    merged.name = name
    bpy.ops.wm.obj_export(filepath=str(MODELS / f'{name}.obj'), export_selected_objects=True,
                          forward_axis='NEGATIVE_Z', up_axis='Y', global_scale=1,
                          export_triangulated_mesh=True, export_materials=True,
                          path_mode='RELATIVE')
    path = MODELS / f'{name}.obj'
    path.write_text('# fio:up=y\n' + path.read_text())
    # Fio's GLB renderer reads UVs directly and the OBJ keeps its authored
    # values: cancel Blender's glTF V conversion on this export copy so both
    # paths agree, as the castle kit does.
    if merged.data.uv_layers.active is not None:
        for uv in merged.data.uv_layers.active.data:
            uv.uv.y = 1 - uv.uv.y
    bpy.ops.export_scene.gltf(filepath=str(MODELS / f'{name}.glb'), export_format='GLB',
                              use_selection=True, export_yup=True, export_apply=True,
                              export_animations=False, export_cameras=False,
                              export_lights=False)
    bpy.data.objects.remove(merged, do_unlink=True)
    points = [obj.matrix_world @ v.co for obj in parts for v in obj.data.vertices]
    low = [min(v[i] for v in points) for i in range(3)]
    high = [max(v[i] for v in points) for i in range(3)]
    return dict(bounds_min=[low[0], low[2], -high[1]],
                bounds_max=[high[0], high[2], -low[1]],
                triangle_count=sum(len(p.vertices) - 2 for o in parts
                                   for p in o.data.polygons))


def setup_scene():
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 24
    scene.cycles.use_denoising = False
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 960
    scene.render.image_settings.file_format = 'PNG'
    scene.world = bpy.data.worlds.new('Houses world')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value = (.37, .44, .52, 1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value = .65
    scene.view_settings.view_transform = 'AgX'
    bpy.ops.object.light_add(type='AREA', location=(-900, -1400, 1500))
    bpy.context.object.data.energy = 3000000
    bpy.context.object.data.shape = 'DISK'
    bpy.context.object.data.size = 1400
    bpy.context.object.rotation_euler = (Vector((200, 0, 220)) -
                                         bpy.context.object.location).to_track_quat('-Z', 'Y').to_euler()
    bpy.ops.object.camera_add()
    scene.camera = bpy.context.object
    scene.camera.data.type = 'ORTHO'
    scene.camera.data.clip_end = 15000
    # Presentation-only ground; the saved source keeps it, named for what it is.
    box('PREVIEW ONLY ground', (0, 0, -9), (16000, 16000, 16), 'Stone')
    return scene


def preview(scene, path, eye, target, span):
    camera = scene.camera
    camera.location = eye
    camera.rotation_euler = (Vector(target) - camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera.data.ortho_scale = span
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--work', type=Path, default=ROOT / 'work/houses')
    parser.add_argument('--export-only', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    MODELS.mkdir(parents=True, exist_ok=True)
    args.work.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.preferences.filepaths.save_version = 0
    build_materials()
    scene = None if args.export_only else setup_scene()
    houses = {}
    for name, build in (('house_cottage', build_cottage),
                        ('house_farmhouse', build_farmhouse),
                        ('house_townhouse', build_townhouse),
                        ('house_inn', build_inn),
                        ('house_bakery', build_bakery),
                        ('house_smithy', build_smithy),
                        ('house_barn', build_barn),
                        ('house_chapel', build_chapel)):
        parts, dims = build()
        stats = export(name, parts, args.work)
        if scene is not None:
            low, high = stats['bounds_min'], stats['bounds_max']
            span = max(high[0] - low[0], high[2] - low[2]) * 1.7
            preview(scene, args.work / f'{name}_preview.png',
                    (low[0] - span, low[2] - span * 1.1, high[1] + span * .7),
                    ((low[0] + high[0]) / 2, (low[2] + high[2]) / 2, 160), span)
        for obj in parts:
            obj.hide_render = True
        houses[name] = dict(**dims, **stats, door_height=DOOR_HEIGHT,
                            up_axis='Y', front_axis='+Z', origin='ground center',
                            model_scale=[1, 1, 1], model_rotation=[0, 0, 0],
                            collision='Exterior scenery. Use matching structural '
                                      'brushes for collision; model Props use a '
                                      'single bounding box.')
    kit = dict(player_height=PLAYER_HEIGHT,
               units='Fio units (1 unit approximately 1.8 cm)',
               houses=houses)
    (MODELS / 'medieval_houses.json').write_text(json.dumps(kit, indent=2) + '\n')
    source = ROOT / 'game/tools/data/medieval_houses.blend'
    source.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(source))
    print('MEDIEVAL_HOUSES ' + json.dumps(kit), flush=True)


if __name__ == '__main__':
    main()
