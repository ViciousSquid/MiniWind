"""
Pack a folder of assets into a ``.fiopak`` archive.

    python tools/make_fiopak.py assets/textures assets/textures.fiopak
    python tools/make_fiopak.py assets/textures/desert assets/textures_desert.fiopak

Members keep their project-relative paths (``assets/textures/desert/sand.png``),
which is what the engine looks them up by (engine/asset_archives.py). Any
number of archives can sit in ``assets/``; all are mounted, later names
overriding earlier ones, and loose files remain the fallback. Run from the
project root.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.getcwd())

from engine import asset_archives  # noqa: E402


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print(__doc__)
        return 2
    source, target = argv
    if not os.path.isdir(source):
        print(f"not a folder: {source}")
        return 1
    if not target.endswith(".fiopak"):
        print("the archive name must end in .fiopak")
        return 1
    n = asset_archives.pack(source, target)
    print(f"packed {n} files from {source} into {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
