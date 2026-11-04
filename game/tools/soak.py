"""Headless soak test: play MiniWind for a long time and catch freezes.

Drives the real editor -> Fio runtime -> MiniWind session on the shipping map
(``maps/miniwind_world.json``) with a randomised "player" and watches for the
ways a game can freeze without printing anything:

* a tick that never returns (an infinite loop): a watchdog dumps every
  thread's stack once a tick has run for ``--hang`` seconds;
* a tick that returns but takes far too long (a hitch): a sampling profiler
  records where the main thread spent the slow tick;
* the logic thread faulting (``_tick_faulted``) or failing to prepare frames
  (``_frame_prepared`` stays False): the screen stops updating while the
  engine only reports it to the in-editor Debug Console, never to stdout;
* (``--threaded``) a deadlock between the free-running logic thread, the
  monster AI thread and the UI thread: frame publication is watched instead.

Modes::

    python game/tools/soak.py --mode single --minutes 10
    python game/tools/soak.py --mode bots   --minutes 10      # 1 human + 3 AI companions
    python game/tools/soak.py --mode mixed  --minutes 10      # 2 humans + 2 AI companions
    python game/tools/soak.py --mode bots --threaded --minutes 5

``--minutes`` is game time at 60 ticks per second (wall-clock minutes with
``--threaded``). Stepped runs are reproducible from ``--seed``; they run the
monster AI on the main thread, so only ``--threaded`` can catch a deadlock
between the logic and MonsterAI threads. The report is printed and written as
JSON (``--report``), with a world-state probe every ``--probe-every`` ticks.

Offscreen there is no GL context, so the harness does the frame handling that
``QtGameView._paint_frame`` would (LevelChanger hand-off). With an X display
(e.g. Xvfb) ``--threaded`` lets the real view paint instead.
"""

from __future__ import annotations

import argparse
import collections
import faulthandler
import io
import json
import math
import os
import random
import sys
import threading
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

if not os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("XDG_RUNTIME_DIR", "/tmp/fio-soak-runtime")
os.makedirs(os.environ["XDG_RUNTIME_DIR"], mode=0o700, exist_ok=True)

TICK = 1.0 / 60.0


# ---------------------------------------------------------------------------
# Instrumentation
# ---------------------------------------------------------------------------

class Sampler(threading.Thread):
    """Samples one thread's stack every few milliseconds into a ring buffer."""

    def __init__(self, ident, interval=0.005, keep=4000):
        super().__init__(daemon=True, name="soak-sampler")
        self.target, self.interval = ident, interval
        self.samples = collections.deque(maxlen=keep)
        self.running = True

    def run(self):
        while self.running:
            frame = sys._current_frames().get(self.target)
            if frame is not None:
                stack = []
                while frame is not None and len(stack) < 40:
                    code = frame.f_code
                    stack.append("%s:%d %s" % (os.path.relpath(code.co_filename, ROOT),
                                               frame.f_lineno, code.co_name))
                    frame = frame.f_back
                self.samples.append((time.perf_counter(), tuple(stack)))
            time.sleep(self.interval)

    def between(self, start, end):
        return [s for t, s in list(self.samples) if start <= t <= end]


def hot_frames(stacks, top=6):
    """The project frames that appear in the most samples, innermost first."""
    counts = collections.Counter()
    leaf = collections.Counter()
    for stack in stacks:
        own = [f for f in stack if not f.startswith((".", "/")) and "game/tools/soak.py" not in f]
        if own:
            leaf[own[0]] += 1
        for f in set(own):
            counts[f] += 1
    n = max(1, len(stacks))
    return {
        "samples": len(stacks),
        "leaf": [(f, round(c / n, 2)) for f, c in leaf.most_common(top)],
        "inclusive": [(f, round(c / n, 2)) for f, c in counts.most_common(top * 2)],
    }


def all_stacks():
    names = {t.ident: t.name for t in threading.enumerate()}
    out = io.StringIO()
    for ident, frame in sys._current_frames().items():
        out.write("--- thread %s (%s)\n" % (names.get(ident, "?"), ident))
        out.write("".join(traceback.format_stack(frame)))
    return out.getvalue()


def rss_mb():
    try:
        with open("/proc/self/statm") as handle:
            return int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") // (1 << 20)
    except (OSError, ValueError):
        return None


