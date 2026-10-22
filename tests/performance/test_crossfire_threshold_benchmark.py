"""Report the scalar/dense crossfire crossover; assert answers, never timings."""

import statistics
import time
from types import SimpleNamespace

import numpy as np
import pytest

from engine.monster_table import MonsterTable

pytestmark = pytest.mark.benchmark


def test_report_crossfire_crossover(monkeypatch):
    rng = np.random.default_rng(72)
    print('\nrows scene     scalar us   dense us')
    for count in (4, 8, 16, 32, 64, 128, 1000):
        for aligned in (False, True):
            monsters = [SimpleNamespace(
                pos=[float(rng.uniform(100, 9000)), 0.,
                     0. if aligned else float(rng.uniform(-2000, 2000))],
                properties={'team': 'enemy' if row else 'shooter'})
                for row in range(count)]
            table = MonsterTable()
            table.gather(monsters)
            timings, answers = [], []
            for threshold in (count, 0):
                monkeypatch.setattr(MonsterTable, 'CROSSFIRE_SCALAR_MAX_ROWS', threshold)
                answers.append(table.crossfire(0, (0., 64., 0.), (10000., 64., 0.)))
                samples = []
                for _ in range(5):
                    started = time.perf_counter()
                    for _ in range(150):
                        table.crossfire(0, (0., 64., 0.), (10000., 64., 0.))
                    samples.append((time.perf_counter() - started) / 150 * 1e6)
                timings.append(statistics.median(samples))
            assert answers[0] is answers[1], (count, aligned)
            print(f'{count:4d} {"aligned" if aligned else "spread":7s}'
                  f' {timings[0]:10.2f} {timings[1]:10.2f}')
