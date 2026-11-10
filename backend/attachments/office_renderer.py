"""用独立的 LibreOffice 实例排版，每次转换使用自己的输入、输出与配置目录。"""

import os
import shutil
import signal
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings


def libreoffice_binary():
    configured = os.environ.get("LIBREOFFICE_BINARY")
    if configured:
        return shutil.which(configured)
    if os.name == "nt":
        for name in ("soffice.com", "soffice.exe"):
            for folder in ("ProgramFiles", "ProgramFiles(x86)"):
                root = os.environ.get(folder)
                if root and (binary := Path(root, "LibreOffice", "program", name)).is_file():
                    return str(binary)
            if binary := shutil.which(name):
                return binary
    return shutil.which("soffice") or shutil.which("libreoffice")


def convert_with_libreoffice(data, extension):
    binary = libreoffice_binary()
    if not binary:
        return None

    with TemporaryDirectory(prefix="weekly-office-", ignore_cleanup_errors=True) as directory:
        root = Path(directory).resolve()
        source = root / ("source" + extension)
        source.write_bytes(data)
        profile = root / "profile"
        (profile / "user").mkdir(parents=True)
        (profile / "user" / "registrymodifications.xcu").write_text(
            '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop>'
            '<prop oor:name="DisableActiveContent" oor:op="fuse"><value>true</value></prop>'
            '<prop oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>true</value></prop>'
            '</item></oor:items>', encoding="utf-8",
        )
        windows = os.name == "nt"
        with subprocess.Popen(
            [binary, "-env:UserInstallation=" + profile.as_uri(), "--headless", "--norestore",
             "--convert-to", "pdf", "--outdir", str(root), str(source)],
            cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=not windows, creationflags=subprocess.CREATE_NO_WINDOW if windows else 0,
        ) as job:
            try:
                status = job.wait(timeout=settings.PREVIEW_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                # soffice 启动器还会派生 soffice.bin。只清理本次作业的进程树。
                if windows:
                    subprocess.run(["taskkill", "/PID", str(job.pid), "/T", "/F"], check=False,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    try:
                        os.killpg(job.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                job.kill()
                raise
        result = root / "source.pdf"
        return result.read_bytes() if status == 0 and result.is_file() else None
