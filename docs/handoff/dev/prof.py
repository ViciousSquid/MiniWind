"""Dev harness (not shipped; see HANDOFF.md). Back up settings.ini first: the
editor window rewrites it.

Profile MiniWind play (all threads) with yappi. usage: prof.py SECONDS [x,z]"""
import os, sys, time, importlib, configparser
ROOT = os.getcwd(); sys.path.insert(0, ROOT)
import yappi
sys.setswitchinterval(0.001)
from PyQt5.QtGui import QSurfaceFormat
from PyQt5.QtWidgets import QApplication
fmt = QSurfaceFormat(); fmt.setVersion(3, 3); fmt.setProfile(QSurfaceFormat.CoreProfile); fmt.setDepthBufferSize(24)
QSurfaceFormat.setDefaultFormat(fmt)
app = QApplication(sys.argv)
cfg = configparser.ConfigParser(); cfg.read("settings.ini")
importlib.import_module(cfg.get("Startup", "game_module", fallback="game")).install()
from plugins.manager import get_manager
bw = get_manager().find_plugin("bigworld"); get_manager().set_enabled(bw, True)
from editor.main_window import MainWindow
w = MainWindow(ROOT); w.resize(1280, 900); w.show()
def pump(t):
    e = time.perf_counter() + t
    while time.perf_counter() < e:
        app.processEvents(); time.sleep(0.001)
pump(1.0)
w.load_level_file(os.path.join(ROOT, "maps/village_walled_source.json")); pump(2.0)
(w.enter_kiosk_mode() if os.environ.get("KIOSK") else w.enter_play_mode()); pump(1.0)
lt = w.view_3d.logic_thread; s = lt._miniwind
s.needs_char_creation = False; s.open_screen = None
if len(sys.argv) > 2:
    x, z = (float(v) for v in sys.argv[2].split(",")); lt.player.pos.x, lt.player.pos.z = x, z
pump(float(os.environ.get("WARM","4")))
yappi.set_clock_type("wall")
yappi.start(builtins=False, profile_threads=True)
f0 = getattr(w.view_3d, "frame_count", None)
t0 = time.perf_counter()
pump(float(sys.argv[1]))
yappi.stop()
dt = time.perf_counter() - t0
try:
    from engine.spatial import tier_of
    import collections
    bw = lt._bigworld
    print("DIAG fit", bw._fit, "aspect", round(lt.frustum_aspect, 2), "tiers", dict(collections.Counter(tier_of(m) for m in lt._monster_things)), "cells", len(bw.manager.active_cells), "chunks", lt.terrain.table.count)
except Exception as e:
    print("DIAG err", e)
print("FPS", getattr(w.view_3d, "fps", None), "dt", round(dt, 1))
for th in yappi.get_thread_stats():
    print("THREAD", th.name, th.id, round(th.ttot, 2))
for th in yappi.get_thread_stats():
    stats = yappi.get_func_stats(ctx_id=th.id)
    stats.sort("tsub")
    print("\n==== thread", th.name, "by tsub")
    for st in list(stats)[:25]:
        print(f"{st.tsub:8.3f} {st.ttot:8.3f} {st.ncall:7d}  {st.module.replace(ROOT+'/','')}:{st.lineno} {st.name}")
    stats.sort("ttot")
    print("---- by ttot")
    for st in list(stats)[:int(os.environ.get("TOPN","30"))]:
        print(f"{st.tsub:8.3f} {st.ttot:8.3f} {st.ncall:7d}  {st.module.replace(ROOT+'/','')}:{st.lineno} {st.name}")
os._exit(0)