def capture_debug_log(sink):
    """Mirror the in-editor Debug Console (``debug_log``) into *sink*."""
    try:
        from editor import debug_console
    except Exception:
        return
    logger = debug_console.get_debug_logger()
    original = logger.log

    def log(category, message, *a, **k):
        sink.append((time.perf_counter(), str(category), str(message)))
        return original(category, message, *a, **k)

    logger.log = log


# ---------------------------------------------------------------------------
# Session setup
# ---------------------------------------------------------------------------

def make_app():
    from PyQt5.QtWidgets import QApplication
    from editor.desktop_style import install_editor_style, prepare_qt
    prepare_qt()
    app = QApplication.instance() or QApplication([])
    install_editor_style(app)
    import game
    from plugins.manager import get_manager
    get_manager().register_builtin_game(game.GAME)
    return app


class OfflineNetwork:
    advertisement = None

    def broadcast(self, message, **kwargs):
        pass

    def poll(self):
        return []

    def stop_browser(self):
        pass

    def close(self):
        pass


def profiles(rng, count):
    from game.rpg import birthsigns, classes, heads, races
    race_ids = list(getattr(races, "RACES", {}) or ["imperial"])
    class_ids = list(getattr(classes, "CLASSES", {}) or ["warrior"])
    sign_ids = list(getattr(birthsigns, "BIRTHSIGNS", {}) or ["none"])
    chosen = rng.sample(list(heads.HEAD_IDS), count)
    return [dict(name="Soak %d" % (i + 1), head=chosen[i], race=rng.choice(race_ids),
                 **{"class": rng.choice(class_ids)}, birthsign=rng.choice(sign_ids),
                 gender=rng.choice(["male", "female"]), handed=rng.choice(["left", "right"]),
                 device="keyboard" if i == 0 else "pad:%d" % i)
            for i in range(count)]


def prepare_coop(rng, humans, bots, tmp_root, respawn=False):
    from game.multiplayer import lobby as launch_state
    from game.multiplayer.lobby import LobbyController
    from game.multiplayer.model import Lobby

    controller = LobbyController(ROOT, "maps/miniwind_world.json",
                                 network=OfflineNetwork(), identity="5" * 64)
    controller.opened, controller.signature = True, "soak"
    controller.lobby = Lobby(signature="soak", map_name="maps/miniwind_world.json")
    people = profiles(rng, humans + bots)
    for i, profile in enumerate(people):
        controller.lobby.add("host", profile, bot=i >= humans)
    if respawn:
        controller.lobby.set_respawn_at_village("host", True)
    controller.lobby.ready("host", True)
    controller.lobby.start("host")
    controller.state = controller.lobby.snapshot()
    controller.started = True
    launch_state.prepare(controller)
    return controller


# ---------------------------------------------------------------------------
# The randomised player
# ---------------------------------------------------------------------------

from PyQt5.QtCore import Qt  # noqa: E402  (after the platform env is set)

KEY = {c: getattr(Qt, "Key_" + c.upper()) for c in "abcdefghijklmnopqrstuvwxyz0123456789"}
KEY["shift"], KEY["esc"], KEY["enter"] = Qt.Key_Shift, Qt.Key_Escape, Qt.Key_Return
KEY.update(up=Qt.Key_Up, down=Qt.Key_Down, left=Qt.Key_Left, right=Qt.Key_Right)


