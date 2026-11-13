"""Friend codes (game/multiplayer/friend_code.py, upnp.py): one short code to
join a friend's party over the Internet, as in Dosidicus.

Everything here stays on this machine: a fake STUN server and a fake router
on loopback; the lobby's admission over real loopback TCP.
"""

from __future__ import annotations

import http.server
import itertools
import socket
import struct
import threading

import pytest

from game.multiplayer import friend_code as fc
from game.multiplayer import lobby as lobby_module
from game.multiplayer import upnp
from game.multiplayer.model import LobbyError
from game.tests.test_multiplayer_network import advance, guest, host


# -- the code ------------------------------------------------------------------
def test_a_code_round_trips_in_three_groups_of_five():
    code = fc.encode("203.0.113.7", 39745, 0xABCDE)
    assert len(code) == 17 and code.count("-") == 2
    assert all(len(group) == 5 for group in code.split("-"))
    assert fc.decode(code) == ("203.0.113.7", 39745, 0xABCDE)


def test_case_spaces_dashes_and_lookalike_letters_do_not_matter():
    code = fc.encode("198.51.100.20", 40000, 77)
    sloppy = code.lower().replace("-", " ").replace("1", "l").replace("0", "o")
    assert fc.decode(sloppy) == ("198.51.100.20", 40000, 77)


def test_any_one_wrong_character_is_caught():
    code = fc.encode("203.0.113.7", 39745, 12345).replace("-", "")
    for i, ch in itertools.product(range(len(code)), fc.ALPHABET):
        if ch == code[i]:
            continue
        with pytest.raises(fc.FriendCodeError):
            fc.decode(code[:i] + ch + code[i + 1:])


def test_two_neighbours_swapped_are_caught():
    code = fc.encode("203.0.113.7", 39745, 54321).replace("-", "")
    for i in range(len(code) - 1):
        if code[i] == code[i + 1]:
            continue
        swapped = code[:i] + code[i + 1] + code[i] + code[i + 2:]
        with pytest.raises(fc.FriendCodeError):
            fc.decode(swapped)


def test_a_code_from_another_game_or_version_is_refused():
    # Same layout, Dosidicus's version (2): readable, but not ours.
    bits = (2 << 68) | (0xCB007107 << 36) | (39745 << 20) | 99
    values = [(bits >> (5 * (13 - i))) & 31 for i in range(14)]
    values.append(fc._check(values))
    other = "".join(fc.ALPHABET[v] for v in values)
    with pytest.raises(fc.FriendCodeError, match="not a MiniWind code"):
        fc.decode(other)


def test_friendly_words_for_bad_input():
    with pytest.raises(fc.FriendCodeError, match="Paste"):
        fc.parse("   ")
    with pytest.raises(fc.FriendCodeError, match="15"):
        fc.decode("ABCDE-FGH")
    with pytest.raises(fc.FriendCodeError, match="not part"):
        fc.decode("ABCDE-FGHJK-MN#QR")


def test_a_typed_address_still_joins():
    assert fc.parse("192.168.1.20") == ("192.168.1.20", fc.GAME_PORT, 0)
    assert fc.parse("192.168.1.20:4000") == ("192.168.1.20", 4000, 0)
    assert fc.parse("my-pc.local") == ("my-pc.local", fc.GAME_PORT, 0)


def test_invitations_are_random_and_never_zero():
    seen = {fc.new_invitation() for _ in range(200)}
    assert 0 not in seen and len(seen) > 190
    assert all(0 < v <= 0xFFFFF for v in seen)


def test_own_network_addresses_are_trusted():
    for address in ("127.0.0.1", "192.168.0.4", "10.1.2.3", "172.16.5.5", "::1", "::ffff:192.168.1.2"):
        assert fc.trusted_address(address), address
    for address in ("203.0.113.7", "8.8.8.8", "", "nonsense"):
        assert not fc.trusted_address(address), address


