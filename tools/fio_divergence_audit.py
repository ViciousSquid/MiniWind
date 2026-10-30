"""
Audit how MiniWind's copied Fio trees differ from an upstream Fio checkout.

    git clone https://github.com/ViciousSquid/Fio.git ../Fio
    python tools/fio_divergence_audit.py ../Fio
    python tools/fio_divergence_audit.py ../Fio --json audit.json

Compares ``engine/``, ``editor/`` and ``plugins/`` (and the shared top-level
files) file by file. For every file that differs, the Fio history is searched
for the revision closest to MiniWind's copy -- the *fork point* -- so the
difference splits into what MiniWind changed locally and what Fio changed
upstream since:

* ``stale``      MiniWind's copy is an exact old Fio revision; take upstream.
* ``local``      only MiniWind changed it; upstream it, or move it into game/.
* ``two-way``    both sides changed it; reconcile by hand.

A ``local`` file whose MiniWind side is mostly removals (``-`` far above
``+``) often lacks newer Fio work rather than carrying a deliberate change:
treat it as two-way until the removed lines are explained.

The two repositories share no Git history, so the fork point is a per-file
estimate (fewest changed lines). The Fio checkout needs its full history
(not a shallow clone). Run from the MiniWind root; read-only on both sides.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import subprocess
import sys

TREES = ("engine", "editor", "plugins")
TOP_LEVEL = ("main.py", "python_runtime.py", "editor_styles.py", "clean.py",
             "conftest.py", "pytest.ini", "requirements.txt", "settings.ini",
             "Dockerfile", "docker-compose.yml")


def _git(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, errors="replace").stdout


def _tracked(cwd, tree) -> set[str]:
    return set(_git(cwd, "ls-files", "--", tree).splitlines())


def _read(path) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def line_changes(a: list[str], b: list[str]) -> tuple[int, int]:
    """(added, removed) lines turning *a* into *b*."""
    added = removed = 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, a, b, autojunk=False).get_opcodes():
        if op != "equal":
            added += j2 - j1
            removed += i2 - i1
    return added, removed


def changed_lines(a: list[str], b: list[str]) -> int:
    """Lines touched turning *a* into *b* (a replaced block counts its larger side)."""
    n = 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, a, b, autojunk=False).get_opcodes():
        if op != "equal":
            n += max(i2 - i1, j2 - j1)
    return n


def fork_point(fio, path, mine: list[str]):
    """The Fio revision of *path* closest to *mine*: (lines, sha, date, text)."""
    best = None
    for rec in _git(fio, "log", "--format=%H %ad", "--date=short",
                    "--", path).splitlines():
        sha, date = rec.split()
        text = _git(fio, "show", f"{sha}:{path}")
        if not text:
            continue
        lines = text.splitlines()
        d = changed_lines(lines, mine)
        if best is None or d < best[0]:
            best = (d, sha[:9], date, lines)
        if d == 0:
            break
    return best


def audit(mw, fio) -> dict:
    files, only_mw, only_fio = [], [], []
    for tree in TREES:
        ours, theirs = _tracked(mw, tree), _tracked(fio, tree)
        only_mw += sorted(ours - theirs)
        only_fio += sorted(theirs - ours)
        for path in sorted(ours & theirs):
            mine = _read(os.path.join(mw, path))
            head = _read(os.path.join(fio, path))
            if mine == head:
                continue
            mine_l, head_l = mine.splitlines(), head.splitlines()
            best = fork_point(fio, path, mine_l)
            if best is None:
                local, sha, date, base = changed_lines(head_l, mine_l), "", "", head_l
            else:
                local, sha, date, base = best
            upstream = changed_lines(base, head_l)
            added, removed = line_changes(base, mine_l)
            kind = ("stale" if local == 0 else
                    "local" if upstream == 0 else "two-way")
            files.append(dict(path=path, kind=kind, fork_commit=sha,
                              fork_date=date, mw_local=local,
                              mw_added=added, mw_removed=removed,
                              upstream_since=upstream))
    top = {p: _read(os.path.join(mw, p)) == _read(os.path.join(fio, p))
           for p in TOP_LEVEL}
    return dict(fio_head=_git(fio, "rev-parse", "HEAD").strip(),
                fio_branch=_git(fio, "rev-parse", "--abbrev-ref", "HEAD").strip(),
                miniwind_head=_git(mw, "rev-parse", "HEAD").strip(),
                differing=files, only_miniwind=only_mw, only_fio=only_fio,
                top_level_identical=top)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("fio", help="path to a full-history Fio checkout")
    parser.add_argument("--json", help="also write the result to this file")
    args = parser.parse_args(argv)
    if not os.path.isdir(os.path.join(args.fio, ".git")):
        print(f"not a Git checkout: {args.fio}")
        return 1
    if _git(args.fio, "rev-parse", "--is-shallow-repository").strip() == "true":
        print("the Fio checkout is shallow; run `git fetch --unshallow` there first")
        return 1
    result = audit(os.getcwd(), args.fio)
    print(f"Fio {result['fio_branch']} @ {result['fio_head'][:9]}  "
          f"MiniWind @ {result['miniwind_head'][:9]}")
    for kind in ("stale", "local", "two-way"):
        rows = [r for r in result["differing"] if r["kind"] == kind]
        print(f"\n{kind} ({len(rows)})")
        for r in rows:
            print(f"  {r['path']:58} {r['fork_commit']} {r['fork_date']}  "
                  f"local=+{r['mw_added']}/-{r['mw_removed']:<4} "
                  f"upstream={r['upstream_since']}")
    for label, paths in (("only in MiniWind", result["only_miniwind"]),
                         ("only in Fio", result["only_fio"])):
        print(f"\n{label} ({len(paths)})")
        for p in paths:
            print(f"  {p}")
    print("\ntop-level files")
    for p, same in result["top_level_identical"].items():
        print(f"  {'same' if same else 'DIFF'}  {p}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
