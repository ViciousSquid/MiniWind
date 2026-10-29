# Windows/macOS editor parity handoff

Updated 2026-10-29. Repository: https://github.com/ViciousSquid/MiniWind

## User intent and current branch

Work on **CANARY** and commit/push changes. The user wants the Windows-designed
editor to match on macOS: every tab, font and control size/alignment, with
explicit application rules instead of native Qt/Mac defaults. The initial
problems were enormous terrain buttons and repeated text in editor/game/debug
console inputs. Tabs were left-aligned on Windows but centered on Mac.

The user has limited remaining usage and asked to finish, push, and leave this
handoff. Keep progress updates frequent. Do not claim complete parity merely
because a capture workflow passes. Do not merge CANARY into another branch.

Latest implementation commit: **0ad2e2b**. Documentation status: **2732ee3**.
Both were pushed. This document is being committed separately.

## What is implemented

- `editor/desktop_style.py`: shared Qt Windows renderer, explicit metrics,
  layout policies, palette, standard/file icons, non-native dialogs, font
  registration, and startup DPI configuration. Rules apply to deferred widgets.
- `editor_styles.py`, appended to `main.dark_stylesheet`: explicit states,
  colours, borders, spacing, indicators and geometry for the editor's control
  families. Component-specific styles remain where intentionally designed.
- Left-aligned non-expanding tabs, left-aligned form labels/headers/spin text,
  explicit Windows button order, combo policies and form wrapping.
- Bundled **Fio UI** and **IBM Plex Mono** in `assets/fonts/editor/`, with OFL
  licences. Fio UI is a renamed Selawik derivative with normalized metrics:
  2100 units/em, ascent 2100, descent 700, zero line gap. The shared line box
  matches Windows at the default/enlarged text sizes. See the font README.
- `prepare_qt()` must run **before QApplication**. `QT_FONT_DPI=96` matters for
  stylesheet fonts too. **Do not enable AA_EnableHighDpiScaling on Cocoa**:
  Qt 5 then restores 72-DPI widget text and introduces an unwanted 4/3 scale.
  Cocoa already handles Retina backing pixels. Native widget tests cover this.
- `set_editor_font_size()` also sets popup/menu/tooltip fonts explicitly.
- Application-owned SVGs in `assets/ui/controls/`; affected emoji/symbol action
  buttons, path-node radius, quest cards and cutscene transports were changed
  to explicit icons or plain descriptive text.
- Compact terrain buttons/indicators; summaries wrap; tabs do not impose an
  excessive dock minimum width. Terrain options reflow to two columns when
  narrow. Cutscene pages scroll. Label/check/radio minimum heights follow fonts.
- Dungeon Designer has a scrolling sidebar, preserving readable radio controls
  instead of growing beyond the available screen or compressing text.
- QMessageBox has platform-specific layout code beyond QStyle/QSS. The shared
  policy now assigns Windows margins, gaps, spacer sizes and button-column
  placement explicitly, preserving its standard buttons and content.
- Latest commit `0ad2e2b`: explicit menu-button indicator (12px) and button-icon
  (16px) metrics; explicit 500x360 starting sizes for NPC/creature wizards;
  asset-grid column calculation includes margins/gaps, fixing horizontal
  overflow; capture waits for the asset browser's 50ms resize debounce.
- Original keyboard fix: `engine/sdl_runtime.py` initializes controller polling
  with **SDL_VIDEODRIVER=dummy**. Qt owns native window/keyboard events, so SDL
  cannot pump Cocoa keyboard events a second time. Audio remains initialized
  separately. Both editor and game controller polling use this helper.

## Native evidence and CI status

Workflow: `.github/workflows/editor-ui-parity.yml`.
Four real runners: Windows/Cocoa Qt at scales 1 and 2. Each tests the font,
layout, message-box and asset controls, captures font setting 11 screenshots,
and measures all surfaces again at setting 16.

### Latest source run (0ad2e2b)

