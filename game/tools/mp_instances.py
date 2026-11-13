"""
Real multiplayer across separate game instances (one OS process each).

    xvfb-run -a python -m game.tools.mp_instances --out /tmp/mp --clients 2 --late-client

The host process opens a party, gets a friend code and writes it to the
output folder; each client process reads the code, joins with it, makes a
character and readies up; the host starts the adventure; then every
instance loads the world (its own MiniWind, its own window) and plays for a
while, walking its own character. Each instance writes what it saw --
every party member's position, on its own screen -- to ``<role>.json``
and a screenshot to ``<role>.png``.

Options:

* ``--late-client``: one more client joins after the adventure has started
  (late arrival);
* ``--no-late-arrival``: the host closes the party at Start (that late
  client must then be refused);
* ``--bad-code``: a client tries a stale code before the game starts (it
  must be refused).

Loopback is the host's "own network", where no code is needed; so that the
invitation is really checked, the host treats every joiner as from outside
(``MW_FRIEND_OUTSIDE=1``).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAP = "maps/miniwind_world.json"
CLASSES = ("warrior", "mage", "thief", "warrior", "mage")


def _profile(i):
    import game.rpg.heads as heads
    return {"name": f"Player {i + 1}", "head": heads.HEAD_IDS[i % len(heads.HEAD_IDS)], "race": "imperial",
            "class": CLASSES[i], "birthsign": "none", "device": "keyboard",
            "handed": "right", "gender": "male"}


def _app():
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    from editor.desktop_style import prepare_qt, install_editor_style
    prepare_qt()
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    install_editor_style(app)
    import importlib
    from plugins.manager import get_manager
    game = importlib.import_module("game")
    get_manager().register_builtin_game(game.GAME)
    import game.integration as integration
    integration.apply()
    return app


def _log(out, role, text):
    with open(Path(out) / f"{role}.log", "a") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {text}\n")


def _pump(controller, until, timeout, out, role, each=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        controller.poll()
        if each is not None:
            each()
        if until():
            return True
        time.sleep(0.02)
    _log(out, role, f"timed out; errors {controller.errors}")
    return False


def _play(app, controller, out, role, seconds, keys):
    """Load the world as this instance and play: walk with *keys*, and note
    every party member's position as seen here."""
    from PyQt5.QtCore import Qt
    from game.multiplayer.lobby import prepare
    from tests.helpers.session import FioTestSession
    keys = {getattr(Qt, "Key_" + k.upper()) for k in keys}
    prepare(controller)
    session = FioTestSession(app, MAP, size=(960, 540))
    session.start_play()
    gs = session.logic.game_session
    _log(out, role, f"world loaded; coop={getattr(gs, 'coop', None) is not None}")
    seen = []
    start = time.monotonic()
    while time.monotonic() - start < seconds:
        walking = (time.monotonic() - start) < seconds * 0.6
        session.step(3, keys=keys if walking else ())
        app.processEvents()
        coop = getattr(gs, "coop", None)
        party = sorted(
            (p.profile["name"], round(float(p.physics.pos[0])), round(float(p.physics.pos[2])))
            for p in (coop.players.values() if coop is not None else ())
            if getattr(p, "connected", True))
        seen.append({"t": round(time.monotonic() - start, 1), "party": party})
    session.view.update()
    app.processEvents()
    session.view.grabFramebuffer().save(str(Path(out) / f"{role}.png"))
    coop = getattr(gs, "coop", None)
    result = {
        "role": role,
        "host": controller.lobby is not None,
        "members": len((controller.state or {}).get("members", [])),
        "players_in_world": len(seen[-1]["party"]) if seen else 0,
        "first": seen[0] if seen else None,
        "last": seen[-1] if seen else None,
        "errors": list(controller.errors),
        "coop_players": len(getattr(coop, "players", {}) or {}),
    }
    (Path(out) / f"{role}.json").write_text(json.dumps(result, indent=1))
    _log(out, role, "done")
    return session