class Driver:
    """Chooses an activity every few seconds and turns it into held keys."""

    ACTIVITIES = ("wander", "wander", "fight", "fight", "talk", "screens",
                  "teleport", "teleport", "spells", "sneak", "clock", "slots",
                  "cave", "idle")

    def __init__(self, soak):
        self.soak = soak
        self.rng = soak.rng
        self.activity, self.left, self.plan = "idle", 0, []
        self.counts = collections.Counter()

    def things(self, *types):
        return [t for t in self.soak.session.state.things
                if t.properties.get("type", getattr(t, "type", "")) in types
                or type(t).__name__.lower() in types]

    def player_pos(self):
        p = self.soak.logic.player_runtime.player
        return None if p is None else (float(p.pos[0]), float(p.pos[1]), float(p.pos[2]))

    def teleport_near(self, thing, spread=150.0):
        import glm
        player = self.soak.logic.player_runtime.player
        if player is None or thing is None:
            return
        x = float(thing.pos[0]) + self.rng.uniform(-spread, spread)
        z = float(thing.pos[2]) + self.rng.uniform(-spread, spread)
        player.pos = glm.vec3(x, float(thing.pos[1]) + 64.0, z)
        coop = getattr(self.soak.logic.game_session, "coop", None)
        if coop is not None:
            # Bring the party along, the way the camera keeps it together.
            for i, ctx in enumerate(coop.players.values()):
                try:
                    ctx.physics.pos = glm.vec3(x + 40 * i, float(thing.pos[1]) + 64.0, z)
                except Exception:
                    pass

    def menu_open(self):
        coop = getattr(self.soak.logic.game_session, "coop", None)
        sessions = ([p.session for p in coop.players.values()] if coop is not None
                    else [self.soak.logic.game_session])
        return any(getattr(s, "open_screen", None) is not None
                   or getattr(s, "dialogue", None) is not None for s in sessions)

    def choose(self):
        self.activity = self.rng.choice(self.soak.args.only or self.ACTIVITIES)
        self.left = self.rng.randint(90, 600)
        self.counts[self.activity] += 1
        a = self.activity
        session = self.soak.logic.game_session
        if a == "teleport":
            pool = self.things("npc", "creature", "container", "levelchanger",
                               "path_node", "marker")
            if pool:
                self.teleport_near(self.rng.choice(pool))
        elif a == "cave":
            pool = self.things("levelchanger")
            if pool:
                self.teleport_near(self.rng.choice(pool), spread=30.0)
        elif a == "fight":
            pool = self.things("creature")
            if pool:
                self.teleport_near(self.rng.choice(pool), spread=120.0)
        elif a == "talk":
            pool = self.things("npc")
            if pool:
                self.teleport_near(self.rng.choice(pool), spread=60.0)
        elif a == "clock":
            try:
                session.clock.hour = (float(session.clock.hour)
                                      + self.rng.uniform(1.0, 9.0)) % 24.0
            except Exception:
                pass

    def keys(self, tick):
        """``(held Qt keys, use pressed)`` for this tick."""
        held = self._keys(tick)
        return held, KEY["e"] in held

    def _keys(self, tick):
        if self.left <= 0:
            self.closing = 12
            self.choose()
        self.left -= 1
        if getattr(self, "closing", 0) > 0:
            # A player shuts what they opened before doing something else:
            # tap Esc (press, release) while a screen or dialogue is up.
            self.closing -= 1
            if self.menu_open() and self.closing % 2 == 0:
                return {KEY["esc"]}
            if self.menu_open():
                return set()
        a, r = self.activity, self.rng
        held = set()
        if tick % r.choice((20, 40, 80)) == 0 or not self.plan:
            self.plan = r.sample("wasd", r.randint(0, 2))
        move = {KEY[c] for c in self.plan}
        if a in ("wander", "teleport", "cave"):
            held |= move
            if r.random() < 0.3:
                held.add(KEY["shift"])
            if a == "cave" and r.random() < 0.1:
                held.add(KEY["e"])
            if a == "cave" and self.left % 120 == 0:
                pool = self.things("levelchanger")
                if pool:
                    self.teleport_near(r.choice(pool), spread=30.0)
        elif a == "fight":
            held |= move
            if r.random() < 0.5:
                held.add(KEY["f"])
            if r.random() < 0.1:
                held.add(KEY["k"])
            if r.random() < 0.1:
                held.add(KEY["b"])
            if r.random() < 0.01:
                held.add(KEY["h"])
        elif a == "talk":
            held |= move if r.random() < 0.3 else set()
            if r.random() < 0.05:
                held.add(KEY["e"])
            if r.random() < 0.05:
                held.add(KEY[r.choice(["up", "down", "enter", "1", "2", "3", "esc"])])
        elif a == "screens":
            if r.random() < 0.04:
                held.add(KEY[r.choice("icjmpqlx")])
            if r.random() < 0.04:
                held.add(KEY[r.choice(["up", "down", "left", "right", "enter", "esc"])])
        elif a == "spells":
            held |= move
            if r.random() < 0.05:
                held.add(KEY["x"])
            if r.random() < 0.2:
                held.add(KEY["k"])
        elif a == "sneak":
            held |= move
            if r.random() < 0.02:
                held.add(KEY["v"])
        elif a == "slots":
            if r.random() < 0.05:
                held.add(KEY[str(r.randint(1, 9))])
            if r.random() < 0.3:
                held.add(KEY["f"])
        return held


