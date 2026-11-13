"""
The UDP connection: how friend codes join a party through home routers.

A home router lets a reply in only to a computer that sent something out to
that address first. UDP packets do that: the joiner's first packets to the
host open its own router, and the host's router opens when the host sends to
the joiner (UPnP, a forwarded port, or the host letting a friend in with the
friend's *reply code* -- :meth:`UdpEndpoint.punch`). TCP's handshake does not
get through the same way, so friend codes use this; typed addresses and LAN
games keep using TCP (:mod:`game.multiplayer.transport`).

One UDP socket per computer carries everything, and each peer behaves like a
TCP :class:`~game.multiplayer.transport.Connection` to the lobby and the
game -- ``send(message, replace=False)``, ``close()``, ``closed``,
``address`` -- with events on the same queue:

* **reliable, in order** (lobby, input, actions, sounds...): JSON, zlib
  when it helps, split into numbered pieces of at most :data:`CHUNK` bytes,
  resent until acknowledged (cumulative ack plus a 64-piece bitmap),
  delivered in order exactly once;
* **latest wins** (``replace=True``: the world frames): sent as patches
  against the newest frame the peer acknowledged (:mod:`.delta`), split into
  pieces and not resent -- a lost frame is simply replaced by the next. A
  token bucket (:data:`RATE`) keeps a big keyframe from flooding the line;
* pings every :data:`PING_EVERY` s measure the round trip (the resend timer);
  nothing heard for :data:`TIMEOUT` s ends the connection.

The host's address the world sees is asked of a STUN server *from this same
socket* (:meth:`UdpEndpoint.stun`), so the port in the friend code is the one
the router really maps for the game.

Standard library only (socket, select, struct, zlib, json, threading) -- the
one platform difference handled is Windows reporting a peer's ICMP "port
unreachable" as ConnectionResetError on a UDP socket, which is ignored -- so it
runs the same on Windows, macOS and Linux, and in a Nuitka build.
"""

from __future__ import annotations

import json
import os
import queue
import select
import socket
import struct
import threading
import time
import uuid
import zlib
from collections import deque

from .delta import FrameReceiver, FrameSender, PatchCache
from . import friend_code

MAGIC = b"MW"
VERSION = 1
CONNECT, ACCEPT, DATA, ACK, FRAME, FRAME_ACK, PING, PONG, CLOSE, PUNCH, REFUSE = range(1, 12)
_HEADER = struct.Struct("!2sBBI")          # magic, version, kind, connection id
_DATA = struct.Struct("!IB")               # sequence, flags (1 = last piece)
_ACK = struct.Struct("!IQ")                # next expected sequence, bitmap after it
_FRAME = struct.Struct("!IIHH")            # frame id, baseline id, piece, pieces
_FRAME_ACK = struct.Struct("!I")
_PING = struct.Struct("!d")
#: Payload bytes per packet: safely under any path's MTU with all headers.
CHUNK = 1150
#: Unacknowledged reliable pieces in flight per peer, at most.
WINDOW = 512
#: Reliable messages and frames, at most (bytes, after decompression).
MAX_MESSAGE = 8 * 1024 * 1024
MAX_FRAME_PIECES = 8000
#: World-frame bandwidth per peer (bytes a second) and burst.
RATE = 2_000_000
BURST = 400_000
PING_EVERY = 0.5
TIMEOUT = 20.0
CONNECT_EVERY = 0.25
CONNECT_FOR = 20.0
MAX_PEERS = 8
#: Messages longer than this (bytes) are zlib-compressed when that helps.
COMPRESS_OVER = 200
#: A FRAME_ACK of this id asks the sender for a whole frame (the receiver
#: lost the baseline a patch was made against).
RESEND_WHOLE = 0xFFFFFFFF


def _encode(message) -> bytes:
    raw = json.dumps(message, ensure_ascii=False, separators=(",", ":"),
                     allow_nan=False).encode("utf-8")
    if len(raw) > MAX_MESSAGE:
        raise ValueError("Multiplayer message is too large.")
    if len(raw) > COMPRESS_OVER:
        packed = zlib.compress(raw, 6)
        if len(packed) < len(raw):
            return b"Z" + packed
    return b"J" + raw


