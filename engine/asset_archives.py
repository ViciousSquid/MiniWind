"""Category .fiopak asset archives, read in place, with loose-file overrides.

``assets/<category>.fiopak`` (``editor``, ``sprites``, ``textures``,
``models``, ``fonts``, ``music``, ``sounds``) holds members under their
project-relative paths (``assets/textures/Dev/256.jpg``). Nothing is
extracted: :func:`prepare_asset_archives` indexes each archive once, and a
loader asks for an asset by the path it always used --
:func:`asset_bytes`, :func:`asset_source` (a path or an in-memory file for
Pillow), :func:`asset_exists`, :func:`asset_listdir`, :func:`asset_files`;
Qt images, icons and fonts through :mod:`engine.asset_qt`. A loose file at
that path still wins (a development override), and a member is also found
by a case-insensitive match, as a Windows file system would. Audio keeps
its streaming reader (:mod:`engine.audio_archives`). Archives are opened per
read, never held open: a repack (``tools/pack_assets.py``) can replace one
while the editor runs, and the next read sees it.

MiniWind also mounts *every* ``*.fiopak`` in the project root and ``assets/``
as data packages (the second half of this module: :func:`read`,
:func:`exists`, :func:`in_archive`, :func:`members`, :func:`listing`,
:func:`pack`), searched in name order with later names overriding earlier
ones. Those calls look in the packages first and fall back to the loose
file; the ``asset_*`` loaders above look at the loose file first, then the
category archives, a played package, and last any mounted data package, so
an asset shipped only in ``textures_desert.fiopak`` still loads.
"""

from __future__ import annotations

import os
from pathlib import Path
import io
import stat
import threading
import zipfile


# Root images belong to the editor; everything else has its own directory.
ASSET_CATEGORIES = ('editor', 'sprites', 'textures', 'models', 'fonts',
                    'music', 'sounds')
_ROOT_IMAGES = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.icns',
                '.ppm', '.pbm', '.pgm', '.pnm'}
_DATA_SUFFIXES = _ROOT_IMAGES | {
    '.webp', '.tga', '.tif', '.tiff', '.dds', '.ktx', '.ktx2',
    '.ttf', '.otf', '.obj', '.mtl', '.glb', '.gltf', '.bin',
    '.json', '.txt', '.md', '.wav', '.ogg', '.mp3',
}
MAX_ENTRY_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_ENTRIES = 10000


def category_member(member: str, category: str) -> bool:
    """Safe data-only project-relative member in exactly one category."""
    parts = member.split('/')
    if '\\' in member or any(p in ('', '.', '..') or ':' in p for p in parts):
        return False
    if not parts or parts[0] != 'assets':
        return False
    suffix = Path(member).suffix.lower()
    if category == 'textures' and member == 'assets/noise_3d.bin':
        return True
    if category == 'editor':
        return len(parts) == 2 and suffix in _ROOT_IMAGES
    return (category in ASSET_CATEGORIES and len(parts) >= 3
            and parts[1] == category
            and (suffix in _DATA_SUFFIXES or not suffix))


def _entries(archive, category):
    infos = [info for info in archive.infolist() if not info.is_dir()]
    if len(infos) > MAX_ENTRIES:
        raise ValueError('too many asset entries')
    total = 0
    names = set()
    for info in infos:
        if not category_member(info.filename, category):
            raise ValueError(f'invalid {category} asset path: {info.filename!r}')
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ValueError('asset archive contains a symbolic link')
        if info.filename in names:
            raise ValueError('asset archive contains duplicate members')
        names.add(info.filename)
        if info.file_size > MAX_ENTRY_BYTES:
            raise ValueError('asset entry exceeds size limit')
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise ValueError('asset archive exceeds total size limit')
    return infos


class _Archive:
    """One category archive's index: its members, and their folded names."""

    __slots__ = ('path', 'signature', 'members', 'folded', 'dirs')

    def __init__(self, path, signature, infos):
        self.path = path
        self.signature = signature
        self.members = {info.filename: info for info in infos}
        self.folded = {name.casefold(): name for name in self.members}
        dirs = set()
        for name in self.members:
            parts = name.split('/')
            for depth in range(1, len(parts)):
                dirs.add('/'.join(parts[:depth]))
        self.dirs = dirs


_lock = threading.Lock()
_state = {'root': None, 'archives': {}, 'package': None}


