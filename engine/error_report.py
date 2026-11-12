"""Errors you can see: a log file, the console, and the screen.

Before this, a failure inside the game loop went only to the in-editor Debug
Console, which the game (kiosk mode) never shows; a freeze or a broken tick
left nothing behind. Every error now goes three places:

* **the log file**, ``logs/miniwind.log`` (rotated at 2 MB, five kept), with
  its full traceback, the thread it happened on and the time;
* **stderr**, so a console or a launcher's output shows it too;
* **the screen**, as a short notice the UI thread picks up with
  :func:`take_notices` and draws over the game (or as an editor toast).

:func:`configure` sets up the file and installs the hooks that catch what
nothing else does: exceptions escaping a thread (``threading.excepthook``) or
the main loop (``sys.excepthook``), ``traceback.print_exc()`` output written
to stderr anywhere in the code base, and native crashes or fatal errors
(``faulthandler`` into ``logs/crash.log``).

Pure Python; nothing here imports Qt, so the logic and AI threads may call
:func:`report_error` directly. Without :func:`configure` (unit tests, tools)
errors still reach stderr through :mod:`logging`'s last-resort handler and the
notice queue, and nothing is written to disk.
"""

from __future__ import annotations

import collections
import faulthandler
import logging
import logging.handlers
import os
import sys
import threading
import time
import traceback

LOGGER_NAME = "miniwind"
LOG_FILE = "miniwind.log"
CRASH_FILE = "crash.log"
#: Notices of the same text within this many seconds are merged ("×3").
NOTICE_MERGE_SECONDS = 10.0
MAX_NOTICES = 32

logger = logging.getLogger(LOGGER_NAME)

_lock = threading.Lock()
_notices = collections.OrderedDict()   # key -> Notice, oldest first
_state = {"log_path": None, "crash_handle": None, "configured": False,
          "stderr": None}


class Notice:
    """One on-screen error: its text, how many times it happened, when."""

    __slots__ = ("message", "detail", "count", "first", "last", "taken")

    def __init__(self, message, detail):
        self.message = message
        self.detail = detail
        self.count = 1
        self.first = self.last = time.monotonic()
        self.taken = False

    def text(self) -> str:
        times = " (×%d)" % self.count if self.count > 1 else ""
        where = log_path()
        if where:
            try:
                where = os.path.relpath(where)
            except ValueError:  # Windows paths on different drives
                pass
        hint = (" — details in %s" % where) if where else ""
        return "%s%s%s" % (self.message, times, hint)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def format_exception(exc) -> str:
    """The traceback of *exc* (an exception instance), as text."""
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def report_error(message, exc=None, *, trace=None, show=True) -> None:
    """Log *message* as an error, with *exc*'s traceback or *trace*.

    Safe from any thread and never raises: error reporting must not become
    the error.
    """
    try:
        message = str(message).strip() or "Unexpected error"
        detail = trace if trace is not None else (
            format_exception(exc) if isinstance(exc, BaseException) else None)
        repeats = _repeats_to_log(message)
        if repeats is not None:
            suffix = " (and %d more times since last logged)" % repeats if repeats else ""
            if detail:
                logger.error("%s%s\n%s", message, suffix, str(detail).rstrip())
            else:
                logger.error("%s%s", message, suffix)
        if show:
            _push_notice(message, detail)
    except Exception:  # pragma: no cover - last line of defence
        try:
            sys.__stderr__.write("error_report failed while reporting: %r\n" % (message,))
        except Exception:
            pass


#: An error repeating faster than this is logged once per interval, with a
#: count of the repeats, so one fault every tick cannot flood the log.
LOG_REPEAT_SECONDS = 30.0
_logged = {}   # message -> [last logged (monotonic), repeats suppressed since]


def _repeats_to_log(message):
    """None to skip logging *message* now, else how many repeats were held."""
    now = time.monotonic()
    with _lock:
        entry = _logged.get(message)
        if entry is not None and now - entry[0] < LOG_REPEAT_SECONDS:
            entry[1] += 1
            return None
        held = entry[1] if entry is not None else 0
        _logged[message] = [now, 0]
        if len(_logged) > 512:
            for key in list(_logged)[:256]:
                del _logged[key]
        return held


