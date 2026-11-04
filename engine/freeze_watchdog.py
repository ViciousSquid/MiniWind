"""Notice when the game stops moving, and say why.

A deadlocked logic thread leaves the UI repainting its last frame: the game
looks frozen and nothing is printed. :class:`FreezeWatchdog` runs on its own
thread and watches two heartbeats:

* the logic thread's simulation serial, which advances every tick (paused
  worlds included);
* a UI heartbeat the main window bumps from a timer.

If the logic thread stops ticking while the UI is still responsive, that is a
freeze (a deadlock or an endless loop): every thread's stack is written to the
log file and the screen says so. If the UI thread itself stops for a long time
(longer than any level load), its stack is logged too. Each stall is reported
once; recovery is logged.

Pure Python and Qt-free: the heartbeats are plain callables.
"""

from __future__ import annotations

import io
import sys
import threading
import time
import traceback

from . import error_report

LOGIC_STALL_SECONDS = 8.0
UI_STALL_SECONDS = 30.0
#: The UI counts as responsive when its heartbeat is at most this old.
UI_FRESH_SECONDS = 2.0


def thread_stacks() -> str:
    """Every thread's current stack, named, as text."""
    names = {t.ident: t.name for t in threading.enumerate()}
    out = io.StringIO()
    for ident, frame in sys._current_frames().items():
        out.write("--- %s (%s)\n" % (names.get(ident, "?"), ident))
        out.write("".join(traceback.format_stack(frame)))
    return out.getvalue()


class FreezeWatchdog(threading.Thread):
    """Watches *logic_serial* and the UI heartbeat; reports stalls.

    *logic_serial()* returns the logic thread's tick counter, or None when
    there is nothing to watch (no logic thread, not playing). The owner calls
    :meth:`ui_beat` from the UI thread a few times a second.
    """

    def __init__(self, logic_serial, *, interval=1.0, clock=time.monotonic,
                 logic_stall=LOGIC_STALL_SECONDS, ui_stall=UI_STALL_SECONDS,
                 on_stall=None):
        super().__init__(name="FreezeWatchdog", daemon=True)
        self._logic_serial = logic_serial
        self._interval = interval
        self._clock = clock
        self.logic_stall = logic_stall
        self.ui_stall = ui_stall
        self._on_stall = on_stall
        self._stop = threading.Event()
        now = clock()
        self._ui_at = now
        self._serial = None
        self._serial_at = now
        self.logic_stalled = False
        self.ui_stalled = False
        self.reports = []

    def ui_beat(self):
        self._ui_at = self._clock()

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.wait(self._interval):
            try:
                self.check()
            except Exception as exc:  # pragma: no cover - never kill the watch
                error_report.report_error("Freeze watchdog failed", exc, show=False)

    def check(self):
        """One look at the heartbeats (the thread calls this every interval)."""
        now = self._clock()
        try:
            serial = self._logic_serial()
        except Exception:
            serial = None
        if serial is None or serial != self._serial:
            if self.logic_stalled:
                self.logic_stalled = False
                error_report.log_info("Logic thread is ticking again after a stall")
            self._serial, self._serial_at = serial, now
        ui_age = now - self._ui_at
        logic_age = now - self._serial_at
        if self.ui_stalled and ui_age < UI_FRESH_SECONDS:
            self.ui_stalled = False
            error_report.log_info("UI thread is responsive again after a stall")

        if (serial is not None and not self.logic_stalled
                and logic_age >= self.logic_stall and ui_age < UI_FRESH_SECONDS):
            self.logic_stalled = True
            self._report("The game stopped responding: the simulation has not "
                         "advanced for %d seconds" % logic_age, "logic")
        if not self.ui_stalled and ui_age >= self.ui_stall:
            self.ui_stalled = True
            self._report("The window stopped responding for %d seconds" % ui_age, "ui")

    def _report(self, message, kind):
        stacks = thread_stacks()
        self.reports.append((kind, message, stacks))
        error_report.report_error(message + " (thread stacks written to the log)",
                                  trace="Thread stacks:\n" + stacks)
        handle = error_report.crash_file()
        if handle is not None:
            try:
                handle.write("\n%s %s\n%s\n" % (time.strftime("%H:%M:%S"), message, stacks))
                handle.flush()
            except Exception:
                pass
        if self._on_stall is not None:
            try:
                self._on_stall(kind, message, stacks)
            except Exception:
                pass
