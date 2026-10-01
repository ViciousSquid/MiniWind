"""Dev harness (not shipped; see HANDOFF.md). Back up settings.ini first: the
editor window rewrites it.

Real-GL screenshot of MiniWind in the editor's play mode (Xvfb + Mesa).

usage: shot.py OUT.png [--camera Overhead|First Person] [--seconds N]
               [--skip-charcreate] [--map PATH] [--size WxH]
"""
import argparse
import importlib
import os
import sys
import time

ROOT = os.getcwd()
sys.path.insert(0, ROOT)

ap = argparse.ArgumentParser()
ap.add_argument("out")
ap.add_argument("--camera", default=None)
ap.add_argument("--seconds", type=float, default=3.0)
ap.add_argument("--skip-charcreate", action="store_true")
ap.add_argument("--map", default="maps/village_walled_source.json")
ap.add_argument("--size", default="1280x800")
ap.add_argument("--editor", action="store_true", help="shoot edit mode, no play")
ap.add_argument("--exit-check", action="store_true")
ap.add_argument("--player-head", default=None)
ap.add_argument("--teleport", default=None, help="x,z")
ap.add_argument("--overhead-height", type=float, default=None)
ap.add_argument("--exec", default=None, help="python run after setup (w, lt, s, pump)")
ap.add_argument("--post", default=None, help="python run before the shot")
ap.add_argument("--kiosk", action="store_true", help="play full-window (kiosk)")
args = ap.parse_args()

from PyQt5.QtGui import QSurfaceFormat  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

fmt = QSurfaceFormat()
fmt.setVersion(3, 3)
fmt.setProfile(QSurfaceFormat.CoreProfile)
fmt.setDepthBufferSize(24)
fmt.setStencilBufferSize(8)
QSurfaceFormat.setDefaultFormat(fmt)
app = QApplication(sys.argv)

import configparser  # noqa: E402
cfg = configparser.ConfigParser()
cfg.read("settings.ini")
name = cfg.get("Startup", "game_module", fallback="")
if not name and os.path.isdir(os.path.join(ROOT, "game")):
    name = "game"          # the pre-migration tree installs it from main.py
if name:
    importlib.import_module(name).install()
from plugins.manager import get_manager  # noqa: E402
bw = get_manager().find_plugin("bigworld")
if bw is not None:
    get_manager().set_enabled(bw, True)

from editor.main_window import MainWindow  # noqa: E402
w = MainWindow(ROOT)
W, H = (int(v) for v in args.size.split("x"))
w.resize(W, H)
w.show()


def pump(seconds):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.01)


pump(1.0)
print("camera dropdown visible:", w.camera_mode_combobox.isVisible())
w.grab().save(args.out.replace(".png", "_window_shot.png"))
w.load_level_file(os.path.join(ROOT, args.map))
pump(2.0)
if args.camera:
    w.set_camera_mode(args.camera)
if not args.editor:
    if args.kiosk:
        w.enter_kiosk_mode()
    else:
        w.enter_play_mode()
    pump(1.0)
    lt = getattr(w.view_3d, "logic_thread", None)
    if args.skip_charcreate and lt is not None:
        s = getattr(lt, "_miniwind", None)
        if s is not None:
            s.needs_char_creation = False
            s.open_screen = None
            if args.player_head:
                s._apply_player_head(args.player_head)
        if args.overhead_height and lt is not None:
            lt.overhead_height = args.overhead_height
        if args.teleport and lt is not None and lt.player is not None:
            x, z = (float(v) for v in args.teleport.split(","))
            lt.player.pos.x, lt.player.pos.z = x, z
if args.exec:
    lt = getattr(w.view_3d, "logic_thread", None)
    s = getattr(lt, "_miniwind", None)
    exec(args.exec)
pump(args.seconds)
if args.post:
    lt = getattr(w.view_3d, "logic_thread", None)
    s = getattr(lt, "_miniwind", None)
    exec(args.post)
view = w.view_3d
view.update()
pump(0.3)
img = view.grabFramebuffer()
img.save(args.out)
lt = getattr(view, "logic_thread", None)
if lt is not None and lt.player is not None:
    pp = lt.player.pos
    ter = getattr(lt, "terrain", None)
    th = ter.get_height_at(pp.x, pp.z) if ter is not None else None
    print("player", round(pp.x), round(pp.y, 1), round(pp.z), "terrain", th)
print("saved", args.out, img.width(), "x", img.height(),
      "| play:", getattr(view, "play_mode", None),
      "| view camera:", getattr(view, "camera_mode", None),
      "| logic overhead:", lt.is_overhead() if lt else None,
      "| paused:", getattr(lt, "world_paused", None))
if args.exit_check:
    w._exit_play_mode() if hasattr(w, "_exit_play_mode") else None
    pump(1.0)
    print("after exit | play:", view.play_mode, "| view camera:", view.camera_mode,
          "| logic camera:", getattr(lt, "camera_mode", None),
          "| dropdown:", w.camera_mode_combobox.currentText())
os._exit(0)
