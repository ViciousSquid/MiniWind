"""Errors reach the log file, the console and the screen (engine/error_report)."""

import io
import logging
import sys
import threading

import pytest

from engine import error_report


@pytest.fixture
def report(tmp_path, monkeypatch):
    """A configured reporter writing into *tmp_path*, undone afterwards."""
    saved_hooks = (sys.excepthook, threading.excepthook, sys.stderr)
    handlers = list(error_report.logger.handlers)
    monkeypatch.setitem(error_report._state, "configured", False)
    monkeypatch.setitem(error_report._state, "log_path", None)
    monkeypatch.setitem(error_report._state, "crash_handle", None)
    error_report.clear_notices()
    error_report._logged.clear()
    console = io.StringIO()
    monkeypatch.setattr(sys, "stderr", console)
    path = error_report.configure(str(tmp_path), hooks=True, tee_stderr=True)
    yield path, console
    for handler in list(error_report.logger.handlers):
        if handler not in handlers:
            error_report.logger.removeHandler(handler)
            handler.close()
    handle = error_report._state.get("crash_handle")
    if handle is not None:
        import faulthandler
        faulthandler.disable()
        handle.close()
    sys.excepthook, threading.excepthook, sys.stderr = saved_hooks
    error_report.clear_notices()


def _log_text(path):
    for handler in error_report.logger.handlers:
        handler.flush()
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def test_an_error_is_logged_with_its_traceback_and_queued_for_the_screen(report):
    path, _console = report
    try:
        raise ValueError("bad tick")
    except ValueError as exc:
        error_report.report_error("Simulation tick failed", exc)
    text = _log_text(path)
    assert "Simulation tick failed" in text and "ValueError: bad tick" in text
    notices = error_report.take_notices()
    assert [n.message for n in notices] == ["Simulation tick failed"]
    assert "miniwind.log" in notices[0].text()
    assert error_report.take_notices() == [], "a notice is shown once"


def test_repeats_merge_on_screen_and_are_not_logged_every_time(report):
    path, _console = report
    for _ in range(50):
        error_report.report_error("Frame could not be prepared", trace="Traceback...\nKeyError: 3")
    notices = error_report.take_notices()
    assert len(notices) == 1 and notices[0].count == 50
    assert "(×50)" in notices[0].text()
    assert _log_text(path).count("Frame could not be prepared") == 1


def test_debug_console_errors_and_tracebacks_are_reported(report):
    path, _console = report
    error_report.from_debug_console("IO", "Speaker.OnSoundStarted (no connections)")
    error_report.from_debug_console(
        "MonsterAI", "Unhandled exception in update:\nTraceback (most recent call last):\n"
        "  File \"x.py\", line 1\nZeroDivisionError: division by zero")
    error_report.from_debug_console("Error", "I/O target missing")
    messages = [n.message for n in error_report.take_notices()]
    assert messages == ["MonsterAI: Unhandled exception in update:", "I/O target missing"]
    text = _log_text(path)
    assert "ZeroDivisionError" in text and "no connections" not in text


def test_print_exc_output_is_logged_and_shown(report, monkeypatch):
    path, _ = report
    console = io.StringIO()
    # pytest swaps sys.stderr per test phase; tee it here, as configure does.
    monkeypatch.setattr(sys, "stderr", error_report._StderrTee(console))
    try:
        {}["missing"]
    except KeyError:
        import traceback
        traceback.print_exc()
    print("plain stderr note", file=sys.stderr)
    assert "KeyError" in console.getvalue(), "stderr still reaches the console"
    messages = [n.message for n in error_report.take_notices()]
    assert messages == ["KeyError: 'missing'"]
    text = _log_text(path)
    assert "KeyError: 'missing'" in text and "plain stderr note" in text


def test_an_exception_escaping_a_thread_is_reported(report):
    path, _console = report

    def boom():
        raise RuntimeError("worker died")

    worker = threading.Thread(target=boom, name="WorkerX")
    worker.start()
    worker.join()
    messages = [n.message for n in error_report.take_notices()]
    assert messages == ["WorkerX crashed: worker died"]
    assert "RuntimeError: worker died" in _log_text(path)


def test_reporting_without_configure_still_logs_and_queues(monkeypatch, caplog):
    """Unconfigured (tools, tests), errors go through logging's own handlers
    (its last-resort stderr handler outside pytest) and still reach the screen."""
    monkeypatch.setitem(error_report._state, "configured", False)
    error_report._logged.clear()
    error_report.clear_notices()
    monkeypatch.setattr(error_report.logger, "handlers", [])
    monkeypatch.setattr(error_report.logger, "propagate", True)
    with caplog.at_level(logging.ERROR, logger=error_report.LOGGER_NAME):
        error_report.report_error("unconfigured failure")
    assert "unconfigured failure" in caplog.text
    assert [n.message for n in error_report.take_notices()] == ["unconfigured failure"]


def test_the_environment_moves_the_logs(tmp_path, monkeypatch):
    """MINIWIND_LOG_DIR wins over the directory the game passes in."""
    monkeypatch.setitem(error_report._state, "configured", False)
    monkeypatch.setitem(error_report._state, "log_path", None)
    monkeypatch.setenv("MINIWIND_LOG_DIR", str(tmp_path / "elsewhere"))
    handlers = list(error_report.logger.handlers)
    try:
        path = error_report.configure(str(tmp_path / "default"), hooks=False,
                                      tee_stderr=False, console=False)
        assert path == str(tmp_path / "elsewhere" / "miniwind.log")
    finally:
        for handler in list(error_report.logger.handlers):
            if handler not in handlers:
                error_report.logger.removeHandler(handler)
                handler.close()


def test_a_read_only_installation_uses_a_writable_log_directory(report, tmp_path, monkeypatch):
    from pathlib import Path
    import os

    blocked = tmp_path / "installation" / "logs"
    fallback = tmp_path / "user-logs"
    real_makedirs = os.makedirs

    def makedirs(path, *args, **kwargs):
        if Path(path) == blocked:
            raise PermissionError("the installation is read-only")
        return real_makedirs(path, *args, **kwargs)

    monkeypatch.setattr(os, "makedirs", makedirs)
    monkeypatch.setattr(error_report, "_user_log_dir", lambda: str(fallback), raising=False)
    monkeypatch.setitem(error_report._state, "configured", False)
    path = error_report.configure(str(blocked), hooks=False, tee_stderr=False)
    error_report.report_error("startup still works")
    assert Path(path).parent == fallback
    assert "startup still works" in _log_text(path)


def test_unavailable_log_directories_do_not_prevent_startup(report, monkeypatch):
    import os

    def unavailable(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(os, "makedirs", unavailable)
    monkeypatch.setitem(error_report._state, "configured", False)
    assert error_report.configure(hooks=True, tee_stderr=False) is None
    error_report.report_error("visible without a file")
    assert any(n.message == "visible without a file" for n in error_report.take_notices())


def test_an_error_banner_can_link_to_logs_on_another_windows_drive(monkeypatch):
    import ntpath

    path = r"D:\logs\miniwind.log"
    monkeypatch.setitem(error_report._state, "log_path", path)
    monkeypatch.setattr(error_report.os.path, "relpath",
                        lambda value: ntpath.relpath(value, r"C:\MiniWind"))
    assert path in error_report.Notice("bad tick", None).text()
