"""Co-op must take its locks in one global order, or the game can freeze.

Two threads touch the party:

* the logic thread runs ``CoopSession.tick`` under ``coop.lock`` and, inside
  it, the root session's tick, which takes ``monster_lock`` (grounding actors,
  projectiles, combat);
* the MonsterAI thread runs ``MonsterAI.update`` under ``monster_lock`` and,
  when a monster hits a party member, ``CoopSession.damage`` takes
  ``coop.lock``.

If the logic thread took ``coop.lock`` first and ``monster_lock`` second while
the AI thread took them the other way round, the two would wait on each other
for ever: no exception, no log line, the last frame left on screen. The order
is therefore ``monster_lock`` before ``coop.lock`` on every thread.
"""

from __future__ import annotations

import threading

import pytest

from game.tests.test_multiplayer_integration import coop_game  # noqa: F401,F811  (fixture)

pytestmark = [pytest.mark.qt, pytest.mark.integration]


class _OrderedLock:
    """An RLock that records when it is taken while *inner* is already held."""

    def __init__(self, name, log, held):
        self._lock = threading.RLock()
        self.name, self._log, self._held = name, log, held

    def _stack(self):
        stack = getattr(self._held, "stack", None)
        if stack is None:
            stack = self._held.stack = []
        return stack

    def acquire(self, blocking=True, timeout=-1):
        stack = self._stack()
        if self.name not in stack:
            self._log.append((self.name, tuple(stack)))
        got = self._lock.acquire(blocking, timeout)
        if got:
            stack.append(self.name)
        return got

    def release(self):
        stack = self._stack()
        stack.reverse()
        stack.remove(self.name)
        stack.reverse()
        self._lock.release()

    __enter__ = acquire

    def __exit__(self, *exc):
        self.release()


def _instrument(game, monkeypatch):
    log, held = [], threading.local()
    logic = game.logic
    coop = logic.game_session.coop
    monkeypatch.setattr(logic.session_runtime, "monster_lock",
                        _OrderedLock("monster_lock", log, held))
    monkeypatch.setattr(coop, "lock", _OrderedLock("coop.lock", log, held))
    return log, coop


def test_coop_tick_never_takes_monster_lock_inside_coop_lock(coop_game, monkeypatch):
    log, coop = _instrument(coop_game, monkeypatch)
    for player in list(coop.players.values())[1:]:
        player.bot = True
    coop_game.step(30)
    assert any(name == "monster_lock" for name, _ in log), "the tick never took monster_lock"
    inverted = [(name, outer) for name, outer in log
                if name == "monster_lock" and "coop.lock" in outer]
    assert not inverted, (
        "monster_lock was taken while coop.lock was held; the MonsterAI thread "
        "takes them the other way round, so this can deadlock: %r" % inverted[:3])


def test_monster_hit_during_coop_tick_does_not_deadlock(coop_game, monkeypatch):
    """The two real code paths, interleaved as the threads can interleave them."""
    logic = coop_game.logic
    coop = logic.game_session.coop
    ai_holds_monster_lock = threading.Event()
    timeouts = []

    class _BoundedRLock:
        """Fails after a few seconds instead of hanging the test run."""

        def __init__(self, name):
            self._lock, self.name = threading.RLock(), name

        def acquire(self, blocking=True, timeout=-1):
            if not self._lock.acquire(timeout=3.0):
                timeouts.append((threading.current_thread().name, self.name))
                raise RuntimeError("deadlock waiting for " + self.name)
            if self.name == "coop.lock" and threading.current_thread().name == "logic-role":
                # Hold the party lock until the monster thread holds its lock:
                # the window in which the real threads deadlock.
                ai_holds_monster_lock.wait(1.0)
            return True

        def release(self):
            self._lock.release()

        __enter__ = acquire

        def __exit__(self, *exc):
            self.release()

    monster_lock = _BoundedRLock("monster_lock")
    monkeypatch.setattr(logic.session_runtime, "monster_lock", monster_lock)
    monkeypatch.setattr(coop, "lock", _BoundedRLock("coop.lock"))
    root = coop.root

    def ai_role():
        with monster_lock:
            ai_holds_monster_lock.set()
            # A monster's melee hit on the party, exactly as MonsterAI does it.
            logic.trigger_runtime._apply_player_damage(1.0, source=None, cause="attack")

    def logic_role():
        # What CoopSession.tick does around the root session's tick.
        ctx = type("Ctx", (), {"delta": 1 / 60, "keys": (), "key_down": staticmethod(lambda _k: False)})()
        coop.tick(ctx)
        root._ground_actors()

    errors = []

    def guarded(body):
        def run():
            try:
                body()
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(repr(exc))
        return run

    logic_thread = threading.Thread(target=guarded(logic_role), name="logic-role", daemon=True)
    ai_thread = threading.Thread(target=guarded(ai_role), name="ai-role", daemon=True)
    logic_thread.start()
    ai_thread.start()
    logic_thread.join(15)
    ai_thread.join(15)
    assert not logic_thread.is_alive() and not ai_thread.is_alive()
    assert not timeouts, "threads deadlocked on %r (%r)" % (timeouts, errors)