https://github.com/ViciousSquid/MiniWind/actions/runs/40887507209

At handoff time:

- Windows scale 1: **success**; job `123495062474`.
- Windows scale 2: **success**; job `123495061782`.
- macOS scale 1: tests passed, enlarged-text capture running; job `123495061914`.
- macOS scale 2: tests passed, enlarged-text capture running; job `123495061568`.
- Final comparison is therefore **not verified yet**. Check this run first.

### Last completed full comparison (ff6127f)

https://github.com/ViciousSquid/MiniWind/actions/runs/40886539573

All four capture jobs and the strict comparison gate passed:

- **Zero font differences** across every recorded font metric.
- **Zero tab-geometry differences**.
- **Zero newly clipped controls or oversized Mac controls**.
- No capture errors/missing configurations.
- Every configuration has matching frame IDs/counts: 953 frames per OS/scale
  at font 11 and 1,153 at font 16; **8,424 frame measurements** in total.
- **140 geometry observations and 7 scrollbar-visibility observations remain**
  in that report. They repeat across configurations and are not 147 separate
  product defects. Some are addressed by the latest 0ad2e2b run.

Shared verified Settings measurements on both OSes:

| Font setting | Fio UI pixels | Line height | Settings dialog |
| --- | ---: | ---: | --- |
| 11 | 15 | 20 | 604x695 |
| 16 | 21 | 28 | 646x741 |

Original audit had Segoe UI 15px/20px on Windows versus Arial 11px/12px on Mac.
The terrain screenshots have been visually inspected after the fix: compact
buttons, matching tab sizes and left alignment.

**Full control-by-control geometry parity is not yet certified.** The report
is deliberately retained for review; do not hide remaining differences.

## Next steps / known remaining observations

1. Finish checking run `40887507209`. Download its platform artifacts/report,
   inspect `summary.json` and group `differences.json` by surface. Compare the
   latest source, not older intermediate failures.
2. Verify the asset/grid, menu-indicator, Arrange button and NPC initial-size
   observations disappeared after 0ad2e2b. Tests now include the grid regression.
3. Remaining known observations from **ff6127f** (before 0ad2e2b):
   - Qt file picker: the intended 720x480 resize on polish was overridden by
     subsequent Qt sizing. Captures still measured Windows 710x454 vs Mac
     675x454, including a 35px sidebar/field offset. Inspect actual QFileDialog
     lifecycle; avoid normalizing away a production issue. Directory contents
     and paths necessarily differ between the native runner filesystems.
   - Project Overview at font 16/scale 2: rich-text label height 610 Windows vs
     582 Mac (dialog 256x678 vs 256x650). Investigate native screen clamping,
     QMessageBox sizing and rich-text layout. This is not caught by the current
     single-line-height clipping check. About dialog margins now match.
   - NPC wizard scale 2 used Mac height 343 vs Windows 360 before the explicit
     initial-size change. Menu-bearing Choose button differed by 4px before
     explicit menu-indicator metrics. Asset thumbnails sometimes wrapped into
     another row before the grid-margin/debounce fixes.
4. Review residual symbol glyph fallback as needed. A QFontInfo family match
   does not prove every Unicode glyph came from that face. Unsupported symbols
   can still use OS fonts; prefer owned SVG icons or plain text for controls.
5. Update `docs/editor-ui-parity-audit.md` with final evidence, commit and push.

## Audit implementation and caveats

- `tools/editor_ui_audit.py`: deterministic scene, all 26 registered entity
  types, brush variants, nested property tabs, terrain/settings/assets/consoles,
  menus/toolbars, authoring tools/wizards, debug tools and Qt file/colour pickers.
  It walks scrollable content. Font 11 saves images; font 16 saves metrics.
- Only the 3D viewport is replaced with a layout placeholder because hosted
  Windows runners lack the required GL context. This does not verify rendered
  game scenes or real hardware keyboard interaction.
