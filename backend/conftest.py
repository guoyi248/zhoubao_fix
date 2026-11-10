from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

import pytest


@pytest.fixture
def local_files(monkeypatch):
    """真实读写临时文件，完整覆盖上传、转换及预览使用的存储路径。"""
    from common.storage import LocalStorage
    with TemporaryDirectory(prefix="weekly-report-test-") as folder:
        monkeypatch.setattr("common.storage.LOCAL_ROOT", Path(folder))
        monkeypatch.delenv("GOTENBERG_URL", raising=False)
        files = Mock(wraps=LocalStorage())
        for name in ("attachments.views.storage", "attachments.services.storage", "attachments.tasks.storage",
                     "common.storage.storage"):
            monkeypatch.setattr(name, files)
        yield files
