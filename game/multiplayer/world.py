"""Map-script bindings owned by a campaign, restored when its session ends."""

from __future__ import annotations

from .. import fio


def collision_brush(brush):
    """A local collision view of scenery parked by world streaming."""
    from engine.spatial import PARKED_HIDDEN_KEY, authored_hidden

    if PARKED_HIDDEN_KEY not in brush:
        return brush
    local = dict(brush, hidden=authored_hidden(brush))
    if brush.get("is_mover") or brush.get("is_door"):
        # Fio 3.5 keeps a door's or mover's live position out of the brush
        # (its ``pos`` is where it was authored) and resolves it by the
        # brush's identity, which a copy does not have: carry where it is now.
        from engine import brush_placement

        local["pos"] = list(brush_placement.placement(brush).centre)
        for key in brush_placement.RUNTIME_CACHE_KEYS:
            local.pop(key, None)
    return local


class CompanionCollisionGrid:
    """Keep offscreen returning bodies solid without waking scenery for rendering."""

    def __init__(self, grid):
        self.grid = grid

    @property
    def water_brushes(self):
        return self.grid.water_brushes

    def get_potential_colliders(self, lo, hi):
        return [collision_brush(b) for b in self.grid.get_potential_colliders(lo, hi)]


class WorldBindings:
    def __init__(self, coop):
        self.coop = coop
        self.views = []
        self.io = getattr(coop.logic, "io_manager", None)
        self.original_query = None
        self.original_set = None

    def install(self):
        legacy = self.coop._settings.get("coop_legacy_store", "miniwind")
        store = self.coop.party_quests.store
        for thing in fio.things(self.coop.logic):
            if (
                str(thing.properties.get("type", "")).replace("_", "").lower()
                != "logicstate"
            ):
                continue
            if thing.properties.get("store_name") == legacy:
                self.views.append((thing, legacy))
                thing.properties["store_name"] = store._name
                for key, value in thing.properties.get("initial_data", {}).items():
                    if store.get(key, None) is None:
                        store.set(key, value)
                thing._sync_from_persistent()
        if self.io is not None:
            self.original_query = self.io.query_keyvalue
            self.original_set = self.io.set_keyvalue

            def query(name, key, default="<missing>"):
                if name == legacy:
                    return store.get(key, default)
                return self.original_query(name, key, default)

            def set_value(name, key, value):
                if name == legacy:
                    if not str(key).strip():
                        return False
                    store.set(key, value)
                    self.sync()
                    return True
                return self.original_set(name, key, value)

            self.io.query_keyvalue = query
            self.io.set_keyvalue = set_value

    def sync(self):
        for thing, _ in self.views:
            thing._sync_from_persistent()

    def close(self):
        for thing, original in self.views:
            thing.properties["store_name"] = original
            thing._sync_from_persistent()
        if self.io is not None and self.original_query is not None:
            self.io.query_keyvalue = self.original_query
            self.io.set_keyvalue = self.original_set
        self.views.clear()
