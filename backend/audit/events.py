"""以应用实际接收的连接记录来源，仅信任指定代理重写的地址。"""
from concurrent.futures import ThreadPoolExecutor, wait
from functools import lru_cache
from ipaddress import ip_address, ip_network
import logging
import socket
from threading import Lock
from time import monotonic

from django.conf import settings

from .models import AuditEvent

logger = logging.getLogger(__name__)
_USE_SESSION = object()
_PRIVATE_NETWORKS = tuple(ip_network(cidr) for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))
_proxy_resolver = ThreadPoolExecutor(max_workers=2, thread_name_prefix="audit-proxy-dns")
_dns_lock = Lock()
_host_lookups = {}
_DNS_TTL = 20.0
_DNS_RETRY = 5.0
_DNS_WAIT = 0.15


@lru_cache(maxsize=8)
def _networks(spec, labelled=False):
    result = []
    for part in filter(None, map(str.strip, spec.split(","))):
        cidr, _, label = part.partition("=")
        try:
            network = ip_network(cidr.strip(), strict=False)
        except ValueError:
            logger.warning("审计来源配置包含无效的网段")
            continue
        if not labelled or label.strip():
            result.append((network, label.strip()))
    return sorted(result, key=lambda item: -item[0].prefixlen)


def _ip(raw):
    try:
        value = ip_address(raw or "")
        return getattr(value, "ipv4_mapped", None) or value
    except ValueError:
        return None


def _resolve_host(host):
    try:
        records = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        addresses = {_ip(sockaddr[0]) for _, _, _, _, sockaddr in records}
        addresses.discard(None)
    except (OSError, UnicodeError, ValueError):
        addresses = set()
    return monotonic() + (_DNS_TTL if addresses else _DNS_RETRY), addresses


def _matches_proxy_host(peer):
    hosts = {name.strip() for name in settings.AUDIT_TRUSTED_PROXY_HOSTS.split(",") if name.strip()}
    pending = []
    with _dns_lock:
        for host in hosts:
            job = _host_lookups.get(host)
            if job is not None and job.done():
                expiry, addresses = job.result()
                if expiry > monotonic():
                    if peer in addresses:
                        return True
                    continue
                job = None
            if job is None:
                # 只解析服务端配置的主机名。一次解析由并发请求共享，慢 DNS 不占满请求线程。
                job = _host_lookups[host] = _proxy_resolver.submit(_resolve_host, host)
            pending.append(job)
    if not pending:
        return False
    completed, _ = wait(pending, timeout=_DNS_WAIT)
    return any(peer in job.result()[1] for job in completed)


def client_address(request):
    peer = _ip(request.META.get("REMOTE_ADDR"))
    if not peer:
        return None
    trusted_network = any(peer in net for net, _ in _networks(settings.AUDIT_TRUSTED_PROXIES))
    if trusted_network or _matches_proxy_host(peer):
        # 部署自带的 nginx 会覆盖 X-Real-IP。缺失/无效时不把代理机当作成员地点。
        return _ip(request.META.get("HTTP_X_REAL_IP"))
    return peer


def _city(address):
    if not settings.AUDIT_GEOIP_DATABASE:
        return ""
    try:
        from geoip2.database import Reader
        from geoip2.errors import GeoIP2Error
        from maxminddb.errors import InvalidDatabaseError
    except ImportError:
        logger.warning("离线 IP 归属地查询需要 geoip 扩展依赖")
        return ""
    try:
        with Reader(settings.AUDIT_GEOIP_DATABASE, locales=["zh-CN", "en"]) as reader:
            record = reader.city(str(address))
            names = (record.country.name, record.subdivisions.most_specific.name, record.city.name)
            return " · ".join(dict.fromkeys(filter(None, names)))
    except (GeoIP2Error, OSError, InvalidDatabaseError, ValueError):
        return ""


def location(address):
    if not address:
        return "来源未知"
    for network, label in _networks(settings.AUDIT_LOCATION_NETWORKS, labelled=True):
        if address in network:
            return label[:160]
    if address.is_loopback:
        return "本机回环"
    if address.is_link_local or any(address in network for network in _PRIVATE_NETWORKS):
        return "内网 · 具体地点未知"
    if not address.is_global:
        return "归属地未知"
    return (_city(address) or "归属地未知")[:160]


def record(request, event_type, summary="", *, actor=_USE_SESSION, target=None, result="success", risk="low"):
    address = client_address(request)
    if actor is _USE_SESSION:
        actor = request.user if request.user.is_authenticated else None
    return AuditEvent.objects.create(
        event_type=event_type, actor=actor, actor_ip=str(address) if address else None,
        actor_location=location(address), actor_user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
        target_type=target._meta.model_name if target else "", target_id=str(target.pk) if target else "",
        request_id=getattr(request, "request_id", ""), summary=summary, result=result, risk_level=risk,
    )


def record_report(request, event_type, report, detail):
    record(request, event_type, f"{report.reporting_period} · {detail}", target=report)
