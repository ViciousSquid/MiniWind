"""Classic is locked: it is the renderer it was, and the only one.

Classic (``engine/renderer/forward``, registry name ``Forward``) is Fio's
original renderer and the only one it ships: the HD_High renderer that once
stood beside it has been removed, and the host draws with Classic whatever is
asked. ``tests/visual/test_classic_golden.py`` checks the pixels and the
shaders the driver holds; this is the rest of the lock:

* every source file Classic is made of -- its package, the shared
  ``engine/renderer/core`` and ``engine/shaders.py`` -- has the digest
  recorded in ``tests/visual/golden/classic_sources.json``. A deliberate
  change to Classic is recorded with
  ``python tools/classic_golden.py --lock-sources``, after
  ``tools/classic_golden.py --check`` or ``--base`` has shown what it does to
  the picture;
* none of those files mentions HD_High, the HD_High package and its material
  maps are gone, and drawing with Classic never looks for a material
  companion map;
* Classic is the renderer, in the registry and in the shipped settings,
  whatever renderer a settings file names;
* an MTL's ``Ke`` / ``Pr`` / ``Pm`` (read only for HD_High once) reach
  nothing Classic draws a model with.
"""

import configparser
import json
import os
import subprocess
import sys

import pytest

from tests.helpers import golden
from tests.helpers.paths import REPO_ROOT, repo_path


def test_classics_source_files_are_the_recorded_ones():
    with open(os.path.join(golden.GOLDEN_DIR, "classic_sources.json")) as handle:
        recorded = json.load(handle)
    current = golden.classic_source_digests()
    added = sorted(set(current) - set(recorded))
    removed = sorted(set(recorded) - set(current))
    changed = sorted(path for path in set(current) & set(recorded)
                     if current[path] != recorded[path])
    assert not (added or removed or changed), (
        "Classic's source changed (added %s, removed %s, changed %s). If that "
        "was meant: check the picture with tools/classic_golden.py --check, then "
        "record it with tools/classic_golden.py --lock-sources." % (added, removed, changed))


def test_classic_does_not_mention_hd_high():
    for path in golden.classic_source_digests():
        with open(os.path.join(REPO_ROOT, path), encoding="utf-8") as handle:
            text = handle.read()
        for word in ("hd_high", "hd_graphics", "material_maps", "HD_High"):
            assert word not in text, "%s mentions %s" % (path, word)


def test_hd_high_and_its_material_maps_are_gone():
    for path in ("engine/renderer/hd_high", "engine/hd_graphics.py",
                 "engine/material_maps.py", "editor/hd_sky_panel.py",
                 "editor/hd_readiness.py", "tools/make_material_maps.py"):
        assert not os.path.exists(repo_path(path)), path
    sidecars = [os.path.join(folder, name)
                for folder, _dirs, files in os.walk(repo_path("assets"))
                for name in files if name.endswith(".mat.json")]
    assert sidecars == []


@pytest.mark.qt
def test_importing_classic_imports_nothing_of_hd_high():
    code = ("import sys; import engine.renderer.forward; "
            "bad = [m for m in sys.modules if 'hd_high' in m or m == 'engine.material_maps']; "
            "print(','.join(bad))")
    result = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "", result.stdout


@pytest.mark.qt
def test_classic_is_the_renderer():
    from engine.renderer import (
        DEFAULT_RENDERER, available_renderers, canonical_name, renderer_factory,
        renderer_from_settings)
    from engine.renderer.forward import ForwardRenderer
    assert DEFAULT_RENDERER == "Forward" and canonical_name("Classic") == "Forward"
    assert renderer_factory("Classic") is ForwardRenderer
    assert "HD_High" not in available_renderers()
    assert renderer_from_settings(None) == "Forward"
    assert renderer_from_settings(configparser.ConfigParser()) == "Forward"
    shipped = configparser.ConfigParser()
    shipped.read(repo_path("settings.ini"))
    # The shipped settings name Classic, and Classic is what they get.
    assert shipped.get("Renderer", "renderer") == "Classic"
    assert renderer_from_settings(shipped) == "Forward"
    # A file that still asks for HD_High is given Classic.
    asked = configparser.ConfigParser()
    asked.add_section("Renderer")
    asked.set("Renderer", "renderer", "HD_High")
    assert renderer_from_settings(asked) == "Forward"


