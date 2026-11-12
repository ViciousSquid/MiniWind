"""Camera-local authoring over Big World's cell index.

The JSON map remains the authoring source. Only resident records become live
brushes/entities; leaving a region writes edits back before releasing objects.
No hidden/disabled gameplay flags are written into authored records.
"""

from engine.data_copy import data_copy
import uuid
from types import SimpleNamespace

from .cell import cell_of_point
from .config import config_from_properties
from .manager import BigWorldManager, DEFAULT_PERSISTENT_TYPES, brush_cells


def record_id(record, kind):
    return record.get('id') if kind == 'brushes' else record.get('properties', {}).get('id')


class EditorCellStream:
    def __init__(self, level, position, *, adopt=False):
        """Index *level*'s records around *position*.

        The stream keeps its own copy of every record unless *adopt* says the
        caller hands the records over (a map parsed just for this load):
        copying the shipped world's 18k records cost a large part of every
        level change.
        """
        self.position = list(position)
        self.records = {'brushes': {}, 'things': {}}
        self.resident = {'brushes': set(), 'things': set()}
        self.suspended = False
        self.whole_world = False
        self.epoch = -1
        seen = set()
        for kind in self.records:
            for original in level.get(kind, []):
                record = original if adopt else data_copy(original)
                props = record if kind == 'brushes' else record.setdefault('properties', {})
                if kind == 'things':
                    props.setdefault('type', record.get('type', ''))
                identity = props.get('id')
                if not identity or identity in seen:
                    identity = str(uuid.uuid4())
                    props['id'] = identity
                seen.add(identity)
                self.records[kind][identity] = record
        settings = next(r for r in self.records['things'].values()
                        if str(r.get('type', r['properties'].get('type', ''))).replace('_', '').lower()
                        == 'bigworldsettings')
        self.config = config_from_properties(settings['properties'])
        self.manager = BigWorldManager(
            activation_radius=self.config['activation_radius'],
            deactivation_radius=self.config['deactivation_radius'],
            persistent_types=DEFAULT_PERSISTENT_TYPES | {
                'playerstart', 'bigworldsettings', 'miniwindsettings'})
        self.reindex()

    @classmethod
    def for_level(cls, level, position=None, *, adopt=False):
        settings = next((r for r in level.get('things', [])
                         if str(r.get('type', r.get('properties', {}).get('type', '')))
                         .replace('_', '').lower() == 'bigworldsettings'), None)
        if settings is None:
            return None
        config = config_from_properties(settings.get('properties', {}))
        if not config['enabled'] or not config['editor_streaming']:
            return None
        if position is None:
            from engine.player_starts import resolve_start_record
            start = resolve_start_record(level)
            position = start.get('pos', [0, 150, 400]) if start else [0, 150, 400]
        return cls(level, position, adopt=adopt)

    #: Above this share of the brushes re-filed one by one, the whole index is
    #: rebuilt instead (:meth:`refile_brushes`).
    REFILE_MAX_SHARE = 0.25

    def refile_brushes(self, replaced):
        """Re-file the brushes whose records *replaced* swaps, ``[(old, new),
        ...]``, leaving the rest of the index as it is.

        For a load that replaces a few records before anything is active (a
        version 3 map's angled brushes moved into their local frame): a
        whole :meth:`reindex` walked every brush of the world to move those.
        Many replacements fall back to the rebuild, which is cheaper then.
        """
        brushes = self.records['brushes']
        if not replaced:
            return
        if len(replaced) > self.REFILE_MAX_SHARE * max(1, len(brushes)):
            self.reindex()
            return
        manager = self.manager
        for old, new in replaced:
            for coord in brush_cells(old, manager.cell_size):
                cell = manager.cells.get(coord)
                if cell is not None:
                    cell.brushes[:] = [b for b in cell.brushes if b is not old]
            manager.add_brush(new)

    def reindex(self):
        self.order = {kind: {identity: i for i, identity in enumerate(records)}
                      for kind, records in self.records.items()}
        proxies = [SimpleNamespace(pos=r.get('pos', [0, 0, 0]), properties=r['properties'])
                   for r in self.records['things'].values()]
        self.manager.index_world(self.records['brushes'].values(), proxies)

    def local_data(self, position=None, pinned=()):
        if position is not None:
            self.position = list(position)
        self.manager.update(self.position, force=True)
        brush_ids = {b['id'] for b in self.manager.active_brushes()}
        thing_ids = {t.properties['id'] for t in (
            self.manager.active_things() + self.manager.active_lights()
            + self.manager.persistent_things)}
        brush_ids.update(pinned)
        thing_ids.update(pinned)
        thing_ids.update(identity for identity, record in self.records['things'].items()
                         if record.get('properties', {}).get('_cutscene_temporary'))
        # Preserve file order, including PlayerStart creation order.
        return {kind: [self.records[kind][identity] for identity in
                       sorted(ids & self.records[kind].keys(), key=self.order[kind].__getitem__)]
                for kind, ids in (('brushes', brush_ids), ('things', thing_ids))}

    def merge(self, brushes, things):
        """Commit resident edits/deletions, leaving unloaded records intact."""
        for kind, records in (('brushes', brushes), ('things', things)):
            current = {record_id(r, kind): r for r in records}
            for identity in self.resident[kind] - current.keys():
                self.records[kind].pop(identity, None)
            for identity, record in current.items():
                self.records[kind][identity] = data_copy(record)
            self.resident[kind] = set(current)

    def remember_resident(self, state):
        self.resident = {
            'brushes': {b['id'] for b in state.brushes},
            'things': {t.properties['id'] for t in state.things}}
        self.epoch = state.world_epoch

    def all_data(self):
        return {kind: list(records.values()) for kind, records in self.records.items()}

    def same_cell(self, position):
        return cell_of_point(position[0], position[2]) == cell_of_point(
            self.position[0], self.position[2])
