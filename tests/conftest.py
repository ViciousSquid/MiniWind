"""MiniWind's collection rules for Fio's test suite.

MiniWind ships Fio's tests as its engine's acceptance suite, but not all of
Fio's *content*: its example and fixture maps (MiniWind ships only its own
village; plain Fio maps sit behind Settings > Editor > Allow Fio maps) and
the Tidy plugin are not in this repository. A Fio test that loads one of
them is skipped here, with the reason shown, instead of failing on a missing
file; the test files themselves are Fio's, unchanged.

A test is skipped only when its own code, its parameters, a fixture or helper
defined in its module, or the short list in ``_NEEDS`` ties it to content
that is absent from this tree.
"""

import inspect
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Fio content MiniWind does not ship, as the strings Fio's tests use for it.
#: Each is (token found in test code, path that would have to exist).
_FIO_CONTENT = [(name, os.path.join("maps", name)) for name in (
    "_SHOWCASE.json", "DevTest.json", "MonsterTest.json", "Portal_Test.json",
    "Simple_Map_Test.json", "Spawner_Test.json", "Terrain_Test_small.json",
    "Terrain_Test_medium.json", "BigWorld_streaming_test.json",
)] + [
    ("plugins.tidy", os.path.join("plugins", "tidy")),
    ("plugins/tidy", os.path.join("plugins", "tidy")),
    ("Tidy_Test.json", os.path.join("plugins", "tidy", "Tidy_Test.json")),
    ("tidyreceptacle", os.path.join("plugins", "tidy")),
    ("TidyReceptacle", os.path.join("plugins", "tidy")),
    ('"tidy", "assets"', os.path.join("plugins", "tidy")),
    ('== "tidy"', os.path.join("plugins", "tidy")),
]

#: Fio tests that rely on Tidy without naming it: they assert the "Reset"
#: input Tidy's plugin adds to every prop.
_NEEDS = {
    "test_replaying_an_extension_keeps_the_core_declarations":
        os.path.join("plugins", "tidy"),
}

_MISSING = [(token, path) for token, path in _FIO_CONTENT
            if not os.path.exists(os.path.join(ROOT, path))]


def _source(obj):
    try:
        return inspect.getsource(obj)
    except (OSError, TypeError):
        return ""


def _test_text(item):
    func = getattr(item, "function", None)
    parts = [_source(func)] if func is not None else []
    callspec = getattr(item, "callspec", None)
    if callspec is not None:
        parts.append(repr(callspec.params))
    module = getattr(item, "module", None)
    names = set(getattr(item, "fixturenames", ()))
    names.update(re.findall(r"\b(_\w+)\(", parts[0] if parts else ""))
    for name in names:
        helper = getattr(module, name, None)
        if callable(helper):
            parts.append(_source(getattr(helper, "__wrapped__", helper)))
    return "\n".join(parts)


def pytest_collection_modifyitems(config, items):
    if not _MISSING:
        return
    for item in items:
        need = _NEEDS.get(getattr(item, "originalname", item.name))
        if need and not os.path.exists(os.path.join(ROOT, need)):
            item.add_marker(pytest.mark.skip(
                reason=f"Fio content MiniWind does not ship: {need}"))
            continue
        text = _test_text(item)
        for token, path in _MISSING:
            if token in text:
                item.add_marker(pytest.mark.skip(
                    reason=f"Fio content MiniWind does not ship: {path}"))
                break