# -- STUN --------------------------------------------------------------------------
def _stun_server(mapped=("203.0.113.9", 51000), xor=True):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(3)

    def serve():
        try:
            data, src = sock.recvfrom(2048)
        except OSError:
            return
        transaction = data[8:20]
        ip = struct.unpack("!I", socket.inet_aton(mapped[0]))[0]
        port = mapped[1]
        if xor:
            attr = struct.pack("!HHBBHI", 0x0020, 8, 0, 1, port ^ 0x2112, ip ^ 0x2112A442)
        else:
            attr = struct.pack("!HHBBHI", 0x0001, 8, 0, 1, port, ip)
        sock.sendto(struct.pack("!HHI", 0x0101, len(attr), 0x2112A442) + transaction + attr, src)
        sock.close()

    threading.Thread(target=serve, daemon=True).start()
    return sock.getsockname()


@pytest.mark.parametrize("xor", [True, False])
def test_stun_tells_the_public_address(xor):
    server = _stun_server(xor=xor)
    assert fc.stun_lookup(server, timeout=3, tries=1) == ("203.0.113.9", 51000)


def test_a_reply_to_someone_elses_request_is_ignored():
    reply = struct.pack("!HHI", 0x0101, 0, 0x2112A442) + b"x" * 12
    assert fc.stun_mapped_address(reply, b"y" * 12) is None
    assert fc.stun_mapped_address(b"short") is None


def test_the_stun_server_comes_from_settings():
    import configparser
    config = configparser.ConfigParser()
    assert fc.stun_server(None) == fc.DEFAULT_STUN
    assert fc.stun_server(config) == fc.DEFAULT_STUN
    config["Multiplayer"] = {"stun_server": "stun.example.org:3479"}
    assert fc.stun_server(config) == ("stun.example.org", 3479)
    config["Multiplayer"] = {"stun_server": ""}
    assert fc.stun_server(config) is None            # off


# -- where friends reach the party -------------------------------------------------
class _FakeMapping:
    def __init__(self, ip):
        self.external_ip = ip
        self.closed = False

    def close(self):
        self.closed = True


class _FakeUpnp:
    def __init__(self, mapping):
        self.mapping = mapping
        self.ports = []

    def open_port(self, port):
        self.ports.append(port)
        return self.mapping


def test_the_router_is_asked_first_and_opens_the_port():
    router = _FakeUpnp(_FakeMapping("198.51.100.4"))
    ip, how, mapping = fc.find_public_address(39745, upnp_module=router,
                                              stun=lambda _s: pytest.fail("no STUN needed"))
    assert (ip, how) == ("198.51.100.4", "router") and router.ports == [39745]
    assert mapping is router.mapping


def test_without_a_router_stun_gives_the_address():
    ip, how, mapping = fc.find_public_address(39745, upnp_module=_FakeUpnp(None),
                                              stun=lambda _s: ("203.0.113.50", 1234))
    assert (ip, how, mapping) == ("203.0.113.50", "stun", None)


def test_a_router_behind_another_router_is_not_trusted_for_the_address():
    inner = _FakeMapping("192.168.0.1")
    ip, how, _m = fc.find_public_address(39745, upnp_module=_FakeUpnp(inner),
                                         stun=lambda _s: ("203.0.113.50", 1234))
    assert how == "stun" and inner.closed


def test_with_nothing_found_the_code_is_for_this_network():
    import configparser
    config = configparser.ConfigParser()
    config["Multiplayer"] = {"stun_server": "", "upnp": "false"}
    ip, how, mapping = fc.find_public_address(39745, config,
                                              upnp_module=_FakeUpnp(_FakeMapping("1.2.3.4")),
                                              stun=lambda _s: pytest.fail("STUN is off"))
    assert how == "local" and mapping is None


