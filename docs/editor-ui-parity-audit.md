# Windows / macOS editor UI parity audit

The native comparison completed successfully on GitHub Actions for commit
`9aad76e1cff0cefbaeed821294108eb81b554105`. **The editor does not yet have
visual parity between Windows and macOS.** A successful workflow means the
captures and comparison completed; it does not mean their appearances match.

- [Completed native run](https://github.com/ViciousSquid/MiniWind/actions/runs/40864744663)
- [Download the searchable comparison report](https://github.com/ViciousSquid/MiniWind/actions/runs/40864744663/artifacts/12893820778)

Download the report ZIP, extract it, and open `index.html`. Search by entity,
dialog, tab, font size, or scale. `differences.csv` and `differences.json`
contain the individual control measurements. Original platform artifacts
include the screenshots and complete `manifest.json` files. GitHub retains
these artifacts for 14 days from the run.

## Coverage

The matrix used native Windows Qt and Cocoa Qt, font settings 11 and 16,
and scale factors 1 and 2. Both platforms used the same source, deterministic
scene, application stylesheet, and settings.

Each configuration captured 76 editor surfaces, including all 26 registered
entity types' property tabs, brush variants, terrain tabs, settings, asset
browser tabs, consoles, toolbars, menus, inspectors, item editor, logic tools,
cutscenes, quest tools, spell editor, NPC/creature wizards, dungeon designer,
simulation tools, loading overlay, and debug tables. Nested tabs and
scrollable form content were visited.

| Platform | Font | Scale | Captures | Capture errors |
| --- | ---: | ---: | ---: | ---: |
| Windows | 11 | 1 | 927 | 0 |
| macOS | 11 | 1 | 811 | 0 |
| Windows | 11 | 2 | 1,032 | 0 |
| macOS | 11 | 2 | 852 | 0 |
| Windows | 16 | 1 | 1,089 | 0 |
| macOS | 16 | 1 | 876 | 0 |
| Windows | 16 | 2 | 1,202 | 0 |
| macOS | 16 | 2 | 933 | 0 |

Total: **7,722 captures**. Every non-scroll frame/tab identifier had a
counterpart on the other platform. Different scroll-page counts reflect
different text metrics, wrapping and layout heights, rather than missing tabs.

The requested main window was 1440×900 logical pixels. Native layout settled
at 1280×800 on both scale-1 runners. Always use each frame's recorded `size`;
the original report's introductory 1440×900 description refers to the requested
size, not a guaranteed final size. Images are normalized to logical pixels;
device pixel ratio and logical DPI are retained separately.

## Confirmed differences

### Fonts and control proportions

The shared stylesheet requests Segoe UI. Windows has that font; macOS falls
back to Arial. The runners report logical DPI 96 on Windows and 72 on macOS,
which also changes the conversion from points to logical pixels.

| Metric at font setting 11, scale 1 | Windows | macOS |
| --- | --- | --- |
| Resolved family | Segoe UI | Arial |
| Resolved pixel size | 15 | 11 |
| Typical font metric height | 20 | 12 |
| Settings → Editor dialog size | 600×668 | 640×733 |
| Terrain Reset Defaults button size | 117×30 | 95×23 |

At setting 16, the common resolved pixel sizes are 21 on Windows and 16 on
macOS. Therefore, using the same point-size setting does not provide the
same text size or wrapping. Fixed indicator sizes and padding take up a larger
proportion of the Mac text. The Settings screenshots visibly demonstrate this
with the checkbox indicators, group spacing, labels, and tabs.

### Enlarged-font clipping

At font setting 16, Cutscenes → Events → I/O Input has Mac controls whose
allocated height is smaller than their font metrics. At scale 1, labels
“At time”, “Input”, and “Parameter” receive 8 pixels; “Target entity” receives
9 pixels; “Add I/O input” receives 9 pixels. Windows allocates 38 pixels to
those labels and 42 pixels to the button. Scale 2 also reproduces the problem.

Terrain → Appearance also has a “0%” label allocated 16 pixels at font setting
16, below its Mac font metric height. These should be corrected before
claiming enlarged-text parity.

### Native layout differences

Settings dialog margins, slider appearance, button order, and tab widths
differ. Some are native platform conventions, such as Cancel/OK order; they
should be distinguished from clipping and disproportionate sizing.

The raw report includes internal Qt arrow buttons and repeated observations
of controls in multiple states. Its flag counts are not counts of unique
product defects. Wider checkbox widget rectangles can result from form growth
without a wider painted checkbox indicator.

## Scope limits and next work

The audit excludes 3D scene rendering, gameplay HUD, OS file/colour pickers,
and arbitrary combinations of every field value. The real editor widgets and
native styles are used, with a layout-only viewport substitute because hosted
Windows runners do not supply the engine's required OpenGL context.

The next implementation work is to establish a font family and text-size
conversion that preserve the Windows reference metrics, make fixed control
dimensions follow that text size, and repair the enlarged-font layouts above.
This audit commit records and measures these remaining issues; it does not
silently change the editor's fonts or native platform conventions.

The reusable workflow is `.github/workflows/editor-ui-parity.yml`. Capture is
implemented in `tools/editor_ui_audit.py`; report generation is in
`tools/compare_editor_ui.py`.
