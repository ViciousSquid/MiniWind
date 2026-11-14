"""Render exported woodland assets with Blender (no art add-ons required).

blender -b -t 4 -P game/tools/render_tree_models.py -- --work work/trees
The pictured meshes are read back from the shipped OBJ exports.
"""
import argparse
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[2]
FOLDER=ROOT/'assets/models/trees'


def material(name,color):
    mat=bpy.data.materials.new(name)
    mat.diffuse_color=(*color,1)
    mat.use_nodes=True
    bsdf=mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value=(*color,1)
    bsdf.inputs['Roughness'].default_value=1
    return mat


def read_obj(path,mat):
    verts=[];uvs=[];faces=[];tex=[]
    for line in path.read_text().splitlines():
        p=line.split()
        if not p: continue
        if p[0]=='v':
            x,y,z=map(float,p[1:4]);verts.append((x,-z,y))
        elif p[0]=='vt': uvs.append(tuple(map(float,p[1:3])))
        elif p[0]=='f':
            idx=[s.split('/') for s in p[1:]]
            faces.append(tuple(int(i[0])-1 for i in idx))
            tex.append([uvs[int(i[1])-1] for i in idx])
    data=bpy.data.meshes.new(path.stem)
    data.from_pydata(verts,[],faces);data.update()
    obj=bpy.data.objects.new(path.stem,data)
    bpy.context.collection.objects.link(obj)
    data.materials.append(mat)
    layer=data.uv_layers.new()
    for poly,uv in zip(data.polygons,tex):
        for li,t in zip(poly.loop_indices,uv): layer.data[li].uv=t
    return obj


def person(mat):
    # A 100-unit scale figure, presentation only.
    for x in (-410,-396):
        bpy.ops.mesh.primitive_cube_add(size=1,location=(x,-110,20))
        o=bpy.context.object;o.dimensions=(9,12,40);o.data.materials.append(mat)
    bpy.ops.mesh.primitive_cube_add(size=1,location=(-403,-110,60))
    o=bpy.context.object;o.dimensions=(28,17,40);o.data.materials.append(mat)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1,radius=10,location=(-403,-110,90))
    bpy.context.object.data.materials.append(mat)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--work',type=Path,default=ROOT/'work/trees')
    parser.add_argument('--only',nargs='*')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    args.work.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mat=material('Woodland palette',(1,1,1))
    img=bpy.data.images.load(str(FOLDER/'tree_palette.png'))
    node=mat.node_tree.nodes.new('ShaderNodeTexImage');node.image=img;node.interpolation='Closest'
    mat.node_tree.links.new(node.outputs['Color'],mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'])
    person(material('100 Fio units',(.20,.33,.34)))
    bpy.ops.mesh.primitive_plane_add(size=20000,location=(0,0,-1))
    bpy.context.object.data.materials.append(material('Preview ground',(.24,.26,.22)))
    scene=bpy.context.scene;scene.render.engine='CYCLES';scene.cycles.samples=16
    scene.cycles.use_denoising=False
    scene.render.resolution_x=320;scene.render.resolution_y=360
    scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    scene.world=bpy.data.worlds.new('World');scene.world.use_nodes=True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.65,.72,.78,1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value=.65
    scene.view_settings.view_transform='AgX'
    bpy.ops.object.light_add(type='SUN',location=(-1000,-2000,2200))
    light=bpy.context.object;light.rotation_euler=(.45,-.55,-.5);light.data.energy=2.4;light.data.angle=.18
    bpy.ops.object.camera_add(location=(1100,-2300,1150))
    scene.camera=bpy.context.object
    scene.camera.rotation_euler=(Vector((-30,0,410))-scene.camera.location).to_track_quat('-Z','Y').to_euler()
    scene.camera.data.type='ORTHO';scene.camera.data.ortho_scale=1170
    scene.camera.data.clip_end=30000
    for info in json.loads((FOLDER/'tree_kit.json').read_text())['models']:
        if args.only and info['name'] not in args.only: continue
        obj=read_obj(FOLDER/info['obj'],mat)
        scene.render.filepath=str(args.work/(info['name']+'.png'))
        bpy.ops.render.render(write_still=True)
        bpy.data.objects.remove(obj,do_unlink=True)
        print('TREE_PREVIEW '+info['name'],flush=True)


if __name__=='__main__': main()
