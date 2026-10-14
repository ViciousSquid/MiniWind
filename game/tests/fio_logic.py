"""A stand-in for Fio 3's logic thread in MiniWind's game tests.

Fio 3 keeps the world, the player, the camera and the session on owned
runtimes (``logic.editor_state.things``, ``logic.player_runtime.player``,
``logic.camera``, ``logic.session_runtime``, ...), and game code reaches them
through :mod:`game.fio`. The game tests describe a scene with a few plain
fields -- ``things``, ``player``, maybe ``set_camera_focus`` -- so their fake
logic threads subclass :class:`FioLogic`, which presents those fields where
Fio 3 keeps them. Nothing here is used outside the tests.
"""


class _Proxy:
    def __init__(self, owner):
        object.__setattr__(self, "_owner", owner)


class _EditorState(_Proxy):
    @property
    def things(self):
        owner = self._owner
        if "things" not in vars(owner):
            owner.things = []
        return owner.things

    @property
    def brushes(self):
        return getattr(self._owner, "brushes", [])


class _PlayerRuntime(_Proxy):
    _DEFAULTS = {"player": None, "player_health": 100, "player_max_health": 100,
                 "god_mode": False, "player_dead": False, "last_damage": None}

    def __getattr__(self, name):
        if name in self._DEFAULTS:
            return getattr(self._owner, name, self._DEFAULTS[name])
        raise AttributeError(name)

    def __setattr__(self, name, value):
        setattr(self._owner, name, value)


class _SessionRuntime(_Proxy):
    def set_world_paused(self, owner, paused=True):
        logic = self._owner
        method = getattr(type(logic), "set_world_paused", None)
        if method is not None:
            method(logic, owner, paused)
            return
        owners = set(vars(logic).get("_pause_owners", ()))
        (owners.add if paused else owners.discard)(owner)
        logic._pause_owners = owners

    @property
    def world_paused(self):
        logic = self._owner
        if hasattr(type(logic), "world_paused") or "world_paused" in vars(logic):
            return bool(logic.world_paused)
        return bool(vars(logic).get("_pause_owners"))


class _Camera(_Proxy):
    def is_overhead(self):
        logic = self._owner
        probe = getattr(logic, "is_overhead", None)
        if callable(probe):
            return bool(probe())
        return str(getattr(logic, "camera_mode", "")).lower() == "overhead"

    @property
    def overhead_orientation(self):
        return getattr(self._owner, "overhead_orientation", "north")

    def set_camera_mode(self, mode):
        self._owner.camera_mode = mode

    @property
    def camera_focus(self):
        return getattr(self._owner, "camera_focus", None)

    def set_camera_focus(self, point=None, glide=True):
        logic = self._owner
        method = getattr(type(logic), "set_camera_focus", None)
        if method is not None:
            method(logic, point, glide)
        else:
            logic.camera_focus = None if point is None else tuple(point)


class _WorldRuntime(_Proxy):
    @property
    def terrain(self):
        return getattr(self._owner, "terrain", None)

    def build_entity_caches(self):
        rebuild = getattr(self._owner, "_build_entity_caches", None)
        if callable(rebuild):
            rebuild()

    def find_entity_by_name(self, name):
        for thing in getattr(self._owner, "things", ()):
            if getattr(thing, "properties", {}).get("name") == name:
                return thing
        return None

    def find_entity_by_id(self, entity_id):
        for thing in getattr(self._owner, "things", ()):
            if getattr(thing, "properties", {}).get("id") == entity_id:
                return thing
        return None


class _CombatRuntime(_Proxy):
    def spawn_projectile(self, pos, vel, **kwargs):
        logic = self._owner
        if "projectiles" not in vars(logic):
            logic.projectiles = []
        logic.projectiles.append(dict(pos=list(pos), vel=list(vel), **kwargs))
        return len(logic.projectiles) - 1


def _runtime(name, cls):
    key = "_" + name

    def get(self):
        found = vars(self).get(key)
        return found if found is not None else cls(self)

    def put(self, value):
        vars(self)[key] = value

    return property(get, put)


class FioLogic:
    """Fio 3's runtime surface over a fake logic thread's plain fields."""

    editor_state = _runtime("editor_state", _EditorState)
    player_runtime = _runtime("player_runtime", _PlayerRuntime)
    session_runtime = _runtime("session_runtime", _SessionRuntime)
    camera = _runtime("camera", _Camera)
    world_runtime = _runtime("world_runtime", _WorldRuntime)
    combat_runtime = _runtime("combat_runtime", _CombatRuntime)
