# MiniWind windmill

A static, game-ready windmill inspired by the reference: tapered brick tower,
gray metal bonnet, red timber lattice sails, timber door and small windows.

## Scale and placement

The player is **100 units tall**. At model scale **[1, 1, 1]**:

| Measurement | Game units |
| --- | ---: |
| Overall height, including sail tips | 842.74 |
| Foundation diameter | 288 |
| Door opening/leaf height | 106 |
| Rotor hub above ground | 550 |
| Overall width | 585.48 |
| Triangle count | approximately 3,240 |

Both model formats are **Y-up**, face **+Z**, and have their origin at the
center of the foundation on **Y=0**. Use **rotation [0, 0, 0]** and
**scale [1, 1, 1]**. Put the Prop's Y coordinate at the ground surface.
All transforms are baked into the exported mesh for Fio's current loaders.

- `../windmill.glb`: GLB model with the shared `windmill/brick_albedo.png` texture.
- `windmill.obj`: keep `windmill.mtl` and `brick_albedo.png` beside it.
- `windmill.json`: dimensions and sprite placement metadata.

Keep the supplied folder structure when copying the assets into Fio. The GLB
uses an external texture so Fio's current renderer displays the brickwork.

Drop either model into the editor from the Models browser. It becomes a Prop.
`maps/Windmill_Comparison.json` places both formats and both rendered sprites
side by side. The examples are scenery, with carrying, physics and collection
disabled. The mesh has no interior; the door and windows are shallow details.

The windmill is taller than Fio's default 800-unit overhead camera. Raise the
camera above the 843-unit sail tips when viewing the complete 3D model; around
1,800–2,400 units is useful for comparison. In Play, `cam overhead 0` selects
the overhead camera, and `overheadangle 90` selects straight down.

## Sprites

The rendered sprites use the same geometry, real transparent alpha, and no
ground or baked ground shadow. Both are 1024×1024. Their ground-center anchor
is at the **center of the canvas**; transparent padding is intentional.

| File in `assets/sprites/scenery/` | View | Prop `sprite_size` |
| --- | --- | --- |
| `windmill_topdown.png` | True orthographic 90° overhead | `[720, 720]` |
| `windmill_overhead.png` | Orthographic 60° elevation | `[860, 860]` |

Create a Prop with `render_mode: "billboard"`, set `sprite_path` to the chosen
file, and use the size above. Place its center at the footprint, just above
the ground. These dimensions match the orthographic render's world scale.
The game camera's perspective can change the apparent size of tall 3D geometry.

The sails are vertical on a real windmill. They appear edge-on in a true
straight-down view; the angled sprite makes the lattice and tower easier to
recognize. Both versions are provided so they can be compared in the game.

The separate `windmill_fantasy_topdown.png` and `windmill_fantasy_overhead.png`
are transparent fantasy artwork, rather than renders of this basic mesh.

## Rebuild / edit

From the repository root, using Blender 4.3 or newer:

```sh
blender -b -t 4 -P game/tools/make_windmill.py -- --samples 96
```

This writes the models, texture, sprites and dimensions to their asset folders,
and an editable `windmill.blend`, model preview and 100-unit scale preview to
`work/windmill/`. The Blender source retains a named rotor pivot. Only model
geometry is exported; lights, cameras and the scale reference are excluded.
