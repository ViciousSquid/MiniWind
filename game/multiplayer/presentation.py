"""Compact party status, independent from the selected character's RPG UI."""

from __future__ import annotations

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QPixmap

from ..rpg import heads

COLOURS = ("#69b6ff", "#ffbf69", "#b1e17d", "#d89fff")


def draw_party(event, coop):
    painter = event.get("painter")
    if painter is None:
        return
    view = event.get("viewport")
    if view is not None and not coop._devices_installed:
        from .devices import install

        install(coop, view)
        coop._devices_installed = True
    width = float(event.get("width", 800))
    card = min(235.0, (width - 32) / max(1, len(coop.players)))
    painter.save()
    for index, context in enumerate(coop.players.values()):
        x = 12 + index * card
        c = context.session.game.character
        painter.setPen(QColor(COLOURS[index % 4]))
        painter.setBrush(QColor(20, 22, 28, 220))
        painter.drawRoundedRect(QRectF(x, 10, card - 6, 72), 5, 5)
        pix = QPixmap(heads.head_path(context.profile["head"]))
        painter.drawPixmap(int(x + 5), 20, 42, 42, pix)
        painter.drawText(
            QRectF(x + 52, 13, card - 60, 22),
            Qt.AlignLeft | Qt.AlignVCenter,
            context.profile["name"],
        )
        status = (
            "Disconnected"
            if not context.connected
            else "Down — hold interact nearby"
            if c.is_dead
            else f"HP {int(c.health)}/{int(c.max_health)}"
        )
        painter.setPen(QColor("#eeeeee"))
        painter.drawText(
            QRectF(x + 52, 34, card - 58, 20), Qt.AlignLeft | Qt.AlignVCenter, status
        )
        painter.setPen(QColor("#adb4c3"))
        text = (
            context.task or "AI companion"
            if context.bot
            else "This computer"
            if context.owner == coop.lobby.owner
            else "Network player"
        )
        if context.player_id == coop._ui_owner:
            text += " · UI"
        painter.drawText(
            QRectF(x + 52, 54, card - 58, 18), Qt.AlignLeft | Qt.AlignVCenter, text
        )
    if coop.paused:
        painter.setPen(QColor("#ffde95"))
        painter.drawText(
            QRectF(0, 90, width, 30), Qt.AlignCenter, "Party paused by host"
        )
    if coop.disconnected:
        painter.setPen(QColor("#ffbf69"))
        painter.setBrush(QColor(15, 18, 25, 235))
        painter.drawRoundedRect(QRectF(width * 0.15, 110, width * 0.7, 100), 6, 6)
        painter.drawText(
            QRectF(width * 0.18, 120, width * 0.64, 80),
            Qt.AlignCenter | Qt.TextWordWrap,
            "The host disconnected. This session has ended. Your character is kept in the host's campaign save. Press Esc to leave.",
        )
    if coop.travel is not None:
        painter.setPen(QColor("#ffde95"))
        painter.drawText(
            QRectF(0, 120, width, 28),
            Qt.AlignCenter,
            "Party travel — press interact when ready",
        )
    pouch = coop.party_quests.pouch()
    if pouch:
        painter.setPen(QColor("#e7d6a2"))
        contents = ", ".join(
            f"{s.get('qty', 1)} {s.get('name') or s.get('id', 'item')}" for s in pouch
        )
        painter.drawText(
            QRectF(12, 84, width - 24, 22),
            Qt.AlignLeft | Qt.AlignVCenter,
            "Party quest pouch: " + contents,
        )
    painter.restore()
