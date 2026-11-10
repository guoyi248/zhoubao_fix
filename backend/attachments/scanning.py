"""将文件流提交给 ClamAV，只有明确的 OK 响应才放行。"""

import socket
import struct

from django.conf import settings

from common.exceptions import MalwareDetectedError, ScanUnavailableError


def scan_stream(stream):
    try:
        with socket.create_connection((settings.CLAMAV_HOST, settings.CLAMAV_PORT), timeout=30) as sock:
            sock.sendall(b"nINSTREAM\n")
            while chunk := stream.read(64 * 1024):
                sock.sendall(struct.pack("!I", len(chunk)) + chunk)
            sock.sendall(struct.pack("!I", 0))
            with sock.makefile("rb") as reply:
                result = reply.readline(4096).strip()
    except OSError as exc:
        raise ScanUnavailableError() from exc

    if result.endswith(b" FOUND"):
        raise MalwareDetectedError()
    if result != b"stream: OK":
        raise ScanUnavailableError()