def report_warning(message, *, show=False) -> None:
    """Log a warning; shown on screen only when *show*."""
    try:
        logger.warning("%s", message)
        if show:
            _push_notice(str(message), None)
    except Exception:  # pragma: no cover
        pass


def log_info(message) -> None:
    logger.info("%s", message)


def log_debug(category, message) -> None:
    """A Debug Console line, for the log file at DEBUG level."""
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("[%s] %s", category, message)


#: Debug Console categories that are errors in their own right.
ERROR_CATEGORIES = frozenset(("error", "exception", "fatal", "critical"))


def from_debug_console(category, message) -> None:
    """Route a ``debug_log`` line: errors are reported, the rest is logged.

    A line in an error category, or one that carries a Python traceback, is
    an error whatever subsystem logged it; the first line becomes the on-screen
    notice and the whole of it goes to the log file.
    """
    text = str(message)
    if str(category).lower() in ERROR_CATEGORIES or "Traceback (most recent call last)" in text:
        first = text.strip().splitlines()[0] if text.strip() else str(category)
        headline = "%s: %s" % (category, first) if str(category).lower() not in ERROR_CATEGORIES else first
        report_error(headline, trace=text if "\n" in text else None)
    else:
        log_debug(category, text)


def _push_notice(message, detail) -> None:
    key = message
    now = time.monotonic()
    with _lock:
        notice = _notices.get(key)
        if notice is not None and now - notice.last < NOTICE_MERGE_SECONDS:
            notice.count += 1
            notice.last = now
            notice.taken = False
            _notices.move_to_end(key)
            return
        _notices[key] = Notice(message, detail)
        _notices.move_to_end(key)
        while len(_notices) > MAX_NOTICES:
            _notices.popitem(last=False)


def take_notices():
    """Notices not shown yet (or repeated since), oldest first; for the UI."""
    with _lock:
        fresh = [n for n in _notices.values() if not n.taken]
        for n in fresh:
            n.taken = True
        cutoff = time.monotonic() - NOTICE_MERGE_SECONDS
        for key in [k for k, n in _notices.items() if n.taken and n.last < cutoff]:
            del _notices[key]
    return fresh


def clear_notices() -> None:
    with _lock:
        _notices.clear()


def log_path():
    """The log file being written, or None before :func:`configure`."""
    return _state["log_path"]


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

class _StderrTee:
    """sys.stderr that also feeds the log, and reports tracebacks it sees.

    Code all over the game prints ``traceback.print_exc()`` and carries on.
    That output reaches the console only; teeing stderr puts it in the log
    file too, and a complete traceback becomes an on-screen notice.
    """

    def __init__(self, stream):
        self._stream = stream
        self._line = ""
        self._trace = None
        self._guard = threading.local()

    def write(self, text):
        try:
            self._stream.write(text)
        except Exception:
            pass
        if getattr(self._guard, "busy", False):
            return len(text)
        self._guard.busy = True
        try:
            self._line += text
            while "\n" in self._line:
                line, self._line = self._line.split("\n", 1)
                self._feed(line)
        finally:
            self._guard.busy = False
        return len(text)

    def _feed(self, line):
        if self._trace is not None:
            self._trace.append(line)
            # The exception line closes a traceback: the first unindented
            # line after the header.
            if line and not line.startswith((" ", "\t")) and not line.startswith(
                    ("Traceback (most recent call last)", "During handling",
                     "The above exception")):
                trace, self._trace = "\n".join(self._trace), None
                report_error(line.strip(), trace=trace)
            return
        if line.startswith("Traceback (most recent call last)"):
            self._trace = [line]
            return
        if line.strip():
            _file_only(logging.WARNING, "[stderr] %s" % line)

    @property
    def raw_stream(self):
        """The real stderr, for text already reported another way."""
        return self._stream

    def flush(self):
        try:
            self._stream.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._stream, name)


class _ConsoleFilter(logging.Filter):
    """Keep lines copied from stderr off the console handler (no echo loop)."""

    def filter(self, record):
        return not getattr(record, "file_only", False)


def _file_only(level, message):
    logger.log(level, "%s", message, extra={"file_only": True})


