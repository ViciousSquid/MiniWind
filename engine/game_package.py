"""Validation and bounded extraction for the editor's Play Game Package action.

Packages contain data, never executable plugins. Keep this reader independent
of Qt and the removed standalone player.
"""

import json
import os
import shutil
import stat
import tempfile
import zipfile

MAX_PACKAGE_ENTRIES = 20000
MAX_ASSET_ENTRY_BYTES = 256 * 1024 * 1024
MAX_TOTAL_ASSET_BYTES = 2 * 1024 * 1024 * 1024
MAX_METADATA_BYTES = 1024 * 1024


def _safe_path(name):
    return (isinstance(name, str) and bool(name)
            and not any(c in name for c in ("\\", ":", "\0"))
            and all(part not in ("", ".", "..") for part in name.split("/")))


def validate_package(archive):
    """Validate every member before writing anything; return the start map."""
    members = archive.infolist()
    if len(members) > MAX_PACKAGE_ENTRIES:
        raise ValueError("Package has too many files")
    names = set()
    files = set()
    total = 0
    for member in members:
        name = member.filename.rstrip("/") if member.is_dir() else member.filename
        if not _safe_path(name):
            raise ValueError(f"Unsafe package path: {member.filename}")
        key = name.casefold()
        if key in names:
            raise ValueError(f"Duplicate package path: {name}")
        names.add(key)
        mode = stat.S_IFMT(member.external_attr >> 16)
        if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise ValueError(f"Package links and special files are forbidden: {name}")
        if name != "metadata.json" and name.split("/")[0] not in (
                "assets", "maps", "cutscenes"):
            raise ValueError(f"Unexpected package path: {name}")
        if name.lower().endswith((".py", ".pyc", ".pyo", ".so", ".dll", ".pyd")):
            raise ValueError(f"Package code is forbidden: {name}")
        if member.flag_bits & 1:
            raise ValueError("Encrypted packages are not supported")
        if member.file_size > MAX_ASSET_ENTRY_BYTES:
            raise ValueError(f"Package file too large: {name}")
        total += member.file_size
        if total > MAX_TOTAL_ASSET_BYTES:
            raise ValueError("Package expands past the size limit")
        if not member.is_dir():
            files.add(name)
    if "metadata.json" not in files:
        raise ValueError("Package is missing metadata.json")
    if archive.getinfo("metadata.json").file_size > MAX_METADATA_BYTES:
        raise ValueError("Package metadata is too large")
    metadata = json.loads(archive.read("metadata.json"))
    start = metadata.get("map_path") if isinstance(metadata, dict) else None
    if (not _safe_path(start) or not start.startswith("maps/")
            or not start.lower().endswith(".json") or start not in files):
        raise ValueError("Package must name an existing start map under maps/")
    return start


def extract_package(path):
    """Return ``(temporary_directory, start_map)``; remove partial extractions."""
    with zipfile.ZipFile(path) as archive:
        start = validate_package(archive)
        destination = tempfile.mkdtemp(prefix="fio_package_")
        try:
            archive.extractall(destination)
        except BaseException:
            shutil.rmtree(destination, ignore_errors=True)
            raise
    return destination, os.path.join(destination, *start.split("/"))