# -- UPnP against a fake router on loopback -------------------------------------
def test_upnp_maps_the_port_and_takes_it_down_again(monkeypatch):
    calls = []
    service = upnp.SERVICES[1]

    class Router(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = (f'<?xml version="1.0"?><root xmlns="urn:schemas-upnp-org:device-1-0"><device>'
                    f'<deviceList><device><serviceList><service><serviceType>{service}</serviceType>'
                    f'<controlURL>/ctl</controlURL></service></serviceList></device></deviceList>'
                    f'</device></root>').encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            data = self.rfile.read(int(self.headers["Content-Length"])).decode()
            action = self.headers["SOAPAction"].strip('"').split("#")[1]
            calls.append((action, data))
            reply = ("<NewExternalIPAddress>198.51.100.77</NewExternalIPAddress>"
                     if action == "GetExternalIPAddress" else "")
            body = f"<s:Envelope><s:Body>{reply}</s:Body></s:Envelope>".encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.HTTPServer(("127.0.0.1", 0), Router)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/desc.xml"
        monkeypatch.setattr(upnp, "discover", lambda timeout=0: [url])
        mapping = upnp.open_port(39745)
        assert mapping is not None and mapping.external_ip == "198.51.100.77"
        add = next(d for a, d in calls if a == "AddPortMapping")
        assert "<NewExternalPort>39745</NewExternalPort>" in add and "<NewProtocol>TCP</NewProtocol>" in add
        mapping.close()
        assert calls[-1][0] == "DeletePortMapping"
    finally:
        server.shutdown()


def test_upnp_gives_up_quietly_without_a_router(monkeypatch):
    monkeypatch.setattr(upnp, "discover", lambda timeout=0: [])
    assert upnp.open_port(39745) is None


# -- the lobby: a code is the key from outside --------------------------------------
@pytest.fixture
def outside(monkeypatch):
    """Treat loopback as the Internet, so the lobby asks for the code."""
    monkeypatch.setattr(lobby_module.friend_code, "trusted_address", lambda _a: False)


def _party():
    server = host()
    server.invitation = fc.new_invitation()
    server.find_code(finder=lambda: ("203.0.113.7", "stun", None), wait=True)
    return server


def _guest_with(server, invitation, identity="b" * 64):
    from game.tests.test_multiplayer_network import ROOT
    from game.multiplayer.lobby import LobbyController
    client = LobbyController(ROOT, "maps/miniwind_world.json", identity=identity)
    client.opened = True
    client.signature = "matching-build"
    client.join_invitation = invitation
    client.join("127.0.0.1", server.network.port)
    return client


def test_the_host_gets_a_code_for_its_address_and_port():
    server = _party()
    try:
        assert fc.decode(server.code) == ("203.0.113.7", server.network.port, server.invitation)
        assert server.code_how == "stun"
    finally:
        server.close()


def test_joining_with_the_code_gets_in(outside):
    server = _party()
    client = _guest_with(server, server.invitation)
    try:
        advance([server, client], lambda: client.state is not None)
        assert len(server.peers) == 1
    finally:
        client.close()
        server.close()


def test_a_wrong_or_old_code_is_turned_away(outside):
    server = _party()
    old = server.invitation
    server.new_code()
    assert server.invitation != old and fc.decode(server.code)[2] == server.invitation
    client = _guest_with(server, old)
    try:
        advance([server, client], lambda: bool(client.errors), timeout=4)
        assert "out of date" in client.errors[0]
        assert not server.peers
    finally:
        client.close()
        server.close()


def test_guessing_codes_shuts_the_door_for_a_while(outside):
    server = _party()
    for guess in range(1, fc.WRONG_ALLOWED + 1):
        with pytest.raises(LobbyError):
            server._admit("p", "owner%d" % guess, (server.invitation + guess) & 0xFFFFF or 1)
    with pytest.raises(LobbyError, match="minute"):
        server._admit("p", "honest", server.invitation)
    server.close()


def test_the_own_network_needs_no_code():
    server = _party()
    client = _guest_with(server, 0)          # loopback: trusted
    try:
        advance([server, client], lambda: client.state is not None)
    finally:
        client.close()
        server.close()


def test_join_code_reads_the_code_and_shows_its_invitation():
    from game.tests.test_multiplayer_network import ROOT
    from game.multiplayer.lobby import LobbyController
    client = LobbyController(ROOT, "maps/miniwind_world.json", identity="c" * 64)
    client.opened = True
    seen = []
    client.join = lambda address, port: seen.append((address, port))
    client.join_code(fc.encode("203.0.113.7", 40001, 4242))
    assert seen == [("203.0.113.7", 40001)] and client.join_invitation == 4242
    with pytest.raises(LobbyError, match="typo"):
        client.join_code("AAAAA-AAAAA-AAAAB")
