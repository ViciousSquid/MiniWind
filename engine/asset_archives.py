"""
``.fiopak`` data packages, mounted as one read-only file system -- the way
Quake 3 treats its PK3s.

A package is a plain ZIP. Every ``*.fiopak`` in the project root or in
``assets/`` is mounted when first needed, its members are indexed by path,
and a file is *streamed* out of its package when something reads it: nothing
is ever extracted to disk. As with PK3s, packages are searched in name order
and a later name overrides an earlier one, so ``pak0.fiopak`` < ``pak1.fiopak``
< ``zz_mymod.fiopak``: shipping a patch or a mod is dropping a package in.

A ``.fiopak`` is an ordinary ZIP whose members keep their project-relative
paths (``assets/sounds/arrest1.mp3``, ``assets/textures/Stone_09.png``).
Any number of them can sit in ``assets/`` -- ``sounds.fiopak``,
``sounds2.fiopak``, ``textures_common.fiopak``, ``textures_desert.fiopak``
-- so content can be split cleanly by kind, region or mod. All are mounted
together and indexed by member path:

* **Archives before loose files.** :func:`read` / :func:`exists` look in the
  archives first and fall back to the loose file on disk, so a project can
  ship packed assets and still let an author drop a loose file in to try
  something.
* **Later archives override earlier ones**, in name order: a member in
  ``sounds2.fiopak`` replaces the same path in ``sounds.fiopak``, which is
  how a patch or a mod pack overrides shipped content without touching it.
* Nothing is extracted. The index is built once (and rebuilt when an
  archive appears, disappears or changes); a read opens the one member it
  needs.

Paths are always the forward-slash, project-relative form
(``assets/textures/foo.png``); Windows separators are normalised. Members
that try to escape (``..``, absolute paths, backslashes) are ignored.
"""

from __future__ import annotations

import glob
import os
import threading
import zipfile
from typing import Dict, List, Optional, Tuple

#: Where packages are found, relative to the working directory.
ASSET_DIR = "assets"
SEARCH_DIRS = (".", ASSET_DIR)
ARCHIVE_GLOB = "*.fiopak"

_lock = threading.Lock()
_index: Dict[str, str] = {}             # member path -> archive path
_signature: Tuple = ()
_checked = 0.0
#: How often (s) to look for archives that appeared, vanished or changed.
RECHECK_SECONDS = 2.0


def normalise(path: str) -> str:
    """``assets/textures/foo.png`` from any spelling of a project path."""
    p = str(path or "").replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    cwd = os.getcwd().replace("\\", "/").rstrip("/") + "/"
    if p.startswith(cwd):
        p = p[len(cwd):]
    return p.lstrip("/")


def _safe(member: str) -> bool:
    if not member or "\\" in member or member.startswith("/") or member.endswith("/"):
        return False
    return not any(part in ("", ".", "..") for part in member.split("/"))


def archives() -> List[str]:
    """Every mounted package, in mount order: by file name, wherever it sits,
    so a later name overrides an earlier one (PK3 order)."""
    found = []
    for folder in SEARCH_DIRS:
        found.extend(glob.glob(os.path.join(folder, ARCHIVE_GLOB)))
    return sorted(set(os.path.normpath(p) for p in found),
                  key=lambda p: (os.path.basename(p).casefold(), p))


def _current_signature() -> Tuple:
    sig = []
    for path in archives():
        try:
            st = os.stat(path)
        except OSError:
            continue
        sig.append((path, st.st_size, st.st_mtime_ns))
    return tuple(sig)


def _ensure_index() -> Dict[str, str]:
    global _index, _signature, _checked
    import time
    now = time.monotonic()
    if _signature and now - _checked < RECHECK_SECONDS:
        return _index
    _checked = now
    sig = _current_signature()
    if sig == _signature:
        return _index
    with _lock:
        if sig == _signature:
            return _index
        index: Dict[str, str] = {}
        for path, _size, _mtime in sig:
            try:
                with zipfile.ZipFile(path, "r") as z:
                    for info in z.infolist():
                        if info.is_dir() or not _safe(info.filename):
                            continue
                        index[info.filename] = path      # later archives win
            except (OSError, zipfile.BadZipFile) as exc:
                print(f"[Assets] Cannot read {os.path.basename(path)}: {exc}")
        _index = index
        _signature = sig
        return index


def refresh() -> None:
    """Forget the index (a test, or an archive written while running)."""
    global _signature, _checked
    with _lock:
        _signature = ()
        _checked = 0.0


def archive_of(path: str) -> Optional[str]:
    """The archive that serves *path*, or None (loose or missing)."""
    return _ensure_index().get(normalise(path))


def in_archive(path: str) -> bool:
    return archive_of(path) is not None


def exists(path: str) -> bool:
    """Whether *path* can be read: from an archive, or loose on disk."""
    p = normalise(path)
    return p in _ensure_index() or os.path.isfile(p)


def read(path: str) -> Optional[bytes]:
    """The bytes of *path*: from the archive that holds it, else the loose
    file, else None."""
    p = normalise(path)
    archive = _ensure_index().get(p)
    if archive is not None:
        try:
            with zipfile.ZipFile(archive, "r") as z:
                return z.read(p)
        except (OSError, KeyError, zipfile.BadZipFile) as exc:
            print(f"[Assets] Cannot read {p} from {os.path.basename(archive)}: {exc}")
    if os.path.isfile(p):
        try:
            with open(p, "rb") as f:
                return f.read()
        except OSError:
            return None
    return None


def members(prefix: str, extensions: Tuple[str, ...] = ()) -> List[str]:
    """Every archived path under *prefix* (``assets/sounds/``), optionally
    only those ending in *extensions*; sorted."""
    pre = normalise(prefix).rstrip("/") + "/"
    exts = tuple(e.lower() for e in extensions)
    out = [m for m in _ensure_index() if m.startswith(pre)
           and (not exts or m.lower().endswith(exts))]
    return sorted(out, key=str.casefold)


def listing(prefix: str, extensions: Tuple[str, ...] = ()) -> List[str]:
    """Archived *and* loose paths under *prefix*, archives first, no repeats."""
    seen = set(members(prefix, extensions))
    out = list(seen)
    root = normalise(prefix).rstrip("/")
    exts = tuple(e.lower() for e in extensions)
    if os.path.isdir(root):
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                rel = normalise(os.path.join(dirpath, name))
                if rel in seen or (exts and not rel.lower().endswith(exts)):
                    continue
                seen.add(rel)
                out.append(rel)
    return sorted(out, key=str.casefold)


def pack(source_dir: str, archive_path: str) -> int:
    """Write every file under *source_dir* into *archive_path* with its
    project-relative path. Returns how many files were packed."""
    n = 0
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, _dirs, files in os.walk(source_dir):
            for name in sorted(files):
                full = os.path.join(dirpath, name)
                rel = normalise(full)
                if not _safe(rel):
                    continue
                # Already-compressed formats gain nothing from deflate.
                method = (zipfile.ZIP_STORED if name.lower().endswith(
                    (".png", ".jpg", ".jpeg", ".gif", ".mp3", ".ogg", ".avif"))
                    else zipfile.ZIP_DEFLATED)
                z.write(full, rel, compress_type=method)
                n += 1
    refresh()
    return n
