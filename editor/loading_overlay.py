"""
A "still working" overlay for the long, blocking stretches of the editor.

Opening a big map parses tens of megabytes of JSON, rebuilds the terrain and
uploads the scene to the GPU, and starting play builds the world's streaming
and physics; all of it runs on the UI thread. For those seconds the window
used to sit frozen on whatever it showed last, which looks exactly like a
crash.

:class:`LoadingOverlay` covers the window with a dark veil, a title ("Loading
village_walled_source") and the same progress bar as the startup splash
(``main.py``), reading "Building terrain (50%)". Work on the UI thread cannot
be interrupted to animate anything, so the long operations call :meth:`step`
between their stages: each call names the stage, moves the bar on and repaints
the overlay at once (``QWidget.repaint`` paints and flushes without running the
event loop, so nothing else, such as a half-loaded frame of the 3D view, gets a
chance to run).

Use it as a context manager; nesting is counted, so an operation built from
others (load a save = load its map + start play) shows one bar throughout,
which only ever moves forward::

    with window.loading_overlay.busy("Loading slot 1"):
        ...
        window.loading_overlay.step("Starting play", 80)
"""

from __future__ import annotations

import contextlib

from PyQt5.QtCore import QEvent, QObject, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPainter
from PyQt5.QtWidgets import QProgressBar, QWidget

#: Where a stage named without a percentage puts the bar: this share of the
#: way from where it is to the end, so it always moves and never fills.
_ADVANCE = 0.25
_CEILING = 95

#: The bar's height, as on the splash.
BAR_HEIGHT = 35

#: Faces a game may set (:func:`set_fonts`) for the title and the bar's text;
#: None keeps Arial for the title and the application font for the bar.
_TITLE_FONT = None
_BAR_FONT = None


def set_fonts(title=None, bar=None):
    """Use *title* / *bar* (QFonts) on every loading overlay from now on.

    The title font's point size is a base; it still scales with the window.
    """
    global _TITLE_FONT, _BAR_FONT
    _TITLE_FONT, _BAR_FONT = title, bar


class LoadingOverlay(QWidget):
    """Full-window "loading" veil with a progress bar; see the module docstring."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.title = ""
        self.stage = ""
        self._depth = 0
        self.bar = QProgressBar(self)
        self.bar.setRange(0, 100)
        self.bar.setFixedHeight(BAR_HEIGHT)
        self.bar.setAlignment(Qt.AlignCenter)
        parent.installEventFilter(self)
        self.hide()

    # -------------------------------------------------------------- lifecycle
    @property
    def active(self) -> bool:
        return self._depth > 0

    @property
    def value(self) -> int:
        return self.bar.value()

    def begin(self, title: str, stage: str = "", percent: int = None) -> None:
        """Raise the overlay (or, nested, just move on to *stage*)."""
        self._depth += 1
        if self._depth == 1:
            self.title = str(title)
            self.bar.setValue(0)
            if _BAR_FONT is not None:
                # A stylesheet, not setFont(): the application stylesheet sets
                # every widget's font-family, which would win over setFont.
                self.bar.setStyleSheet(
                    f'QProgressBar {{ font-family: "{_BAR_FONT.family()}"; '
                    f'font-size: {_BAR_FONT.pointSize()}pt; }}')
            self._layout()
            self.show()
            self.raise_()
        self.step(stage or "", percent)

    def end(self) -> None:
        """Lower the overlay once the outermost operation is done."""
        if self._depth <= 0:
            return
        self._depth -= 1
        if self._depth == 0:
            self.hide()

    @contextlib.contextmanager
    def busy(self, title: str, stage: str = "", percent: int = None):
        self.begin(title, stage, percent)
        try:
            yield self
        finally:
            self.end()

    def step(self, stage: str, percent: int = None) -> None:
        """Name the stage now under way, move the bar on and show it at once."""
        if not self.active:
            return
        if stage:
            self.stage = str(stage)
        current = self.bar.value()
        if percent is None:
            target = current + max(1, int((_CEILING - current) * _ADVANCE))
        else:
            target = int(percent)
        self.bar.setValue(max(current, min(_CEILING, target)))
        self.bar.setFormat(f"{self.stage} (%p%)" if self.stage else "%p%")
        try:
            self.raise_()
            self.repaint()
        except RuntimeError:
            pass   # the window is being torn down

    def _layout(self):
        parent = self.parentWidget()
        self.setGeometry(parent.rect())
        w, h = self.width(), self.height()
        bar_w = max(240, min(640, int(w * 0.5)))
        self.bar.setGeometry((w - bar_w) // 2, h // 2, bar_w, BAR_HEIGHT)

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Resize:
            self._layout()
        return False

    # ------------------------------------------------------------------ paint
    def paintEvent(self, _event):
        w = self.width()
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(14, 14, 18, 235))
        p.setPen(QColor(240, 236, 230))
        size = max(13, min(22, w // 60))
        if _TITLE_FONT is not None:
            font = QFont(_TITLE_FONT)
            font.setPointSize(int(size * 1.3))
            if _TITLE_FONT.wordSpacing() == 0:
                font.setWordSpacing(size * 0.5)   # display faces' spaces run thin
        else:
            font = QFont("Arial", size, QFont.Bold)
        p.setFont(font)
        fm = p.fontMetrics()
        top = self.bar.y() - fm.height() - 14
        p.drawText(QRectF(0, top, w, fm.height() + 4),
                   Qt.AlignHCenter | Qt.AlignTop, self.title)
        p.end()


class _NullOverlay(QObject):
    """Stand-in where no window exists to cover (tools, tests)."""

    active = False

    def begin(self, *_a, **_k):
        pass

    def end(self):
        pass

    def step(self, *_a, **_k):
        pass

    @contextlib.contextmanager
    def busy(self, *_a, **_k):
        yield self


NULL_OVERLAY = _NullOverlay()


def overlay_for(window):
    """*window*'s loading overlay, created on first use (a null one if it has none)."""
    overlay = getattr(window, "_loading_overlay", None)
    if overlay is not None:
        return overlay
    if not isinstance(window, QWidget):
        return NULL_OVERLAY
    try:
        overlay = LoadingOverlay(window)
    except Exception:
        return NULL_OVERLAY
    window._loading_overlay = overlay
    return overlay
