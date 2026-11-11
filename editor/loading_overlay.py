"""
A "still working" panel for the long, blocking stretches of the editor.

Opening a big map parses tens of megabytes of JSON, rebuilds the terrain and
uploads the scene to the GPU, and starting play builds the world's streaming
and physics; all of it runs on the UI thread. For those seconds the window
used to sit frozen on whatever it showed last, which looks exactly like a
crash.

:class:`LoadingOverlay` is a small panel floating in the middle of the
window with a title ("Loading cave01"), a throbber (a short horizontal line
travelling back and forth along a track) and the stage under way ("Building
terrain"). The editor stays visible behind it, slightly blurred -- a picture
of the window taken as the panel is raised, softened and drawn under it --
so it reads as set aside for a moment rather than frozen. It used to be a
dark veil over the whole window with a percentage bar, which for a load of a
second or two was a full-screen flash.

Work on the UI thread cannot be interrupted to animate anything, so the long
operations call :meth:`step` between their stages: each call names the stage
and repaints the panel at once (``QWidget.repaint`` paints and flushes
without running the event loop, so nothing else, such as a half-loaded frame
of the 3D view, gets a chance to run). The throbber's line is placed by the
clock, so each repaint shows it where the time has carried it; no timer, no
thread and no second process draws it.

Use it as a context manager; nesting is counted, so an operation built from
others (a level change = load its map + restart play) shows one panel
throughout::

    with window.loading_overlay.busy("Loading cave01", "Reading the map", 5):
        ...
        window.loading_overlay.step("Building terrain", 40)

The percentages are still taken (and only ever move forward, see
:attr:`LoadingOverlay.value`) so callers and tools can tell how far a load
has got; the panel does not show them.

A game has its own presentation instead of the panel, never beside it: once
it has installed its faces with :func:`set_fonts`, the overlay is the staged
loading bar -- a dark veil over the whole window, the title in the game's
face and the same progress bar as the startup splash (``main.py``), reading
"Building terrain (50%)". :func:`staged` says which of the two is in use.
"""

from __future__ import annotations

import contextlib
import time

from PyQt5.QtCore import QEvent, QObject, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QProgressBar, QWidget

#: Where a stage named without a percentage puts the progress: this share of
#: the way from where it is to the end, so it always moves and never fills.
_ADVANCE = 0.25
_CEILING = 95

#: The height of the startup splash's progress bar (``main.py``).
BAR_HEIGHT = 10

#: The floating panel, in logical pixels.
PANEL_WIDTH = 320
PANEL_HEIGHT = 92
#: The throbber: a track with a line this share of its width, crossing it
#: and coming back once every THROB_SECONDS.
THROB_LINE = 0.28
THROB_SECONDS = 1.6
FIO_ORANGE = QColor(240, 128, 0)
#: The backdrop's blur: the window's picture is shrunk by this factor with
#: smooth filtering and drawn back at full size. Slight, but plain to see.
BLUR_FACTOR = 3


#: Faces a game may set (:func:`set_fonts`) for the title and the bar's text.
#: Setting either selects the staged bar over the floating panel.
_TITLE_FONT = None
_BAR_FONT = None


def set_fonts(title=None, bar=None):
    """Use *title* / *bar* (QFonts) on every loading overlay from now on, and
    show loads as the staged bar rather than the floating panel.

    The title font's point size is a base; it still scales with the window.
    ``set_fonts()`` with neither goes back to the panel.
    """
    global _TITLE_FONT, _BAR_FONT
    _TITLE_FONT, _BAR_FONT = title, bar


def staged() -> bool:
    """Whether loads show the game's staged bar (see :func:`set_fonts`)."""
    return _TITLE_FONT is not None or _BAR_FONT is not None


