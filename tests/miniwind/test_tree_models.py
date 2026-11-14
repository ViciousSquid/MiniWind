"""Woodland exports remain upright, cheap and compatible with both Fio loaders."""
import json
from pathlib import Path

import numpy as np
import pytest

from engine.obj_loader import OBJLoader

ROOT=Path(__file__).resolve().parents[2]
FOLDER=ROOT/'assets/models/trees'
MANIFEST=json.loads((FOLDER/'tree_kit.json').read_text())


@pytest.mark.parametrize('info',MANIFEST['models'],ids=lambda m:m['name'])
def test_geometry_scale_normals_and_palette_survive_export(info):
    obj=OBJLoader()
    assert obj.load(str(FOLDER/info['obj']))
    assert obj.up_axis=='y'
    v=np.asarray(obj.vertices)
    np.testing.assert_allclose(v.min(0),info['bounds_min'],atol=2e-6)
    np.testing.assert_allclose(v.max(0),info['bounds_max'],atol=2e-6)
    assert v[:,1].min()==0
    assert np.ptp(v[:,1])==pytest.approx(info['height'],abs=1e-3)
    assert 150<=info['height']<=850
    assert len(obj.faces)==info['triangle_count']<=1700
    tri=np.array([[v[c[0]] for c in f['vertices']] for f in obj.faces])
    normal=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
    area=np.linalg.norm(normal,axis=1)
    assert (area>1e-7).all()
    authored=np.array([obj.normals[f['vertices'][0][2]] for f in obj.faces])
    np.testing.assert_allclose(normal/area[:,None],authored,atol=2e-4)
    assert np.isfinite(v).all()
    assert set(obj.materials)=={'Tree_palette'}
    assert {f['material'] for f in obj.faces}=={'Tree_palette'}
    mat=obj.materials['Tree_palette']
    assert mat['texture']=='tree_palette.png'
    assert mat['color']==(1,1,1) and mat['alpha']==1
    # Every triangle samples one swatch center; no boundary filtering artifacts.
    for face in obj.faces:
        uv=np.array([obj.texcoords[c[1]] for c in face['vertices']])
        np.testing.assert_allclose(uv, np.tile(uv[0],(3,1)))
        np.testing.assert_allclose((uv[0]*8)%1,[.5,.5])


@pytest.mark.parametrize('info',MANIFEST['models'],ids=lambda m:m['name'])
def test_glb_matches_obj_in_the_actual_loaders(info):
    pytest.importorskip('OpenGL')
    from engine.glb_loader import GLBLoader
    obj=OBJLoader();glb=GLBLoader()
    assert obj.load(str(FOLDER/info['obj']))
    assert glb.load(str(FOLDER/info['glb']))
    a=np.array([[obj.vertices[c[0]] for c in f['vertices']] for f in obj.faces]).reshape(-1,3)
    b=np.asarray(glb.get_flattened_vertices())
    np.testing.assert_allclose(a,b,atol=1e-4)
    assert len(glb.get_flattened_triangles())==info['triangle_count']
    primitive=list(glb._primitives())[0]
    uv=np.array([obj.texcoords[c[1]] for f in obj.faces for c in f['vertices']])
    np.testing.assert_allclose(uv,primitive['uvs'],atol=1e-6)
    normal=np.array([obj.normals[c[2]] for f in obj.faces for c in f['vertices']])
    np.testing.assert_allclose(normal,primitive['normals'],atol=1e-6)
    assert glb.materials['Tree_palette']['texture']=='tree_palette.png'
    j=glb.json_data
    assert len(j['nodes'])==len(j['meshes'])==len(j['materials'])==1
    assert len(j['meshes'][0]['primitives'])==1
    assert not any(k in j['nodes'][0] for k in ('translation','rotation','scale','matrix'))
    assert j['materials'][0].get('alphaMode','OPAQUE')=='OPAQUE'


def test_variety_bare_branches_and_placement_reference():
    models=MANIFEST['models']
    assert len(models)==48
    assert len({m['species'] for m in models})>=15
    assert sum(m['season']=='bare' for m in models)>=10
    assert {'gold','orange','crimson','evergreen','blue','snow'} <= {m['season'] for m in models}
    for info in models:
        if info['season']!='bare': continue
        obj=OBJLoader();assert obj.load(str(FOLDER/info['obj']))
        for face in obj.faces:
            # The first row of the palette is bark; bare models have no leaf colors.
            assert all(obj.texcoords[c[1]][1]<1/8 for c in face['vertices'])
    things=json.loads((FOLDER/'tree_kit_props.json').read_text())['things']
    assert len(things)==48 and len({t['properties']['id'] for t in things})==48
    for thing,info in zip(things,models):
        p=thing['properties']
        assert p['model_path']=='assets/models/trees/'+info['glb']
        assert p['scale']==[1,1,1] and p['rotation']==[0,0,0]
        assert p['no_collision'] and not p['physics_enabled']