- Capture windows use equal logical viewports. Modal windows may already be
  clamped before interception: spell-editor modal now gets explicit 800x900;
  other native/private resize behavior still merits investigation.
- Worker Qt code must run inside `app.exec_()`/QTimer. Manual startup event
  pumping caused hangs on Cocoa earlier. Watchdog is 600 seconds.
- Keep `capture_complete` validation. A partial manifest must fail comparison.
- Worker `os._exit(verdict)` **after saving/flushing artifacts** is intentional:
  Windows/PyQt global teardown otherwise returned exit 1 after successful
  captures and skipped font 16. Verdict still fails incomplete/error captures.
  This is only the disposable audit process, not normal application shutdown.
- `tools/compare_editor_ui.py`: paired HTML, CSV/JSON, metrics comparison.
  It matches uniquely identified controls across anonymous Qt wrapper paths;
  duplicates are not guessed. Earlier raw missing-control counts included
  wizard header wrappers that moved from QWidget[0] to QWidget[1] on Windows.
- Comparison exit status fails font/tab/clipping/oversize regressions and
  incomplete matrices. Other geometry/missing-control observations remain in
  the report and require review; a green job does not certify all geometry.
- Text antialiasing can differ between CoreText and Windows despite identical
  fonts/geometry. Do not claim byte-identical image rendering.

## Local verification and useful commands

Python with desktop dependencies: `/workspace/.venvs/miniwind/bin/python`.
Repository path in this session: `/workspace/MiniWind`.

Completed local checks include 113 broader regression tests, four isolated
SDL/controller tests, 18 focused style/terrain/cutscene tests, six comparison
unit tests, and three asset-browser tests. The latest metric/asset changes
passed 13 style/terrain tests and three asset tests before pushing.
A separate enlarged-font 2x capture completed 204 frames with no errors.

```bash
QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=2 PYOPENGL_PLATFORM=egl \
SDL_AUDIODRIVER=dummy /workspace/.venvs/miniwind/bin/python -m pytest -q \
 tests/editor/test_desktop_style.py tests/editor/test_terrain_panel_layout.py \
 tests/editor/test_asset_browser.py tests/editor/test_cutscene_preview_restore.py \
 tests/tools/test_compare_editor_ui.py tests/engine/test_sdl_runtime.py

/workspace/.venvs/miniwind/bin/python tools/compare_editor_ui.py \
 --captures /workspace/work/native-ff --output /workspace/work/review-report
```

Separate general `Tests` workflow is not all green. Earlier core-tier
collection lacked PyQt5/OpenGL; renderer checks reported raw/wrapped upload
pixel differences and a zero-ambient fog comparison failure. Do not describe
all repository tests as passing. Check the latest run before attributing
failures to these UI changes or expanding scope to unrelated renderer work.

## Local evidence / tooling

Scratch evidence is outside Git, under `/workspace/work/`:

- `native-ff/`, `native-ff-report/`: ff6127f scale-2 Windows/Mac manifests/images.
- `native-latest/`, `native-latest-report/`: de1a9ad full matrix (name predates
  newer commits; do not confuse it with current branch HEAD).
- `native-corrected/`: 9df5925 full matrix; `native-final/`: superseded 68f0d06
  with the DPI regression. Do not use the latter as final evidence.

GitHub connector tools fetch run jobs, logs, artifacts and artifact ZIPs.
`UI_PARITY_SUMMARY` in the comparison-job log contains the full summary;
`UI_PARITY_PRIORITY` contains the first 100 priority observations. Tools can
fetch run metadata with a GitHub API resource URL. Prefer these over shell API
requests in this environment.

Individual platform ZIPs are around 16-18 MB and can be downloaded with the
Sediment `download_file` tool using the returned file_id. The combined report
ZIP can exceed that tool's 32 MB limit: download platform artifacts separately
and regenerate the report locally. GitHub retains artifacts for 14 days.
Do not print signed download URLs or credentials into reports. Git pushes work
through the configured credentials; shell network access may need the normal
additional network permission profile.
