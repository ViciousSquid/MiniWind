"""
MiniWind's background music.

Every ``.mp3`` in ``assets/music`` is the game's soundtrack: while a play
session runs they play one after another, shuffled, everywhere in the world
(not from a speaker), until the player switches music off in the pause menu.
The choice is kept in ``settings.ini`` (``[GAME] music``), so it holds for the
next game too. Leaving play for the editor stops the music.

Playback streams through ``pygame.mixer.music``, the one music channel of the
mixer the engine already opens for its sound effects, so music and effects
never compete for a channel. When the mixer is not available (no audio device,
a headless test) the player does nothing at all.
"""

from __future__ import annotations

import os
import random
import sys
import threading
import time

#: Where the soundtrack lives, relative to the working directory (the repo root).
MUSIC_DIR = os.path.join("assets", "music")

#: settings.ini switch for the music, and its volume (0..1).
SETTING = ("GAME", "music")
VOLUME_SETTING = ("GAME", "music_volume")
DEFAULT_VOLUME = 0.5

#: How often, at most, :meth:`MusicPlayer.poll` looks for the end of a track.
POLL_SECONDS = 1.0


def _pygame_music():
    """``pygame.mixer.music`` when the engine has an open mixer, else None.

    Never imports pygame itself: the engine's view opens the mixer, and a
    process without that view (tools, most tests) has no business making
    sound.
    """
    pygame = sys.modules.get("pygame")
    if pygame is None:
        return None
    try:
        if not pygame.mixer.get_init():
            return None
        return pygame.mixer.music
    except Exception:
        return None


class MusicPlayer:
    """Shuffled playlist of :data:`MUSIC_DIR` for the length of a play session."""

    def __init__(self, music_dir: str = MUSIC_DIR, backend=None, rng=None):
        self.music_dir = music_dir
        self._backend = backend
        self._rng = rng or random.Random()
        self._config = None
        self._save = None
        #: The player's choice (pause menu); True until settings say otherwise.
        self.enabled = True
        self.volume = DEFAULT_VOLUME
        #: Whether a play session is running and wants music.
        self.session_active = False
        #: The track playing now (a path), or None.
        self.current = None
        self._queue = []
        self._last_poll = 0.0
        self._lock = threading.RLock()

    # ------------------------------------------------------------- settings
    @property
    def configured(self) -> bool:
        return self._config is not None

    def configure(self, config, save=None) -> None:
        """Read the music choice from *config*; *save* writes it back to disk."""
        self._config = config
        self._save = save
        try:
            self.enabled = config.getboolean(*SETTING, fallback=True)
        except Exception:
            self.enabled = True
        try:
            volume = config.getfloat(*VOLUME_SETTING, fallback=DEFAULT_VOLUME)
            self.volume = max(0.0, min(1.0, float(volume)))
        except Exception:
            self.volume = DEFAULT_VOLUME

    def _persist(self) -> None:
        config = self._config
        if config is None:
            return
        try:
            section, key = SETTING
            if not config.has_section(section):
                config.add_section(section)
            config.set(section, key, str(bool(self.enabled)))
            if self._save is not None:
                self._save()
        except Exception as exc:
            print(f"[MiniWind] could not save the music setting: {exc}")

    # ----------------------------------------------------------------- tracks
    def tracks(self):
        """Every ``.mp3`` in :attr:`music_dir`, sorted (empty if there is none)."""
        try:
            names = os.listdir(self.music_dir)
        except OSError:
            return []
        return sorted(os.path.join(self.music_dir, n) for n in names
                      if n.lower().endswith(".mp3")
                      and os.path.isfile(os.path.join(self.music_dir, n)))

    def _next_track(self):
        """The next track of the shuffle, reshuffling once every track has played.

        A fresh shuffle never starts with the track that just ended, so the
        same song is never heard twice in a row.
        """
        if not self._queue:
            tracks = self.tracks()
            if not tracks:
                return None
            self._rng.shuffle(tracks)
            if len(tracks) > 1 and tracks[0] == self.current:
                tracks.append(tracks.pop(0))
            self._queue = tracks
        return self._queue.pop(0)

    # -------------------------------------------------------------- playback
    def _music(self):
        return self._backend if self._backend is not None else _pygame_music()

    def _play_next(self) -> bool:
        music = self._music()
        if music is None:
            return False
        # A track that will not load (corrupt, unsupported) is skipped; give
        # up after one pass over the folder rather than spinning.
        for _ in range(max(1, len(self.tracks()))):
            track = self._next_track()
            if track is None:
                return False
            try:
                music.load(track)
                music.set_volume(self.volume)
                music.play()
                self.current = track
                return True
            except Exception as exc:
                print(f"[MiniWind] music: cannot play {os.path.basename(track)}: {exc}")
                self.current = track
        self.current = None
        return False

    def _silence(self) -> None:
        music = self._music()
        self.current = None
        if music is None:
            return
        try:
            music.stop()
        except Exception:
            pass

    @property
    def playing(self) -> bool:
        return self.current is not None

    def start(self) -> None:
        """A play session began: start the soundtrack (if music is on)."""
        with self._lock:
            self.session_active = True
            if self.enabled and not self.playing:
                self._play_next()

    def stop(self) -> None:
        """The play session ended: stop the soundtrack."""
        with self._lock:
            self.session_active = False
            self._silence()

    def set_enabled(self, enabled: bool) -> None:
        """Switch music on or off (the pause menu), and remember the choice."""
        with self._lock:
            self.enabled = bool(enabled)
            self._persist()
            if not self.enabled:
                self._silence()
            elif self.session_active and not self.playing:
                self._play_next()

    def toggle(self) -> bool:
        self.set_enabled(not self.enabled)
        return self.enabled

    def poll(self, now: float = None) -> None:
        """Move on to the next track once the current one has finished.

        Cheap enough to call every tick: it looks at the mixer at most every
        :data:`POLL_SECONDS`.
        """
        now = time.monotonic() if now is None else now
        if now - self._last_poll < POLL_SECONDS:
            return
        self._last_poll = now
        with self._lock:
            if not (self.session_active and self.enabled and self.playing):
                return
            music = self._music()
            if music is None:
                return
            try:
                busy = music.get_busy()
            except Exception:
                return
            if not busy:
                self._play_next()


#: The process-wide soundtrack.
PLAYER = MusicPlayer()
