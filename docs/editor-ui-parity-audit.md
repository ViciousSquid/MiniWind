# Windows / macOS editor UI parity

The shared presentation implementation is committed on `CANARY`. The
[completed native run for `9df5925`](https://github.com/ViciousSquid/MiniWind/actions/runs/40882539900)
recorded **zero font differences, zero tab-geometry differences and zero
oversized macOS controls** across Windows/macOS, font settings 11/16 and scale
factors 1/2. This includes every font metric recorded by the audit: family,
point/pixel size, weight, italic, line height and sample width.

That run still found clipped radio controls in Dungeon Designer and other
geometry differences. Commit `de1a9ad` makes the dungeon sidebar scrollable,
protects checkbox/radio text height, replaces more symbol buttons with SVGs,
and fixes equal-viewport comparison of modal dialogs and wizards. Its
[follow-up native run](https://github.com/ViciousSquid/MiniWind/actions/runs/40884265845)
is in progress. **Full control-by-control geometry parity is not yet certified.**

- [Searchable comparison report for `9df5925`](https://github.com/ViciousSquid/MiniWind/actions/runs/40882539900/artifacts/12901058884)

A completed capture job alone does not establish visual parity; inspect the
measured differences and paired screenshots as well.

## Explicit presentation contract

- Bundled Fio UI and IBM Plex Mono fonts, loaded directly by Qt. Fio UI is an
  OFL-licensed Selawik derivative with normalized line metrics. Both systems
  convert point sizes at 96 logical DPI while retaining Retina pixel density.
- A shared Qt Windows renderer with explicit layout metrics and style hints,
  plus control styles for buttons, inputs, spin boxes, combo boxes, checks,
  radios, tabs, groups, views, headers, menus, sliders, scrollbars, toolbars,
  docks, progress bars and tooltips. Colours, control states, borders, padding,
  indicators, icons and spacing are defined by the application.
- Left-aligned, non-expanding tabs; left-aligned form labels, headers and spin
  text; Windows dialog button order. Actual widget policies also apply to
  deferred pages and dialogs with component stylesheets.
- Application-owned SVG control/action/file icons, explicit menu and popup
  fonts, an application palette for every colour group, and non-native Qt
  file/colour dialogs. macOS native control themes and emoji glyphs no longer
  determine the affected control geometry.
- Compact terrain controls, responsive option rows, wrapped summaries and
  scrollable cutscene pages. Label height follows the font when enlarged or
  reduced, preventing layout compression from cutting off a text line.

The keyboard fix is separate: controller polling uses SDL's dummy video
backend so it cannot pump Cocoa window/keyboard events alongside Qt. Qt
continues to own editor and console text input.

Definitions live in `editor/desktop_style.py`, `editor_styles.py`, and
`assets/ui/controls/`. Font sources, modifications and licences are documented
in `assets/fonts/editor/README.md`.

## Native verification

The reusable workflow is `.github/workflows/editor-ui-parity.yml`. It runs
actual Windows Qt and Cocoa Qt at scale factors 1 and 2. Every runner checks
alignment, fonts and terrain layout before capturing all editor surfaces at
font setting 11 and measuring them again at setting 16. Partial captures and
missing configurations cause report generation to fail.

The fixture visits all 26 registered entity types, brush variants, nested
property tabs, terrain tabs, settings, assets, consoles, menus, toolbars,
inspectors, item/logic/quest/spell tools, cutscenes, creature/NPC wizards,
dungeon tools, simulation tools, loading/debug surfaces and Qt file/colour
pickers. Scrollable content is visited page by page. Logical capture viewports
are fixed to avoid differences caused by the runners' desktop work areas.

Download **editor-ui-parity-report** from the run, extract it, and open
`index.html`. Search by surface, tab, font size or scale. `differences.csv` and
`differences.json` contain individual measurements, including resolved font
family, pixel size, weight, line height and sample width. Each platform
artifact includes screenshots and complete `manifest.json` files. Artifacts
expire after 14 days.

Local verification of the final implementation: **113 regression tests and
four SDL/controller isolation tests passed**; the strengthened native font
and terrain checks also passed in all four runner jobs. A focused enlarged-font 2×
capture completed with **204 frames and no capture errors**.

## Original baseline

The [initial audit](https://github.com/ViciousSquid/MiniWind/actions/runs/40864744663)
exposed the OS defaults that motivated the shared contract:

| Font setting 11, scale 1 | Original Windows | Original macOS |
| --- | --- | --- |
| Resolved family | Segoe UI | Arial |
| Resolved pixel size | 15 | 11 |
| Typical line height | 20 | 12 |
| Settings dialog | 600×668 | 640×733 |

The completed shared-font run measured the same results on both platforms:

| Metric | Setting 11 | Setting 16 |
| --- | ---: | ---: |
| Fio UI pixel size | 15 | 21 |
| Line height | 20 | 28 |
| Settings dialog | 604×695 | 646×741 |

Across all eight configurations the run recorded 8,631 frame measurements
and no capture errors. Frame counts can differ for scroll pages. Structural
paths through Qt's internal anonymous widgets also differ between platforms;
raw missing-control counts require reviewing their text and screenshots.

A local 2× check of `de1a9ad` confirms all six dungeon radio controls retain
full text height at both settings, the sidebar scrolls vertically, and it
requires no horizontal scrolling.

## Scope

The audit exercises real editor widgets using the platform's Qt backend.
Only the 3D viewport is replaced by a layout placeholder because hosted
Windows runners do not provide the engine's required OpenGL context. It does
not compare rendered game scenes or arbitrary combinations of every property
value. Shared fonts and dimensions do not make CoreText and Windows text
antialiasing byte-identical; screenshots remain useful alongside geometry
and font measurements.
