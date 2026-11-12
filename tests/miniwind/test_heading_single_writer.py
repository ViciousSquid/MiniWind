"""Ratchet: an actor's heading has one store and one writer.

The heading is ``properties['angle']`` (degrees), written only by
:mod:`engine.monster_facing`, which journals each turn with the FACING record
(the head sprite's spin is the only thing a turn changes in the tables). A
second writer would turn an actor the tables never hear about; a second store
(MiniWind once kept ``_facing`` in radians beside Fio's ``angle``) splits the
truth. Editor tools author a placed actor's angle and are not scanned.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
OWNER = ROOT / 'engine' / 'monster_facing.py'
SCANNED = ('engine', 'game', 'plugins')

WRITE = re.compile(r"""\[\s*['"]angle['"]\s*\]\s*=(?!=)|\.update\([^)]*\bangle\s*=""")
SECOND_STORE = re.compile(r"""['"]_facing['"]|\b_facing\s*=""")


def _sources():
    for top in SCANNED:
        for path in (ROOT / top).rglob('*.py'):
            if 'tests' in path.parts or path == OWNER:
                continue
            yield path


def test_only_monster_facing_writes_an_actor_heading():
    offenders = []
    for path in _sources():
        for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            code = line.split('#', 1)[0]
            if SECOND_STORE.search(code):
                offenders.append('%s:%d second heading store: %s'
                                 % (path.relative_to(ROOT), n, line.strip()))
            elif WRITE.search(code) and not _allowed(path, code):
                offenders.append('%s:%d writes angle: %s'
                                 % (path.relative_to(ROOT), n, line.strip()))
    assert not offenders, '\n'.join(offenders)


#: Writes of a key named ``angle`` that are not an actor's heading.
_NOT_A_HEADING = {
    'engine/mover_table.py',        # a rotating brush's spin angle
    'engine/terrain.py',            # a paint stamp's angle
}


def _allowed(path, code):
    rel = str(path.relative_to(ROOT)).replace('\\', '/')
    # Offline map-authoring tools place furniture the way the editor does.
    return rel in _NOT_A_HEADING or rel.startswith('game/tools/')
