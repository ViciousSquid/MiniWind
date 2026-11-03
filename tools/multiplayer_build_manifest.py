"""Run before freezing MiniWind; no desktop dependencies are needed."""

import json
import runpy
from pathlib import Path


def write_manifest(root):
    root = Path(root)
    api = runpy.run_path(str(root / "game/multiplayer/compatibility.py"))
    path = root / api["MANIFEST"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"source_sha256": api["source_signature"](root)}, indent=2) + "\n"
    )
    return path


if __name__ == "__main__":
    print(write_manifest(Path(__file__).resolve().parents[1]))