def host_main(args):
    app = _app()
    if os.environ.get("MW_FRIEND_OUTSIDE"):
        import game.multiplayer.friend_code as friend_code
        friend_code.trusted_address = lambda _address: False
    from game.multiplayer.lobby import LobbyController
    out, role = args.out, "host"
    controller = LobbyController(ROOT, MAP, identity="a" * 64)
    controller.open()
    controller.host("Instances party", port=0)
    controller.request("late_arrival", enabled=not args.no_late_arrival)
    controller.find_code(finder=lambda: ("127.0.0.1", "local", None), wait=True)
    stale = controller.code
    controller.new_code()                       # the first code is now stale
    (Path(out) / "stale_code.txt").write_text(stale)
    (Path(out) / "code.txt").write_text(controller.code)
    _log(out, role, f"code {controller.code} (stale {stale})")
    controller.request("add", profile=_profile(0))
    expected = 1 + args.clients

    def ready_up():
        lobby = controller.lobby
        if len(lobby.members) == expected and not all(m.ready for m in lobby.owned(controller.owner)):
            controller.request("ready", ready=True)

    if not _pump(controller, lambda: controller.lobby.can_start and len(controller.lobby.members) == expected,
                 240, out, role, ready_up):
        return 1
    if args.bad_code:
        _pump(controller, lambda: (Path(out) / "bad.json").exists(), 60, out, role)
    controller.request("start")
    (Path(out) / "started").write_text("1")
    _log(out, role, "started")
    _play(app, controller, out, role, args.seconds + (40 if args.late_client else 0), ("w",))
    return 0


def client_main(args):
    app = _app()
    from game.multiplayer.lobby import LobbyController
    out, role, index = args.out, args.role, args.index
    code_file = Path(out) / ("stale_code.txt" if role == "bad" else "code.txt")
    deadline = time.monotonic() + 240
    while not code_file.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    code = code_file.read_text().strip()
    import hashlib
    controller = LobbyController(ROOT, MAP, identity=hashlib.sha256(role.encode()).hexdigest())
    controller.open()
    controller.join_code(code)
    _log(out, role, f"joining with {code}")
    if role == "bad":
        _pump(controller, lambda: bool(controller.errors) or controller.state is not None, 30, out, role)
        result = {"role": role, "admitted": controller.state is not None, "errors": list(controller.errors)}
        (Path(out) / "bad.json").write_text(json.dumps(result, indent=1))
        controller.close()
        return 0
    got = _pump(controller, lambda: controller.state is not None or bool(controller.errors), 60, out, role)
    if not got or controller.state is None:
        result = {"role": role, "admitted": False, "errors": list(controller.errors)}
        (Path(out) / f"{role}.json").write_text(json.dumps(result, indent=1))
        _log(out, role, f"refused: {controller.errors}")
        controller.close()
        return 0
    controller.request("add", profile=_profile(index))

    def ready_up():
        state = controller.state or {}
        mine = [m for m in state.get("members", []) if m["owner"] == controller.owner]
        if mine and not all(m["ready"] for m in mine):
            controller.request("ready", ready=True)

    if not _pump(controller, lambda: controller.started, 300, out, role, ready_up):
        return 1
    _log(out, role, "started")
    _play(app, controller, out, role, args.seconds, (("d",), ("a",), ("s",), ("d",))[index % 4])
    controller.close()
    return 0


def orchestrate(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for f in out.iterdir():
        if f.is_file():
            f.unlink()
    env = dict(os.environ, MW_FRIEND_OUTSIDE="1", LIBGL_ALWAYS_SOFTWARE="1")
    base = [sys.executable, "-m", "game.tools.mp_instances", "--out", str(out),
            "--clients", str(args.clients), "--seconds", str(args.seconds)]
    if args.no_late_arrival:
        base.append("--no-late-arrival")
    if args.late_client:
        base.append("--late-client")
    if args.bad_code:
        base.append("--bad-code")
    logs = []

    def spawn(role, index=0):
        log = open(out / f"{role}.stdout", "w")
        logs.append(log)
        return subprocess.Popen(base + ["--role", role, "--index", str(index)], cwd=ROOT, env=env,
                                stdout=log, stderr=subprocess.STDOUT)

    procs = [spawn("host")]
    procs += [spawn(f"client{i}", i) for i in range(1, args.clients + 1)]
    if args.bad_code:
        procs.append(spawn("bad", 9))
    if args.late_client:
        deadline = time.monotonic() + 600
        while not (out / "started").exists() and time.monotonic() < deadline:
            time.sleep(0.5)
        time.sleep(5)
        procs.append(spawn("late", args.clients + 1))
    for p in procs:
        try:
            p.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            p.kill()
    for log in logs:
        log.close()
    report = {}
    for f in sorted(out.glob("*.json")):
        report[f.stem] = json.loads(f.read_text())
    print(json.dumps(report, indent=1))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--out", required=True)
    parser.add_argument("--role", default="")
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--clients", type=int, default=2)
    parser.add_argument("--seconds", type=float, default=40.0)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--late-client", action="store_true")
    parser.add_argument("--no-late-arrival", action="store_true")
    parser.add_argument("--bad-code", action="store_true")
    args = parser.parse_args(argv)
    if args.role == "host":
        return host_main(args)
    if args.role:
        return client_main(args)
    return orchestrate(args)


if __name__ == "__main__":
    sys.exit(main())
