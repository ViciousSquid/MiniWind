# Validation: lockpicking, artwork and overhead camera

All **6,557 collected tests** have passing results, reconciled by pytest node
id across the full non-GL run, the GL/benchmark run and focused final reruns.
There are no collected cases without a passing result.

Validation ran on Linux with Python 3.14, PyQt5 and dummy SDL audio. The 212
OpenGL/optional benchmark cases ran with an actual Xvfb display and Mesa software
rendering. Shader validation used `glslangValidator`. These checks do not replace
native Windows/macOS hardware playtesting or establish a hardware FPS target.

The final focused run passed 1,116 cases, covering lock mechanics, resource loss,
jam persistence, Knock, witnesses, live-world input, interruption on lethal damage,
charged-weapon cancellation, logical/scaled mouse coordinates, camera geometry,
console commands, artwork import and suite integrity. The final artwork checks
also passed after the bare-fist render was imported.

All 103 item definitions have individual transparent 256px icons. All 108
archived originals match the original Git blobs byte for byte, and item data is
unchanged. Category fallback icons and the arrow sprite are replaced too.

The gallery passed desktop/mobile Chromium checks for image loading, searching,
category filtering, comparisons, modal browsing, keyboard dismissal and overflow.
The Fist detail view was checked again after replacement; its image bytes match
the game's asset. No browser JavaScript errors were observed.
