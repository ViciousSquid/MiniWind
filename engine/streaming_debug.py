"""
The world-streaming debug overlay: a stats panel and an active-cell minimap.

Pure presentation over :class:`engine.world_streaming.WorldStreamingSession` —
it reads ``session.stats()`` and the cell index and draws with the viewport's
live ``QPainter``. Kept apart from the viewport so the streaming numbers have
one place to be formatted, and apart from the streaming session so the session
carries no UI.

Drawn only in play mode, only when the map's ``BigWorldSettings`` entity asks
for it (``show_cell_debug``), and never at the cost of a frame: the caller
guards the whole thing.
"""

from __future__ import annotations


def paint_streaming_debug(painter, session, width, height):
    from PyQt5.QtCore import Qt, QRect
    from PyQt5.QtGui import QColor, QFont

    s = session.stats()
    pc = s.get("player_cell")
    pc_txt = f"{pc[0]}, {pc[1]}" if pc else "-"
    lines = [
        ("Player Cell", pc_txt),
        ("Active Cells", f"{s['active_cells']}"),
        ("Loaded Cells", f"{s['loaded_cells']}"),
        ("Activation Radius", f"{s['activation_radius']:.0f}"),
        ("Active Brushes", f"{s['active_brushes']:,}"),
        ("Total Brushes", f"{s['total_brushes']:,}"),
        ("Active Entities", f"{s['active_entities']:,}"),
        ("Total Entities", f"{s['total_entities']:,}"),
        ("Active Lights", f"{s['active_lights']:,} / {s['total_lights']:,}"),
    ]
    if s.get("terrain_fill"):
        if s.get("terrain_infinite"):
            stream_txt = "∞"  # ∞: streaming forever, no world edge
        else:
            stream_txt = "on" if s.get("terrain_streaming") else "off"
        lines.append(("Terrain Chunks",
                      f"{s.get('terrain_chunks', 0):,} (stream {stream_txt})"))

    pad = 10
    row_h = 16
    panel_w = 230
    panel_h = pad * 2 + row_h * (len(lines) + 1)
    x0 = 12
    y0 = 90  # sit below Fio's own top-left debug text

    painter.save()
    painter.setRenderHint(painter.Antialiasing, False)
    painter.fillRect(QRect(x0, y0, panel_w, panel_h), QColor(10, 12, 20, 200))
    painter.setPen(QColor(120, 90, 200))
    painter.drawRect(QRect(x0, y0, panel_w, panel_h))

    font = QFont("Consolas", 9)
    painter.setFont(font)
    painter.setPen(QColor(180, 150, 240))
    painter.drawText(x0 + pad, y0 + pad + row_h - 4, "WORLD STREAMING")

    painter.setFont(QFont("Consolas", 8))
    y = y0 + pad + row_h * 2 - 4
    for label, value in lines:
        painter.setPen(QColor(150, 150, 170))
        painter.drawText(x0 + pad, y, label)
        painter.setPen(QColor(230, 230, 245))
        painter.drawText(x0 + pad + 130, y, value)
        y += row_h

    _paint_minimap(painter, session, x0, y0 + panel_h + 8)
    painter.restore()

def _paint_minimap(painter, session, x0, y0):
    """A tiny top-down map of loaded cells, active ones highlighted."""
    from PyQt5.QtCore import QRect
    from PyQt5.QtGui import QColor

    mgr = session.cells
    if not mgr.cells:
        return
    pc = mgr._last_player_cell or (0, 0)
    span = 8  # cells each way around the player
    px_per_cell = 12
    size = (span * 2 + 1) * px_per_cell
    painter.fillRect(QRect(x0, y0, size, size), QColor(10, 12, 20, 200))
    painter.setPen(QColor(120, 90, 200))
    painter.drawRect(QRect(x0, y0, size, size))
    for cx in range(pc[0] - span, pc[0] + span + 1):
        for cz in range(pc[1] - span, pc[1] + span + 1):
            coord = (cx, cz)
            cell = mgr.cells.get(coord)
            if cell is None:
                continue
            sx = x0 + (cx - (pc[0] - span)) * px_per_cell
            sz = y0 + (cz - (pc[1] - span)) * px_per_cell
            if coord in mgr.active_cells:
                col = QColor(110, 200, 130, 230)
            else:
                col = QColor(60, 60, 80, 200)
            painter.fillRect(QRect(sx + 1, sz + 1, px_per_cell - 2, px_per_cell - 2), col)
    # Player cell marker.
    sx = x0 + span * px_per_cell
    sz = y0 + span * px_per_cell
    painter.setPen(QColor(255, 220, 120))
    painter.drawRect(QRect(sx + 1, sz + 1, px_per_cell - 2, px_per_cell - 2))
