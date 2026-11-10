from ipaddress import ip_address
import socket
from threading import Event

from django.test import RequestFactory

from audit import events


def source(peer, **headers):
    request = RequestFactory().get("/", REMOTE_ADDR=peer, **headers)
    return events.client_address(request)


def test_hostname_only_trusts_the_resolved_peer(monkeypatch, settings):
    host = "nginx-for-audit"
    settings.AUDIT_TRUSTED_PROXIES = ""
    settings.AUDIT_TRUSTED_PROXY_HOSTS = host
    calls = []

    def resolve(name, port, type):
        calls.append(name)
        return [(socket.AF_INET, type, 0, "", ("172.20.1.3", 0)),
                (socket.AF_INET6, type, 0, "", ("fd00::3", 0, 0, 0))]

    monkeypatch.setattr(events.socket, "getaddrinfo", resolve)
    headers = {"HTTP_X_REAL_IP": "10.22.2.8", "HTTP_X_FORWARDED_FOR": "8.8.8.8",
               "HTTP_X_FORWARDED_HOST": host, "HTTP_HOST": host}
    assert source("172.20.1.7", **headers) == ip_address("172.20.1.7")
    assert source("172.20.1.3", **headers) == ip_address("10.22.2.8")
    assert source("fd00::3", **headers) == ip_address("10.22.2.8")
    assert source("::ffff:172.20.1.3", HTTP_X_FORWARDED_FOR="8.8.8.8") is None
    assert calls == [host]


def test_expired_addresses_are_distrusted_even_if_dns_fails(monkeypatch, settings):
    host = "nginx-for-dns-failure"
    settings.AUDIT_TRUSTED_PROXIES = ""
    settings.AUDIT_TRUSTED_PROXY_HOSTS = host
    answers = iter(["172.18.0.2", None, "172.18.0.5"])
    now = [100.0]

    def resolve(name, port, type):
        assert name == host
        address = next(answers)
        if address is None:
            raise socket.gaierror("DNS unavailable")
        return [(socket.AF_INET, type, 0, "", (address, 0))]

    monkeypatch.setattr(events, "monotonic", lambda: now[0])
    monkeypatch.setattr(events.socket, "getaddrinfo", resolve)
    headers = {"HTTP_X_REAL_IP": "10.22.2.8"}
    assert source("172.18.0.2", **headers) == ip_address("10.22.2.8")
    now[0] += events._DNS_TTL + 1
    assert source("172.18.0.2", **headers) == ip_address("172.18.0.2")
    assert source("172.18.0.2", **headers) == ip_address("172.18.0.2")
    now[0] += events._DNS_RETRY + 1
    assert source("172.18.0.5", **headers) == ip_address("10.22.2.8")
    assert source("172.18.0.2", **headers) == ip_address("172.18.0.2")


def test_slow_lookup_is_bounded_and_shared(monkeypatch, settings):
    host = "nginx-for-slow-dns"
    settings.AUDIT_TRUSTED_PROXIES = ""
    settings.AUDIT_TRUSTED_PROXY_HOSTS = host
    unblock = Event()
    calls = []

    def resolve(name, port, type):
        calls.append(name)
        assert unblock.wait(3)
        return [(socket.AF_INET, type, 0, "", ("172.30.0.3", 0))]

    monkeypatch.setattr(events, "_DNS_WAIT", 0.01)
    monkeypatch.setattr(events.socket, "getaddrinfo", resolve)
    headers = {"HTTP_X_REAL_IP": "10.22.2.8"}
    try:
        # Returns before the lookup completes; the unverified peer cannot supply a client IP.
        for _ in range(2):
            assert source("172.30.0.3", **headers) == ip_address("172.30.0.3")
    finally:
        unblock.set()
        events._host_lookups[host].result(timeout=3)
    assert source("172.30.0.3", **headers) == ip_address("10.22.2.8")
    assert calls == [host]
