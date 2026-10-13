"""
MiniWind's background music.

Every ``.mp3`` in ``assets/music`` is the game's soundtrack: while a play
session runs they play one after another, shuffled, everywhere in the world
(not from a speaker), at Fio's music volume (``[Audio] music_volume``, 0-100:
the pause menu's options and Settings > Play Modes > Audio set the same one);
0% is off, and so is ``[GAME] music``, the pause menu's switch. Both are kept
in ``settings.ini``, so they hold for the next game too.
Leaving play for the editor stops the music.

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
import zipfile

from engine.audio_archives import list_archive_audio, open_archive_audio

#: Loose soundtrack folder and adjacent ZIP-based asset archive.
MUSIC_DIR = os.path.join("assets", "music")
MUSIC_ARCHIVE = os.path.join("assets", "music.fiopak")
_ARCHIVE_TRACK_PREFIX = "fiopak://"

#: settings.ini switch for the music, and Fio's music volume (percent).
SETTING = ("GAME", "music")
VOLUME_SETTING = ("Audio", "music_volume")
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

    def __init__(self, music_dir: str = MUSIC_DIR, backend=None, rng=None,
                 music_archive: str = None):
        self.music_dir = music_dir
        # Use the configured archive for default assets, or a sibling archive
        # when a custom music_dir is supplied by tests/alternate project roots.
        if music_archive is not None:
            self.music_archive = music_archive
        elif os.path.normpath(music_dir) == os.path.normpath(MUSIC_DIR):
            self.music_archive = MUSIC_ARCHIVE
        else:
            self.music_archive = os.path.join(
                os.path.dirname(os.path.normpath(music_dir)), "music.fiopak"
            )
        self._current_archive = None
        self._current_archive_stream = None
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
        volume = self._configured_volume()
        self.volume = DEFAULT_VOLUME if volume is None else volume
        self._seen_volume = volume

    def _configured_volume(self):
        """Fio's music volume from the config, 0..1, or None if unreadable."""
        config = self._config
        if config is None:
            return None
        try:
            percent = config.getfloat(*VOLUME_SETTING,
                                      fallback=DEFAULT_VOLUME * 100.0)
            return max(0.0, min(1.0, float(percent) / 100.0))
        except Exception:
            return None

    def _persist(self) -> None:
        config = self._config
        if config is None:
            return
        try:
            section, key = SETTING
            if not config.has_section(section):
                config.add_section(section)
            config.set(section, key, str(bool(self.enabled)))
            vsection, vkey = VOLUME_SETTING
            if not config.has_section(vsection):
                config.add_section(vsection)
            percent = int(round(self.volume * 100.0)) if self.enabled else 0
            config.set(vsection, vkey, str(percent))
            self._seen_volume = percent / 100.0
            if self._save is not None:
                self._save()
        except Exception as exc:
            print(f"[MiniWind] could not save the music setting: {exc}")

    # ----------------------------------------------------------------- tracks
    def tracks(self):
        """Sorted soundtrack tracks from music.fiopak, or the legacy loose folder.

        Archive entries retain their project-relative names behind a private
        marker, so tracks can be identified without extracting them. An
        existing archive is authoritative; loose files remain the fallback
        when no archive exists.
        """
        if os.path.normpath(self.music_archive) == os.path.normpath(MUSIC_ARCHIVE):
            # The game's own soundtrack: every mounted .fiopak may carry
            # tracks (music.fiopak, music2.fiopak, ...); later ones override.
            from engine import asset_archives
            members = asset_archives.members("assets/music", (".mp3",))
            if members:
                return [_ARCHIVE_TRACK_PREFIX + member for member in members]
        if os.path.isfile(self.music_archive):
            try:
                members = list_archive_audio(
                    self.music_archive, "assets/music", (".mp3",)
                )
            except (OSError, zipfile.BadZipFile) as exc:
                print(f"[MiniWind] music archive cannot be read: {exc}")
                return []
            return [_ARCHIVE_TRACK_PREFIX + member for member in members]

        try:
            names = os.listdir(self.music_dir)
        except OSError:
            return []
        return sorted(os.path.join(self.music_dir, n) for n in names
                      if n.lower().endswith(".mp3")
                      and os.path.isfile(os.path.join(self.music_dir, n)))

    def _load_track(self, music, track):
        """Load a loose path or keep an archive member open for streaming."""
        if not track.startswith(_ARCHIVE_TRACK_PREFIX):
            music.load(track)
            self._close_current_archive()
            return

        member = track[len(_ARCHIVE_TRACK_PREFIX):]
        archive_path = self.music_archive
        if os.path.normpath(archive_path) == os.path.normpath(MUSIC_ARCHIVE):
            from engine import asset_archives
            archive_path = asset_archives.archive_of(member) or archive_path
        opened = open_archive_audio(
            archive_path, member, "assets/music", (".mp3",)
        )
        if opened is None:
            raise FileNotFoundError(f"Music track missing from archive: {member}")
        archive, stream = opened
        try:
            # SDL_mixer needs the format hint for a file-like object. Keep both
            # the ZipExtFile and its ZIP owner alive throughout playback.
            music.load(stream, "mp3")
        except BaseException:
            stream.close()
            archive.close()
            raise

        old_archive = self._current_archive
        old_stream = self._current_archive_stream
        self._current_archive = archive
        self._current_archive_stream = stream
        if old_stream is not None:
            old_stream.close()
        if old_archive is not None:
            old_archive.close()

    def _close_current_archive(self):
        """Release the active ZIP stream after music has stopped or been replaced."""
        stream = self._current_archive_stream
        archive = self._current_archive
        self._current_archive_stream = None
        self._current_archive = None
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
        if archive is not None:
            try:
                archive.close()
            except Exception:
                pass

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
                self._load_track(music, track)
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
        try:
            if music is not None:
                music.stop()
                unload = getattr(music, "unload", None)
                if callable(unload):
                    unload()
        except Exception:
            pass
        finally:
            self._close_current_archive()

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

    @property
    def effective_volume(self) -> float:
        """The volume the player hears: 0 while music is off."""
        return self.volume if self.enabled else 0.0

    def set_volume(self, volume: float) -> None:
        """Set the music volume (0..1), live; 0 switches the music off.

        Raising it from 0 switches the music back on and starts a track if a
        session is running. Remembered in settings.ini.
        """
        volume = max(0.0, min(1.0, float(volume)))
        with self._lock:
            self.enabled = volume > 0.0
            if self.enabled:
                self.volume = volume
            self._persist()
            if not self.enabled:
                self._silence()
                return
            music = self._music()
            if self.playing and music is not None:
                try:
                    music.set_volume(self.volume)
                except Exception:
                    pass
            elif self.session_active:
                self._play_next()

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
            # Settings > Play Modes > Audio sets the same volume: follow it.
            volume = self._configured_volume()
            if volume is not None and volume != getattr(self, "_seen_volume", None):
                self._seen_volume = volume
                if volume > 0.0:
                    self.volume = volume
                music = self._music()
                if self.playing and music is not None:
                    try:
                        music.set_volume(self.volume if volume > 0.0 else 0.0)
                    except Exception:
                        pass
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
