"""Bounded JSON streams and opt-in LAN discovery, using desktop Python only.

No socket, thread, DNS lookup or firewall rule is created at import or object
construction. start_browser(), host() and join() are explicit UI actions.
TCP supplies reliable ordered commands; queued world frames are replaceable so
a slow connection cannot accumulate seconds of stale movement. No pickle or
remote executable content is accepted.
"""

from __future__ import annotations

import json
import queue
import select
import socket
import struct
import threading
import time
import uuid
import zlib

from . import PROTOCOL_VERSION

GAME_PORT = 39745
DISCOVERY_PORT = 39744
MAX_PACKET = 8 * 1024 * 1024
DISCOVERY_MAGIC = "miniwind-lan-v1"


def encode(message):
    raw = json.dumps(
        message, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    if not raw or len(raw) > MAX_PACKET:
        raise ValueError("Multiplayer message is too large.")
    if len(raw) > 4096:
        packed = zlib.compress(raw, 3)
        if len(packed) < len(raw):
            return struct.pack("!I", len(packed) | 0x80000000) + packed
    return struct.pack("!I", len(raw)) + raw


class Decoder:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        out = []
        while len(self.buffer) >= 4:
            header = struct.unpack_from("!I", self.buffer)[0]
            compressed = bool(header & 0x80000000)
            size = header & 0x7FFFFFFF
            if not 0 < size <= MAX_PACKET:
                raise ValueError("Invalid multiplayer packet length.")
            if len(self.buffer) < size + 4:
                break

            def no_constants(value):
                raise ValueError("Non-finite JSON value.")

            raw = bytes(self.buffer[4 : 4 + size])
            if compressed:
                inflater = zlib.decompressobj()
                raw = inflater.decompress(raw, MAX_PACKET + 1)
                if (
                    len(raw) > MAX_PACKET
                    or inflater.unconsumed_tail
                    or not inflater.eof
                ):
                    raise ValueError("Invalid compressed multiplayer frame.")
            message = json.loads(raw, parse_constant=no_constants)
            del self.buffer[: 4 + size]
            if not isinstance(message, dict) or not isinstance(
                message.get("type"), str
            ):
                raise ValueError("Invalid multiplayer message.")  # noqa: TRY004 - malformed wire data
            out.append(message)
            if len(out) > 256:
                raise ValueError("Too many multiplayer messages.")
        return out


class Connection:
    def __init__(self, sock, events, peer):
        self.sock, self.events, self.peer = sock, events, peer
        self.outgoing = queue.Queue(maxsize=128)
        self._latest = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.thread = None
        self.closed = False
        #: The far end's IP address ('' when not known).
        self.address = ""

    def start(self):
        self.sock.setblocking(False)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.thread = threading.Thread(
            target=self._run, name="MiniWind peer", daemon=True
        )
        self.thread.start()

    def send(self, message, *, replace=False):
        data = encode(message)
        if self.closed:
            return False
        if replace:
            with self._lock:
                self._latest = data
            return True
        try:
            self.outgoing.put_nowait(data)
            return True
        except queue.Full:
            self.close()
            return False

    def _event(self, message):
        try:
            self.events.put_nowait((self.peer, message))
        except queue.Full:
            raise ValueError("Peer exceeded the incoming message limit.")

    def _run(self):
        decoder = Decoder()
        pending = b""
        last_received = time.monotonic()
        last_ping = last_received
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                if now - last_received > 20:
                    raise OSError("Connection timed out.")
                if not pending:
                    try:
                        pending = self.outgoing.get_nowait()
                    except queue.Empty:
                        with self._lock:
                            pending, self._latest = self._latest or b"", None
                    if not pending and now - last_ping > 3:
                        pending = encode({"type": "ping"})
                        last_ping = now
                readable, writable, _ = select.select(
                    [self.sock], [self.sock] if pending else [], [], 0.03
                )
                if readable:
                    raw = self.sock.recv(65536)
                    if not raw:
                        break
                    last_received = now
                    for message in decoder.feed(raw):
                        if message["type"] != "ping":
                            self._event(message)
                if writable:
                    sent = self.sock.send(pending[:65536])
                    if not sent:
                        break
                    pending = pending[sent:]
        except (OSError, ValueError, UnicodeError, RecursionError, zlib.error) as exc:
            try:
                self._event({"type": "connection_error", "message": str(exc)[:200]})
            except ValueError:
                pass
        finally:
            self.closed = True
            self._stop.set()
            try:
                self.sock.close()
            except OSError:
                pass
            try:
                self._event({"type": "disconnected"})
            except ValueError:
                pass

    def close(self):
        self._stop.set()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=1)
        self.sock.close()
        self.closed = True


