# Fio's renderer: Classic

Fio draws through a renderer contract. The host (`QtGameView`) builds a frame
input from the dense tables the logic thread publishes and hands it to the
active renderer; it knows a renderer only by the members of
`engine.renderer.api.Renderer`. Renderers are registered by name
(`engine/renderer/registry.py`).

One renderer ships with Fio, and it is the only one the host draws with:
**Classic** (`engine/renderer/forward`, class `ForwardRenderer`, registry
name `Forward`, alias `Classic`). It uses the shared `engine/renderer/core`
(GPU resources, culling, terrain upkeep). The HD_High renderer that once
stood beside it has been removed, with its HD Sky properties panel, the
View > HD preview switch, the HD Readiness Report and the material maps
(`*_n` / `*_m` / `.mat.json`) baked for it.

## Classic is enforced

* **`settings.ini`**: `[Renderer] renderer` is not consulted. Classic starts
  whatever it says: a file written when HD_High existed may still say
  `HD_High`, and it starts Classic; saving Settings writes `Classic` back.
  (`engine.renderer.renderer_from_settings` always answers `Forward`.)
* **Settings > Display** has no renderer choice.
* **Console**: `r_renderer` shows Classic; `r_renderer Classic` (or
  `Forward`) keeps it; any other name, HD_High included, is refused.
* **In code**: `view.switch_renderer(name)` refuses every name but Classic
  while `engine.renderer.registry.ENFORCE_CLASSIC` holds, which it always does
  in Fio. A renderer a plugin registers can still be made with
  `create_renderer(name, config)` and is held to the contract, but the host
  does not draw with it. The tests of the host's swap machinery lift the
  enforcement to swap their stand-in renderers in and out.
* A map's `hd_*` PlayerStart properties, if an older map has them, are kept
  with the map and never read.

---

## Classic

Fio's original renderer, and the one every map was built against. OpenGL 3.3
core, designed for low-power hardware.

**Lighting.** Each lit surface is its texture multiplied by light, in display
space: `(0.1 + ambient) + sum over lamps of intensity * falloff * N.L * colour`,
with `falloff = (1 - distance / radius)^2`. Up to 128 lamps per frame (fewer in
low-power mode), the eight nearest shadow-casting ones with depth cube-map
shadows, light cookies, emissive brushes as lights. Terrain has a fixed sun
and sky tint of its own.

**What it draws.** Textured, Solid Lit, Wireframe and Overlay display modes;
box and convex brushes (instanced and batched); OBJ and GLB models; sprites,
monsters, effects and particles; projected decals (wet ones reflect); water
(cheap, or with depth, caustics and screen-space reflections); glass; fog
volumes and distance fog; a sky panorama; stencil world portals; reflection
probes; the terrain and its grass; the editor's overlays.

**Settings** (`[Renderer]`): `shadows_enabled`, `shadow_map_size`,
`sky_cubemap_size`, `occlusion_culling`, `lowpower_mode`, `geo_batching`.

**Locked.** Classic must not change:

* `tests/visual/test_classic_golden.py` draws the stock maps from fixed
  cameras, in the editor and in Play, and compares every pixel with the
  stored frames, and every program's final fragment source with the stored
  text.
* `tests/visual/test_classic_lock.py` checks the digest of every file Classic
  is made of (`forward/`, `core/`, `engine/shaders.py`), that none of them
  mentions HD_High, that HD_High and its material maps are gone, that drawing
  with Classic looks for no material map, and that Classic is the renderer
  whatever the settings ask for.
* `tools/classic_golden.py --check` runs the comparison by hand; `--base DIR`
  compares this checkout with another on whatever GPU is present; after a
  *deliberate* change to Classic, `--update` stores new frames and
  `--lock-sources` records the new digests.

---

## Writing another renderer

`docs/examples/deferred_renderer` is a complete renderer that shares nothing
with Classic, and the wiki's Renderer Development Guide walks through it. It
is held to the contract by its tests; Fio itself still draws with Classic
only.
