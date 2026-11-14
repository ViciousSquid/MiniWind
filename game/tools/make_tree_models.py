"""Original low-poly woodland kit; run with Python 3, no third-party modules.

Deterministic OBJ + GLB exports in Fio units. Author Z-up; both exports are
Y-up with baked coordinates, one material and ground-level trunk origins.
Run: python game/tools/make_tree_models.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import random
import struct
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'assets/models/trees'
TAU = math.tau

# Eight rows, from bottom to top. Four adjacent shades per foliage family.
PALETTE = [
    (53,35,26),(76,49,32),(103,69,42),(130,91,55),
    (181,180,156),(218,215,187),(61,54,45),(146,125,89),
    (32,68,36),(43,89,41),(63,108,47),(86,125,56),
    (38,82,42),(56,108,47),(81,131,55),(109,149,65),
    (122,100,24),(161,126,28),(199,153,34),(224,183,58),
    (158,111,26),(192,144,32),(220,173,50),(239,204,87),
    (133,53,24),(174,72,25),(205,100,32),(229,132,46),
    (144,65,29),(183,91,35),(211,125,47),(229,156,67),
    (102,29,30),(139,39,33),(173,55,37),(200,78,44),
    (120,39,44),(153,47,48),(184,66,51),(210,92,61),
    (20,52,42),(25,68,48),(37,85,54),(51,101,61),
    (30,57,62),(42,76,76),(57,96,89),(77,116,104),
    (72,87,35),(93,111,43),(118,134,52),(142,154,68),
    (59,87,33),(77,112,38),(104,139,44),(132,159,56),
    (170,183,184),(196,207,204),(219,227,219),(239,241,230),
    (66,47,36),(99,69,47),(140,94,52),(173,120,60),
]
FOLIAGE = dict(green=8, lime=12, russet=24, gold=16, amber=20,
               orange=28, red=32, crimson=36, evergreen=40, blue=44,
               olive=48, palm=52, snow=56, copper=60)

# name, architecture, season, height, crown spread ratio, deterministic seed
SPECS = [
    ('oak_sapling','oak','green',165,.60,10),
    ('oak_mature','oak','green',570,1.10,11),
    ('oak_ancient','oak','green',760,1.30,12),
    ('oak_autumn','oak','russet',580,1.12,13),
    ('oak_bare','oak','bare',620,1.10,14),
    ('maple_green','maple','lime',430,.93,20),
    ('maple_gold','maple','gold',460,.96,21),
    ('maple_orange','maple','orange',510,1.02,22),
    ('maple_crimson','maple','crimson',450,.94,23),
    ('birch_green','birch','lime',490,.55,30),
    ('birch_gold','birch','amber',530,.55,31),
    ('birch_twin','birch_twin','gold',580,.65,32),
    ('birch_bare','birch','bare',510,.58,33),
    ('beech_green','beech','green',650,.85,40),
    ('beech_copper','beech','copper',620,.90,41),
    ('beech_bare','beech','bare',660,.88,42),
    ('rowan_green','rowan','lime',295,.92,50),
    ('rowan_red','rowan','red',340,.90,51),
    ('rowan_gold','rowan','gold',320,.95,52),
    ('willow_green','willow','olive',500,1.20,60),
    ('willow_gold','willow','amber',470,1.24,61),
    ('willow_bare','willow','bare',510,1.17,62),
    ('poplar_green','poplar','lime',730,.35,70),
    ('poplar_gold','poplar','gold',760,.36,71),
    ('poplar_bare','poplar','bare',700,.35,72),
    ('pine_young','pine','evergreen',260,.64,80),
    ('pine_tall','pine','evergreen',820,.60,81),
    ('pine_windswept','pine_wind','evergreen',590,.92,82),
    ('spruce_green','spruce','evergreen',690,.65,90),
    ('spruce_blue','spruce','blue',610,.66,91),
    ('spruce_snow','spruce','snow',650,.67,92),
    ('fir_dense','fir','evergreen',730,.57,100),
    ('fir_snow','fir','snow',780,.56,101),
    ('cedar_spreading','cedar','evergreen',640,1.18,110),
    ('cedar_blue','cedar','blue',700,1.12,111),
    ('cypress_column','cypress','evergreen',660,.25,120),
    ('cypress_twisted','cypress','olive',580,.31,121),
    ('larch_green','larch','lime',650,.61,130),
    ('larch_gold','larch','gold',670,.62,131),
    ('larch_bare','larch','bare',650,.63,132),
    ('dead_stag','dead','bare',560,.83,140),
    ('dead_snag','snag','bare',390,.48,141),
    ('dead_lightning','lightning','bare',680,.60,142),
    ('palm_oasis','palm','palm',510,.96,150),
    ('palm_bent','palm','palm',620,1.02,151),
    ('apple_green','apple','green',260,1.08,160),
    ('apple_autumn','apple','orange',280,1.12,161),
    ('hawthorn_bare','hawthorn','bare',270,1.20,170),
]


def add(a,b): return tuple(x+y for x,y in zip(a,b))
def sub(a,b): return tuple(x-y for x,y in zip(a,b))
def mul(a,s): return tuple(x*s for x in a)
def cross(a,b): return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def unit(a): return mul(a,1/math.sqrt(sum(x*x for x in a)))


class Mesh:
    def __init__(self,seed):
        self.rng=random.Random(seed)
        self.verts=[]
        self.faces=[]

    def piece(self,verts,faces,colors):
        offset=len(self.verts)
        self.verts.extend(verts)
        for i,face in enumerate(faces):
            color=colors[i%len(colors)]
            for j in range(1,len(face)-1):
                self.faces.append((tuple(offset+k for k in (face[0],face[j],face[j+1])),color))

    def tube(self,points,radii,sides=5,bark=0):
        verts=[]
        # Parallel horizontal-ish rings, using one stable frame for the tube.
        axis=unit(sub(points[-1],points[0]))
        u=unit(cross(axis,(0,0,1) if abs(axis[2])<.95 else (0,1,0)))
        v=cross(axis,u)
        for point,radius in zip(points,radii):
            for i in range(sides):
                a=TAU*i/sides
                verts.append(add(point,add(mul(u,radius*math.cos(a)),mul(v,radius*math.sin(a)))))
        faces=[tuple(reversed(range(sides)))]
        for j in range(len(points)-1):
            for i in range(sides):
                n=(i+1)%sides
                faces.append((j*sides+i,j*sides+n,(j+1)*sides+n,(j+1)*sides+i))
        faces.append(tuple((len(points)-1)*sides+i for i in range(sides)))
        colors=[bark+(i%3) for i in range(len(faces))] if bark==0 else [bark,bark+1,bark]
        self.piece(verts,faces,colors)

    def crown(self,center,radii,palette,sides=9):
        # Irregular triangulated rings with offset azimuths: angular leaf masses
        # rather than smooth spheres. Each closed lobe has 54 triangles.
        rng=self.rng
        verts=[add(center,(0,0,-radii[2]*.92))]
        for ring,(z,r) in enumerate(((-.48,.78),(.12,1),(.67,.62))):
            for i in range(sides):
                a=TAU*(i+.27*ring)/sides
                jitter=rng.uniform(.88,1.12)
                verts.append(add(center,(radii[0]*r*math.cos(a)*jitter,
                                         radii[1]*r*math.sin(a)*jitter,
                                         radii[2]*(z+rng.uniform(-.11,.11)))))
        verts.append(add(center,(radii[0]*.08,0,radii[2])))
        faces=[]
        for i in range(sides):
            n=(i+1)%sides
            faces.append((0,1+n,1+i))
            for j in range(2):
                a=1+j*sides+i;b=1+j*sides+n;c=1+(j+1)*sides+n;d=1+(j+1)*sides+i
                faces.extend(((a,b,c),(a,c,d)))
            faces.append((1+2*sides+i,1+2*sides+n,len(verts)-1))
        self.piece(verts,faces,[palette+rng.randrange(4) for _ in faces])

    def tier(self,center,radius,height,palette,sides=12,skirt=.72):
        rng=self.rng
        verts=[add(center,(0,0,-height*.12))]
        for j,(rad,z) in enumerate(((radius*.30,-height*.06),(radius,0),(radius*.62,height*.35))):
            for i in range(sides):
                a=TAU*i/sides
                r=rad*(1 if i%2==0 else skirt)*rng.uniform(.92,1.06)
                verts.append(add(center,(r*math.cos(a),r*math.sin(a),z+rng.uniform(-.025,.025)*height)))
        verts.append(add(center,(radius*.06,0,height)))
        faces=[];colors=[]
        for i in range(sides):
            n=(i+1)%sides
            faces.append((0,1+n,1+i));colors.append(palette)
            for j in range(2):
                a=1+j*sides+i;b=1+j*sides+n;c=1+(j+1)*sides+n;d=1+(j+1)*sides+i
                faces.append((a,b,c,d));colors.append(palette+rng.randrange(3))
            faces.append((1+2*sides+i,1+2*sides+n,len(verts)-1));colors.append(palette+2+rng.randrange(2))
        self.piece(verts,faces,colors)


def roots(mesh,radius,height,bark):
    for i in range(5):
        a=TAU*i/5+mesh.rng.uniform(-.3,.3)
        mesh.tube([(math.cos(a)*radius*.3,math.sin(a)*radius*.3,height*.055),
                   (math.cos(a)*radius*2.8,math.sin(a)*radius*2.8,height*.012)],
                  [radius*.65,radius*.16],4,bark)


def broadleaf(mesh,kind,season,spread):
    rng=mesh.rng
    bare=season=='bare'
    bark=4 if kind.startswith('birch') else 6 if kind in ('dead','snag','lightning') else 0
    wide=spread/2
    girth=.027 if kind.startswith('birch') or kind=='poplar' else .045
    if kind in ('oak','willow'): girth=.065
    if kind=='oak' and spread>1.2: girth=.095
    lean=rng.uniform(-.065,.065)
    trunk_top=.65 if kind=='poplar' else .52
    mesh.tube([(0,0,0),(lean*.2,.005,.18),(lean,.01,.37),(lean*.7,-.008,trunk_top)],
              [girth*1.4,girth,girth*.73,girth*.40],7,bark)
    roots(mesh,girth,1,bark)
    if kind=='birch_twin':
        mesh.tube([(.035,0,0),(.09,.02,.24),(.12,.04,.51),(.16,.03,.83)],
                  [.03,.026,.016,.004],6,4)
    if kind.startswith('birch'):
        # Small bark scars, sculpted on the pale trunk, also visible in bare form.
        for i in range(7):
            z=.08+i*.057
            p=(lean*z/.52,-girth*.85,z)
            mesh.tube([add(p,(-girth*.65,0,0)),add(p,(girth*.4,0,.007))],[.004,.003],4,6)
    branches=9 if kind in ('oak','beech','willow') else 7
    if kind=='snag': branches=4
    if kind=='hawthorn': branches=10
    if kind in ('dead','lightning'): branches=8
    for i in range(branches):
        a=i*2.399963+rng.uniform(-.25,.25)
        layer=i/(branches-1)
        start=(lean*.6,0,.23+layer*.37)
        if kind=='poplar':
            end=(math.cos(a)*wide*(.78-.25*layer),math.sin(a)*wide*(.78-.25*layer),.62+layer*.29)
        else:
            end=(math.cos(a)*wide*(.82-.30*layer),math.sin(a)*wide*(.82-.30*layer),.52+layer*.32)
        mid=add(mul(start,.40),mul(end,.60))
        mid=add(mid,(rng.uniform(-.025,.025),rng.uniform(-.025,.025),.035))
        radius=girth*(.44-.19*layer)
        mesh.tube([start,mid,end],[radius,radius*.62,.004],5,bark)
        # Strongly differentiated architecture: willow droops, poplar rises,
        # oak forks spread, bare specimens carry fine tapering twigs.
        for j in range(3 if bare else 2):
            aa=a+(j-1)*.50+rng.uniform(-.20,.20)
            length=(.11+.08*(1-layer))*(.55 if kind=='poplar' else 1)
            tip=add(end,(math.cos(aa)*length,math.sin(aa)*length,.08+(.02*j)))
            if kind=='willow': tip=add(end,(math.cos(aa)*length,math.sin(aa)*length,-.18-j*.045))
            if kind=='snag': tip=add(end,(math.cos(aa)*.04,math.sin(aa)*.04,.055))
            mesh.tube([mid,end,tip],[radius*.65,.008,.0018],4,bark)
            if bare:
                for k in (-1,1):
                    twig=add(tip,(math.cos(aa+k*.65)*.055,math.sin(aa+k*.65)*.055,.055))
                    mesh.tube([add(mul(end,.3),mul(tip,.7)),twig],[.0038,.0008],3,bark)
        if not bare:
            palette=FOLIAGE[season]
            rad=(.17,.16,.19)
            if kind=='oak': rad=(.23,.20,.20)
            elif kind=='beech': rad=(.19,.18,.25)
            elif kind.startswith('birch'): rad=(.13,.12,.22)
            elif kind=='poplar': rad=(.09,.09,.24)
            elif kind=='willow': rad=(.22,.20,.24)
            elif kind in ('rowan','apple'): rad=(.19,.17,.20)
            center=add(end,(0,0,.025))
            mesh.crown(center,rad,palette,8 if kind=='maple' else 9)
            if kind=='willow':
                mesh.crown(add(end,(math.cos(a)*.09,math.sin(a)*.09,-.17)),(.105,.10,.25),palette,7)
            if kind=='rowan':
                mesh.crown(add(end,(.02,-.045,-.09)),(.024,.024,.028),32,5)
            if kind=='apple':
                for k in (-1,1):
                    mesh.crown(add(end,(k*.07,-.09,-.06)),(.021,.021,.023),32,5)
    if not bare:
        rad=(wide*.50,wide*.47,.23 if kind!='poplar' else .26)
        mesh.crown((lean*.8,0,.86),rad,FOLIAGE[season],10)
    if kind=='lightning':
        mesh.tube([(lean,0,.46),(lean*.8,.015,.90),(lean+.03,.01,1.01)],
                  [.044,.026,.008],6,6)
        mesh.tube([(lean*.8,0,.86),(lean-.035,.01,1.02)],[.020,.001],4,6)
    if kind=='snag':
        mesh.tube([(lean,0,.46),(lean-.02,0,.88)],[.06,.027],6,6)


def conifer(mesh,kind,season,spread):
    rng=mesh.rng
    bare=season=='bare'
    mesh.tube([(0,0,0),(.013,0,.36),(-.012,.015,.72),(.015,0,1)],
              [.036,.024,.012,.0015],7,0)
    roots(mesh,.034,1,0)
    tiers=7 if kind=='fir' else 6
    base=.17 if kind in ('fir','spruce') else .27
    if kind in ('pine_wind','cedar'): base=.42;tiers=4
    for i in range(tiers):
        f=i/(tiers-1)
        z=base+(.83-base)*f
        r=spread*.5*(1-f*.77)
        center=(.015*math.sin(i),0,z)
        if kind=='pine_wind': center=(.10+.15*f,0,z);r*=.82
        if kind=='cedar': center=(.06*math.sin(i*2),.04*math.cos(i),z)
        for j in range(5):
            a=TAU*j/5+i*.7
            end=add(center,(r*.85*math.cos(a),r*.85*math.sin(a),-.025))
            mesh.tube([(.005,0,z-.025),end],[.013*(1-f*.6),.002],4,0)
            if bare:
                for k in (-1,1):
                    twig=add(end,(.06*math.cos(a+k*.7),.06*math.sin(a+k*.7),.045))
                    mesh.tube([add(mul(center,.4),mul(end,.6)),twig],[.0035,.0007],3,0)
        if not bare:
            palette=40 if season=='snow' else FOLIAGE[season]
            ht=.22 if kind not in ('cedar','pine_wind') else .12
            mesh.tier(center,r,ht,palette,14 if kind=='larch' else 12,.48 if kind=='larch' else .72)
            if season=='snow':
                mesh.tier(add(center,(0,0,.045)),r*.77,ht*.84,56,12,.76)


def cypress(mesh,season):
    mesh.tube([(0,0,0),(.025,0,.44),(-.018,0,.82)],[.035,.018,.004],6)
    roots(mesh,.03,1,0)
    for i in range(5):
        mesh.crown((.025*math.sin(i*1.8),.01*math.cos(i),.27+.135*i),
                   (.115*(1-.1*i),.10*(1-.1*i),.23),FOLIAGE[season],8)


def palm(mesh,seed):
    bend=.22 if seed==151 else .08
    points=[(bend*(i/5)**2,0,i*.16) for i in range(6)]
    mesh.tube(points,[.045-i*.004 for i in range(6)],7)
    for i in range(8):
        z=.06+i*.09
        mesh.tube([(bend*(z/.8)**2,0,z),(bend*((z+.012)/.8)**2,0,z+.012)],[.047-i*.002,.046-i*.002],7)
    top=points[-1]
    for i in range(11):
        a=TAU*i/11;length=.40 if i%2 else .46
        verts=[]
        for j in range(6):
            f=j/5
            c=add(top,(length*f*math.cos(a),length*f*math.sin(a),.20*math.sin(f*math.pi)-.16*f*f))
            w=.065*math.sin(math.pi*f)+.001
            verts.extend([add(c,(-w*math.sin(a),w*math.cos(a),-.022)),add(c,(0,0,.012)),
                          add(c,(w*math.sin(a),-w*math.cos(a),-.022))])
        # Folded solid fronds, not alpha cards or one-sided leaf planes.
        faces=[]
        for j in range(5):
            b=j*3;n=b+3
            faces.extend(((b,n,n+1,b+1),(b+1,n+1,n+2,b+2),(b+2,n+2,n,b)))
        faces.extend(((0,1,2),(15,17,16)))
        mesh.piece(verts,faces,[52,54,53,55])


def make(spec):
    name,kind,season,height,spread,seed=spec
    mesh=Mesh(seed)
    if kind in ('pine','pine_wind','spruce','fir','cedar','larch'):
        conifer(mesh,kind,season,spread)
    elif kind=='cypress': cypress(mesh,season)
    elif kind=='palm': palm(mesh,seed)
    else: broadleaf(mesh,kind,season,spread)
    low=min(v[2] for v in mesh.verts)
    high=max(v[2] for v in mesh.verts)
    scale=height/(high-low)
    mesh.verts=[(x*scale,(z-low)*scale,-y*scale) for x,y,z in mesh.verts]
    return mesh


def swatch(index): return ((index%8+.5)/8,(index//8+.5)/8)


def png_palette(path):
    size=256
    pixels=bytearray()
    for y in range(size):
        pixels.append(0)
        for x in range(size):
            pixels.extend(PALETTE[((size-1-y)//32)*8+x//32])
    def chunk(tag,data): return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',size,size,8,2,0,0,0))+
                     chunk(b'IDAT',zlib.compress(bytes(pixels),9))+chunk(b'IEND',b''))


def export(name,mesh):
    name='tree_'+name
    vertices=[];normals=[];uvs=[]
    lines=['# fio:up=y','# Original MiniWind woodland kit; Fio units; trunk base at ground.',
           'mtllib tree_palette.mtl','o '+name]
    for v in mesh.verts: lines.append('v '+' '.join(f'{x:.6f}' for x in v))
    for i in range(64): lines.append('vt '+' '.join(f'{x:.6f}' for x in swatch(i)))
    for face,color in mesh.faces:
        normal=unit(cross(sub(mesh.verts[face[1]],mesh.verts[face[0]]),sub(mesh.verts[face[2]],mesh.verts[face[0]])))
        normals.extend([normal]*3)
        vertices.extend(mesh.verts[v] for v in face)
        uvs.extend([swatch(color)]*3)
        lines.append('vn '+' '.join(f'{x:.7f}' for x in normal))
    lines.append('usemtl Tree_palette')
    for i,(face,color) in enumerate(mesh.faces):
        lines.append('f '+' '.join(f'{v+1}/{color+1}/{i+1}' for v in face))
    (OUT/f'{name}.obj').write_text('\n'.join(lines)+'\n')
    # One node, one primitive, no transforms or unsupported material features.
    binary=bytearray();views=[];accessors=[]
    for data,width in ((vertices,3),(normals,3),(uvs,2)):
        blob=struct.pack('<'+'f'*len(data)*width,*(x for v in data for x in v))
        views.append(dict(buffer=0,byteOffset=len(binary),byteLength=len(blob),target=34962))
        binary.extend(blob)
        accessor=dict(bufferView=len(views)-1,componentType=5126,count=len(data),type='VEC'+str(width))
        if len(views)==1:
            accessor['min']=[min(v[i] for v in vertices) for i in range(3)]
            accessor['max']=[max(v[i] for v in vertices) for i in range(3)]
        accessors.append(accessor)
    doc=dict(asset=dict(version='2.0',generator='MiniWind original woodland kit'),
             scene=0,scenes=[dict(nodes=[0])],nodes=[dict(name=name,mesh=0)],
             meshes=[dict(name=name,primitives=[dict(attributes=dict(POSITION=0,NORMAL=1,TEXCOORD_0=2),material=0,mode=4)])],
             materials=[dict(name='Tree_palette',pbrMetallicRoughness=dict(baseColorFactor=[1,1,1,1],
                             baseColorTexture=dict(index=0),metallicFactor=0,roughnessFactor=1),doubleSided=False)],
             images=[dict(uri='tree_palette.png')],textures=[dict(source=0,sampler=0)],
             samplers=[dict(magFilter=9728,minFilter=9728,wrapS=33071,wrapT=33071)],
             buffers=[dict(byteLength=len(binary))],bufferViews=views,accessors=accessors)
    # Fio consumes GLB UVs directly with the same bottom-left texture convention
    # as OBJ. Keep identical UVs here, as in the bundled windmill/castle pipeline.
    encoded=json.dumps(doc,separators=(',',':')).encode()
    encoded+=b' '*(-len(encoded)%4)
    binary+=bytes(-len(binary)%4)
    glb=struct.pack('<III',0x46546c67,2,28+len(encoded)+len(binary))
    glb+=struct.pack('<II',len(encoded),0x4e4f534a)+encoded
    glb+=struct.pack('<II',len(binary),0x004e4942)+binary
    (OUT/f'{name}.glb').write_bytes(glb)
    return dict(name=name,obj=f'{name}.obj',glb=f'{name}.glb',
                triangle_count=len(mesh.faces),height=round(max(v[1] for v in vertices),4),
                bounds_min=[round(min(v[i] for v in vertices),6) for i in range(3)],
                bounds_max=[round(max(v[i] for v in vertices),6) for i in range(3)])


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    png_palette(OUT/'tree_palette.png')
    (OUT/'tree_palette.mtl').write_text('newmtl Tree_palette\nKa 0.2 0.2 0.2\nKd 1 1 1\nKs 0 0 0\nNs 0\nd 1\nillum 1\nmap_Kd tree_palette.png\n')
    models=[];things=[]
    for i,spec in enumerate(SPECS):
        info=export(spec[0],make(spec))
        info.update(species=spec[1],season=spec[2],seed=spec[5])
        models.append(info)
        things.append(dict(type='prop',pos=[(i%8)*1200,0,(i//8)*1500],properties=dict(
            type='prop',name=spec[0].replace('_',' ').title(),
            id=str(uuid.uuid5(uuid.NAMESPACE_URL,'miniwind/woodland/'+spec[0])),
            render_mode='model',model_path='assets/models/trees/'+info['glb'],rotation=[0,0,0],scale=[1,1,1],
            carry_enabled=False,collect_enabled=False,physics_enabled=False,no_collision=True),io_connections=[]))
    manifest=dict(player_height=100,units='Fio units; 1 unit approximately 1.8 cm',up_axis='Y',
                  origin='ground-level trunk center',model_scale=[1,1,1],model_rotation=[0,0,0],
                  material='Tree_palette',texture='tree_palette.png',models=models)
    (OUT/'tree_kit.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (OUT/'tree_kit_props.json').write_text(json.dumps(dict(
        description='Placement reference, not an automatically loaded map. Give duplicates fresh IDs. Non-solid scenery; use separate trunk collision brushes.',
        things=things),indent=2)+'\n')
    print(f'Built {len(models)} original trees: '+str(min(m['triangle_count'] for m in models))+'–'+
          str(max(m['triangle_count'] for m in models))+' triangles; '+str(sum((OUT/m['glb']).stat().st_size for m in models))+' GLB bytes.')


if __name__=='__main__': main()
