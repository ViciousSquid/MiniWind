"""
The inked district borders, kept out of the editor's view.

The borders are baked into the overworld's own paint (game/districts.py), so
in play they cost nothing. In the editor they would be in the way, so while
the map is open for editing they are lifted out of the live terrain (and out
of the scene's terrain data, so an undo cannot bring them back), and put
back:

* into every copy of the level the editor makes -- a save, an autosave, a
  savegame (``EditorState.level_data_hooks``): laid, serialised, lifted
  again; a chunk nobody touched swaps back the very arrays it had, so the
  paint serialiser's cache holds and a save costs next to nothing;
* into the live terrain for Play (``on_play_start``), and out again after
  (``on_play_stop``).

:class:`game.districts.Drawing` checks the paint itself before lifting or
laying, so none of this can ink a texel twice or lose one.
"""

from __future__ import annotations


class EditorBorders:
    def __init__(self):
        self.state = None
        self.terrain = None
        self.drawing = None
        self._hooked = set()

    def level_loaded(self, state, terrain, play_mode=False) -> None:
        """A map became the scene (``editor.level_loaded``)."""
        self.state, self.terrain, self.drawing = state, terrain, None
        if state is None or terrain is None:
            return
        try:
            from . import districts
            found = districts.load()
            if not found.map or not found.fits(getattr(state, "terrain_data", None)):
                return
            drawing = districts.Drawing.load(districts.record_path(found.map),
                                             int(terrain.TERRAIN_PAINT_RESOLUTION))
        except Exception as exc:
            print(f"[MiniWind] district borders not managed in the editor: {exc}")
            return
        if drawing is None:
            return
        self.drawing = drawing
        hooks = getattr(state, "level_data_hooks", None)
        if hooks is not None and id(state) not in self._hooked:
            hooks.append(self._put_back)
            self._hooked.add(id(state))
        if not play_mode:
            self._lift()

    # -- out of view ---------------------------------------------------------------
    def _lift(self) -> None:
        if self.drawing is None or self.terrain is None:
            return
        self.drawing.lift(self.terrain)
        self._sync_paint()

    def _sync_paint(self) -> None:
        """The scene's terrain data follows the live terrain's paint."""
        state, terrain = self.state, self.terrain
        data = getattr(state, "terrain_data", None)
        if not isinstance(data, dict):
            return
        data = dict(data)                       # history entries keep the old dict
        paint = terrain._serialize_texture_paint()
        if paint:
            data["texture_paint_resolution"] = terrain.TERRAIN_PAINT_RESOLUTION
            data["texture_paint"] = paint
        else:
            data.pop("texture_paint", None)
        state.terrain_data = data

    def _put_back(self, level) -> None:
        """Every level dict the editor builds keeps the borders in its paint."""
        if self.drawing is None or self.terrain is None or "terrain_data" not in level:
            return
        terrain = self.terrain
        was_laid = self.drawing.is_laid(terrain)
        if not was_laid:
            self.drawing.lay(terrain)
        try:
            data = dict(level["terrain_data"])
            paint = terrain._serialize_texture_paint()
            if paint:
                data["texture_paint_resolution"] = terrain.TERRAIN_PAINT_RESOLUTION
                data["texture_paint"] = paint
            level["terrain_data"] = data
        finally:
            if not was_laid:
                self.drawing.lift(terrain)

    # -- Play ----------------------------------------------------------------------
    def play_start(self) -> None:
        """Into the live terrain: Play shows the map as its file has it."""
        if self.drawing is not None and self.terrain is not None:
            self.drawing.lay(self.terrain)

    def play_stop(self) -> None:
        """Out of view again, back in the editor."""
        self._lift()


#: The one the MiniWind plugin wires to the editor (game/host.py).
EDITOR = EditorBorders()
