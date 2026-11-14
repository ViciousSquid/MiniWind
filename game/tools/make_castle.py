"""Build MiniWind's castle kit. Blender 4.3+: blender -b -t 4 -P this_file.

Original meshes and baked stone colour; no external art or add-ons.
Author Z-up, export Y-up in Fio units, like make_windmill.py.
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
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / 'assets/models'
PARTS = []
MATS = {}
TAU = math.tau


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


def stone_texture():
    rng = random.Random(61013)
    size, rows, cols = 1024, 16, 8
    colors = [[rng.choice(((.43,.42,.36),(.49,.47,.40),(.54,.51,.43),
                          (.46,.46,.41),(.58,.54,.45),(.40,.41,.37)))
               for _ in range(cols)] for _ in range(rows)]
    pixels = array('f')
    # Periodic noise keeps the tile edges continuous. Stones are paint, not
    # thousands of separate bricks: the wall can be repeated cheaply.
    for y in range(size):
        row, fy = divmod(y * rows / size, 1)
        for x in range(size):
            col, fx = divmod(x * cols / size + .5 * (int(row) % 2), 1)
            edge = min(fx * 2, (1-fx) * 2, fy, 1-fy)
            mortar = edge < .035
            c = (.27,.28,.25) if mortar else colors[int(row)][int(col) % cols]
            grain = .94 + .12 * rng.random()
            relief = .90 if edge < .065 else 1.0
            fleck = .86 if rng.random() < .012 else 1
            pixels.extend((*(v * grain * relief * fleck for v in c), 1))
    img = bpy.data.images.new('Castle stone', size, size, alpha=False)
    img.pixels.foreach_set(pixels)
    img.filepath_raw = str(MODELS / 'castle_stone_albedo.png')
    img.file_format = 'PNG'
    img.save()
    mat = material('Castle_stone', (1,1,1))
    node = mat.node_tree.nodes.new('ShaderNodeTexImage')
    node.image = img
    mat.node_tree.links.new(node.outputs['Color'], mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'])
    img.pack()
    material('Dressed_stone', (.57,.55,.47))
    material('Foundation', (.34,.37,.31))
    material('Oak', (.20,.105,.048))
    material('Iron', (.065,.075,.072), .3)
    material('Recess', (.055,.065,.060))


def mesh(name, verts, faces, mat, uvs=None):
    data = bpy.data.meshes.new(name)
    data.from_pydata(verts, [], faces)
    data.update()
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(MATS[mat])
    layer = data.uv_layers.new(name='UVMap')
    for poly in data.polygons:
        # Planar world-scale mapping for boxes; lathes supply cylindrical UVs.
        normal = poly.normal
        axes = (1,2) if abs(normal.x) > .7 else (0,2) if abs(normal.y) > .7 else (0,1)
        for k, li in enumerate(poly.loop_indices):
            v = data.vertices[data.loops[li].vertex_index].co
            layer.data[li].uv = uvs[poly.index][k] if uvs else (v[axes[0]]/256, v[axes[1]]/256)
    PARTS.append(obj)
    return obj


def box(name, center, size, mat='Dressed_stone', yaw=0):
    x,y,z = center
    a,b,c = (s/2 for s in size)
    co,si = math.cos(yaw),math.sin(yaw)
    verts = [(x+co*i-si*j,y+si*i+co*j,z+k)
             for i,j,k in ((-a,-b,-c),(a,-b,-c),(a,b,-c),(-a,b,-c),
                           (-a,-b,c),(a,-b,c),(a,b,c),(-a,b,c))]
    return mesh(name, verts, [(3,2,1,0),(0,1,5,4),(1,2,6,5),
                              (2,3,7,6),(3,0,4,7),(4,5,6,7)],mat)


def lathe(name, profile, mat, sides=32):
    verts = [(r*math.cos(i*TAU/sides),r*math.sin(i*TAU/sides),z)
             for z,r in profile for i in range(sides)]
    faces, uvs = [], []
    for j in range(len(profile)-1):
        for i in range(sides):
            faces.append((j*sides+i,j*sides+(i+1)%sides,(j+1)*sides+(i+1)%sides,(j+1)*sides+i))
            # An exact circumference tile count avoids a seam at the back.
            uvs.append(((i/sides*5,profile[j][0]/256),((i+1)/sides*5,profile[j][0]/256),
                        ((i+1)/sides*5,profile[j+1][0]/256),(i/sides*5,profile[j+1][0]/256)))
    return mesh(name, verts, faces, mat, uvs)


def sector(name, r0, r1, z0, z1, a0, a1, mat):
    n=2
    verts=[(r*math.cos(a0+(a1-a0)*i/n),r*math.sin(a0+(a1-a0)*i/n),z)
           for z in (z0,z1) for r in (r0,r1) for i in range(n+1)]
    faces=[]
    k=n+1
    for i in range(n):
        faces.extend([(i,i+1,2*k+i+1,2*k+i),
                      (k+i,3*k+i,3*k+i+1,k+i+1),
                      (i,k+i,k+i+1,i+1),
                      (2*k+i,2*k+i+1,3*k+i+1,3*k+i)])
    faces += [(0,2*k,3*k,k),(n,k+n,3*k+n,2*k+n)]
    return mesh(name,verts,[tuple(reversed(f)) for f in faces],mat)


def disk(name, radius, z, mat, sides=32, down=False):
    verts=[(0,0,z)]+[(radius*math.cos(i*TAU/sides),radius*math.sin(i*TAU/sides),z)
                            for i in range(sides)]
    faces=[(0,1+i,1+(i+1)%sides) for i in range(sides)]
    return mesh(name,verts,[tuple(reversed(f)) for f in faces] if down else faces,mat)


def socket(sign, edge, inner, prefix):
    """A flat, wall-profile connection, contained within the asset's X bounds."""
    width=edge-inner
    x=sign*(edge+inner)/2
    for label,z,h,depth,mat in (
            ('foundation',24,48,144,'Foundation'),
            ('masonry',208,352,112,'Castle_stone'),
            ('lower course',100,12,120,'Dressed_stone'),
            ('cornice',376,16,136,'Dressed_stone'),
            ('walkway',388,8,128,'Dressed_stone')):
        box(f'{prefix} {label}',(x,0,z),(width,depth,h),mat)
    for y in (-58,58):
        box(f'{prefix} parapet',(x,y,411),(width,20,38),'Castle_stone')
        box(f'{prefix} coping',(x,y,431),(width,24,6))
        box(f'{prefix} half merlon',(sign*(edge-16),y,453),(32,22,38),'Castle_stone')
        box(f'{prefix} merlon cap',(sign*(edge-16),y,476),(32,26,8))


