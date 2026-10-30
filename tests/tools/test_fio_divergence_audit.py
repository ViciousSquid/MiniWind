"""The Fio divergence audit sorts copied files by who changed them."""

import shutil
import subprocess

import pytest

from tools.fio_divergence_audit import audit

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    *args], cwd=cwd, check=True, capture_output=True)


def _write(root, path, text):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def _commit(root, files, message):
    for path, text in files.items():
        _write(root, path, text)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)


@pytest.fixture
def repos(tmp_path):
    fio, mw = tmp_path / "fio", tmp_path / "mw"
    for root in (fio, mw):
        root.mkdir()
        _git(root, "init", "-q")
    base = {
        "engine/same.py": "a\nb\n",
        "engine/stale.py": "one\n",
        "engine/local.py": "x\ny\n",
        "engine/both.py": "p\nq\nr\n",
        "editor/gone.py": "old\n",
    }
    _commit(fio, base, "fork")
    _commit(fio, {"engine/stale.py": "one\ntwo\n",
                  "engine/both.py": "p\nq\nr\nupstream\n",
                  "engine/fio_only.py": "new\n"}, "upstream work")
    mine = dict(base)
    mine.update({"engine/local.py": "x\ny\nmine\n",
                 "engine/both.py": "p\nmine\nr\n",
                 "engine/mw_only.py": "game\n"})
    _commit(mw, mine, "copy")
    return mw, fio


def test_files_are_sorted_by_who_changed_them(repos):
    mw, fio = repos
    result = audit(str(mw), str(fio))
    kinds = {r["path"]: r["kind"] for r in result["differing"]}
    assert kinds == {"engine/stale.py": "stale",
                     "engine/local.py": "local",
                     "engine/both.py": "two-way"}
    assert result["only_miniwind"] == ["engine/mw_only.py"]
    assert result["only_fio"] == ["engine/fio_only.py"]


def test_local_changes_are_measured_from_the_fork_point(repos):
    mw, fio = repos
    rows = {r["path"]: r for r in audit(str(mw), str(fio))["differing"]}
    assert (rows["engine/local.py"]["mw_added"],
            rows["engine/local.py"]["mw_removed"]) == (1, 0)
    assert rows["engine/stale.py"]["upstream_since"] == 1
    assert rows["engine/both.py"]["upstream_since"] == 1
