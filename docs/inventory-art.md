# Inventory artwork

All 103 item definitions use individual 256×256 transparent PNG icons in
`assets/sprites/items/`. Category fallback icons and the generic arrow sprite
use the same material/lighting style. Item ids, names, statistics and gameplay
properties are unchanged.

The previous 108 PNGs are preserved in
`archive/inventory-icons/2026-10-22/`. Its manifest records each original path
and SHA-256 checksum. That archive is outside the live asset search path.

The realistic replacements are original procedural 3D models rendered by
Blender Cycles on the CPU, with worn metal, wood, leather, cloth, glass and
paper materials. No external model or texture dependencies are needed at
runtime. Blender is only an optional artwork production tool.
The Fist icon depicts a bare clenched human hand, with curled fingers and a
crossing thumb, rendered under the same studio lighting as the other items.

To reproduce or extend the set:

```sh
blender -b -t 4 -P game/tools/render_item_icons.py -- --output work/item-renders
python -m game.tools.import_item_art work/item-renders
```

The importer checks completeness, image resolution and transparency before
replacing any icons, and preserves the first archive across repeated imports.
The original 64px drawing utility (`game.tools.make_item_icons`) remains a
legacy tool; running it without `--missing` replaces the realistic artwork.
