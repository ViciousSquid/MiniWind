"""Cut assets/sounds/bowsounds.mp3 into the two clips the game plays.

    python tools/split_bow_sounds.py

bowsounds.mp3 is a real bow being drawn and loosed: the draw (the string
pulled back, 0.07-0.90 s), silence, then the release (the string let go at
1.58 s, the limbs' snap at 1.82 s, dying away by 2.29 s). The game plays the
draw while the bow is drawn and the release the moment the arrow is loosed:

* assets/sounds/bow_draw.mp3     0.05 - 0.92 s
* assets/sounds/bow_release.mp3  1.56 - 2.32 s

Each clip gets a 5 ms fade at either end so it neither clicks in nor out.
Needs ffmpeg with an MP3 encoder (libmp3lame).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOUNDS = ROOT / "assets" / "sounds"
SOURCE = SOUNDS / "bowsounds.mp3"
#: (clip, start s, end s)
CLIPS = (("bow_draw.mp3", 0.05, 0.92), ("bow_release.mp3", 1.56, 2.32))
FADE = 0.005


def cut(name, start, end) -> Path:
    out = SOUNDS / name
    length = end - start
    subprocess.run(
        # Trim inside the filter so the fades are timed from the clip's start.
        ["ffmpeg", "-v", "error", "-y", "-i", str(SOURCE),
         "-af", f"atrim=start={start}:end={end},asetpts=PTS-STARTPTS,"
                f"afade=t=in:d={FADE},afade=t=out:st={length - FADE:.3f}:d={FADE}",
         "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "44100", "-map_metadata", "-1", str(out)],
        check=True)
    return out


def main() -> int:
    if not SOURCE.exists():
        print(f"missing {SOURCE}")
        return 1
    for name, start, end in CLIPS:
        print(cut(name, start, end))
    return 0


if __name__ == "__main__":
    sys.exit(main())