class NetworkService:
    def __init__(self):
        self.events = queue.Queue(maxsize=1024)
        self.connections = {}
        self.games = {}
        self.discovery = None
        self.listener = None
        self._host_discovery = None
        self._pending_socket = None
        self.advertisement = None
        self._discovery_thread = None
        self._accept_thread = None
        self._connecting = None
        self._stop = threading.Event()
        self._discovery_stop = threading.Event()
        self._lock = threading.Lock()
        self._last_search = 0.0
        self.port = None
        self.is_host = False

    def start_browser(self):
        if self._stop.is_set():
            raise ValueError("This multiplayer section has closed.")
        if self.discovery is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("", 0))
            sock.settimeout(0.2)
        except OSError:
            sock.close()
            raise
        self.discovery = sock
        self._discovery_stop.clear()
        self._discovery_thread = threading.Thread(
            target=self._browse, name="MiniWind discovery", daemon=True
        )
        self._discovery_thread.start()
        self.search()

    def search(self, address="255.255.255.255"):
        if self.discovery is None:
            return
        request = json.dumps({"magic": DISCOVERY_MAGIC, "query": True}).encode()
        self.discovery.sendto(request, (address, DISCOVERY_PORT))
        self._last_search = time.monotonic()

    def _browse(self):
        sock = self.discovery
        while not self._stop.is_set() and not self._discovery_stop.is_set():
            try:
                data, source = sock.recvfrom(8192)
                value = json.loads(data)
                if value.get("magic") != DISCOVERY_MAGIC or value.get("query"):
                    continue
                port = int(value["port"])
                if not 1 <= port <= 65535:
                    continue
                value["address"] = source[0]
                value["seen_at"] = time.monotonic()
                with self._lock:
                    self.games[(source[0], port)] = value
            except (TimeoutError, ValueError, TypeError, KeyError, UnicodeError):
                continue
            except OSError:
                break

    def found_games(self):
        with self._lock:
            return [
                dict(v)
                for v in self.games.values()
                if time.monotonic() - v["seen_at"] < 8
            ]

    def host(self, port=GAME_PORT, address=""):
        if self._stop.is_set():
            raise ValueError("This multiplayer section has closed.")
        if self.listener is not None:
            raise ValueError("Already hosting a party.")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((address, int(port)))
            listener.listen(8)
            listener.settimeout(0.2)
        except (OSError, ValueError):
            listener.close()
            raise
        self.listener = listener
        self.port = listener.getsockname()[1]
        self.is_host = True
        # Bind discovery during the visible UI action, not later in a worker
        # which might first run after the user has already left Multiplayer.
        udp = None
        try:
            udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            udp.bind(("", DISCOVERY_PORT))
            udp.setblocking(False)
        except OSError:
            if udp is not None:
                udp.close()
            udp = None  # Direct joining still works when LAN discovery is unavailable.
        self._host_discovery = udp
        self._accept_thread = threading.Thread(
            target=self._accept, name="MiniWind host", daemon=True
        )
        self._accept_thread.start()

    def _accept(self):
        udp = self._host_discovery
        listener = self.listener
        try:
            while not self._stop.is_set():
                try:
                    sock, source = listener.accept()
                    with self._lock:
                        if self._stop.is_set():
                            sock.close()
                            break
                        live = sum(not c.closed for c in self.connections.values())
                        if live >= 8:
                            sock.close()
                            continue
                        peer = uuid.uuid4().hex
                        # "connected" is queued before the peer's reader
                        # starts: a joiner sends hello at once, and its hello
                        # must never be handled before its connection is.
                        try:
                            self.events.put_nowait((peer, {"type": "connected"}))
                        except queue.Full:
                            sock.close()    # too busy to take anyone now
                            continue
                        connection = Connection(sock, self.events, peer)
                        connection.address = source[0] if source else ""
                        self.connections[peer] = connection
                        connection.start()
                except TimeoutError:
                    pass
                if udp is not None and select.select([udp], [], [], 0)[0]:
                    data, source = udp.recvfrom(8192)
                    try:
                        query = json.loads(data)
                        if (
                            query.get("magic") == DISCOVERY_MAGIC
                            and query.get("query")
                            and self.advertisement
                        ):
                            reply = dict(
                                self.advertisement,
                                magic=DISCOVERY_MAGIC,
                                port=self.port,
                                protocol=PROTOCOL_VERSION,
                            )
                            udp.sendto(json.dumps(reply).encode(), source)
                    except (ValueError, TypeError, UnicodeError):
                        pass
        except (OSError, ValueError, queue.Full):
            pass
        finally:
            if udp is not None:
                udp.close()

    def join(self, address, port=GAME_PORT):
        if self._stop.is_set():
            raise ValueError("This multiplayer section has closed.")
        if self._connecting is not None and self._connecting.is_alive():
            raise ValueError("Already connecting.")
        if any(not c.closed for c in self.connections.values()):
            raise ValueError(
                "Already connected. Leave this party before joining another."
            )

        def connect():
            sock = None
            try:
                addresses = socket.getaddrinfo(
                    str(address), int(port), type=socket.SOCK_STREAM
                )
                last_error = OSError("The host address could not be reached.")
                for family, kind, protocol, _, destination in addresses:
                    with self._lock:
                        if self._stop.is_set():
                            return
                        sock = socket.socket(family, kind, protocol)
                        self._pending_socket = sock
                    try:
                        sock.settimeout(5)
                        sock.connect(destination)
                    except OSError as exc:
                        last_error = exc
                        sock.close()
                        continue
                    with self._lock:
                        if self._stop.is_set():
                            sock.close()
                            return
                        self._pending_socket = None
                        self.events.put_nowait(("host", {"type": "connected"}))
                        connection = Connection(sock, self.events, "host")
                        self.connections["host"] = connection
                        connection.start()
                    return
                raise last_error
            except (OSError, ValueError) as exc:
                if not self._stop.is_set():
                    self.events.put_nowait(
                        (
                            "host",
                            {"type": "connection_error", "message": str(exc)[:200]},
                        )
                    )
            finally:
                with self._lock:
                    if self._pending_socket is sock:
                        self._pending_socket = None

        self._connecting = threading.Thread(
            target=connect, name="MiniWind join", daemon=True
        )
        self._connecting.start()

    def send(self, peer, message, *, replace=False):
        with self._lock:
            connection = self.connections.get(peer)
        return connection.send(message, replace=replace) if connection else False

    def broadcast(self, message, *, replace=False, peers=None):
        with self._lock:
            selected = list(self.connections) if peers is None else list(peers)
        for peer in selected:
            self.send(peer, message, replace=replace)

    def poll(self, limit=256):
        events = []
        for _ in range(limit):
            try:
                event = self.events.get_nowait()
                events.append(event)
                if event[1].get("type") == "disconnected":
                    with self._lock:
                        connection = self.connections.get(event[0])
                        if connection is not None and connection.closed:
                            self.connections.pop(event[0], None)
            except queue.Empty:
                break
        return events

    def stop_browser(self):
        self._discovery_stop.set()
        if self.discovery is not None:
            self.discovery.close()
            self.discovery = None
        if self._discovery_thread is not None:
            self._discovery_thread.join(timeout=0.5)
            self._discovery_thread = None

    def peer_address(self, peer) -> str:
        """The IP address a connected *peer* came from ('' if unknown)."""
        connection = self.connections.get(peer)
        return getattr(connection, "address", "") if connection is not None else ""

    def disconnect(self, peer):
        with self._lock:
            connection = self.connections.pop(peer, None)
        if connection is not None:
            connection.close()

    def close(self):
        self._stop.set()
        self.stop_browser()
        listener, self.listener = self.listener, None
        if listener is not None:
            listener.close()
        with self._lock:
            pending, self._pending_socket = self._pending_socket, None
            peers = list(self.connections)
        if pending is not None:
            pending.close()
        for peer in peers:
            self.disconnect(peer)
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=0.5)
        if (
            self._connecting is not None
            and self._connecting is not threading.current_thread()
        ):
            self._connecting.join(timeout=0.1)
        if self._host_discovery is not None:
            self._host_discovery.close()
            self._host_discovery = None
        self.advertisement = None