def set_package(path, names=()):
    """Serve a played game package's ``assets/...`` members (read in place,
    see ``editor/package_session.py``) after the loose files and the
    category archives; ``None`` ends it."""
    with _lock:
        if path is None:
            _state['package'] = None
        else:
            members = {n: n for n in names if n.startswith('assets/')}
            _state['package'] = (os.fspath(path), members,
                                 {n.casefold(): n for n in members})


def prepare_asset_archives(root_dir) -> tuple[str, ...]:
    """Index *root_dir*'s ``assets/*.fiopak``; write nothing.

    Called before the splash and icons and by MainWindow for alternative
    hosts. Repeated calls only stat the archives unless one changed. A bad
    archive is reported and ignored, so a working loose-file installation
    can still start. Returns the categories that have an archive.
    """
    root = Path(root_dir).resolve()
    assets = root / 'assets'
    found = tuple(c for c in ASSET_CATEGORIES
                  if (assets / f'{c}.fiopak').is_file())
    with _lock:
        if _state['root'] != root:
            _state['root'] = root
            _state['archives'] = {}
        archives = _state['archives']
        for category in list(archives):
            if category not in found:
                del archives[category]
        for category in found:
            _index(archives, category, assets / f'{category}.fiopak')
    return found


def _index(archives, category, path):
    """(Re)index *category*'s archive at *path* when it is new or changed."""
    try:
        stamp = path.stat()
        signature = (stamp.st_mtime_ns, stamp.st_size)
        held = archives.get(category)
        if held is not None and held.signature == signature:
            return held
        with zipfile.ZipFile(path) as archive:
            infos = _entries(archive, category)
        archives[category] = held = _Archive(path, signature, infos)
        return held
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        archives.pop(category, None)
        print(f'[Assets] Cannot read {path.name}: {exc}')
        return None


def _root():
    root = _state['root']
    if root is None:
        prepare_asset_archives(os.getcwd())
        root = _state['root']
    return root


def asset_member(path):
    """The archive member name (``assets/...``) of *path* -- absolute, or
    relative to the working directory, as ``open`` reads it -- or None when
    it is not inside the project's ``assets`` folder."""
    root = _root()
    try:
        rel = os.path.relpath(os.path.abspath(os.fspath(path)), root)
    except ValueError:                      # another drive (Windows)
        return None
    rel = rel.replace(os.sep, '/')
    if rel == 'assets' or not rel.startswith('assets/'):
        return None
    return rel


def _find(member):
    """``(archive, info)`` holding *member* (exact, then case-insensitive)."""
    if member is None:
        return None, None
    with _lock:
        archives = list(_state['archives'].items())
    for category, archive in archives:
        info = archive.members.get(member)
        if info is None:
            name = archive.folded.get(member.casefold())
            info = archive.members.get(name) if name is not None else None
        if info is not None:
            return (category, archive), info
    package = _state['package']
    if package is not None:
        path, members, folded = package
        name = members.get(member) or folded.get(member.casefold())
        if name is not None:
            return ('package', path), name
    mounted = _ensure_index().get(member)
    if mounted is not None:
        return ('mount', mounted), member
    return None, None


def _read(found, info):
    (category, archive) = found
    if category in ('package', 'mount'):
        with zipfile.ZipFile(archive) as handle:
            return handle.read(info)
    # Opened per read: never held, so a repack can replace the file. A
    # changed archive is re-indexed first (its members may have moved).
    with _lock:
        current = _index(_state['archives'], category, archive.path)
    if current is not archive:
        if current is None:
            return None
        info = current.members.get(info.filename)
        if info is None:
            return None
        archive = current
    with zipfile.ZipFile(archive.path) as handle:
        return handle.read(info)


def asset_bytes(path):
    """The bytes of the asset at *path*: the loose file if there is one,
    else the archive member, else None."""
    full = os.fspath(path)
    if os.path.isfile(full):
        with open(full, 'rb') as handle:
            return handle.read()
    found, info = _find(asset_member(full))
    if found is None:
        return None
    try:
        return _read(found, info)
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError, KeyError) as exc:
        print(f'[Assets] Cannot read {getattr(info, "filename", info)}: {exc}')
        return None


def asset_source(path):
    """What a loader that takes a path or a file object (Pillow) opens:
    *path* itself when it is a loose file, an in-memory file of the archive
    member otherwise, None when the asset is in neither."""
    full = os.fspath(path)
    if os.path.isfile(full):
        return full
    data = asset_bytes(full)
    return None if data is None else io.BytesIO(data)