def _decode(data: bytes):
    if not data:
        raise ValueError("Empty message.")
    kind, body = data[:1], data[1:]
    if kind == b"Z":
        inflater = zlib.decompressobj()
        body = inflater.decompress(body, MAX_MESSAGE + 1)
        if len(body) > MAX_MESSAGE or inflater.unconsumed_tail:
            raise ValueError("Multiplayer message is too large.")
    elif kind != b"J":
        raise ValueError("Unknown message encoding.")

    def no_constants(name):
        raise ValueError(f"Invalid number {name}.")

    message = json.loads(body.decode("utf-8"), parse_constant=no_constants)
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        raise ValueError("Invalid multiplayer message.")
    return message


def _pieces(data: bytes):
    return [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)] or [b""]


class UdpPeer:
    """One connection over the shared UDP socket (see the module doc)."""

    def __init__(self, endpoint, peer, addr, conn):
        self.endpoint, self.peer, self.addr, self.conn = endpoint, peer, addr, conn
        self.address = addr[0]
        self.closed = False
        self.accepted = False
        self._lock = threading.Lock()
        # reliable out
        self.next_seq = 1
        self.queue = deque()               # (seq, flags, payload) not yet sent
        self.unacked = {}                  # seq -> [packet, sent_at, sends]
        self.delivered_to = 1              # the peer has delivered every piece before this
        # reliable in
        self.expected = 1
        self.early = {}                    # seq -> (flags, payload)
        self.assembling = bytearray()
        self.ack_due = False
        # frames
        self.frames_out = FrameSender(endpoint.patch_cache)
        self.frames_in = FrameReceiver()
        self.latest = None                 # frame object waiting to be sent
        self.key_pending = None            # (frame id, last sequence) of a whole frame in flight
        self.tokens = float(BURST)
        self.tokens_at = time.monotonic()
        self.incoming = {}                 # frame id -> [pieces, base, {index: bytes}]
        # timing
        now = time.monotonic()
        self.heard = now
        self.pinged = 0.0
        self.srtt = 0.2
        self.stats = {"sent": 0, "received": 0, "frames": 0, "frame_bytes": 0, "resent": 0}

    # -- the Connection surface ------------------------------------------------
    def send(self, message, *, replace=False):
        if self.closed:
            return False
        if replace:
            with self._lock:
                self.latest = message
            return True
        try:
            data = _encode(message)
        except (TypeError, ValueError):
            return False
        if self._enqueue(data) is None:
            self.close("The connection could not keep up.")
            return False
        self.endpoint.wake()
        return True

    def _enqueue(self, data):
        """Queue *data* on the reliable channel; its last sequence number,
        or None when the connection is hopelessly behind."""
        pieces = _pieces(data)
        with self._lock:
            last = None
            for i, piece in enumerate(pieces):
                last = self.next_seq
                self.queue.append((self.next_seq, 1 if i == len(pieces) - 1 else 0, piece))
                self.next_seq = (self.next_seq + 1) & 0xFFFFFFFF or 1
            if len(self.queue) + len(self.unacked) > 64 * WINDOW:
                return None
        return last

    def close(self, reason=None):
        if self.closed:
            return
        self.closed = True
        self.endpoint.drop(self, reason, tell=True)

    # -- packets in ---------------------------------------------------------------
    def on_data(self, seq, flags, payload):
        self.ack_due = True
        ahead = (seq - self.expected) & 0xFFFFFFFF
        if ahead >= 0x80000000 or ahead > 64 * WINDOW:
            return                          # old (a resend) or absurd
        self.early[seq] = (flags, payload)
        while self.expected in self.early:
            f, p = self.early.pop(self.expected)
            self.expected = (self.expected + 1) & 0xFFFFFFFF or 1
            self.assembling += p
            if len(self.assembling) > MAX_MESSAGE + 1:
                raise ValueError("Peer exceeded the message size limit.")
            if f & 1:
                data, self.assembling = bytes(self.assembling), bytearray()
                message = _decode(data)
                if message.get("type") == "_frame":
                    # A whole frame, sent reliably: the baseline for patches.
                    frame, _fid = self.frames_in.take(message)
                    if frame is not None:
                        self.endpoint.deliver(self, frame)
                else:
                    self.endpoint.deliver(self, message)

    def on_ack(self, expected, bits):
        # Everything before *expected* has been delivered, in order.
        if (expected - self.delivered_to) & 0xFFFFFFFF < 0x80000000:
            self.delivered_to = expected
        with self._lock:
            for seq in list(self.unacked):
                behind = (expected - seq) & 0xFFFFFFFF
                if 0 < behind < 0x80000000:
                    del self.unacked[seq]
                    continue
                gap = (seq - expected) & 0xFFFFFFFF
                if 1 <= gap <= 64 and bits & (1 << (gap - 1)):
                    del self.unacked[seq]

    def on_frame(self, fid, base, index, count, payload):
        if count == 0 or count > MAX_FRAME_PIECES or index >= count:
            return
        if fid <= self.frames_in.newest:
            return
        entry = self.incoming.get(fid)
        if entry is None:
            entry = self.incoming[fid] = [count, base, {}]
            for old in sorted(self.incoming)[:-4]:       # keep a few in progress
                del self.incoming[old]
        if entry[0] != count:
            return
        entry[2][index] = payload
        if len(entry[2]) == count:
            del self.incoming[fid]
            packet = _decode(b"".join(entry[2][i] for i in range(count)))
            base_id = packet.get("base", 0)
            if base_id and base_id not in self.frames_in.frames and fid > self.frames_in.newest:
                self.endpoint.send_raw(self, FRAME_ACK, _FRAME_ACK.pack(RESEND_WHOLE))
                return
            frame, got = self.frames_in.take(packet)
            if frame is not None:
                self.endpoint.send_raw(self, FRAME_ACK, _FRAME_ACK.pack(got))
                self.endpoint.deliver(self, frame)
            for old in [k for k in self.incoming if k <= self.frames_in.newest]:
                del self.incoming[old]

    # -- packets out (endpoint thread) ----------------------------------------------
    def service(self, now):
        ep = self.endpoint
        if self.ack_due:
            self.ack_due = False
            bits = 0
            for i in range(64):
                if ((self.expected + 1 + i) & 0xFFFFFFFF) in self.early:
                    bits |= 1 << i
            ep.send_raw(self, ACK, _ACK.pack(self.expected, bits))
        rto = max(0.06, min(1.5, self.srtt * 1.6 + 0.03))
        with self._lock:
            for seq, entry in list(self.unacked.items()):
                if now - entry[1] >= rto * min(8, 2 ** (entry[2] - 1)):
                    entry[1] = now
                    entry[2] += 1
                    self.stats["resent"] += 1
                    ep.send_packet(self, entry[0])
            while self.queue and len(self.unacked) < WINDOW:
                seq, flags, payload = self.queue.popleft()
                packet = ep.packet(self, DATA, _DATA.pack(seq, flags) + payload)
                self.unacked[seq] = [packet, now, 1]
                ep.send_packet(self, packet)
            latest = self.latest
        if self.key_pending is not None:
            fid, last = self.key_pending
            # Delivered once the peer's in-order point has passed its last
            # piece (a bitmap ack of the last piece alone is not enough).
            if 0 < (self.delivered_to - last) & 0xFFFFFFFF < 0x80000000:
                # Every piece acknowledged: the peer holds it as a baseline.
                self.key_pending = None
                self.frames_out.ack(fid)
            latest = None                  # nothing more until it lands
        if latest is not None and self.frames_out.acked == 0:
            # No baseline yet (or the peer lost it): this frame goes whole,
            # on the reliable channel -- a big frame of many pieces would
            # rarely arrive complete on a lossy line, and patches need it.
            with self._lock:
                if self.latest is latest:
                    self.latest = None
            packet = self.frames_out.make(latest)
            data = _encode(packet)
            last = self._enqueue(data)
            if last is None:
                raise ValueError("The connection could not keep up.")
            self.key_pending = (packet["id"], last)
            self.stats["frames"] += 1
            self.stats["frame_bytes"] += len(data)
            latest = None
        if latest is not None:
            self.tokens = min(float(BURST), self.tokens + (now - self.tokens_at) * RATE)
            self.tokens_at = now
            packet = self.frames_out.make(latest)
            data = _encode(packet)
            if len(data) <= self.tokens or self.tokens >= BURST:
                with self._lock:
                    if self.latest is latest:
                        self.latest = None
                self.tokens -= len(data)
                pieces = _pieces(data)
                if len(pieces) <= MAX_FRAME_PIECES:
                    for i, piece in enumerate(pieces):
                        ep.send_raw(self, FRAME, _FRAME.pack(packet["id"], packet["base"], i,
                                                             len(pieces)) + piece)
                    self.stats["frames"] += 1
                    self.stats["frame_bytes"] += len(data)
            else:
                self.frames_out.next_id -= 1                 # not sent: reuse the id
                self.frames_out.sent.pop(packet["id"], None)
        with self._lock:
            while self.queue and len(self.unacked) < WINDOW:
                seq, flags, payload = self.queue.popleft()
                packet = ep.packet(self, DATA, _DATA.pack(seq, flags) + payload)
                self.unacked[seq] = [packet, now, 1]
                ep.send_packet(self, packet)
        if now - self.pinged >= PING_EVERY:
            self.pinged = now
            ep.send_raw(self, PING, _PING.pack(now))
        if now - self.heard > TIMEOUT:
            self.closed = True
            ep.drop(self, "Connection timed out.", tell=False)


