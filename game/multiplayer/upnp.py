"""
Opening the party's port on the home router, by UPnP, so friends can join.

Most home routers let a program on the network ask for a port to be
forwarded to it (UPnP Internet Gateway Device). When the player hosts, this
asks for the party's TCP port, and asks the router for the address the world
sees it by; on leaving, it takes the forwarding down again. A router that
does not answer, or refuses, just means the player forwards the port by hand
(or plays on a LAN or VPN): :func:`open_port` returns None.

Plain stdlib (SSDP over UDP multicast, then HTTP and SOAP to the router's
own control address). Nothing is sent until the player hosts.
"""

from __future__ import annotations

import re
import socket
import urllib.parse
import urllib.request
from xml.etree import ElementTree

SSDP = ("239.255.255.250", 1900)
SERVICES = ("urn:schemas-upnp-org:service:WANIPConnection:2",
            "urn:schemas-upnp-org:service:WANIPConnection:1",
            "urn:schemas-upnp-org:service:WANPPPConnection:1")
DESCRIPTION = "MiniWind party"
#: Seconds to wait for a router to answer, and the mapping's lease (0 would
#: be permanent; a lease means a crash leaves nothing open for long).
DISCOVER_SECONDS = 1.5
LEASE_SECONDS = 4 * 3600


class Mapping:
    """A forwarded port: close() takes it down."""

    def __init__(self, control_url, service, port, internal_ip, external_ip, protocols=("TCP",)):
        self.control_url = control_url
        self.service = service
        self.port = port
        self.protocols = tuple(protocols)
        self.internal_ip = internal_ip
        self.external_ip = external_ip
        self.closed = False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for protocol in self.protocols:
            try:
                _soap(self.control_url, self.service, "DeletePortMapping",
                      (("NewRemoteHost", ""), ("NewExternalPort", self.port), ("NewProtocol", protocol)))
            except Exception:
                pass


def discover(timeout=DISCOVER_SECONDS):
    """The routers' description URLs that answered an SSDP search."""
    request = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
               "MAN: \"ssdp:discover\"\r\nMX: 1\r\n"
               "ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n").encode()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    found = []
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(timeout)
        sock.sendto(request, SSDP)
        while True:
            try:
                data, _src = sock.recvfrom(4096)
            except (socket.timeout, TimeoutError):
                break
            match = re.search(rb"(?im)^location:\s*(\S+)", data)
            if match:
                url = match.group(1).decode("latin-1")
                if url not in found:
                    found.append(url)
    except OSError:
        pass
    finally:
        sock.close()
    return found


def control_for(description_url, timeout=3.0):
    """``(control_url, service)`` of the router's WAN connection, or None."""
    with urllib.request.urlopen(description_url, timeout=timeout) as reply:
        xml = reply.read(256 * 1024)
    root = ElementTree.fromstring(xml)
    for node in root.iter():
        if not node.tag.endswith("service"):
            continue
        kind = control = None
        for child in node:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "serviceType":
                kind = (child.text or "").strip()
            elif tag == "controlURL":
                control = (child.text or "").strip()
        if kind in SERVICES and control:
            return urllib.parse.urljoin(description_url, control), kind
    return None


def _soap(control_url, service, action, args, timeout=3.0):
    body = "".join(f"<{k}>{v}</{k}>" for k, v in args)
    envelope = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
                f'<u:{action} xmlns:u="{service}">{body}</u:{action}></s:Body></s:Envelope>').encode()
    request = urllib.request.Request(control_url, data=envelope, method="POST", headers={
        "Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": f'"{service}#{action}"'})
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return reply.read(64 * 1024)


def _local_ip_towards(url) -> str:
    host = urllib.parse.urlparse(url).hostname or "10.255.255.255"
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((host, 1))
        return sock.getsockname()[0]
    finally:
        sock.close()


def open_port(port, timeout=DISCOVER_SECONDS, protocols=("UDP", "TCP")):
    """Forward *port* (UDP for friend codes, TCP for typed addresses) to this
    machine; the :class:`Mapping`, or None when the router would not."""
    for url in discover(timeout):
        try:
            found = control_for(url)
            if not found:
                continue
            control, service = found
            internal = _local_ip_towards(control)
            mapped = []
            for protocol in protocols:
                try:
                    _soap(control, service, "AddPortMapping", (
                        ("NewRemoteHost", ""), ("NewExternalPort", int(port)),
                        ("NewProtocol", protocol), ("NewInternalPort", int(port)),
                        ("NewInternalClient", internal), ("NewEnabled", 1),
                        ("NewPortMappingDescription", DESCRIPTION),
                        ("NewLeaseDuration", LEASE_SECONDS)))
                    mapped.append(protocol)
                except Exception:
                    continue
            if not mapped:
                continue
            external = ""
            try:
                reply = _soap(control, service, "GetExternalIPAddress", ())
                match = re.search(rb"<NewExternalIPAddress>([^<]*)<", reply)
                external = match.group(1).decode().strip() if match else ""
            except Exception:
                external = ""
            return Mapping(control, service, int(port), internal, external, mapped)
        except Exception:
            continue
    return None
