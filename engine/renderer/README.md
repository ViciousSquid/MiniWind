# engine/renderer

Fio's renderers draw the world from the dense tables the logic thread
publishes each frame. The editor and the game talk to a renderer only through
the contract in `api.py`.

| Part | What it is |
|---|---|
| `api.py` | The renderer contract: the `Renderer` protocol, `RendererOptions` (what a renderer may offer beyond it), `FRAME_INPUT` (every key a frame hands a renderer) and `contract_violations`, the check of an object against all of it. |
| `registry.py` | Registers renderers by name. `renderer_from_settings` names the one the host draws with -- Classic, always. `create_renderer` refuses, and cleans up, whatever does not satisfy the contract. |
| `core/` | Shared, renderer-independent pieces: GPU geometry and resources, culling and visibility, terrain, overlays. |
| `forward/` | **Classic**: Fio's original renderer, `ForwardRenderer` (registered as `"Forward"`; `"Classic"` is an alias). The only renderer. |

Classic is the only renderer Fio ships, and the host enforces it: the view
always starts Classic, whatever `[Renderer] renderer` says in `settings.ini`
(a file written when the HD_High renderer existed may still name it; it
starts Classic all the same, and saving Settings writes `Classic` back), and
`QtGameView.switch_renderer` / the console's `r_renderer` refuse any other
name. What a factory returns is checked before the host paints with it:
every member, each method's arguments (names, order, defaults), each
attribute's type and permitted values, a declared `contract_version`, and no
property that raises (`tests/visual/test_renderer_conformance.py`,
`tests/renderer/test_built_in_renderer_classes.py`; the malformed
implementations the registry must refuse are in
`tests/renderer/test_renderer_contract_validation.py`). It is documented in
[`docs/renderers.md`](../../docs/renderers.md).

Classic is locked. Its package, `core/` and `engine/shaders.py` are checked
against recorded digests (`tests/visual/test_classic_lock.py`), and its frames
and final shader sources against a stored set
(`tests/visual/test_classic_golden.py`). After a deliberate change to any of
those files, check the picture with `tools/classic_golden.py --check` (or
`--base` against another checkout) and record it with
`tools/classic_golden.py --lock-sources`.

Inside `forward/`:

| Part | What it is |
|---|---|
| `renderer.py` | `ForwardRenderer`: the frame, pass by pass. |
| `textured/` | The **Textured** display mode (and the Unlit render mode). |
| `solid_lit/` | The **Solid Lit** display mode, and every untextured brush. |
| `wireframe/` | The **Wireframe** display mode: brush edges coloured by distance. |
| `overlay/` | The **Overlay** display mode: Textured with the triangles drawn over it. |
| `passes.py` | Passes every mode shares: glow, terrain, models, sprites, effects, water, glass, fog. |
| `instancing.py`, `lighting.py`, `shaders.py`, `decals.py`, `portals.py`, `occlusion.py` | Instance buffers, lights and shadows, shaders, decals, portals, occlusion queries. |
| `explosion_rows.py` | EXPLOSION instance rows, laid out by `engine.shaders.EXPLOSION_INSTANCE_LAYOUT` (which also generates the shader's attributes); a loop for a handful, NumPy for many. |

More detail is on the wiki:

* [Renderer Technical overview](https://github.com/ViciousSquid/Fio/wiki/Renderer-Technical-overview)
* [Renderer Development Guide](https://github.com/ViciousSquid/Fio/wiki/Renderer-Development-Guide)
