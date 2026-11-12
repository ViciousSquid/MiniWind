"""Exercise the real loop with a deterministic clock and variable tick costs."""

import pytest

pytest.importorskip('PyQt5')

from engine.logic_thread import LogicThread

pytestmark = pytest.mark.qt


def test_deadlines_do_not_drift_with_sleep_overshoot(monkeypatch):
    from engine import logic_thread

    from editor.editor_state import EditorState
    from engine.threaded_game_state import ThreadedGameState

    clock = [10.0]
    frames = []
    # The real thread object; only its frame work is replaced, and run() is
    # driven on this thread so the clock can be controlled.
    logic = LogicThread(ThreadedGameState(), EditorState())
    logic.running = True

    def step(accumulator, *, frame_time):
        frames.append(frame_time)
        clock[0] += (0.003, 0.007, 0.001)[len(frames) % 3]
        if len(frames) == 121:
            logic.running = False
        return accumulator % logic.TICK_DURATION

    logic._step_frame = step
    logic._publish_frame = lambda: None
    monkeypatch.setattr(logic_thread.time, 'perf_counter', lambda: clock[0])
    monkeypatch.setattr(logic_thread.time, 'sleep', lambda delay: clock.__setitem__(0, clock[0] + delay + 0.001))
    logic.run()
    # The first frame carries one sleep overshoot (1 ms) and the stubbed
    # frame's cost; from then on every frame starts exactly a tick after the
    # last, so the overshoot never accumulates.
    assert logic.TICK_DURATION < frames[1] - frames[0] < logic.TICK_DURATION + 0.0015
    assert [b - a for a, b in zip(frames[1:], frames[2:])] == pytest.approx([logic.TICK_DURATION] * 119)
