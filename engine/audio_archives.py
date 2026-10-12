"""Helpers for audio stored in ZIP-based asset archives.

Asset archives are ordinary ZIP files named, for example, assets/sounds.fiopak.
Their member names retain project-relative paths such as assets/sounds/shoot.wav.
No extraction is required.
"""

from __future__ import annotations

import zipfile
from typing import BinaryIO, Optional, Tuple

AUDIO_EXTENSIONS = (".wav", ".ogg", ".mp3")


def _valid_member(member: str, asset_root: str,
                  extensions: tuple[str, ...]) -> bool:
    """Whether member is a safe audio path within asset_root."""
    if not isinstance(member, str) or not member or "\\" in member:
        return False
    if member.startswith("/"):
        return False
    parts = member.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    root = str(asset_root or "").strip("/")
    if not root or any(part in ("", ".", "..") for part in root.split("/")):
        return False
    if not member.startswith(root + "/"):
        return False
    suffixes = tuple(ext.lower() for ext in extensions)
    return bool(suffixes) and member.lower().endswith(suffixes)


def list_archive_audio(archive_path: str, asset_root: str,
                       extensions: tuple[str, ...] = AUDIO_EXTENSIONS) -> list[str]:
    """Return sorted safe audio member paths below asset_root.

    Missing or invalid archives raise their normal OSError / BadZipFile errors
    so callers can report the packaging problem.
    """
    with zipfile.ZipFile(archive_path, "r") as archive:
        members = {
            info.filename for info in archive.infolist()
            if not info.is_dir()
            and _valid_member(info.filename, asset_root, extensions)
        }
    return sorted(members, key=str.casefold)


def open_archive_audio(
    archive_path: str,
    member: str,
    asset_root: str,
    extensions: tuple[str, ...] = AUDIO_EXTENSIONS,
) -> Optional[Tuple[zipfile.ZipFile, BinaryIO]]:
    """Open one safe archive member and return its owning ZIP and stream.

    The caller must keep both objects alive for as long as the stream is used,
    then close the stream and ZIP. None means the member is not an allowed
    audio file or does not exist.
    """
    if not _valid_member(member, asset_root, extensions):
        return None
    archive = zipfile.ZipFile(archive_path, "r")
    try:
        info = archive.getinfo(member)
    except KeyError:
        archive.close()
        return None
    if info.is_dir():
        archive.close()
        return None
    try:
        stream = archive.open(info, "r")
    except BaseException:
        archive.close()
        raise
    return archive, stream


def read_archive_audio(
    archive_path: str,
    member: str,
    asset_root: str,
    extensions: tuple[str, ...] = AUDIO_EXTENSIONS,
) -> Optional[bytes]:
    """Read one safe audio member fully into memory.

    Suitable for short sound effects, whose decoded data is copied by
    pygame.mixer.Sound. Long music tracks should use open_archive_audio so
    they remain streamed.
    """
    opened = open_archive_audio(archive_path, member, asset_root, extensions)
    if opened is None:
        return None
    archive, stream = opened
    try:
        return stream.read()
    finally:
        stream.close()
        archive.close()
