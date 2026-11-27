# Ruined Cathedral (OBJ)

A large, low-poly Gothic cathedral ruin for MiniWind/Fio. The silhouette includes twin broken west towers, a pointed entrance and rose window, open nave, transept, crossing-tower shell, faceted apse, flying buttresses, surviving roof fragments, exposed ribs, broken columns and scattered masonry.

## Files

- `ruined_cathedral.obj` — static mesh with embedded UVs
- `ruined_cathedral.mtl` — material definitions
- `ruined_cathedral_atlas.xpm` — 256 × 256, 4 × 4 albedo atlas

## Scale and orientation

- Y-up; ground-level origin near the centre of the nave footprint
- Front entrance faces +Z
- Approximate footprint: 1,280 × 1,560 units
- Highest surviving tower: approximately 690 units
- Static model; no map placement is included

Keep the OBJ, MTL and XPM together under `assets/models/`. The OBJ references the MTL by filename and the MTL references the atlas by filename. XPM is used because it is already supported by the existing MiniWind model assets.