def asset_exists(path) -> bool:
    """Whether *path* names an asset file, loose or archived."""
    full = os.fspath(path)
    return os.path.isfile(full) or _find(asset_member(full))[0] is not None


def asset_isdir(path) -> bool:
    """Whether *path* is an asset folder, on disk or inside an archive."""
    full = os.fspath(path)
    if os.path.isdir(full):
        return True
    member = asset_member(full)
    if member is None:
        return False
    with _lock:
        archives = list(_state['archives'].values())
    folded = member.casefold()
    return any(member in a.dirs or any(d.casefold() == folded for d in a.dirs)
               for a in archives)


def _archive_children(member):
    """``(files, dirs)``: names directly inside archive folder *member*."""
    prefix = member.rstrip('/') + '/'
    files, dirs = set(), set()
    with _lock:
        archives = list(_state['archives'].values())
    for archive in archives:
        for name in archive.members:
            if name.startswith(prefix):
                head, sep, _rest = name[len(prefix):].partition('/')
                (dirs if sep else files).add(head)
    return files, dirs


def asset_listdir(path) -> list[str]:
    """Names inside folder *path*: the loose ones and the archived ones
    (``os.listdir`` over both, sorted; empty when it is neither)."""
    full = os.fspath(path)
    names = set()
    if os.path.isdir(full):
        try:
            names.update(os.listdir(full))
        except OSError:
            pass
    member = asset_member(full)
    if member is not None:
        files, dirs = _archive_children(member)
        names |= files | dirs
    names.discard('.gitkeep')
    return sorted(names)


def asset_files(path, suffixes=None) -> list[str]:
    """Every asset file under folder *path*, recursively, loose or archived,
    as paths under *path* (``os.path.join(path, 'sub', 'name')``), sorted.
    *suffixes*: keep only names ending so (lower-case, e.g. ``('.png',)``)."""
    full = os.fspath(path)
    found = set()
    if os.path.isdir(full):
        for folder, _dirs, files in os.walk(full):
            for name in files:
                found.add(os.path.relpath(os.path.join(folder, name), full))
    member = asset_member(full)
    if member is not None:
        prefix = member.rstrip('/') + '/'
        with _lock:
            archives = list(_state['archives'].values())
        for archive in archives:
            for name in archive.members:
                if name.startswith(prefix):
                    found.add(name[len(prefix):].replace('/', os.sep))
    out = []
    for rel in found:
        base = os.path.basename(rel)
        if base == '.gitkeep':
            continue
        if suffixes and not base.lower().endswith(tuple(suffixes)):
            continue
        out.append(os.path.join(full, rel))
    return sorted(out)


# ---------------------------------------------------------------------------
# MiniWind: every ``*.fiopak`` mounted as one read-only file system
# ---------------------------------------------------------------------------
#
# The way Quake 3 treats its PK3s. Every ``*.fiopak`` in the project root or
# in ``assets/`` is mounted when first needed and indexed by member path;
# packages are searched in name order and a later name overrides an earlier
# one (``pak0.fiopak`` < ``pak1.fiopak`` < ``zz_mymod.fiopak``), so shipping a
# patch or a mod is dropping a package in. Nothing is extracted.
#
# * **Archives before loose files** for :func:`read` / :func:`exists`.
# * Paths are the forward-slash, project-relative form
#   (``assets/textures/foo.png``); members that try to escape are ignored.

import glob
from typing import Dict, List, Optional, Tuple

#: Where packages are found, relative to the working directory.
ASSET_DIR = "assets"
SEARCH_DIRS = (".", ASSET_DIR)
ARCHIVE_GLOB = "*.fiopak"

_mount_lock = threading.Lock()
_mount_index: Dict[str, str] = {}             # member path -> archive path
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
    global _mount_index, _signature, _checked
    import time
    now = time.monotonic()
    if _signature and now - _checked < RECHECK_SECONDS:
        return _mount_index
    _checked = now
    sig = _current_signature()
    if sig == _signature:
        return _mount_index
    with _mount_lock:
        if sig == _signature:
            return _mount_index
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
        _mount_index = index
        _signature = sig
        return index


def refresh() -> None:
    """Forget the index (a test, or an archive written while running)."""
    global _mount_index, _signature, _checked
    with _mount_lock:
        _mount_index = {}
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
    destination = os.path.realpath(archive_path)
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, _dirs, files in os.walk(source_dir):
            for name in sorted(files):
                full = os.path.join(dirpath, name)
                if os.path.realpath(full) == destination:
                    continue
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
