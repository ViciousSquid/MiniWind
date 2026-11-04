"""The freeze watchdog reports a stalled game with every thread's stack."""

import threading
import time

from engine import error_report
from engine.freeze_watchdog import FreezeWatchdog


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _watch(serial, clock, **kw):
    reports = []
    dog = FreezeWatchdog(lambda: serial[0], clock=clock,
                         on_stall=lambda *r: reports.append(r), **kw)
    return dog, reports


def setup_function(_):
    error_report.clear_notices()
    error_report._logged.clear()


def test_a_logic_stall_with_a_live_ui_is_reported_once_with_stacks():
    clock, serial = Clock(), [1]
    dog, reports = _watch(serial, clock, logic_stall=8.0)
    for _ in range(20):            # 20 s: UI beating, simulation stuck
        clock.now += 1.0
        dog.ui_beat()
        dog.check()
    assert len(reports) == 1 and reports[0][0] == "logic"
    assert "MainThread" in reports[0][2], "every thread's stack is captured"
    notices = error_report.take_notices()
    assert notices and "stopped responding" in notices[0].message


def test_a_ticking_game_or_one_not_playing_is_never_reported():
    clock, serial = Clock(), [0]
    dog, reports = _watch(serial, clock)
    for i in range(60):
        clock.now += 1.0
        serial[0] = i              # ticking
        dog.ui_beat()
        dog.check()
    serial[0] = None               # not playing: nothing to watch
    for _ in range(60):
        clock.now += 1.0
        dog.ui_beat()
        dog.check()
    assert reports == []


def test_a_level_load_blocking_both_threads_is_not_a_freeze():
    """Loading a map holds the UI thread and the tick lock for seconds: the
    simulation stops, but so does the UI, which is not a logic freeze."""
    clock, serial = Clock(), [5]
    dog, reports = _watch(serial, clock, logic_stall=8.0, ui_stall=30.0)
    dog.check()
    for _ in range(12):            # a 12 s load: no UI beats, no ticks
        clock.now += 1.0
        dog.check()
    clock.now += 1.0
    serial[0] = 6                  # load done: both resume
    dog.ui_beat()
    dog.check()
    assert reports == []


def test_a_ui_stall_longer_than_any_load_is_reported():
    clock, serial = Clock(), [None]
    dog, reports = _watch(serial, clock, ui_stall=30.0)
    for _ in range(31):
        clock.now += 1.0
        dog.check()
    assert [r[0] for r in reports] == ["ui"]


def test_the_thread_catches_a_real_blocked_logic_loop():
    """End to end: a thread stuck on a lock it can never get."""
    lock = threading.Lock()
    lock.acquire()
    serial = [0]

    def stuck_logic():
        serial[0] += 1
        with lock:                 # never acquired: the "deadlock"
            serial[0] += 1

    worker = threading.Thread(target=stuck_logic, name="LogicThread-test", daemon=True)
    worker.start()
    reports = []
    dog = FreezeWatchdog(lambda: serial[0], interval=0.02, logic_stall=0.3,
                         on_stall=lambda *r: reports.append(r))
    beating = threading.Event()

    def ui():
        while not beating.is_set():
            dog.ui_beat()
            time.sleep(0.01)

    ui_thread = threading.Thread(target=ui, daemon=True)
    ui_thread.start()
    dog.start()
    deadline = time.monotonic() + 5.0
    while not reports and time.monotonic() < deadline:
        time.sleep(0.02)
    dog.stop()
    beating.set()
    lock.release()
    worker.join(2.0)
    assert reports, "the stuck logic thread was not reported"
    assert "LogicThread-test" in reports[0][2] and "stuck_logic" in reports[0][2]
