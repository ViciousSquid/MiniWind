# Blood stains (physical gibs)

When an actor is **gibbed** by a *physical* killing blow (melee or an arrow) —
a hit dealing at least 120% of its maximum health — the body is blown apart and
replaced by one of the blood-stain sprites in this folder.

## Provide your own

Drop your own images in here (`.png`, `.jpg`, `.webp`, …). Two rules:

1. **Order = severity.** Files are sorted by filename and treated as
   **mild → severe**. The game picks a stain by how far the killing blow
   overshot the victim's health: a hit just over the gib threshold uses the
   first (mildest) file; a massive overkill (≥ 3× max health) uses the last
   (severest). Prefix names to control the order, e.g. `1_mild.png`,
   `2_light.png`, `3_heavy.png`, `4_severe.png`.
2. **Any count works.** Two files or twenty — the severity range maps across
   however many are present.

Images are drawn flat on the ground (top-down), so a roughly square,
transparent-background splatter reads best.

The files shipped here are procedural placeholders (from
`python -m game.tools.make_sprites`); replace them with your own art freely.
For *magical* kills the target disintegrates instead — see the sibling
`../disintegrate/` folder.