class UdpEndpoint:
    """The game's one UDP socket: the host's (taking peers) or a joiner's."""

    def __init__(self, events, *, host=False, address="", port=0, admit=None, on_peer=None):
        self.events = events
        self.is_host = host
        self.admit = admit or (lambda: True)
        self.on_peer = on_peer or (lambda peer: None)
        self.patch_cache = PatchCache()
        self.peers = {}                    # (addr, conn) -> UdpPeer
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._punches = deque()            # (due, addr)
        self._stun = {}                    # transaction -> [event, result]
        #: Test hooks: return True to drop a packet (in: (data, addr); out: (data, addr)).
        self.drop_in = None
        self.drop_out = None
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Windows reports a peer's ICMP "port unreachable" as a
            # ConnectionResetError on the next recvfrom. Turning that off
            # needs an ioctl Python does not offer everywhere, so it is tried
            # here and, either way, the receive loop ignores the error.
            control = getattr(socket, "SIO_UDP_CONNRESET", None)
            if control is not None and hasattr(sock, "ioctl"):
                try:
                    sock.ioctl(control, False)
                except (OSError, ValueError):
                    pass
            sock.bind((address, int(port)))
            sock.setblocking(False)
        except (OSError, ValueError):
            sock.close()
            raise
        self.sock = sock
        self.port = sock.getsockname()[1]
        self._wake_r, self._wake_w = socket.socketpair() if hasattr(socket, "socketpair") else (None, None)
        if self._wake_r is not None:
            self._wake_r.setblocking(False)
            self._wake_w.setblocking(False)
        self._thread = threading.Thread(target=self._run, name="MiniWind UDP", daemon=True)
        self._thread.start()

    # -- joining ---------------------------------------------------------------------
    def connect(self, host, port, peer_id="host"):
        """Knock on the host at (*host*, *port*) until it answers (or
        :data:`CONNECT_FOR` passes). Returns the peer, not yet accepted."""
        info = socket.getaddrinfo(str(host), int(port), socket.AF_INET, socket.SOCK_DGRAM)
        addr = info[0][4]
        conn = int.from_bytes(os.urandom(4), "big") or 1
        peer = UdpPeer(self, peer_id, addr, conn)
        peer.knock_until = time.monotonic() + CONNECT_FOR
        peer.knocked = 0.0
        with self._lock:
            self.peers[(addr, conn)] = peer
        self.on_peer(peer)
        self.wake()
        return peer

    def punch(self, host, port, times=6):
        """Send a few packets to a joiner's public address, so this
        computer's router lets their knocking in (their reply code)."""
        addr = socket.getaddrinfo(str(host), int(port), socket.AF_INET, socket.SOCK_DGRAM)[0][4]
        now = time.monotonic()
        with self._lock:
            for i in range(times):
                self._punches.append((now + i * 0.2, addr))
        self.wake()

    def stun(self, server, timeout=2.5, tries=3):
        """The public ``(ip, port)`` this socket is seen as, or None."""
        try:
            destination = socket.getaddrinfo(server[0], int(server[1]), socket.AF_INET,
                                             socket.SOCK_DGRAM)[0][4]
        except (OSError, ValueError, IndexError, TypeError):
            return None
        for _ in range(max(1, tries)):
            transaction = os.urandom(12)
            done = threading.Event()
            self._stun[transaction] = [done, None]
            try:
                self._sendto(friend_code.stun_request(transaction), destination)
            except OSError:
                self._stun.pop(transaction, None)
                return None
            done.wait(timeout / max(1, tries))
            result = self._stun.pop(transaction, [None, None])[1]
            if result:
                return result
        return None

    # -- internals ---------------------------------------------------------------------
    def wake(self):
        if self._wake_w is not None:
            try:
                self._wake_w.send(b"x")
            except OSError:
                pass

    def packet(self, peer, kind, body=b""):
        return _HEADER.pack(MAGIC, VERSION, kind, peer.conn) + body

    def send_packet(self, peer, packet):
        peer.stats["sent"] += len(packet)
        self._sendto(packet, peer.addr)

    def send_raw(self, peer, kind, body=b""):
        self.send_packet(peer, self.packet(peer, kind, body))

    def _sendto(self, data, addr):
        if self.drop_out is not None and self.drop_out(data, addr):
            return
        try:
            self.sock.sendto(data, addr)
        except (BlockingIOError, InterruptedError):
            pass                            # full send buffer: a resend covers it
        except OSError:
            pass

    def deliver(self, peer, message):
        try:
            self.events.put_nowait((peer.peer, message))
        except queue.Full:
            raise ValueError("Peer exceeded the incoming message limit.")

    def drop(self, peer, reason, tell):
        with self._lock:
            self.peers.pop((peer.addr, peer.conn), None)
        if tell:
            for _ in range(3):
                self.send_raw(peer, CLOSE)
        try:
            if reason:
                self.events.put_nowait((peer.peer, {"type": "connection_error", "message": str(reason)[:200]}))
            self.events.put_nowait((peer.peer, {"type": "disconnected"}))
        except queue.Full:
            pass

    def _incoming(self, data, addr):
        if self.drop_in is not None and self.drop_in(data, addr):
            return
        if len(data) >= 20 and data[:2] == b"\x01\x01":
            transaction = data[8:20]
            waiting = self._stun.get(transaction)
            if waiting is not None:
                found = friend_code.stun_mapped_address(data, transaction)
                if found:
                    waiting[1] = found
                    waiting[0].set()
            return
        if len(data) < _HEADER.size:
            return
        magic, version, kind, conn = _HEADER.unpack_from(data)
        if magic != MAGIC or version != VERSION:
            return
        body = data[_HEADER.size:]
        with self._lock:
            peer = self.peers.get((addr, conn))
        if peer is None:
            if kind == CONNECT and self.is_host:
                self._accept(addr, conn)
            return
        peer.heard = time.monotonic()
        peer.stats["received"] += len(data)
        try:
            if kind == ACCEPT and not self.is_host and not peer.accepted:
                peer.accepted = True
                self.deliver(peer, {"type": "connected"})
            elif kind == CONNECT and self.is_host:
                self.send_raw(peer, ACCEPT)          # our accept was lost
            elif kind == DATA and len(body) >= _DATA.size:
                seq, flags = _DATA.unpack_from(body)
                peer.on_data(seq, flags, body[_DATA.size:])
            elif kind == ACK and len(body) >= _ACK.size:
                peer.on_ack(*_ACK.unpack_from(body))
            elif kind == FRAME and len(body) >= _FRAME.size:
                fid, base, index, count = _FRAME.unpack_from(body)
                peer.on_frame(fid, base, index, count, body[_FRAME.size:])
            elif kind == FRAME_ACK and len(body) >= _FRAME_ACK.size:
                fid = _FRAME_ACK.unpack_from(body)[0]
                if fid == RESEND_WHOLE:
                    peer.frames_out.reset()
                else:
                    peer.frames_out.ack(fid)
            elif kind == PING and len(body) >= _PING.size:
                self.send_raw(peer, PONG, body[:_PING.size])
            elif kind == PONG and len(body) >= _PING.size:
                rtt = max(0.0, time.monotonic() - _PING.unpack_from(body)[0])
                peer.srtt = peer.srtt * 0.8 + rtt * 0.2
            elif kind == CLOSE:
                peer.closed = True
                self.drop(peer, None, tell=False)
            elif kind == REFUSE and not self.is_host:
                peer.closed = True
                self.drop(peer, "The party is not taking connections.", tell=False)
        except (ValueError, UnicodeError, zlib.error, RecursionError) as exc:
            peer.closed = True
            self.drop(peer, exc, tell=True)

    def _accept(self, addr, conn):
        if self._stop.is_set():
            return
        with self._lock:
            live = sum(1 for p in self.peers.values() if not p.closed)
        if live >= MAX_PEERS or not self.admit():
            self._sendto(_HEADER.pack(MAGIC, VERSION, REFUSE, conn), addr)
            return
        peer = UdpPeer(self, uuid.uuid4().hex, addr, conn)
        peer.accepted = True
        # "connected" before anything else from this peer can be delivered.
        try:
            self.events.put_nowait((peer.peer, {"type": "connected"}))
        except queue.Full:
            return
        with self._lock:
            self.peers[(addr, conn)] = peer
        self.on_peer(peer)
        self.send_raw(peer, ACCEPT)

    def _run(self):
        while not self._stop.is_set():
            sock = self.sock
            watch = [sock] + ([self._wake_r] if self._wake_r is not None else [])
            try:
                readable, _w, _x = select.select(watch, [], [], 0.005)
            except (OSError, ValueError):
                break
            if self._wake_r is not None and self._wake_r in readable:
                try:
                    while self._wake_r.recv(4096):
                        pass
                except (BlockingIOError, InterruptedError, OSError):
                    pass
            if sock in readable:
                for _ in range(512):
                    try:
                        data, addr = sock.recvfrom(65536)
                    except (BlockingIOError, InterruptedError):
                        break
                    except ConnectionResetError:
                        continue            # Windows: a peer's ICMP; ignore
                    except OSError:
                        break
                    self._incoming(data, addr)
            now = time.monotonic()
            with self._lock:
                peers = list(self.peers.values())
                punches = []
                while self._punches and self._punches[0][0] <= now:
                    punches.append(self._punches.popleft()[1])
            for addr in punches:
                self._sendto(_HEADER.pack(MAGIC, VERSION, PUNCH, 0), addr)
            for peer in peers:
                if peer.closed:
                    continue
                if not peer.accepted:
                    if now > getattr(peer, "knock_until", now):
                        peer.closed = True
                        self.drop(peer, "No answer from the host. Check the code, or ask "
                                        "the host to let you in with your reply code.", tell=False)
                    elif now - peer.knocked >= CONNECT_EVERY:
                        peer.knocked = now
                        self.send_raw(peer, CONNECT)
                    continue
                try:
                    peer.service(now)
                except (ValueError, TypeError) as exc:
                    peer.closed = True
                    self.drop(peer, exc, tell=True)

    def close(self):
        if self._stop.is_set():
            return
        with self._lock:
            peers = list(self.peers.values())
        for peer in peers:
            if not peer.closed:
                peer.closed = True
                for _ in range(3):
                    self.send_raw(peer, CLOSE)
        self._stop.set()
        self.wake()
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=1)
        for s in (self.sock, self._wake_r, self._wake_w):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
