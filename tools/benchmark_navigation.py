"""Reproduce navigation work at the AI tick rate, optionally against a baseline.

Run from any directory: python tools/benchmark_navigation.py --help
Timings are descriptive; tests guard work counts rather than machine speed.
"""

import argparse
import importlib.util
import math
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from game import navigation


def load_reference(filename):
    spec = importlib.util.spec_from_file_location("navigation_reference", filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def measured_type(module):
    class Measured(module.Navigator):
        searches = 0
        probes = 0

        def find_path(self, *args, **kwargs):
            self.searches += 1
            return super().find_path(*args, **kwargs)

        def line_clear(self, *args, **kwargs):
            self.probes += 1
            return super().line_clear(*args, **kwargs)
    return Measured


def run(module, scenario, npcs, seconds, hz):
    now = [0.0]
    cell = module.CELL

    def blocked(x, y, z):
        if scenario == "unreachable":
            return max(abs(math.floor(x / cell)), abs(math.floor(z / cell))) == 2
        return scenario == "wall" and -400 < x < 400 and 200 < z < 260

    nav = measured_type(module)(blocked, lambda: now[0])
    actors = [object() for _ in range(npcs)]
    starts = [(24, 0, 24)] * npcs
    targets = [(24, 0, 1000)] * npcs
    started = time.perf_counter()
    for tick in range(round(seconds * hz)):
        now[0] = tick / hz
        nav.steer_many(actors, starts, targets)
    elapsed = (time.perf_counter() - started) * 1000
    return nav.searches, nav.probes, elapsed


def corridor(module):
    cells = []
    for row in range(10):
        xs = range(21) if row % 2 == 0 else range(20, -1, -1)
        cells.extend((x, row * 4) for x in xs)
        if row < 9:
            edge = cells[-1][0]
            cells.extend((edge, row * 4 + z) for z in range(1, 4))
    open_cells = set(cells)
    nav = measured_type(module)(lambda x, y, z: (math.floor(x / module.CELL),
                                                math.floor(z / module.CELL)) not in open_cells)
    points = [((x + .5) * module.CELL, (z + .5) * module.CELL) for x, z in cells]
    started = time.perf_counter()
    path = nav._smooth(points[0], points[1:], 0)
    elapsed = (time.perf_counter() - started) * 1000
    return nav.probes, elapsed, len(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, help="baseline navigation.py")
    parser.add_argument("--npcs", type=int, default=100)
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--hz", type=int, default=30)
    args = parser.parse_args()
    if args.npcs <= 0 or args.seconds <= 0 or args.hz <= 0:
        parser.error("npcs, seconds and hz must be positive")
    modules = [("current", navigation)]
    if args.reference:
        modules.insert(0, ("reference", load_reference(args.reference)))
    print(f"{args.npcs} NPCs, {args.seconds:g} seconds, {args.hz} Hz; stationary starts")
    print(f"{'version':10} {'scenario':12} {'searches':>9} {'A*/NPC/s':>9} {'LOS probes':>11} {'ms':>10}")
    for name, module in modules:
        for scenario in ("open", "wall", "unreachable"):
            searches, probes, elapsed = run(module, scenario, args.npcs, args.seconds, args.hz)
            print(f"{name:10} {scenario:12} {searches:9} {searches / args.npcs / args.seconds:9.2f} "
                  f"{probes:11} {elapsed:10.2f}")
        probes, elapsed, points = corridor(module)
        print(f"{name:10} {'smoothing':12} {'-':>9} {'-':>9} {probes:11} {elapsed:10.2f} "
              f"({points} waypoints)")


if __name__ == "__main__":
    main()