def tower():
    start=len(PARTS)
    lathe('Battered mossy plinth',[(0,224),(16,224),(72,204)],'Foundation')
    lathe('Tower masonry',[(64,204),(620,192),(636,192)],'Castle_stone')
    # Close ground and roof. This is an exterior scenery shell, like the mill.
    disk('Ground closure',224,0,'Foundation',down=True)
    disk('Roof deck',206,638,'Dressed_stone')
    lathe('Lower string course',[(148,202),(154,206),(164,206),(170,201)],'Dressed_stone')
    lathe('Upper string course',[(478,196),(484,200),(494,200),(500,195)],'Dressed_stone')
    lathe('Corbelled crown',[(606,193),(620,206),(632,214),(644,214)],'Dressed_stone')
    lathe('Circular parapet',[(640,214),(684,214),(684,182),(640,182)],'Castle_stone')
    lathe('Parapet coping',[(680,218),(690,218),(690,178),(680,178)],'Dressed_stone')
    for i in range(16):
        a=i*TAU/16
        sector(f'Merlon {i+1:02}',181,215,684,758,a-.105,a+.105,'Castle_stone')
        sector(f'Merlon cap {i+1:02}',178,218,758,768,a-.115,a+.115,'Dressed_stone')
        # Small brackets under the crown articulate the overhead silhouette.
        box(f'Crown corbel {i+1:02}',(198*math.cos(a),198*math.sin(a),594),
            (24,18,46),'Dressed_stone',a)
    # Front is Blender -Y => Fio +Z. Arched oak door, 120 units high.
    box('Door shadow',(0,-224,51),(70,5,98),'Recess')
    for i in range(7):
        x=(i-3)*9
        h=88+math.sqrt(max(0,32*32-x*x))
        box('Oak door plank',(x,-226,h/2+4),(8.2,4,h),'Oak')
    for x in (-40,40):
        box('Door jamb',(x,-226,48),(12,16,96))
    for i in range(9):
        a0=i*math.pi/9+.018
        a1=(i+1)*math.pi/9-.018
        # Arch wedges in XZ with depth along Y.
        pts=[(r*math.cos(a),y,92+r*math.sin(a))
             for y in (-234,-218) for r,a in ((32,a0),(44,a0),(44,a1),(32,a1))]
        faces=[(3,2,1,0),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
        mesh('Door arch voussoir',pts,[tuple(reversed(f)) for f in faces],'Dressed_stone')
    box('Threshold',(0,-238,4),(96,40,8))
    for z in (32,78):
        box('Iron door strap',(0,-230,z),(61,3,4),'Iron')
    box('Iron latch',(20,-233,55),(4,4,10),'Iron')
    # Shallow dark arrow loops; no alpha surfaces or hidden interior geometry.
    for level in (290,520):
        r=204-(level-64)*12/572
        for i in range(4):
            a=i*TAU/4
            co,si=math.cos(a),math.sin(a)
            for label,w,h,rr,mat in [('Loop surround',27,70,r+1,'Dressed_stone'),
                                    ('Arrow slit',8,52,r+5,'Recess'),
                                    ('Arrow cross',20,6,r+5.5,'Recess')]:
                box(label,(rr*si,-rr*co,level),(w,6,h),mat,a)
            box('Loop sill',((r+7)*si,-(r+7)*co,level-37),(34,14,7),'Dressed_stone',a)
    box('Roof hatch',(40,15,640),(68,82,4),'Oak')
    for x in (17,63):
        box('Hatch strap',(x,15,643),(4,75,2),'Iron')
    for sign in (-1,1):
        socket(sign,224,170,'Tower wall socket')
    return PARTS[start:]


def wall():
    start=len(PARTS)
    # Exact X ends, no projecting trim across them. Period = 512 units.
    box('Wall foundation',(0,0,24),(512,144,48),'Foundation')
    box('Curtain masonry',(0,0,208),(512,112,352),'Castle_stone')
    box('Wall lower course',(0,0,100),(512,120,12))
    box('Walkway cornice',(0,0,376),(512,136,16))
    box('Walkway deck',(0,0,388),(512,128,8))
    # 96-unit clear walk between the parapets, wide enough for a person.
    for y in (-58,58):
        box('Parapet',(0,y,411),(512,20,38),'Castle_stone')
        box('Parapet coping',(0,y,431),(512,24,6))
        for i in range(5):
            cx=-256+i*128
            lo,hi=max(-256,cx-32),min(256,cx+32)
            box('Wall merlon',((lo+hi)/2,y,453), (hi-lo,22,38),'Castle_stone')
            box('Wall merlon coping',((lo+hi)/2,y,476),(hi-lo,26,8))
    # One buttress per period on each side. Its stepped top is visible overhead.
    for y in (-1,1):
        box('Buttress foot',(0,y*73,36),(62,50,72),'Foundation')
        box('Buttress',(0,y*69,190),(46,38,244),'Castle_stone')
        box('Buttress shoulder',(0,y*65,321),(52,34,18))
    return PARTS[start:]


def gatehouse():
    start=len(PARTS)
    for cx in (-352,352):
        box('Gate tower plinth',(cx,0,24),(320,320,48),'Foundation')
        box('Gate tower masonry',(cx,0,284),(288,288,480),'Castle_stone')
        for z in (160,488):
            box('Gate tower string course',(cx,0,z),(300,300,12))
        box('Gate tower crown',(cx,0,516),(320,320,24))
        box('Gate tower roof',(cx,0,527),(280,280,6))
        for sign in (-1,1):
            box('Gate parapet front',(cx,sign*150,550),(280,20,44),'Castle_stone')
            box('Gate parapet side',(cx+sign*150,0,550),(20,320,44),'Castle_stone')
            box('Gate coping front',(cx,sign*150,574),(280,20,8))
            box('Gate coping side',(cx+sign*150,0,574),(20,320,8))
        for dx,dy in [(dx,dy) for dy in (-144,144) for dx in (-144,-72,0,72,144)]+[
                (dx,dy) for dx in (-144,144) for dy in (-72,0,72)]:
            box('Gate tower merlon',(cx+dx,dy,604),(32,32,56),'Castle_stone')
            box('Gate tower merlon cap',(cx+dx,dy,636),(32,32,8))
        for side in (-1,1):
            for z in (240,430):
                box('Gate arrow loop frame',(cx,side*146,z),(30,6,68))
                box('Gate arrow slit',(cx,side*150,z),(8,4,50),'Recess')
                box('Gate arrow cross',(cx,side*151,z),(20,3,6),'Recess')
        box('Gate roof hatch',(cx,0,532),(60,72,4),'Oak')
    # A genuine open barrel arch: extruded spandrel wedges above the opening,
    # not a black rectangle painted over a solid wall. No floor blocks the road.
    for side in (-1,1):
        box('Gate arch pier',(side*168,0,192),(80,176,384),'Castle_stone')
    segments=16
    for i in range(segments):
        a0=i*math.pi/segments
        a1=(i+1)*math.pi/segments
        x0,z0=128*math.cos(a0),180+128*math.sin(a0)
        x1,z1=128*math.cos(a1),180+128*math.sin(a1)
        pts=[(x,y,z) for y in (-88,88) for x,z in
             ((x0,z0),(x1,z1),(x1,384),(x0,384))]
        mesh('Gate barrel arch',pts,[(3,2,1,0),(4,5,6,7),(0,1,5,4),
                                   (1,2,6,5),(2,3,7,6),(3,0,4,7)],'Castle_stone')
        for side in (-1,1):
            # Raised dressed-stone voussoirs make the arch readable overhead.
            pts=[(r*math.cos(a),y,180+r*math.sin(a))
                 for y in (side*89,side*98) for r,a in
                 ((128,a0+.006),(150,a0+.006),(150,a1-.006),(128,a1-.006))]
            faces=[(3,2,1,0),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
            mesh('Gate arch stone',pts,[tuple(reversed(f)) for f in faces] if side>0 else faces,'Dressed_stone')
    for side in (-1,1):
        for x in (-140,140):
            box('Gate jamb',(x,side*93,90),(24,12,180))
    box('Gate bridge deck',(0,0,388),(416,192,8))
    for y in (-86,86):
        box('Gate bridge parapet',(0,y,411),(416,20,38),'Castle_stone')
        box('Gate bridge coping',(0,y,431),(416,24,6))
        for x in (-160,-32,96):
            box('Gate bridge merlon',(x,y,453),(64,22,38),'Castle_stone')
            box('Gate bridge merlon coping',(x,y,476),(64,26,8))
    # Raised portcullis remains above the arch and cannot obstruct passage.
    for x in range(-112,113,28):
        box('Raised portcullis bar',(x,-101,357),(4,4,78),'Iron')
    for z in (326,353,380):
        box('Raised portcullis rail',(0,-104,z),(244,5,4),'Iron')
    for sign in (-1,1):
        socket(sign,512,450,'Gatehouse wall socket')
    return PARTS[start:]


def export(name, parts, work):
    bpy.context.view_layer.update()
    copies=[]
    for obj in parts:
        data=obj.data.copy()
        data.transform(obj.matrix_world)
        copy=bpy.data.objects.new('Export',data)
        bpy.context.collection.objects.link(copy)
        copies.append(copy)
    bpy.ops.object.select_all(action='DESELECT')
    for obj in copies:
        obj.select_set(True)
    bpy.context.view_layer.objects.active=copies[0]
    bpy.ops.object.join()
    merged=bpy.context.object
    merged.name=name
    bpy.ops.wm.obj_export(filepath=str(MODELS/f'{name}.obj'),export_selected_objects=True,
                         forward_axis='NEGATIVE_Z',up_axis='Y',global_scale=1,
                         export_triangulated_mesh=True,export_materials=True,path_mode='RELATIVE')
    path=MODELS/f'{name}.obj'
    path.write_text('# fio:up=y\n'+path.read_text())
    mtl=MODELS/f'{name}.mtl'
    text='\n'.join('map_Kd castle_stone_albedo.png' if l.startswith('map_Kd ') else l
                    for l in mtl.read_text().splitlines())+'\n'
    text=text.replace('newmtl Castle_stone\n','newmtl Castle_stone\nKd 1.000000 1.000000 1.000000\n')
    mtl.write_text(text)
    # Fio uploads model textures with the OBJ bottom-left convention for
    # both formats, and consumes GLB UVs directly. Cancel Blender's glTF V
    # conversion on this temporary export copy so both Fio paths agree.
    # The editable originals and the OBJ UVs keep their authored values.
    for uv in merged.data.uv_layers.active.data:
        uv.uv.y=1-uv.uv.y
    temp=work/f'{name}.gltf'
    bpy.ops.export_scene.gltf(filepath=str(temp),export_format='GLTF_SEPARATE',use_selection=True,
                              export_yup=True,export_apply=True,export_animations=False,
                              export_cameras=False,export_lights=False)
    document=json.loads(temp.read_text())
    binary=(temp.parent/document['buffers'][0].pop('uri')).read_bytes()
    # Fio's GLB renderer reads external image URIs, as in the windmill.
    for img in document.get('images',[]):
        img.pop('bufferView',None)
        img.pop('mimeType',None)
        img['uri']='castle_stone_albedo.png'
    chunk=json.dumps(document,separators=(',',':')).encode()
    chunk+=b' '*(-len(chunk)%4)
    binary+=bytes(-len(binary)%4)
    tail=struct.pack('<II',len(binary),0x004e4942)+binary
    (MODELS/f'{name}.glb').write_bytes(struct.pack('<III',0x46546c67,2,20+len(chunk)+len(tail))+
                                    struct.pack('<II',len(chunk),0x4e4f534a)+chunk+tail)
    bpy.data.objects.remove(merged,do_unlink=True)
    points=[obj.matrix_world@v.co for obj in parts for v in obj.data.vertices]
    low=[min(v[i] for v in points) for i in range(3)]
    high=[max(v[i] for v in points) for i in range(3)]
    return dict(bounds_min=[low[0],low[2],-high[1]],bounds_max=[high[0],high[2],-low[1]],
                triangle_count=sum(len(p.vertices)-2 for o in parts for p in o.data.polygons))


def preview(scene,path,eye,target,span):
    camera=scene.camera
    camera.location=eye
    camera.rotation_euler=(Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler()
    camera.data.ortho_scale=span
    scene.render.filepath=str(path)
    bpy.ops.render.render(write_still=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--work',type=Path,default=ROOT/'work/castle')
    parser.add_argument('--export-only',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    MODELS.mkdir(parents=True,exist_ok=True)
    args.work.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.preferences.filepaths.save_version=0
    stone_texture()
    tower_parts=tower()
    tower_stats=export('castle_tower',tower_parts,args.work)
    for o in tower_parts: o.hide_render=True
    wall_parts=wall()
    wall_stats=export('town_wall',wall_parts,args.work)
    for o in wall_parts: o.hide_render=True
    gate_parts=gatehouse()
    gate_stats=export('castle_gatehouse',gate_parts,args.work)
    for o in gate_parts: o.hide_render=True
    stats=dict(player_height=100,units='Fio units (1 unit approximately 1.8 cm)',up_axis='Y',
               front_axis='+Z',origin='ground center',model_scale=[1,1,1],model_rotation=[0,0,0],
               tower=dict(**tower_stats,height=768,base_diameter=448,door_height=120,roof_deck_height=638),
               wall=dict(**wall_stats,length=512,height=480,walkway_height=392,walkway_clear_width=96,
                         repeat_offset=[512,0,0],join_planes=[-256,256]),
               gatehouse=dict(**gate_stats,length=1024,height=640,opening_width=256,
                              opening_spring_height=180,opening_crown_height=308,join_planes=[-512,512]),
               tower_join_planes=[-224,224],
               collision='Exterior scenery. Use matching structural brushes for collision; model Props use a single bounding box.')
    (MODELS/'castle_kit.json').write_text(json.dumps(stats,indent=2)+'\n')
    for o in tower_parts+wall_parts+gate_parts: o.hide_render=False
    # Flat X sockets: tower end 224, wall end 736, gatehouse end 1760.
    # This assembly uses exactly one exported instance of each requested model.
    for o in wall_parts: o.location.x+=480
    for o in gate_parts: o.location.x+=1248
    # Player-sized scale reference, excluded from exports.
    material('Scale reference',(.16,.43,.45))
    mannequin=box('100 unit person torso',(-290,-300,50),(26,18,60),'Scale reference')
    for x in (-298,-282): box('Reference leg',(x,-300,20),(9,12,40),'Scale reference')
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12,ring_count=6,radius=10,location=(-290,-300,90))
    bpy.context.object.data.materials.append(MATS['Scale reference'])
    scene=bpy.context.scene
    scene.render.engine='CYCLES'
    scene.cycles.samples=24
    scene.cycles.use_denoising=False
    scene.render.resolution_x=1600
    scene.render.resolution_y=1000
    scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'
    scene.world=bpy.data.worlds.new('Castle world')
    scene.world.use_nodes=True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.37,.44,.52,1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value=.65
    scene.view_settings.view_transform='AgX'
    bpy.ops.object.light_add(type='AREA',location=(-600,-1000,1800))
    bpy.context.object.data.energy=6000000
    bpy.context.object.data.shape='DISK'
    bpy.context.object.data.size=1100
    bpy.context.object.rotation_euler=(Vector((400,0,300))-bpy.context.object.location).to_track_quat('-Z','Y').to_euler()
    bpy.ops.object.camera_add()
    scene.camera=bpy.context.object
    scene.camera.data.type='ORTHO'
    scene.camera.data.clip_end=15000
    # Ground is presentation-only; saved source makes this explicit.
    ground=box('PREVIEW ONLY ground',(600,0,-9),(14000,14000,16),'Foundation')
    if not args.export_only:
        preview(scene,args.work/'castle_kit_preview.png',(2200,-3600,2000),(720,0,310),2500)
        preview(scene,args.work/'castle_kit_overhead.png',(720,-1800,3400),(720,0,240),2500)
    source=ROOT/'game/tools/data/castle_kit.blend'
    source.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(source))
    print('CASTLE_KIT '+json.dumps(stats),flush=True)


if __name__=='__main__':
    main()