@pytest.mark.qt
def test_an_mtls_ke_pr_pm_reach_nothing_classic_draws_with(tmp_path):
    from engine import obj_loader
    from engine.renderer.core.resources import ModelDrawGroup, ResourcesMixin
    (tmp_path / "lamp.mtl").write_text(
        "newmtl glow\nKd 0.5 0.4 0.3\nKe 2.0 1.5 1.0\nPr 0.2\nPm 0.9\n")
    (tmp_path / "lamp.obj").write_text(
        "mtllib lamp.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nusemtl glow\nf 1 2 3\n")
    model = obj_loader.OBJLoader()
    model._load_mtl(str(tmp_path / "lamp.obj"), "lamp.mtl")
    material = model.materials["glow"]
    # Classic reads no emission, roughness or metalness from an MTL, and
    # nothing is kept for a renderer that would.
    for key in ("emissive", "hd_emissive", "roughness", "metallic"):
        assert key not in material, key
    assert material["diffuse"] == (0.5, 0.4, 0.3)

    class Renderer(ResourcesMixin):
        def __init__(self):
            self._model_draw_group_cache = {}

    class Model:
        materials = {"glow": material}
        groups = [{"material": "glow", "start": 0, "count": 3}]
        ebo = None

    group = Renderer()._model_draw_groups(Model())[0]
    assert type(group) is ModelDrawGroup and not hasattr(group, "surface")
    assert group.emissive == (0.0, 0.0, 0.0)


@pytest.mark.gl
def test_a_classic_frame_never_looks_for_material_maps(monkeypatch):
    import engine.asset_archives as archives
    from tests.helpers import gl as glh
    seen = []

    def watched(real):
        def lookup(path, *args, **kwargs):
            text = str(path).replace("\\", "/").lower()
            stem = text.rsplit(".", 1)[0]
            if text.endswith(".mat.json") or stem.endswith(("_n", "_m", "_h", "_e")):
                seen.append(text)
            return real(path, *args, **kwargs)
        return lookup
    for name in ("asset_exists", "asset_bytes", "asset_source"):
        if hasattr(archives, name):
            monkeypatch.setattr(archives, name, watched(getattr(archives, name)))

    config = configparser.ConfigParser()
    config.add_section("Renderer")
    config.set("Renderer", "lowpower_mode", "False")
    glh.reset_texture_cache()
    with glh.GLTestContext(96, 96) as context:
        renderer = glh.make_renderer(config, name="Classic")
        try:
            assert type(renderer).__name__ == "ForwardRenderer"
            assert not hasattr(renderer, "hd") and not hasattr(renderer, "environment")
            renderer.set_background_image("assets/backgrounds/cloudy-sky-panorama.webp")
            brushes, things = glh.lit_cube_scene()
            for brush in brushes:
                brush["textures"] = {face: "Stone_09-512x512.png" for face in
                                     ("north", "south", "east", "west", "top", "down")}
            projection, view, eye = glh.camera_matrices()
            for play in (False, True):
                frame = glh.render_config(all_brushes=brushes, all_things=things,
                                          play_mode=play)
                for _ in range(2):
                    context.bind()
                    with glh.no_gl_errors("classic frame"):
                        renderer.render_scene(projection, view, eye, None, frame,
                                              brush_slots=frame["all_brush_slots"])
            assert not glh.is_blank(context.read_pixels())
        finally:
            renderer.cleanup()
    glh.reset_texture_cache()
    assert seen == [], seen
