# Medieval village house set (OBJ)

Four low-poly, top-down-friendly medieval buildings for MiniWind/Fio.

| OBJ | Style | Approximate footprint |
|---|---|---|
| `village_cottage_thatch.obj` | Limewashed cottage, thatch roof, chimney | 284 × 238 units |
| `village_timber_framed_house.obj` | Two-storey half-timbered house, clay roof | 362 × 278 units |
| `village_stone_smithy.obj` | Stone smithy/workshop, clay roof, tall chimney | 320 × 260 units |
| `village_merchant_house.obj` | Merchant house with shop awning and sign | 276 × 296 units |

## Import

Keep each OBJ, `village_houses.mtl`, and `village_house_atlas.xpm` together in
`assets/models/`. Each OBJ references `village_houses.mtl`; the MTL maps all
materials to the shared atlas. UVs are embedded in each OBJ. The XPM texture is
loaded through Qt's image loader and needs no separate conversion.

Models use Y-up coordinates, a ground-level centre origin, and front-facing +Z.
Vertices are authored at twice the blockout scale to give a plausible footprint
beside a 100-unit player character. The diffuse atlas contains plaster, oak,
thatch, clay roof tiles, rough stone, leaded glass, limewash and dark timber.
