"""The UDP connection behind friend codes (game/multiplayer/udp.py), on real
loopback sockets, with a hostile wire: lost, duplicated and reordered
packets, a home router that only lets replies in, a full party, a silent
peer -- and the lobby joining by friend code over it."""

from __future__ import annotations

import json
import queue
import random
import threading
import time

import pytest

from game.multiplayer import friend_code as fc
from game.multiplayer import udp
from game.multiplayer.transport import NetworkService
from game.tests.test_multiplayer import profile
from game.tests.test_multiplayer_network import ROOT, advance


def _wait(pred, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.005)
    return False


def _drain(events, into):
    while True:
        try:
            into.append(events.get_nowait())
        except queue.Empty:
            return into


class Chaos:
    """A wire that loses, duplicates and reorders packets (both ways)."""

    def __init__(self, endpoint, seed=1, loss=0.25, dup=0.1, hold=0.1):
        self.endpoint, self.rng = endpoint, random.Random(seed)
        self.loss, self.dup, self.hold = loss, dup, hold
        self.held = []
        self.inside = threading.local()

    def __call__(self, data, addr):
        if getattr(self.inside, "on", False):
            return False
        r = self.rng.random()
        if r < self.loss:
            return True
        if r < self.loss + self.hold:
            self.held.append((data, addr))
            return True
        if self.held and self.rng.random() < 0.5:
            self._reinject(self.held.pop(self.rng.randrange(len(self.held))))
        if self.rng.random() < self.dup:
            self._reinject((data, addr))
        return False

    def _reinject(self, packet):
        self.inside.on = True
        try:
            self.endpoint._incoming(*packet)
        finally:
            self.inside.on = False


@pytest.fixture
def pair():
    """A host endpoint and a joined client, with their event queues."""
    host_events, client_events = queue.Queue(maxsize=4096), queue.Queue(maxsize=4096)
    host = udp.UdpEndpoint(host_events, host=True, address="127.0.0.1")
    client = udp.UdpEndpoint(client_events, host=False, address="127.0.0.1")
    try:
        peer = client.connect("127.0.0.1", host.port)
        got = []
        assert _wait(lambda: any(e[1]["type"] == "connected" for e in _drain(client_events, got)))
        host_got = _drain(host_events, [])
        assert _wait(lambda: any(e[1]["type"] == "connected" for e in _drain(host_events, host_got)))
        host_peer = next(iter(host.peers.values()))
        yield host, client, peer, host_peer, host_events, client_events
    finally:
        client.close()
        host.close()


def test_reliable_messages_arrive_once_and_in_order_over_a_bad_wire(pair):
    host, client, peer, host_peer, host_events, client_events = pair
    host.drop_in = Chaos(host, seed=2)
    client.drop_in = Chaos(client, seed=3)
    rng = random.Random(4)
    sent = []
    for i in range(300):
        size = rng.choice([10, 200, 1500, 5000]) if i != 150 else 300_000   # one big one
        message = {"type": "lobby_request", "n": i,
                   "blob": "".join(rng.choice("abcdefgh") for _ in range(size))}
        sent.append(message)
        assert peer.send(message)
    got = []
    assert _wait(lambda: len([e for e in _drain(host_events, got) if e[1]["type"] == "lobby_request"]) >= 300,
                 timeout=30), f"only {len(got)} arrived"
    received = [e[1] for e in got if e[1]["type"] == "lobby_request"]
    assert [m["n"] for m in received] == list(range(300))      # in order, exactly once
    assert received == sent
    assert peer.stats["resent"] > 0                            # the wire really lost some


def test_world_frames_rebuild_exactly_and_travel_as_patches(pair):
    host, client, peer, host_peer, host_events, client_events = pair
    client.drop_in = Chaos(client, seed=5, loss=0.15, dup=0.05, hold=0.05)
    rng = random.Random(6)
    world = {"type": "world", "sequence": 0,
             "entities": [{"id": f"e{i}", "pos": [rng.random(), 0.0, rng.random()], "hp": 20}
                          for i in range(1500)]}
    sent = {}
    for n in range(1, 81):
        world = json.loads(json.dumps(world))
        world["sequence"] = n
        for e in rng.sample(world["entities"], 8):
            e["pos"][0] += 1.0
        sent[n] = world
        host_peer.send(world, replace=True)
        time.sleep(0.01)
    got = []

    def last_arrived():
        _drain(client_events, got)
        if not any(e[1].get("sequence") == 80 for e in got):
            host_peer.send(sent[80], replace=True)               # the game keeps sending
            time.sleep(0.02)
            return False
        return True

    assert _wait(last_arrived, timeout=15)
    frames = [e[1] for e in got if e[1].get("type") == "world"]
    assert frames and all(f == sent[f["sequence"]] for f in frames)        # exact
    sequences = [f["sequence"] for f in frames]
    assert sequences == sorted(set(sequences))                             # latest wins, no repeats
    full = len(json.dumps(sent[80]))
    average = host_peer.stats["frame_bytes"] / host_peer.stats["frames"]
    assert average * 20 < full, (average, full)                            # patches, not worlds


