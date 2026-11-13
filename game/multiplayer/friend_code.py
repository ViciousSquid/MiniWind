"""
Friend codes: invite friends over the Internet with one short code.

The host presses **Host game** and gets a code such as ``7K2QD-M4XA9-0RT3V``;
a friend pastes it into **Join with a code** and is in the party. No server
looks anything up -- the code *is* the address, as in Dosidicus:

* 15 Crockford base32 characters (75 bits), shown in groups of five; case,
  spaces and dashes do not matter, and I / L / O read as 1 / 1 / 0;
* a 2-bit version (:data:`VERSION` -- a code from another game or an older
  MiniWind is refused with a clear word, not misread);
* the host's public IPv4 address (32 bits) and the party's TCP port (16);
* a 20-bit random **invitation**: a joiner from outside the host's own
  network must show it, so the code is also the key (``New code`` makes a
  fresh one; friends already in stay in);
* a check character that catches any one mistyped character and any two
  neighbours swapped.

A typed ``1.2.3.4`` or ``1.2.3.4:39745`` still works (no invitation: only
for the host's own network, or a host that admits it).

How the host learns its public address (:func:`find_public_address`), in
order: the router itself, by UPnP (:mod:`game.multiplayer.upnp`, which also
opens the port so friends can reach it); then a STUN server's word
(``[Multiplayer] stun_server``, Google's public one by default); failing
both, the machine's own LAN address, which works on the same network or a
VPN. Nothing is sent anywhere until the player hosts.

Pure stdlib; the codec and STUN parsing are tested headless.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import struct

from .transport import GAME_PORT

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_READ_AS = {"I": "1", "L": "1", "O": "0", "U": "V"}
#: This game's code version (Dosidicus uses 2; anything else is refused).
VERSION = 3
LENGTH = 15
GROUP = 5
#: How many different wrong invitations an outside address may try in
#: :data:`WRONG_WINDOW` seconds before code joins are shut for that long.
WRONG_ALLOWED = 8
WRONG_WINDOW = 60.0
#: STUN server used when settings.ini names none.
DEFAULT_STUN = ("stun.l.google.com", 19302)


class FriendCodeError(ValueError):
    """A code that cannot be read; the message is fit to show the player."""


def new_invitation() -> int:
    """A fresh random invitation, never 0 (0 means "no invitation")."""
    while True:
        value = int.from_bytes(os.urandom(3), "big") & 0xFFFFF
        if value:
            return value


def _check(values) -> int:
    """A check character over GF(32): the sum of each value times its own
    weight (2, 3, 4 ... as field elements; the check character itself has
    weight 1). Every weight differs and none is 0, so any single wrong
    character, and any two different neighbours swapped -- the check
    character too -- leaves the sum wrong."""
    def mul(a, b):
        out = 0
        for _ in range(5):
            if b & 1:
                out ^= a
            b >>= 1
            a <<= 1
            if a & 0x20:
                a ^= 0x25          # x^5 + x^2 + 1
        return out
    total = 0
    for i, v in enumerate(values):
        total ^= mul(v, i + 2)
    return total


def encode(ip: str, port: int, invitation: int) -> str:
    """The friend code for *ip* (IPv4) and *port*, with *invitation*."""
    address = int(ipaddress.IPv4Address(ip))
    if not 0 < int(port) < 65536:
        raise FriendCodeError("That port cannot be in a code.")
    bits = (VERSION << 68) | (address << 36) | (int(port) << 20) | (int(invitation) & 0xFFFFF)
    values = [(bits >> (5 * (13 - i))) & 31 for i in range(14)]
    values.append(_check(values))
    text = "".join(ALPHABET[v] for v in values)
    return "-".join(text[i:i + GROUP] for i in range(0, LENGTH, GROUP))


def decode(text: str):
    """``(ip, port, invitation)`` from a code, or :class:`FriendCodeError`."""
    raw = "".join(ch for ch in str(text).upper() if ch not in " -_\t\r\n")
    raw = "".join(_READ_AS.get(ch, ch) for ch in raw)
    if not raw:
        raise FriendCodeError("Paste a friend code first.")
    bad = [ch for ch in raw if ch not in ALPHABET]
    if bad:
        raise FriendCodeError(f"'{bad[0]}' is not part of a friend code.")
    if len(raw) != LENGTH:
        raise FriendCodeError(f"A friend code has {LENGTH} letters and digits; this one has {len(raw)}.")
    values = [ALPHABET.index(ch) for ch in raw]
    if _check(values[:-1]) != values[-1]:
        raise FriendCodeError("That code has a typo in it: check it letter by letter.")
    bits = 0
    for v in values[:-1]:
        bits = (bits << 5) | v
    if bits >> 68 != VERSION:
        raise FriendCodeError("That code is not a MiniWind code, or is from another version.")
    ip = str(ipaddress.IPv4Address((bits >> 36) & 0xFFFFFFFF))
    port = (bits >> 20) & 0xFFFF
    invitation = bits & 0xFFFFF
    if not port:
        raise FriendCodeError("That code has no port in it.")
    return ip, port, invitation


def parse(text: str):
    """A friend code, or a typed ``host[:port]``: ``(host, port, invitation)``
    (invitation 0 for an address)."""
    text = str(text).strip()
    if not text:
        raise FriendCodeError("Paste a friend code first.")
    compact = "".join(_READ_AS.get(ch, ch) for ch in text.upper() if ch not in " -_\t")
    looks_like_code = len(compact) == LENGTH and all(ch in ALPHABET for ch in compact)
    if looks_like_code or not ("." in text or ":" in text):
        return decode(text)
    head, sep, tail = text.rpartition(":")
    if sep and tail.isdigit() and head.count(":") == 0:
        host, port = head, int(tail)
    else:
        host, port = text, GAME_PORT
    if not 0 < port < 65536:
        raise FriendCodeError("That port is out of range.")
    return host, port, 0


#: The host's own network: private ranges, this machine, link-local.
_OWN_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16",
    "::1/128", "fc00::/7", "fe80::/10"))


def trusted_address(address) -> bool:
    """The host's own network (or this machine): joins without a code."""
    try:
        ip = ipaddress.ip_address(str(address).split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(ip.version == net.version and ip in net for net in _OWN_NETWORKS)


# -- STUN (RFC 5389): the address the world sees ---------------------------------
_MAGIC = 0x2112A442


def stun_request(transaction: bytes = None) -> bytes:
    """A binding request (20 bytes)."""
    transaction = transaction or os.urandom(12)
    return struct.pack("!HHI", 0x0001, 0, _MAGIC) + transaction


def stun_mapped_address(data: bytes, transaction: bytes = None):
    """``(ip, port)`` from a binding response, or None."""
    if len(data) < 20:
        return None
    kind, length, magic = struct.unpack("!HHI", data[:8])
    if kind != 0x0101 or magic != _MAGIC:
        return None
    if transaction is not None and data[8:20] != transaction:
        return None
    body = data[20:20 + length]
    found = None
    i = 0
    while i + 4 <= len(body):
        attr, size = struct.unpack("!HH", body[i:i + 4])
        value = body[i + 4:i + 4 + size]
        if attr in (0x0020, 0x0001) and len(value) >= 8 and value[1] == 0x01:
            port = struct.unpack("!H", value[2:4])[0]
            raw = struct.unpack("!I", value[4:8])[0]
            if attr == 0x0020:                  # XOR-MAPPED-ADDRESS
                port ^= _MAGIC >> 16
                raw ^= _MAGIC
                return str(ipaddress.IPv4Address(raw)), port
            found = (str(ipaddress.IPv4Address(raw)), port)
        i += 4 + size + ((4 - size % 4) % 4)
    return found


def stun_lookup(server=DEFAULT_STUN, timeout=2.5, tries=3):
    """The public ``(ip, port)`` a STUN server sees this machine as, or None."""
    host, port = server
    try:
        destination = socket.getaddrinfo(host, int(port), socket.AF_INET, socket.SOCK_DGRAM)[0][4]
    except (OSError, ValueError):
        return None
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout / max(1, tries))
        for _ in range(max(1, tries)):
            transaction = os.urandom(12)
            try:
                sock.sendto(stun_request(transaction), destination)
                while True:
                    data, _src = sock.recvfrom(2048)
                    found = stun_mapped_address(data, transaction)
                    if found:
                        return found
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                return None
        return None
    finally:
        sock.close()


