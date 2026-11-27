# Medieval hovel homes (OBJ)

Five additional low-poly, slightly crooked medieval hovels for MiniWind/Fio. Designed to read clearly from an elevated top-down camera and use the same Y-up, ground-level-centred coordinate convention as the existing village houses.

| OBJ | Style | Approximate footprint |
|---|---|---:|
| `village_hovel_wattle_daub.obj` | Wattle-and-daub cottage, exposed framing, thatch and porch canopy | 232 × 208 units |
| `village_hovel_stonecroft.obj` | Low stone cottage, patched clay/thatch roof, chimney and quoins | 214 × 228 units |
| `village_hovel_tanners_lean_to.obj` | Lean-to home/workshop with drying rack and tanning tubs | 290 × 220 units |
| `village_hovel_peatcutters_longhouse.obj` | Longhouse with attached peat store, chimney and woodpile | 350 × 226 units |
| `village_hovel_fishers_crook.obj` | Narrow crooked cottage with side porch, drying rack and chimney | 270 × 260 units |

## Materials and import

Each OBJ references the existing `village_houses.mtl` and `village_house_atlas.xpm` diffuse atlas. UV coordinates are embedded in every OBJ and address the atlas regions for plaster, oak, thatch, clay roof, stone, glass, limewash and dark oak. Keep the existing MTL and XPM files alongside these models in `assets/models/`; no additional texture installation or conversion is required.

All five files are standalone OBJ meshes. They do not require GLB sidecars or asset-loader changes. They are added as reusable assets and are not automatically placed into a world map.