def test_a_closed_peer_is_noticed_at_once(pair):
    host, client, peer, host_peer, host_events, client_events = pair
    peer.close()
    got = []
    assert _wait(lambda: any(e[1]["type"] == "disconnected" for e in _drain(host_events, got)))


def test_a_silent_peer_times_out(pair, monkeypatch):
    host, client, peer, host_peer, host_events, client_events = pair
    monkeypatch.setattr(udp, "TIMEOUT", 0.6)
    host.drop_in = lambda data, addr: True                     # the joiner vanished
    got = []
    assert _wait(lambda: any(e[1].get("message") == "Connection timed out."
                             for e in _drain(host_events, got)), timeout=5)


class RestrictedRouter:
    """The host behind a home router: a packet comes in only from an address
    the host has sent to (endpoint-restricted filtering)."""

    def __init__(self, endpoint):
        self.sent_to = set()
        endpoint.drop_out = self.outgoing
        endpoint.drop_in = self.incoming

    def outgoing(self, data, addr):
        self.sent_to.add(addr)
        return False

    def incoming(self, data, addr):
        return addr not in self.sent_to


def test_a_router_keeps_a_joiner_out_until_the_host_lets_them_in(monkeypatch):
    monkeypatch.setattr(udp, "CONNECT_FOR", 6.0)
    host_events, client_events = queue.Queue(), queue.Queue()
    host = udp.UdpEndpoint(host_events, host=True, address="127.0.0.1")
    client = udp.UdpEndpoint(client_events, address="127.0.0.1")
    RestrictedRouter(host)
    try:
        client.connect("127.0.0.1", host.port)
        time.sleep(0.8)
        assert not host.peers                                 # knocking, kept out
        # The joiner's reply code: its address as the world sees it.
        reply = fc.reply_code("127.0.0.1", client.port)
        ip, port, invitation = fc.decode(reply)
        assert invitation == 0
        host.punch(ip, port)                                  # the host lets them in
        got = []
        assert _wait(lambda: any(e[1]["type"] == "connected" for e in _drain(client_events, got)))
    finally:
        client.close()
        host.close()


def test_with_no_answer_the_joiner_is_told_what_to_do(monkeypatch):
    monkeypatch.setattr(udp, "CONNECT_FOR", 0.8)
    host_events, client_events = queue.Queue(), queue.Queue()
    host = udp.UdpEndpoint(host_events, host=True, address="127.0.0.1")
    client = udp.UdpEndpoint(client_events, address="127.0.0.1")
    RestrictedRouter(host)
    try:
        client.connect("127.0.0.1", host.port)
        got = []
        assert _wait(lambda: any("reply code" in str(e[1].get("message", ""))
                                 for e in _drain(client_events, got)), timeout=4)
    finally:
        client.close()
        host.close()


def test_a_full_party_turns_a_joiner_away(monkeypatch):
    monkeypatch.setattr(udp, "MAX_PEERS", 1)
    events = [queue.Queue() for _ in range(3)]
    host = udp.UdpEndpoint(events[0], host=True, address="127.0.0.1")
    a = udp.UdpEndpoint(events[1], address="127.0.0.1")
    b = udp.UdpEndpoint(events[2], address="127.0.0.1")
    try:
        a.connect("127.0.0.1", host.port)
        got_a = []
        assert _wait(lambda: any(e[1]["type"] == "connected" for e in _drain(events[1], got_a)))
        b.connect("127.0.0.1", host.port)
        got_b = []
        assert _wait(lambda: any("not taking" in str(e[1].get("message", ""))
                                 for e in _drain(events[2], got_b)))
    finally:
        for e in (a, b, host):
            e.close()


def test_stun_is_asked_from_the_game_socket():
    import socket
    import struct
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    server.settimeout(3)
    endpoint = udp.UdpEndpoint(queue.Queue(), address="127.0.0.1")
    seen = {}

    def serve():
        data, src = server.recvfrom(2048)
        seen["src"] = src
        ip = struct.unpack("!I", socket.inet_aton("198.51.100.9"))[0]
        attr = struct.pack("!HHBBHI", 0x0020, 8, 0, 1, 40123 ^ 0x2112, ip ^ 0x2112A442)
        server.sendto(struct.pack("!HHI", 0x0101, len(attr), 0x2112A442) + data[8:20] + attr, src)

    threading.Thread(target=serve, daemon=True).start()
    try:
        assert endpoint.stun(server.getsockname(), timeout=3, tries=1) == ("198.51.100.9", 40123)
        assert seen["src"][1] == endpoint.port            # from the game's own socket
    finally:
        endpoint.close()
        server.close()


def test_garbage_and_other_programs_packets_are_ignored(pair):
    host, client, peer, host_peer, host_events, client_events = pair
    import socket
    stray = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for junk in (b"", b"x", b"MW", b"MW\x01\x03" + b"\x00" * 3, b"\x01\x01" + b"\x00" * 30,
                     udp._HEADER.pack(b"MW", 99, udp.DATA, 1) + b"zz"):
            stray.sendto(junk, ("127.0.0.1", host.port))
        peer.send({"type": "lobby_request", "n": 1})
        got = []
        assert _wait(lambda: any(e[1].get("n") == 1 for e in _drain(host_events, got)))
        assert not any(e[1]["type"] == "disconnected" for e in got)
    finally:
        stray.close()