def _session_header():
    try:
        import platform
        version = ""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        vpath = os.path.join(root, "editor", "version.txt")
        if os.path.isfile(vpath):
            with open(vpath, encoding="utf-8") as handle:
                version = handle.read().strip()
        # editor/version.txt is the engine's build ("version 3.5.0.1111"),
        # not the game's: say so, so a log never reads as a game version.
        engine = version.replace("version", "", 1).strip() if version else ""
        return "MiniWind on Fio engine %s — Python %s on %s" % (
            engine or "(unknown version)", platform.python_version(), platform.platform())
    except Exception:
        return "MiniWind session"


def _user_log_dir():
    """A writable per-user fallback for read-only application installs."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/AppData/Local")
        return os.path.join(base, "MiniWind", "logs")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Logs/MiniWind")
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "miniwind", "logs")


def configure(log_dir=None, *, level=None, console=True, tee_stderr=True,
              hooks=True) -> str | None:
    """Start logging to ``<log_dir>/miniwind.log``; returns the file's path.

    ``$MINIWIND_LOG_DIR`` overrides *log_dir*, which defaults to ``logs/``
    beside the game.
    *level* (or ``$MINIWIND_LOG_LEVEL``) sets what the file keeps: INFO by
    default, DEBUG to include every Debug Console line. Calling it again only
    returns the path. Read-only installs fall back to the user's log directory;
    if neither is writable, console and on-screen reporting remain available
    and the returned path is None.
    """
    if _state["configured"]:
        return _state["log_path"]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # The environment wins over the caller's default, so a player or tester
    # can always move the logs (MINIWIND_LOG_DIR).
    log_dir = os.environ.get("MINIWIND_LOG_DIR") or log_dir or os.path.join(root, "logs")
    level_name = (level or os.environ.get("MINIWIND_LOG_LEVEL") or "INFO").upper()
    handler = None
    path = None
    failures = []
    for directory in dict.fromkeys((os.path.abspath(log_dir), _user_log_dir())):
        try:
            os.makedirs(directory, exist_ok=True)
            candidate = os.path.join(directory, LOG_FILE)
            handler = logging.handlers.RotatingFileHandler(
                candidate, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
        except OSError as exc:
            failures.append("%s: %s" % (directory, exc))
            continue
        path, log_dir = candidate, directory
        break

    logger.setLevel(getattr(logging, level_name, logging.INFO))
    logger.propagate = False
    if handler is not None:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s [%(threadName)s] %(message)s"))
        logger.addHandler(handler)
    if console:
        stream = logging.StreamHandler(sys.__stderr__ or sys.stderr)
        stream.setLevel(logging.WARNING)
        stream.addFilter(_ConsoleFilter())
        stream.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        logger.addHandler(stream)
    _state["log_path"] = path
    _state["configured"] = True
    logger.info("%s", "=" * 20 + " " + _session_header() + " " + "=" * 20)

    if hooks:
        _install_hooks(log_dir if path else None)
    if tee_stderr and not isinstance(sys.stderr, _StderrTee) and sys.stderr is not None:
        _state["stderr"] = sys.stderr
        sys.stderr = _StderrTee(sys.stderr)
    if failures:
        if path:
            report_warning("Could not use the requested log directory; logging to %s. %s"
                           % (path, "; ".join(failures)))
        else:
            report_warning("Log files are unavailable; errors will still appear on screen. %s"
                           % "; ".join(failures), show=True)
    return path


def _install_hooks(log_dir):
    previous_sys_hook = sys.excepthook

    def sys_hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            previous_sys_hook(exc_type, exc, tb)
            return
        report_error("Unhandled exception: %s" % (exc,) if str(exc) else exc_type.__name__,
                     trace="".join(traceback.format_exception(exc_type, exc, tb)))

    sys.excepthook = sys_hook

    def thread_hook(args):
        if args.exc_type is SystemExit:
            return
        name = getattr(args.thread, "name", "thread")
        report_error("%s crashed: %s" % (name, args.exc_value),
                     trace="".join(traceback.format_exception(
                         args.exc_type, args.exc_value, args.exc_traceback)))

    threading.excepthook = thread_hook
    if log_dir is None:
        return
    try:
        handle = open(os.path.join(log_dir, CRASH_FILE), "a", encoding="utf-8")
        handle.write("\n==== %s %s ====\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), _session_header()))
        handle.flush()
        faulthandler.enable(file=handle, all_threads=True)
        _state["crash_handle"] = handle
    except OSError:
        pass


def crash_file():
    """The open ``crash.log`` handle (faulthandler's), or None."""
    return _state["crash_handle"]
