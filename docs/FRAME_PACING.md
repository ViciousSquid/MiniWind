# Play-mode frame pacing

The simulation advances at 60 Hz. Play-mode presentation follows the
`QOpenGLWidget.frameSwapped` signal when VSync is enabled, so the display can
present at 60, 120 or another refresh rate. The precise 16 ms UI timer still
handles input, sound and recovery after the window is exposed; it also drives
presentation when VSync is disabled. The launcher's swap interval is preserved
when constructing the view.

The logic loop uses absolute deadlines. Its former 90%-of-remaining-time sleep
woke it faster than 60 Hz, periodically publishing the same simulation pose
again. Independent 16 ms repaint polling and the lack of interpolation made
walking and camera turns uneven even when average FPS looked healthy.

`CameraHistory` keeps two small camera samples, dated at simulation tick
boundaries. The renderer interpolates eye position, orientation and player
presentation position one tick behind the simulation (about 16.7 ms at normal
speed). This introduces that presentation delay rather than predicting through
walls. It changes only a borrowed snapshot's scalar camera fields; movement,
collision, targeting, entity tables and game time remain authoritative. Both
split-screen cameras use the same interpolation fraction.

Empty loop iterations retain the existing sample time. Pauses, session/camera
mode changes, large teleports and long sample gaps reset interpolation. A late
renderer clamps to the newest pose. Camera history never retains a render-state
lease, and drawing releases its lease before Qt composites and swaps the frame.

Fullscreen play also avoids refreshing hidden editor panels or rescanning
editor terrain settings on every frame. The FPS counter and SysMon frame times
now measure actual paints, rather than UI timer callbacks.

Regression checks cover 60/120/144 Hz camera motion, angle wraparound, rigid
camera transforms, split-screen, pause/cut/teleport resets, publication during a
borrow, and sleep overshoot. Real OpenGL smoke checks run under Xvfb/Mesa on
Linux. They do not establish an M5 GPU performance target or replace a native
macOS check: launch fullscreen with VSync enabled, walk and turn in the same
area, and compare regularity as well as FPS. Camera interpolation cannot hide
arbitrarily long simulation or GPU stalls.