def stun_server(config) -> tuple:
    """``[Multiplayer] stun_server`` as (host, port); empty turns STUN off
    (returns None)."""
    value = None
    if config is not None:
        try:
            value = config.get("Multiplayer", "stun_server", fallback=None)
        except Exception:
            value = None
    if value is None:
        return DEFAULT_STUN
    value = value.strip()
    if not value:
        return None
    host, sep, port = value.rpartition(":")
    if sep and port.isdigit():
        return host, int(port)
    return value, 3478


def local_address() -> str:
    """This machine's address on its own network (no packet is sent)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def find_public_address(port, config=None, upnp_module=None, stun=stun_lookup):
    """Where friends can reach a party on TCP *port*: ``(ip, how, mapping)``.

    *how* is ``"router"`` (UPnP gave the address and opened the port),
    ``"stun"`` (the address is right; the port may need forwarding) or
    ``"local"`` (this network or a VPN only). *mapping* is the UPnP mapping
    to remove on leaving, or None."""
    use_upnp = True
    if config is not None:
        try:
            use_upnp = config.getboolean("Multiplayer", "upnp", fallback=True)
        except Exception:
            use_upnp = True
    if use_upnp:
        if upnp_module is None:
            from . import upnp as upnp_module
        try:
            mapping = upnp_module.open_port(int(port))
        except Exception:
            mapping = None
        if mapping is not None and mapping.external_ip and not trusted_address(mapping.external_ip):
            return mapping.external_ip, "router", mapping
        if mapping is not None:
            try:
                mapping.close()
            except Exception:
                pass
    server = stun_server(config)
    if server is not None:
        found = stun(server)
        if found and not trusted_address(found[0]):
            return found[0], "stun", None
    return local_address(), "local", None