def blurred(pixmap, factor: int = BLUR_FACTOR):
    """*pixmap* softened: shrunk in two smooth steps and scaled back (the
    cheap, even blur the pause menu uses), at its original size."""
    if pixmap is None or pixmap.isNull():
        return None
    w, h = pixmap.width(), pixmap.height()
    half = pixmap.scaled(max(1, w // 2), max(1, h // 2),
                         Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    small = half.scaled(max(1, w // factor), max(1, h // factor),
                        Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def throbber_span(seconds: float, width: float):
    """``(start, end)`` in pixels of the throbber's line on a track *width*
    wide, *seconds* after it started: left to right and back, eased at the
    turns."""
    phase = (seconds / THROB_SECONDS) % 1.0
    travel = 1.0 - abs(2.0 * phase - 1.0)            # 0 -> 1 -> 0
    travel = travel * travel * (3.0 - 2.0 * travel)  # smoothstep
    line = width * THROB_LINE
    start = (width - line) * travel
    return start, start + line


class LoadingOverlay(QWidget):
    """A small floating "loading" panel with a throbber over the blurred
    window; see the module docstring."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)
        self.title = ""
        self.stage = ""
        self._depth = 0
        self._value = 0
        self._started = 0.0
        #: The window as it looked when the panel was raised, blurred.
        self.backdrop = None
        #: Injected by tests: the clock the throbber is placed by.
        self.clock = time.perf_counter
        #: The staged presentation's progress bar; made when first needed.
        self.bar = None
        #: Which presentation the load under way was raised with.
        self._staged = False
        parent.installEventFilter(self)
        self.hide()

    # -------------------------------------------------------------- lifecycle
    @property
    def active(self) -> bool:
        return self._depth > 0

    @property
    def value(self) -> int:
        """How far the operation has got, 0-95; not drawn."""
        return self._value

    def begin(self, title: str, stage: str = "", percent: int = None) -> None:
        """Raise the panel (or, nested, just move on to *stage*)."""
        self._depth += 1
        if self._depth == 1:
            self.title = str(title)
            self._value = 0
            self._started = self.clock()
            self._staged = staged()
            if self._staged:
                self.backdrop = None
                self._prepare_bar()
            else:
                self.backdrop = self._grab_backdrop()
                if self.bar is not None:
                    self.bar.hide()
            self._layout()
            self.show()
            self.raise_()
        self.step(stage or "", percent)

    def end(self) -> None:
        """Lower the panel once the outermost operation is done."""
        if self._depth <= 0:
            return
        self._depth -= 1
        if self._depth == 0:
            self.hide()
            self.backdrop = None

    @contextlib.contextmanager
    def busy(self, title: str, stage: str = "", percent: int = None):
        self.begin(title, stage, percent)
        try:
            yield self
        finally:
            self.end()

    def step(self, stage: str, percent: int = None) -> None:
        """Name the stage now under way and show it, and the throbber, at once."""
        if not self.active:
            return
        if stage:
            self.stage = str(stage)
        current = self._value
        if percent is None:
            target = current + max(1, int((_CEILING - current) * _ADVANCE))
        else:
            target = int(percent)
        self._value = max(current, min(_CEILING, target))
        if self._staged and self.bar is not None:
            self.bar.setValue(self._value)
        try:
            self.raise_()
            self.repaint()
        except RuntimeError:
            pass   # the window is being torn down

    def _grab_backdrop(self):
        """A blurred picture of the window as it is now (taken before the
        panel shows, so the panel is not in it), or None if it cannot be
        taken -- the panel then floats over the live window."""
        parent = self.parentWidget()
        try:
            if not parent.isVisible() or parent.width() < 2 or parent.height() < 2:
                return None
            return blurred(parent.grab())
        except Exception:
            return None

    def _prepare_bar(self):
        """The staged presentation's bar: the splash's, empty."""
        if self.bar is None:
            self.bar = QProgressBar(self)
            self.bar.setRange(0, 100)
            self.bar.setFixedHeight(BAR_HEIGHT)
            self.bar.setTextVisible(False)
            self.bar.setAlignment(Qt.AlignCenter)
        self.bar.setValue(0)
        if _BAR_FONT is not None:
            # A stylesheet, not setFont(): the application stylesheet sets
            # every widget's font-family, which would win over setFont.
            self.bar.setStyleSheet(
                f'QProgressBar {{ font-family: "{_BAR_FONT.family()}"; '
                f'font-size: {_BAR_FONT.pointSize()}pt; }}')
        self.bar.show()

    def _layout(self):
        """Cover the window (to draw its blurred picture, or the staged
        veil); the panel itself is :meth:`panel_rect`, in the middle."""
        self.setGeometry(self.parentWidget().rect())
        if self._staged and self.bar is not None:
            w, h = self.width(), self.height()
            bar_w = max(240, min(640, int(w * 0.5)))
            self.bar.setGeometry((w - bar_w) // 2, h // 2, bar_w, BAR_HEIGHT)

    def panel_rect(self) -> QRectF:
        w = min(PANEL_WIDTH, max(160, self.width() - 24))
        h = min(PANEL_HEIGHT, max(60, self.height() - 24))
        return QRectF((self.width() - w) // 2, (self.height() - h) // 2, w, h)

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Resize:
            self._layout()
        return False

    # ------------------------------------------------------------------ paint
    def throbber_track(self) -> QRectF:
        """The throbber's track, in this widget's coordinates."""
        panel = self.panel_rect()
        margin = 22.0
        return QRectF(panel.left() + margin, panel.center().y() + 2.0,
                      panel.width() - 2 * margin, 2.0)

    def _paint_staged(self):
        """The game's presentation: a veil, the title and the staged bar."""
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
            font = QFont("Fio UI", size, QFont.Bold)
        p.setFont(font)
        fm = p.fontMetrics()
        top = self.bar.y() - fm.height() - 14
        p.drawText(QRectF(0, top, w, fm.height() + 4),
                   Qt.AlignHCenter | Qt.AlignTop, self.title)
        # Keep the stage readable without squeezing text into a 10px bar.
        p.setFont(QFont(_BAR_FONT) if _BAR_FONT is not None else self.font())
        stage_height = p.fontMetrics().height()
        p.drawText(QRectF(8, self.bar.geometry().bottom() + 10, w - 16, stage_height + 4),
                   Qt.AlignHCenter | Qt.AlignTop, f"{self.stage} ({self.value}%)")
        p.end()

    def paintEvent(self, _event):
        if self._staged and self.bar is not None:
            self._paint_staged()
            return
        p = QPainter(self)
        if self.backdrop is not None:
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.drawPixmap(self.rect(), self.backdrop)
        p.setRenderHint(QPainter.Antialiasing, True)
        panel = self.panel_rect().adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(85, 85, 90), 1.0))
        p.setBrush(QColor(24, 24, 28, 245))
        p.drawRoundedRect(panel, 6.0, 6.0)

        track = self.throbber_track()
        left, width = panel.left() + 10, panel.width() - 20
        p.setPen(QColor(240, 236, 230))
        p.setFont(QFont("Fio UI", 11, QFont.Bold))
        fm = p.fontMetrics()
        p.drawText(QRectF(left, track.top() - fm.height() - 10, width, fm.height() + 4),
                   Qt.AlignHCenter | Qt.AlignTop,
                   fm.elidedText(self.title, Qt.ElideMiddle, int(width) - 4))

        # The track, and the line where the clock has carried it.
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(70, 70, 76))
        p.drawRoundedRect(track, 1.0, 1.0)
        start, end = throbber_span(self.clock() - self._started, track.width())
        p.setBrush(FIO_ORANGE)
        p.drawRoundedRect(QRectF(track.left() + start, track.top() - 0.5,
                                 end - start, track.height() + 1.0), 1.5, 1.5)

        p.setPen(QColor(190, 188, 184))
        p.setFont(self.font())
        fm = p.fontMetrics()
        p.drawText(QRectF(left, track.bottom() + 9, width, fm.height() + 4),
                   Qt.AlignHCenter | Qt.AlignTop,
                   fm.elidedText(self.stage, Qt.ElideRight, int(width) - 4))
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
