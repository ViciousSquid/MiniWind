"""File identities for caches derived from authored content."""

import os


def file_version(path):
    """Identify a file version, including replacements preserving size/mtime.

    Editors and copy tools can preserve modification times. The inode and
    change time keep derived data from surviving an atomic replacement or
    an in-place edit whose modification time was restored.
    """
    path = os.path.realpath(path)
    stat = os.stat(path)
    return (path, stat.st_dev, stat.st_ino, stat.st_size,
            stat.st_mtime_ns, stat.st_ctime_ns)
