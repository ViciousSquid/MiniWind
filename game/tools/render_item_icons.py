"""Render realistic inventory assets with Blender's CPU path tracer.

Usage from the repository root::

    blender -b -t 4 -P game/tools/render_item_icons.py -- --output work/icons
    blender -b -t 4 -P game/tools/render_item_icons.py -- --only iron_longsword

No external models or textures: geometry, material grain and lighting are
procedural. Output is transparent 256px PNG, compatible with the ordinary
inventory, quickbar, editor and projectile icon paths. This script does not
archive or replace live assets; inspect its output before importing it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import sys


# Blender is optional outside this asset-production script.
try:
    import bpy
    from mathutils import Vector
except ImportError:
    bpy = None
    Vector = None

ROOT = Path(__file__).resolve().parents[2]
M = {}


def material(name, color, metal=0, rough=.5, grain=0, glass=0, emission=0):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Metallic"].default_value = metal
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Transmission Weight"].default_value = glass
    bsdf.inputs["IOR"].default_value = 1.45
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*color, 1)
        bsdf.inputs["Emission Strength"].default_value = emission
    if grain:
        tex = nodes.new("ShaderNodeTexNoise")
        tex.inputs["Scale"].default_value = 42 if metal else 23
        tex.inputs["Detail"].default_value = 3
        ramp = nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].position = .15
        ramp.color_ramp.elements[0].color = (*(c * .78 for c in color), 1)
        ramp.color_ramp.elements[1].position = .85
        ramp.color_ramp.elements[1].color = (*(min(1, c * 1.12) for c in color), 1)
        links.new(tex.outputs["Fac"], ramp.inputs["Fac"])
        links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
        bump = nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = grain
        bump.inputs["Distance"].default_value = .008
        links.new(tex.outputs["Fac"], bump.inputs["Height"])
        links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def materials():
    values = {
        "iron": ((.19, .21, .23), .85, .35, .24),
        "steel": ((.42, .48, .52), .9, .23, .14),
        "silver": ((.65, .72, .75), .95, .18, .05),
        "elven": ((.48, .32, .10), .8, .25, .12),
        "gold": ((.63, .39, .08), .85, .23, .10),
        "copper": ((.48, .19, .08), .8, .28, .15),
        "mithril": ((.48, .65, .66), .9, .23, .10),
        "wood": ((.13, .055, .021), 0, .48, .48),
        "leather": ((.16, .065, .026), 0, .62, .65),
        "hide": ((.30, .19, .095), 0, .76, .75),
        "cloth": ((.17, .21, .24), 0, .92, .75),
        "fur": ((.23, .18, .12), 0, .95, .9),
        "black": ((.012, .015, .016), 0, .75, .1),
        "paper": ((.67, .56, .36), 0, .85, .3),
        "bone": ((.68, .62, .46), 0, .65, .28),
        "red": ((.30, .025, .018), 0, .36, .18),
        "blue": ((.025, .12, .31), 0, .28, .1),
        "green": ((.035, .20, .08), 0, .48, .3),
        "leaf": ((.055, .17, .028), 0, .66, .28),
        "purple": ((.13, .025, .17), 0, .35, .1),
        "milk": ((.88, .83, .68), 0, .32, 0),
        "bread": ((.35, .14, .035), 0, .8, .9),
        "glass": ((.75, .88, .85), 0, .08, 0, 1),
        "fire": ((1, .24, .015), 0, .28, 0, .15, 2),
        "gem": ((.06, .38, .33), .25, .14, 0, .2),
        "skin": ((.43, .225, .135), 0, .52, .12),
        "skin_crease": ((.245, .105, .063), 0, .65, 0),
        "nail": ((.48, .285, .225), 0, .44, .025),
    }
    for name, args in values.items():
        M[name] = material(name, *args)
    skin = M["skin"].node_tree.nodes.get("Principled BSDF")
    skin.inputs["Subsurface Weight"].default_value = .08
    skin.inputs["Subsurface Scale"].default_value = .025
    for node in M["skin"].node_tree.nodes:
        if node.type == "TEX_NOISE":
            node.inputs["Scale"].default_value = 180
        elif node.type == "BUMP":
            node.inputs["Distance"].default_value = .002
        elif node.type == "VALTORGB":
            for element, factor in zip(node.color_ramp.elements, (.94, 1.04)):
                element.color = (*(.43 * factor, .225 * factor, .135 * factor), 1)


def finish(obj, mat, bevel=0, smooth=True):
    obj.data.materials.append(M[mat] if isinstance(mat, str) else mat)
    if bevel:
        mod = obj.modifiers.new("worn bevel", "BEVEL")
        mod.width, mod.segments = bevel, 3
    if smooth and hasattr(obj.data, "polygons"):
        for face in obj.data.polygons:
            face.use_smooth = True
    return obj


def box(loc, scale, mat, bevel=.035):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.object
    obj.dimensions = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return finish(obj, mat, bevel, False)


def sphere(loc, scale, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, location=loc)
    obj = bpy.context.object
    obj.scale = scale
    return finish(obj, mat)


def rod(start, end, radius, mat, vertices=16):
    start, end = Vector(start), Vector(end)
    vec = end - start
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=vec.length,
                                       location=(start + end) / 2)
    obj = bpy.context.object
    obj.rotation_euler = vec.to_track_quat("Z", "Y").to_euler()
    return finish(obj, mat, min(.015, radius / 4))


def tube(points, radius, mat):
    curve = bpy.data.curves.new("formed wire", "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth, curve.bevel_resolution = radius, 3
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, co in zip(spline.points, points):
        point.co = (*co, 1)
    obj = bpy.data.objects.new("formed wire", curve)
    bpy.context.collection.objects.link(obj)
    return finish(obj, mat)


def ring(loc, major, minor, mat, scale=None):
    bpy.ops.mesh.primitive_torus_add(major_radius=major, minor_radius=minor,
                                    major_segments=32, minor_segments=8, location=loc)
    obj = bpy.context.object
    if scale:
        obj.scale = scale
    return finish(obj, mat)


def plate(points, depth, mat, z=0, bevel=.025):
    n = len(points)
    verts = [(x, y, z + side * depth / 2) for side in (-1, 1) for x, y in points]
    faces = [tuple(reversed(range(n))), tuple(range(n, 2 * n))]
    faces += [(i, (i + 1) % n, (i + 1) % n + n, i + n) for i in range(n)]
    mesh = bpy.data.meshes.new("forged profile")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("forged profile", mesh)
    bpy.context.collection.objects.link(obj)
    return finish(obj, mat, bevel, False)


def lathe(profile, mat, offset=(0, 0, 0)):
    verts, faces, segments = [], [], 40
    for y, radius in profile:
        for j in range(segments):
            a = j * math.tau / segments
            verts.append((offset[0] + radius * math.cos(a), offset[1] + y,
                          offset[2] + radius * math.sin(a)))
    for i in range(len(profile) - 1):
        for j in range(segments):
            a = i * segments + j
            b = i * segments + (j + 1) % segments
            faces.append((a, a + segments, b + segments, b))
    faces += [tuple(range(segments)), tuple(reversed(range((len(profile) - 1) * segments, len(profile) * segments)))]
    mesh = bpy.data.meshes.new("turned form")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new("turned form", mesh)
    bpy.context.collection.objects.link(obj)
    return finish(obj, mat, .008)


def rivet(x, y, z=.18, mat="gold"):
    sphere((x, y, z), (.033, .033, .018), mat)


def bare_fist():
    """A palm-facing closed hand: four curled fingers and a crossing thumb."""
    parts = []

    def flesh(loc, scale, angle=0):
        obj = sphere(loc, scale, "skin")
        obj.rotation_euler.z = angle
        parts.append(obj)
        return obj

    # Continuous palm, heel and open-ended wrist. Voxel fusion removes the
    # primitive intersections without erasing the gaps between curled fingers.
    wrist = lathe([(-.99, .255), (-.85, .26), (-.55, .28), (-.3, .34)], "skin")
    wrist.scale.z = .58
    parts.append(wrist)
    flesh((-.015, -.14, -.015), (.535, .49, .22))
    flesh((-.30, -.22, .025), (.25, .31, .20), -.2)
    flesh((.31, -.18, .04), (.26, .36, .23), .25)
    # The little finger sits lower; the middle knuckle is highest. Each finger
    # bends forward and down into the palm, rather than extending like a glove.
    fingers = [(-.425, .33, .135), (-.155, .48, .15),
               (.135, .52, .15), (.405, .43, .14)]
    for x, y, width in fingers:
        flesh((x, y - .08, .015), (width, .20, .18), -.07)
        flesh((x - .012, y - .10, .21), (width * .99, .265, .185), -.07)
        flesh((x - .015, y - .245, .15), (width * .90, .105, .105))
    # Thenar mound and two thumb segments cross the front of the index finger.
    flesh((.47, -.08, .07), (.23, .32, .22), -.25)
    flesh((.43, .16, .26), (.175, .27, .17), -.58)
    flesh((.225, .285, .375), (.225, .155, .12), .38)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in parts:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    hand = bpy.context.object
    # Apply the wrist's bevel before the union, then smooth the organic surface.
    for mod in list(hand.modifiers):
        bpy.ops.object.modifier_apply(modifier=mod.name)
    remesh = hand.modifiers.new("continuous anatomy", "REMESH")
    remesh.mode, remesh.voxel_size = "VOXEL", .009
    remesh.use_smooth_shade = True
    bpy.ops.object.modifier_apply(modifier=remesh.name)
    smooth = hand.modifiers.new("soft skin", "SMOOTH")
    smooth.factor, smooth.iterations = .65, 25
    bpy.ops.object.modifier_apply(modifier=smooth.name)
    # Only the thumb nail faces the viewer; the other nails are tucked inside.
    nail = sphere((.215, .292, .489), (.125, .093, .013), "nail")
    nail.rotation_euler.z = .38
    # Fine flexion lines follow the skin surface; they read at inventory scale
    # without turning the hand into separated armored finger plates.
    def crease(points, radius=.0018):
        surface = []
        for x, y in points:
            hit, position, _normal, _face = hand.ray_cast(Vector((x, y, 2)), Vector((0, 0, -1)))
            if hit:
                surface.append((position.x, position.y, position.z + .0005))
        if len(surface) > 1:
            tube(surface, radius, "skin_crease")

    for x, y, width in fingers[:3]:
        for offset in (-.10, -.075):
            crease([(x - width * .57 + j * width * 1.14 / 14,
                     y + offset + .015 * math.sin(j * math.pi / 14)) for j in range(15)])
    crease([(.28 - .21 * t + .04 * t * t, .03 - .40 * t) for t in [j / 24 for j in range(25)]])
    crease([(-.33 + .36 * t, -.10 - .10 * math.sin(t * math.pi / 2)) for t in [j / 24 for j in range(25)]])
    crease([(-.20 + .41 * t, -.49 - .012 * math.sin(t * math.pi)) for t in [j / 24 for j in range(25)]], .0014)


def weapon(iid, mat):
    if any(s in iid for s in ("arrow", "bolt")) or iid == "_ammo":
        length = 1.0 if "bolt" in iid else 1.5
        rod((0, -length, 0), (0, length - .35, 0), .035, "wood")
        plate([(-.16, length - .4), (0, length), (.16, length - .4), (0, length - .32)], .07, mat)
        for side in (-1, 1):
            plate([(side * .04, -length + .15), (side * .22, -length + .2),
                   (side * .20, -length + .72), (side * .04, -length + .88)], .025, "bone")
        return
    if "bow" in iid:
        cross = "crossbow" in iid
        pts = []
        for i in range(41):
            t = i / 40
            x = -.65 * math.sin(t * math.pi)
            y = (t - .5) * 2.6
            pts.append((y if cross else x, x if cross else y, .03))
        tube(pts, .055, "elven" if "elven" in iid else "wood")
        tube([pts[0], pts[-1]], .008, "paper")
        if cross:
            box((0, -.35, 0), (.16, 2, .16), "wood")
            rod((0, -.1, .12), (0, .8, .12), .025, "steel")
        else:
            rod((-.62, -.2, .02), (-.62, .2, .02), .085, "leather")
        return
    if "staff" in iid:
        rod((0, -1.3, 0), (.04, 1.1, 0), .065, "wood")
        ring((0, 1.08, 0), .17, .04, "gold")
        sphere((0, 1.08, .03), (.11, .16, .11), "gem")
        return
    if iid == "fist":
        bare_fist()
        return
    if iid in ("bucket", "milk"):
        lathe([(-.65, .42), (-.6, .44), (.5, .60), (.53, .56), (-.56, .38)], "wood")
        for y, r in [(-.5, .46), (.35, .58)]:
            obj = ring((0, y, 0), r, .035, "iron")
            obj.rotation_euler[0] = math.pi / 2
        tube([(.55 * math.cos(t), .5 + .55 * math.sin(t), 0) for t in [i * math.pi / 24 for i in range(25)]], .025, "iron")
        if iid == "milk":
            rod((0, .34, 0), (0, .36, 0), .52, "milk", 40)
        return
    length = 1.1 if "dagger" in iid else 1.6
    if "shortsword" in iid:
        length = 1.3
    rod((0, -1.15, 0), (0, -.45, 0), .075, "leather")
    for y in [-1.1 + i * .085 for i in range(8)]:
        obj = ring((0, y, 0), .075, .008, "copper")
        obj.rotation_euler[0] = math.pi / 2
    sphere((0, -1.22, 0), (.12, .12, .11), mat)
    if any(s in iid for s in ("sword", "saber", "dagger")) or iid == "_weapon":
        width = .13 if "dagger" in iid else .18
        tipx = .26 if "saber" in iid else 0
        plate([(-width, -.4), (-width * .8, length - .3), (tipx, length),
               (width, length - .3), (width, -.4)], .085, mat)
        rod((-.36, -.4, 0), (.36, -.4, 0), .055, mat)
        rod((0, -.25, .05), (tipx * .5, length - .32, .05), .018, "silver")
    else:
        rod((0, -.5, 0), (0, 1.15, 0), .065, "wood")
        if "mace" in iid:
            sphere((0, 1.0, 0), (.26, .4, .26), mat)
            for angle in range(0, 360, 60):
                x, z = .23 * math.cos(math.radians(angle)), .23 * math.sin(math.radians(angle))
                plate([(x - .035, .75), (x + .035, .75), (x + .08, 1), (x + .035, 1.3), (x - .035, 1.3)], .18, mat, z)
        elif "hammer" in iid:
            box((0, 1, 0), (.95, .37, .38), mat, .055)
        elif "scythe" in iid:
            plate([(0, 1.08), (.05, 1.28), (.6, 1.22), (1.05, 1),
                   (1.4, .5), (1.05, .82), (.55, 1.03)], .07, mat)
            rod((0, -.4, 0), (.32, -.4, .03), .04, "wood")
        elif "axe" in iid:
            plate([(-.1, .78), (-.1, 1.18), (.35, 1.48), (.75, 1.25), (.85, .55), (.35, .7)], .12, mat)
        elif "pitchfork" in iid:
            tube([(-.35, 1.45, 0), (-.35, .7, 0), (.35, .7, 0), (.35, 1.45, 0)], .045, mat)
            rod((0, .7, 0), (0, 1.45, 0), .045, mat)
        elif "shovel" in iid:
            plate([(-.3, .6), (.3, .6), (.38, 1.15), (0, 1.6), (-.38, 1.15)], .08, mat)
        else:
            sphere((0, .72, 0), (.19, .62, .18), "wood")


def armor(iid, mat):
    if any(s in iid for s in ("shield", "buckler")):
        round_ = any(s in iid for s in ("round", "buckler", "iron_shield"))
        pts = [(math.cos(i * math.tau / 48) * .85, math.sin(i * math.tau / 48) * .85) for i in range(48)] if round_ else [(-.8, .95), (.8, .95), (.72, -.25), (0, -1.1), (-.72, -.25)]
        plate(pts, .16, "wood", bevel=.04)
        tube([(x, y, .1) for x, y in pts + [pts[0]]], .045, mat)
        if round_:
            sphere((0, 0, .15), (.27, .27, .14), mat)
        else:
            box((0, .05, .13), (.15, 1.45, .04), mat)
            box((0, .35, .13), (1.15, .12, .04), mat)
        for x, y in pts[::max(1, len(pts) // 10)]:
            rivet(x * .9, y * .9, .14, mat)
        return
    if any(s in iid for s in ("helmet", "helm", "cap", "coif", "hood")):
        sphere((0, .15, 0), (.72, .92, .55), mat)
        plate([(-.42, .1), (.42, .1), (.35, -.58), (0, -.7), (-.35, -.58)], .02, "black", .53)
        if any(s in iid for s in ("iron", "steel", "plate", "scale")):
            box((0, -.15, .59), (.10, .85, .08), mat)
            for x in (-.25, .25):
                box((x, -.28, .56), (.36, .2, .06), mat)
                box((x, -.2, .61), (.24, .035, .012), "black", .005)
        tube([(-.64, -.42, .20), (-.4, -.65, .37), (0, -.73, .42), (.4, -.65, .37), (.64, -.42, .20)], .055, mat)
        return
    if any(s in iid for s in ("boots", "sabatons", "sandals")):
        for side in (-1, 1):
            x = side * .42
            if "sandals" in iid:
                box((x, -.3, -.05), (.53, 1.05, .09), "leather", .09)
                for y in (-.5, -.1, .1):
                    tube([(x - .24, y, 0), (x - .18, y, .16), (x + .18, y, .16), (x + .24, y, 0)], .035, "hide")
                continue
            box((x, -.45, .11), (.55, .83, .3), mat, .13)
            box((x, .12, -.03), (.45, .80 if "sandals" not in iid else .15, .36), mat, .1)
            box((x, -.5, -.09), (.57, .82, .09), "black", .025)
            for y in [-.55, -.35, -.15]:
                box((x, y, .29), (.43, .045, .035), "leather", .01)
                rivet(x, y, .33)
        return
    if any(s in iid for s in ("greaves", "leggings", "trousers")):
        for side in (-1, 1):
            x = side * .4
            plate([(x - .27, .9), (x + .27, .9), (x + .2, -.85), (x - .18, -.85)], .22, mat)
            if "trousers" not in iid:
                sphere((x, .45, .18), (.25, .27, .12), mat)
                for y in (-.6, .1):
                    box((x, y, .14), (.48, .08, .07), "leather")
                    rivet(x + .15, y, .2)
        return
    if any(s in iid for s in ("gauntlets", "gloves", "wraps", "bracers")):
        for side in (-1, 1):
            x = side * .43
            box((x, -.25, 0), (.52, .9, .2), mat, .1)
            if "bracers" not in iid:
                for j in range(4):
                    box((x - .18 + j * .12, .37, 0), (.11, .58 - .08 * abs(j - 1), .20), mat, .04)
                sphere((x + side * .28, .05, .05), (.13, .28, .12), mat)
            for y in (-.5, -.1):
                box((x, y, .12), (.5, .06, .05), "leather", .01)
                rivet(x, y, .17)
        return
    robe = "robe" in iid
    outline = [(-.82, .8), (-.32, 1), (-.20, .80), (.20, .80), (.32, 1), (.82, .8),
               (.72, .38), (.49, .24), (.46, -.35), (.73 if robe else .57, -1.3 if robe else -.8),
               (0, -1.33 if robe else -.93), (-.73 if robe else -.57, -1.3 if robe else -.8), (-.46, -.35), (-.49, .24), (-.72, .38)]
    plate(outline, .23, mat, bevel=.06)
    if mat in ("iron", "steel", "elven", "mithril"):
        sphere((0, .1, .12), (.47, .65, .18), mat)
        tube([(-.47, -.4, .17), (0, -.5, .27), (.47, -.4, .17)], .022, "gold")
    for x in (-.38, .38):
        box((x, .12, .27), (.08, 1.2, .04), "leather", .01)
        for y in (-.35, .25, .65):
            rivet(x, y, .31)
    box((0, -.38, .3), (1.05, .12, .06), "leather")
    ring((0, -.38, .35), .075, .018, "gold", (1.3, 1, 1))
    if "chain" in iid or "mithril" in iid:
        for row in range(9):
            for col in range(7):
                ring((-.34 + col * .11 + (row % 2) * .025, -.68 + row * .16, .33), .045, .011, mat)
    if "scale" in iid:
        for row in range(6):
            for col in range(5):
                sphere((-.34 + col * .17, -.6 + row * .23, .35), (.105, .16, .025), mat)


def potion(iid):
    color = "blue" if "magicka" in iid else "green" if "stamina" in iid else "purple" if "cure" in iid else "gold" if "shield" in iid else "red"
    radius = .46 if "minor" in iid else .6
    profile = [(-.75, .12), (-.7, radius * .75), (-.45, radius), (.1, radius), (.4, .23), (.8, .19), (.85, .22)]
    inner = [(y + .03, max(.025, r - .035)) for y, r in profile]
    lathe(profile + list(reversed(inner)), "glass")
    lathe([(-.67, .1), (-.62, radius * .65), (-.4, radius * .87),
           (.05, radius * .87), (.19, radius * .75), (.19, 0)], color)
    lathe([(.78, .15), (.96, .17), (1.01, .18)], "wood")
    obj = ring((0, .6, 0), .21, .025, "gold")
    obj.rotation_euler[0] = math.pi / 2
    box((0, -.08, radius + .005), (.30, .32, .015), "paper", .01)
    box((0, -.08, radius + .02), (.07, .23, .01), color, .005)
    box((0, -.08, radius + .025), (.21, .06, .01), color, .005)


def misc(iid, record):
    if "ring" in iid:
        ring((0, 0, 0), .65, .11, "copper" if "copper" in iid else "gold")
        if "protection" in iid:
            sphere((0, .62, .15), (.18, .18, .12), "blue")
        return
    if any(s in iid for s in ("amulet", "keepsake")):
        ring((0, .35, 0), .65, .027, "silver", (.8, 1.25, 1))
        ring((0, -.45, .05), .1, .02, "gold")
        sphere((0, -.7, .04), (.3, .4, .08), "silver" if "silver" in iid else "gold")
        sphere((0, -.7, .13), (.14, .24, .05), "gem")
        return
    if "book" in iid or "tome" in iid or iid == "_book":
        color = {"book_marksman": "hide", "book_blade": "red", "book_lore": "blue",
                 "book_last_ferryman": "black", "book_ember_wyrm": "copper",
                 "book_lament_greywood": "green", "ember_tome": "purple"}.get(iid, "leather")
        box((0, 0, 0), (1.25, 1.7, .24), "paper", .025)
        for z in (-.16, .16):
            box((0, 0, z), (1.37, 1.82, .065), color, .025)
        box((-.64, 0, 0), (.12, 1.82, .36), color)
        for y in (-.65, -.35, .35, .65):
            box((-.66, y, .1), (.15, .055, .25), "gold", .01)
        ring((.03, .08, .21), .29, .022, "gold", (1, 1.25, 1))
        spokes = 3 + int(hashlib.sha256(iid.encode()).hexdigest()[:2], 16) % 5
        for i in range(spokes):
            angle = i * math.tau / spokes
            rod((.03, .08, .22), (.03 + math.sin(angle) * .22, .08 + math.cos(angle) * .28, .22), .014, "gold")
        for y in (-.65, .65):
            box((.02, y, .21), (.85, .02, .018), "gold", .004)
        return
    if "letter" in iid:
        box((0, 0, 0), (1.45, 1, .025), "paper", .015)
        tube([(-.72, .5, .022), (0, -.12, .022), (.72, .5, .022)], .008, "leather")
        sphere((0, -.12, .035), (.16, .16, .026), "red")
        return
    if iid in ("gold", "_gold"):
        for i, (x, y) in enumerate([(-.35, -.2), (.25, -.25), (.08, .32), (-.2, .2), (.43, .28)]):
            rod((x, y, i * .045), (x, y, i * .045 + .06), .36, "gold", 40)
            ring((x, y, i * .045 + .065), .29, .015, "gold")
            box((x, y, i * .045 + .075), (.04, .27, .012), "gold", .005)
        return
    if iid == "lockpick":
        tube([(-.72, -.35, 0), (.68, -.35, 0), (.83, -.19, 0), (.83, .08, 0)], .025, "steel")
        box((-.67, -.35, 0), (.5, .12, .08), "wood")
        tube([(-.75, .24, 0), (.67, .24, 0), (.75, .36, 0)], .02, "iron")
        return
    if iid == "torch":
        rod((0, -1, 0), (0, .6, 0), .08, "wood")
        for y in [.3 + i * .08 for i in range(6)]:
            obj = ring((0, y, 0), .14, .045, "leather")
            obj.rotation_euler[0] = math.pi / 2
        lathe([(.6, .12), (.85, .25), (1.15, .12), (1.5, 0)], "fire")
        return
    if "satchel" in iid or iid == "_misc":
        box((0, -.18, 0), (1.4, 1.1, .4), "leather", .15)
        box((0, .18, .26), (1.3, .58, .12), "hide", .10)
        tube([(-.6, .25, 0), (-.65, .85, -.03), (0, 1.04, -.03), (.65, .85, -.03), (.6, .25, 0)], .045, "leather")
        for x in (-.4, .4):
            box((x, -.04, .35), (.1, .7, .04), "leather")
            ring((x, -.15, .39), .085, .018, "gold", (1, 1.2, 1))
        return
    if "hammer" in iid:
        rod((0, -.85, 0), (0, .6, 0), .07, "wood")
        box((0, .62, 0), (.9, .32, .32), "steel")
        return
    if iid == "bread":
        sphere((0, 0, 0), (.8, .55, .32), "bread")
        for x in (-.4, -.1, .2, .5):
            tube([(x - .08, -.2, .27), (x + .02, .1, .32), (x + .1, .3, .23)], .025, "paper")
        return
    if iid == "egg":
        sphere((0, 0, 0), (.49, .74, .45), "bone")
        return
    if iid == "wool":
        sphere((0, 0, 0), (.65, .65, .5), "bone")
        for i in range(18):
            t = i * math.tau / 18
            tube([(.65 * math.cos(a), .65 * math.sin(a), .15 * math.sin(a * 4 + t))
                  for a in [j * math.tau / 40 + t for j in range(41)]], .025, "paper")
        return
    if "mushroom" in iid:
        for x, y, size in [(-.35, -.1, .85), (.35, .15, 1)]:
            rod((x, y - .65 * size, 0), (x, y + .25 * size, 0), .11 * size, "bone")
            sphere((x, y + .26 * size, 0), (.42 * size, .17 * size, .36 * size), "bread")
        return
    if "pelt" in iid:
        plate([(-.3, 1), (.3, 1), (.75, .7), (.55, .22), (.7, -.65), (.35, -.85), (0, -.65),
               (-.35, -.85), (-.7, -.65), (-.55, .22), (-.75, .7)], .065, "fur", bevel=.08)
        return
    if "bonemeal" in iid:
        lathe([(-.4, .3), (-.25, .6), (.1, .7), (.14, .63), (-.19, .52)], "wood")
        sphere((0, -.02, 0), (.58, .13, .58), "bone")
        return
    # Flax / nightshade and the ingredient fallback: stems, leaves and flowers.
    for i in range(3):
        x = (i - 1) * .3
        tube([(0, -.9, 0), (x, .1, .02), (x * 1.3, .85 - i * .12, 0)], .018, "leaf")
        for side in (-1, 1):
            leaf = sphere((x + side * .18, .1 + i * .14, .04), (.25, .09, .025), "leaf")
            leaf.rotation_euler[2] = side * .5
        color = "purple" if "nightshade" in iid else "blue"
        for j in range(5):
            t = j * math.tau / 5
            sphere((x * 1.3 + math.cos(t) * .1, .85 - i * .12 + math.sin(t) * .1, .04), (.09, .09, .025), color)


def build(iid, record):
    mat = next((m for m in ("mithril", "elven", "silver", "steel", "copper", "iron") if m in iid), "iron")
    category = record.get("category", "")
    if iid.startswith("_"):
        category = {"_ammo": "ammo", "_armor": "armour", "_armour": "armour", "_potion": "potion", "_weapon": "weapon"}.get(iid, "misc")
    if iid in ("milk", "bucket"):
        weapon(iid, mat)
    elif category in ("weapon", "ammo") or iid == "arrow":
        weapon(iid, mat)
    elif category == "armour":
        if any(s in iid for s in ("ring", "amulet", "keepsake")):
            misc(iid, record)
        else:
            mat = "cloth" if any(s in iid for s in ("cloth", "sandals", "hood")) else "hide" if "hide" in iid else "leather" if any(s in iid for s in ("leather", "studded")) else "fur" if "fur" in iid else mat
            armor(iid, mat)
    elif category == "potion" and iid != "bread":
        potion(iid)
    else:
        misc(iid, record)


def setup(samples):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = False
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = .015
    scene.cycles.max_bounces = 12
    scene.cycles.transmission_bounces = 8
    scene.render.resolution_x = scene.render.resolution_y = 256
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.world = bpy.data.worlds.new("studio")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs[0].default_value = (.32, .36, .42, 1)
    scene.world.node_tree.nodes["Background"].inputs[1].default_value = .3
    bpy.ops.object.camera_add(location=(2.1, -3.2, 12))
    camera = bpy.context.object
    camera.rotation_euler = (Vector((0, 0, 0)) - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 3.8
    scene.camera = camera
    for loc, energy, color, size in [((-3, 4, 6), 650, (1, .86, .67), 4), ((4, 0, 3), 450, (.65, .8, 1), 3), ((0, -3, 2), 180, (1, .6, .32), 2)]:
        bpy.ops.object.light_add(type="AREA", location=loc)
        light = bpy.context.object
        light.data.energy, light.data.color, light.data.shape, light.data.size = energy, color, "DISK", size
        light.rotation_euler = (-light.location).to_track_quat("-Z", "Y").to_euler()
    materials()
    return scene


def frame(scene):
    objects = [o for o in scene.objects if o.type in ("MESH", "CURVE")]
    bpy.context.view_layer.update()
    # Fit projected bounds, preserving upright arrows and leaving a safe gutter.
    inv = scene.camera.matrix_world.inverted()
    corners = [inv @ (o.matrix_world @ Vector(corner)) for o in objects for corner in o.bound_box]
    xmin, xmax = min(p.x for p in corners), max(p.x for p in corners)
    ymin, ymax = min(p.y for p in corners), max(p.y for p in corners)
    center = scene.camera.matrix_world.to_quaternion() @ Vector(((xmin + xmax) / 2, (ymin + ymax) / 2, 0))
    scene.camera.location += center
    scene.camera.data.ortho_scale = max(xmax - xmin, ymax - ymin) / .79


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "work/realistic-icons")
    parser.add_argument("--only", default="")
    parser.add_argument("--samples", type=int, default=160)
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = parser.parse_args(argv)
    if bpy is None:
        raise SystemExit("Run this asset-production script inside Blender")
    db = json.loads((ROOT / "game/data/items.json").read_text())
    for iid, category in [("_ammo", "ammo"), ("_armor", "armour"), ("_armour", "armour"),
                          ("_book", "book"), ("_gold", "gold"), ("_ingredient", "ingredient"),
                          ("_misc", "misc"), ("_potion", "potion"), ("_weapon", "weapon"), ("arrow", "ammo")]:
        db[iid] = {"category": category}
    ids = args.only.split(",") if args.only else list(db)
    args.output.mkdir(parents=True, exist_ok=True)
    for index, iid in enumerate(ids):
        seed = int(hashlib.sha256(iid.encode()).hexdigest()[:8], 16)
        random.seed(seed)
        M.clear()
        scene = setup(args.samples)
        build(iid, db[iid])
        if iid == "fist":
            # A nearly frontal view keeps the thumb crossing and four folded
            # fingers readable at quickbar size, under the same studio lights.
            scene.camera.location = (.6, -1.5, 12)
            scene.camera.rotation_euler = (-scene.camera.location).to_track_quat("-Z", "Y").to_euler()
        if db[iid].get("category") == "ammo":
            scene.camera.location.x = 0
            scene.camera.rotation_euler = (-scene.camera.location).to_track_quat("-Z", "Y").to_euler()
        # Give otherwise identical crafted pieces their own finish, without
        # changing the item's identity, color family or gameplay data.
        for mat in M.values():
            if mat.use_nodes:
                node = mat.node_tree.nodes.get("Principled BSDF")
                node.inputs["Roughness"].default_value *= .94 + random.random() * .12
        frame(scene)
        scene.render.filepath = str((args.output / f"{iid}.png").resolve())
        bpy.ops.render.render(write_still=True)
        print(f"ITEM_ICON {index + 1}/{len(ids)} {iid}", flush=True)


if __name__ == "__main__":
    main()