# -- the lobby over UDP ------------------------------------------------------------
def _udp_party():
    from game.multiplayer.lobby import LobbyController
    from game.multiplayer.model import Lobby
    network = NetworkService()
    network.host(port=0, address="127.0.0.1")
    assert network.udp is not None and network.udp.port == network.port   # one port, both ways
    server = LobbyController(ROOT, "maps/miniwind_world.json", network=network, identity="a" * 64)
    server.opened = True
    server.signature = "matching-build"
    server.lobby = Lobby(signature=server.signature, map_name="maps/miniwind_world.json")
    server.invitation = fc.new_invitation()
    server.find_code(finder=lambda: ("127.0.0.1", network.udp.port, "local", None), wait=True)
    return server


def _udp_guest(code, identity="b" * 64):
    from game.multiplayer.lobby import LobbyController
    client = LobbyController(ROOT, "maps/miniwind_world.json", identity=identity)
    client.opened = True
    client.signature = "matching-build"
    client.join_code(code)
    return client


@pytest.fixture
def outside(monkeypatch):
    from game.multiplayer import lobby as lobby_module
    monkeypatch.setattr(lobby_module.friend_code, "trusted_address", lambda _a: False)


def test_a_friend_code_joins_the_lobby_over_udp_and_plays(outside):
    server = _udp_party()
    client = _udp_guest(server.code)
    try:
        advance([server, client], lambda: client.state is not None, timeout=8)
        assert isinstance(client.network.connections["host"], udp.UdpPeer)    # it is UDP
        server.request("add", profile=profile(0))
        client.request("add", profile=profile(1, "keyboard"))
        advance([server, client], lambda: len(server.lobby.members) == 2, timeout=8)
        client.request("ready", ready=True)
        server.request("ready", ready=True)
        advance([server, client], lambda: server.lobby.can_start, timeout=8)
        server.request("start")
        advance([server, client], lambda: client.started, timeout=8)
    finally:
        client.close()
        server.close()


def test_a_stale_code_is_turned_away_over_udp_too(outside):
    server = _udp_party()
    old = server.code
    server.new_code()
    client = _udp_guest(old)
    try:
        advance([server, client], lambda: bool(client.errors), timeout=8)
        assert "out of date" in client.errors[0]
    finally:
        client.close()
        server.close()


def test_typed_addresses_still_join_over_tcp():
    from game.multiplayer.transport import Connection
    server = _udp_party()
    client = _udp_guest(f"127.0.0.1:{server.network.port}")
    try:
        advance([server, client], lambda: client.state is not None, timeout=8)
        assert isinstance(client.network.connections["host"], Connection)    # TCP
    finally:
        client.close()
        server.close()


def test_a_windows_connection_reset_on_receive_is_shrugged_off(pair):
    """Windows reports a peer's ICMP "port unreachable" as ConnectionResetError
    on the next recvfrom of a UDP socket; the game socket carries on."""
    host, client, peer, host_peer, host_events, client_events = pair

    class Resetting:
        def __init__(self, sock):
            self.sock, self.raised = sock, 0

        def recvfrom(self, size):
            if self.raised < 3:
                self.raised += 1
                raise ConnectionResetError(10054, "An existing connection was forcibly closed")
            return self.sock.recvfrom(size)

        def __getattr__(self, name):
            return getattr(self.sock, name)

    wrapped = Resetting(host.sock)
    host.sock = wrapped
    host.wake()
    got, n = [], [100]

    def through():
        _drain(host_events, got)
        if wrapped.raised < 3:
            n[0] += 1
            peer.send({"type": "lobby_request", "n": n[0]})   # until the resets came
            time.sleep(0.02)
            return False
        return any(e[1].get("n") == n[0] for e in got)

    assert _wait(through)
    assert not any(e[1]["type"] == "disconnected" for e in got)
    host.sock = wrapped.sock


def test_a_friend_code_can_join_over_tcp_too(outside):
    from game.multiplayer.transport import Connection
    server = _udp_party()
    client = LobbyControllerFor()
    client.join_code(server.code, tcp=True)
    try:
        advance([server, client], lambda: client.state is not None, timeout=8)
        assert isinstance(client.network.connections["host"], Connection)    # TCP, with the code
    finally:
        client.close()
        server.close()


def test_from_outside_a_typed_address_is_told_to_use_the_code(outside):
    server = _udp_party()
    client = _udp_guest(f"127.0.0.1:{server.network.port}")
    try:
        advance([server, client], lambda: bool(client.errors), timeout=8)
        assert "friend code" in client.errors[0]
    finally:
        client.close()
        server.close()


def LobbyControllerFor(identity="d" * 64):
    from game.multiplayer.lobby import LobbyController
    client = LobbyController(ROOT, "maps/miniwind_world.json", identity=identity)
    client.opened = True
    client.signature = "matching-build"
    return client