# ---------------------------------------------------------------------------
# The soak run
# ---------------------------------------------------------------------------

class Soak:
    def __init__(self, args):
        self.args = args
        self.rng = random.Random(args.seed)
        random.seed(args.seed)
        self.report = dict(mode=args.mode, seed=args.seed, threaded=args.threaded,
                           hangs=[], slow_ticks=[], faults=[], debug_log=[],
                           level_changes=[], tick_ms={})
        self.debug = []
        self._checked_debug = 0
        capture_debug_log(self.debug)

    def log(self, *parts):
        print("[soak %s s=%d]" % (self.args.mode, self.args.seed), *parts, flush=True)

    def setup(self):
        from tests.helpers.session import FioTestSession
        self.app = make_app()
        self.controller = None
        if self.args.mode in ("bots", "mixed"):
            humans = 1 if self.args.mode == "bots" else 2
            self.controller = prepare_coop(self.rng, humans, 4 - humans, ROOT,
                                           respawn=self.args.respawn)
        t = time.perf_counter()
        self.session = FioTestSession(self.app, "maps/miniwind_world.json")
        self.logic = self.session.logic
        self.session.start_play()
        gs = self.logic.game_session
        if self.args.mode == "single":
            p = profiles(self.rng, 1)[0]
            gs.begin_new_character(p["name"], p["race"], p["class"], p["birthsign"],
                                   p["gender"], head=p["head"], handed=p["handed"])
        else:
            bots = sum(bool(p.bot) for p in gs.coop.players.values())
            self.log("party of %d, %d bots" % (len(gs.coop.players), bots))
        self.log("ready in %.1fs" % (time.perf_counter() - t))

    # -- per-tick checks ------------------------------------------------------

    def check(self, tick):
        from engine.error_report import ERROR_CATEGORIES

        # A background subsystem can fault while ticks and frames continue.
        # Such a run must fail, rather than merely listing the error in its
        # last 200 Debug Console lines. Only inspect new lines each tick.
        end = len(self.debug)
        start, self._checked_debug = self._checked_debug, end
        for _at, category, message in self.debug[start:end]:
            if (category.lower() in ERROR_CATEGORIES
                    or "Traceback (most recent call last)" in message):
                self.report["faults"].append(dict(tick=tick, kind="debug_error",
                                                  category=category, trace=message))
                self.log("DEBUG ERROR at", tick, category, message)
                return False
        logic = self.logic
        if getattr(logic, "_tick_faulted", False) and not self.report["faults"]:
            self.report["faults"].append(dict(tick=tick, kind="tick_faulted",
                                              trace=logic._tick_fault_message))
            self.log("TICK FAULT at", tick, "\n" + logic._tick_fault_message)
            return False
        if not getattr(logic, "_frame_prepared", True):
            self.report["faults"].append(dict(tick=tick, kind="frame_not_prepared",
                                              trace=getattr(logic, "_last_prepare_error", "")))
        if not self.session.playing:
            self.report["faults"].append(dict(tick=tick, kind="play_mode_ended"))
            self.log("play mode ended at tick", tick)
            return False
        return True

    def human_inputs(self, tick):
        """Second human (mixed mode) plays from a gamepad, via InputFrame."""
        coop = getattr(self.logic.game_session, "coop", None)
        if coop is None:
            return
        from game.multiplayer.model import InputFrame
        r = self.rng
        for ctx in coop.players.values():
            if ctx.bot or ctx.profile.get("device") == "keyboard":
                continue
            if tick % 30 == 0:
                ctx._soak_move = (r.uniform(-1, 1), r.uniform(-1, 1))
            mx, mz = getattr(ctx, "_soak_move", (0.0, 0.0))
            held = set()
            if r.random() < 0.2:
                held.add(r.choice(["right_hand", "left_hand", "block", "sprint"]))
            actions = []
            if r.random() < 0.01:
                actions.append((r.choice(["attack", "cast", "heal", "interact",
                                          "next_spell", "sneak"]), []))
            coop.local_input(ctx.player_id, InputFrame(mx, mz, r.uniform(0, math.tau),
                                                       frozenset(held)), actions)

    def paint_like_view(self, tick):
        """What ``QtGameView._paint_frame`` does with a frame, minus the GL.

        Offscreen there is no GL context, so ``paintGL`` never runs; without
        this a LevelChanger's request would never reach the main window.
        """
        from PyQt5.QtCore import QTimer
        view = self.session.view
        with self.session.render_state() as frame:
            ui = getattr(frame, "level_complete_ui", None)
        view._cached_level_complete_ui = ui
        if ui and ui.get("immediate") and not getattr(view, "_level_change_queued", False):
            view._level_change_queued = True
            QTimer.singleShot(0, view._confirm_immediate_level_change)
        elif ui and not ui.get("immediate") and self.rng.random() < 0.02:
            view._confirm_level_complete()   # the player clicks Continue
        if ui:
            self._ui_since = getattr(self, "_ui_since", None) or tick
            if tick - self._ui_since == 600:
                self.report["faults"].append(dict(tick=tick, kind="level_change_stuck", ui=dict(ui)))
                self.log("level_complete_ui pending for 600 ticks:", ui)
        else:
            self._ui_since = None

    def state(self):
        """Why the world might not be moving, in one line."""
        logic = self.logic
        gs = getattr(logic, "game_session", None)
        sr = logic.session_runtime
        player = logic.player_runtime.player
        out = dict(
            map=os.path.basename(str(getattr(self.session.window, "file_path", "") or "")),
            paused=bool(sr.world_paused),
            pause_owners=sorted(map(str, getattr(sr, "_world_pause_owners", ()) or ())),
            pause_menu=bool(getattr(sr, "pause_menu_open", False)),
            level_ui=bool(logic.interaction_runtime.level_complete_ui),
            cutscene=bool(logic.cutscene_runtime.state),
            dead=bool(logic.player_runtime.player_dead),
            pos=None if player is None else [round(float(v)) for v in player.pos],
            monster_ai_thread=sr.monster_ai_thread is not None,
            published=getattr(self.session.game_state, "published_frames", None),
            rss_mb=rss_mb(), threads=threading.active_count(),
        )
        if gs is not None:
            out.update(screen=getattr(gs, "open_screen", None),
                       dialogue=getattr(gs, "dialogue", None) is not None,
                       char_creation=bool(getattr(gs, "needs_char_creation", False)),
                       hour=round(float(getattr(getattr(gs, "clock", None), "hour", -1)), 2),
                       health=round(float(gs.game.character.health), 1))
            coop = getattr(gs, "coop", None)
            if coop is not None:
                out["party"] = [dict(n=p.profile.get("name"), bot=bool(p.bot),
                                     dead=bool(p.session.game.character.is_dead),
                                     hp=round(float(p.session.game.character.health)),
                                     returning=bool(getattr(p, "returning", False)),
                                     task=getattr(p, "task", None),
                                     pos=[round(float(v)) for v in p.physics.pos])
                                for p in coop.players.values()]
                out["travel_pending"] = coop.travel is not None
        else:
            out["game_session"] = None
        return out

    def softlock(self, tick):
        """Everyone a human controls has been down (or dead) for a minute."""
        gs = getattr(self.logic, "game_session", None)
        coop = getattr(gs, "coop", None)
        if coop is not None:
            humans = [p for p in coop.players.values() if not p.bot and p.connected]
            down = bool(humans) and all(p.session.game.character.is_dead for p in humans)
        else:
            # Single-player death opens the death screen and waits for the
            # player's choice by design; only a party can be stuck downed.
            down = False
        if not down:
            self._down_since = None
            return
        self._down_since = getattr(self, "_down_since", None) or tick
        if tick - self._down_since == 3600:
            state = self.state()
            self.report["faults"].append(dict(tick=tick, kind="humans_down_60s", state=state))
            self.log("SOFTLOCK? every human down for 60 s:", state)

    # -- stepped run ------------------------------------------------------------

    def run_stepped(self):
        args, session = self.args, self.session
        driver = Driver(self)
        sampler = Sampler(threading.main_thread().ident)
        sampler.start()
        hang_log = open(args.hang_log, "w")
        ticks = int(args.minutes * 60 * 60)
        times = []
        started = time.perf_counter()
        prev_map = getattr(self.session.window, "file_path", None)
        try:
            for tick in range(ticks):
                keys, use = driver.keys(tick)
                self.human_inputs(tick)
                faulthandler.dump_traceback_later(args.hang, repeat=True, file=hang_log)
                t0 = time.perf_counter()
                session.step(1, keys=keys, use=use)
                self.paint_like_view(tick)
                if tick % 6 == 0:
                    self.app.processEvents()  # level changes, deferred UI work
                t1 = time.perf_counter()
                faulthandler.cancel_dump_traceback_later()
                ms = (t1 - t0) * 1000.0
                times.append(ms)
                if ms > args.hang * 1000.0:
                    self.report["hangs"].append(dict(tick=tick, ms=round(ms), activity=driver.activity,
                                                     where=hot_frames(sampler.between(t0, t1))))
                    self.log("HANG-LIKE tick %d took %.1fs during %s" % (tick, ms / 1000, driver.activity))
                elif ms > args.slow_ms:
                    self.report["slow_ticks"].append(dict(tick=tick, ms=round(ms, 1),
                                                          activity=driver.activity,
                                                          pos=driver.player_pos(),
                                                          where=hot_frames(sampler.between(t0, t1),
                                                                           4 if ms < 2000 else 15)))
                cur = getattr(self.session.window, "file_path", None)
                if cur != prev_map:
                    import gc
                    entry = dict(tick=tick, to=cur, ms=round(ms), rss_mb=rss_mb(),
                                 objects=len(gc.get_objects()) if args.count_objects else None,
                                 threads=threading.active_count())
                    self.report["level_changes"].append(entry)
                    self.log("map ->", cur, entry)
                    prev_map = cur
                self.softlock(tick)
                if not self.check(tick):
                    break
                if tick and tick % 3600 == 0:
                    elapsed = time.perf_counter() - started
                    recent = sorted(times[-3600:])
                    self.log("game min %d  real %.0fs  p50 %.1fms  p99 %.1fms  max %.0fms  %s" % (
                        tick // 3600, elapsed, recent[len(recent) // 2],
                        recent[int(len(recent) * .99)], recent[-1], dict(driver.counts)))
                if tick % args.probe_every == 0:
                    state = self.state()
                    self.report.setdefault("states", []).append(dict(tick=tick, **state))
                    if args.verbose:
                        self.log("tick", tick, driver.activity, state)
        finally:
            faulthandler.cancel_dump_traceback_later()
            sampler.running = False
            hang_log.close()
        self.finish(times, driver)

    # -- threaded run -----------------------------------------------------------

    def run_threaded(self):
        """The real threads, free-running; the main thread plays the UI."""
        args, logic, session = self.args, self.logic, self.session
        driver = Driver(self)
        logic.running = True
        runner = threading.Thread(target=logic.run, name="LogicThread-soak", daemon=True)
        runner.start()
        logic.session_runtime.start_monster_ai()
        gs = session.game_state
        renderer = getattr(session.view, "renderer", None)
        gl = bool(renderer is not None and getattr(renderer, "ready", False))
        self.report["gl"] = gl
        self.log("threaded run, real GL paint:", gl)
        published = gs.published_frames
        painted = [0]
        original_paint = session.view.paintGL

        def counted_paint():
            painted[0] += 1
            return original_paint()

        if gl:
            session.view.paintGL = counted_paint
        last_paint_check, last_painted = time.perf_counter(), 0
        deadline = time.perf_counter() + args.minutes * 60.0
        last_serial, last_change = logic._simulation_serial, time.perf_counter()
        tick = 0
        stalls = 0
        prev_map = getattr(self.session.window, "file_path", None)
        try:
            while time.perf_counter() < deadline:
                keys, use = driver.keys(tick)
                gs.set_keys(set(keys))
                if use:
                    gs.set_use_key_pressed()
                self.human_inputs(tick)
                if not gl:
                    # No GL context, so paintGL never runs: do its frame
                    # handling (level changes) here. With GL the view's own
                    # repaint timer paints, as in the shipped game.
                    gs.try_swap()
                    self.paint_like_view(tick)
                self.app.processEvents()
                serial = logic._simulation_serial
                now = time.perf_counter()
                if serial != last_serial:
                    last_serial, last_change = serial, now
                elif now - last_change > args.hang:
                    stalls += 1
                    dump = all_stacks()
                    self.report["hangs"].append(dict(kind="logic_stalled", seconds=round(now - last_change, 1),
                                                     activity=driver.activity, stacks=dump))
                    self.log("LOGIC STALLED for %.0fs during %s\n%s" % (now - last_change, driver.activity, dump))
                    last_change = now
                    if stalls >= 3:
                        break
                if gl and now - last_paint_check > args.hang:
                    if painted[0] == last_painted:
                        self.report["hangs"].append(dict(kind="no_paint", seconds=round(now - last_paint_check, 1),
                                                         activity=driver.activity, state=self.state()))
                        self.log("NO PAINT for %.0fs" % (now - last_paint_check), self.state())
                    last_paint_check, last_painted = now, painted[0]
                cur = getattr(self.session.window, "file_path", None)
                if cur != prev_map:
                    self.report["level_changes"].append(dict(tick=tick, to=cur))
                    self.log("map ->", cur)
                    prev_map = cur
                if tick % args.probe_every == 0:
                    state = self.state()
                    self.report.setdefault("states", []).append(dict(tick=tick, serial=logic._simulation_serial, **state))
                    if args.verbose:
                        self.log("tick", tick, driver.activity, state)
                if not self.check(tick):
                    break
                tick += 1
                time.sleep(1 / 60.0)
        finally:
            logic.running = False
            logic.session_runtime.stop_monster_ai()
            runner.join(5.0)
        self.report["threaded_ticks"] = logic._simulation_serial
        self.report["published_frames"] = gs.published_frames - published
        self.report["painted_frames"] = painted[0]
        self.finish([], driver)

    def finish(self, times, driver):
        if times:
            s = sorted(times)
            self.report["tick_ms"] = dict(n=len(s), p50=round(s[len(s) // 2], 2),
                                          p99=round(s[int(len(s) * .99)], 2),
                                          max=round(s[-1], 1), total_s=round(sum(s) / 1000, 1))
        self.report["activities"] = dict(driver.counts)
        self.report["debug_log"] = [dict(cat=c, msg=m[:4000]) for _t, c, m in self.debug][-200:]
        try:
            coop = getattr(self.logic.game_session, "coop", None)
            if coop is not None:
                self.report["party"] = [dict(name=p.profile.get("name"), bot=bool(p.bot),
                                             dead=bool(p.session.game.character.is_dead),
                                             pos=[round(float(v)) for v in p.physics.pos])
                                        for p in coop.players.values()]
        except Exception:
            self.report["party_error"] = traceback.format_exc()

    def close(self):
        try:
            self.session.close()
        except Exception:
            traceback.print_exc()
        if self.controller is not None:
            from game.multiplayer import lobby as launch_state
            launch_state.finish()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", choices=("single", "bots", "mixed"), default="single")
    p.add_argument("--minutes", type=float, default=5.0, help="game minutes to play")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--threaded", action="store_true", help="free-running logic + monster AI threads")
    p.add_argument("--hang", type=float, default=10.0, help="seconds before a tick counts as hung")
    p.add_argument("--slow-ms", type=float, default=250.0, help="report ticks slower than this")
    p.add_argument("--report", default=None)
    p.add_argument("--only", nargs="*", choices=Driver.ACTIVITIES, default=None,
                   help="restrict the player to these activities (e.g. --only cave)")
    p.add_argument("--count-objects", action="store_true", help="count live objects at each map change")
    p.add_argument("--respawn", action="store_true", help="co-op: Respawn at village")
    p.add_argument("--probe-every", type=int, default=600, help="record world state every N ticks")
    p.add_argument("--verbose", action="store_true", help="print every state probe")
    p.add_argument("--hang-log", default=None)
    args = p.parse_args(argv)
    args.report = args.report or "soak-%s-%d.json" % (args.mode, args.seed)
    args.hang_log = args.hang_log or args.report.replace(".json", ".hang.txt")
    faulthandler.enable()
    soak = Soak(args)
    try:
        soak.setup()
        (soak.run_threaded if args.threaded else soak.run_stepped)()
    except Exception:
        soak.report["crash"] = traceback.format_exc()
        traceback.print_exc()
    finally:
        with open(args.report, "w") as handle:
            json.dump(soak.report, handle, indent=1, default=str)
        r = soak.report
        soak.log("done: hangs=%d slow=%d faults=%d debug_log=%d level_changes=%d tick_ms=%s" % (
            len(r["hangs"]), len(r["slow_ticks"]), len(r["faults"]), len(r["debug_log"]),
            len(r["level_changes"]), r.get("tick_ms")))
        soak.close()
    return 1 if (soak.report["hangs"] or soak.report["faults"] or "crash" in soak.report) else 0


if __name__ == "__main__":
    sys.exit(main())
