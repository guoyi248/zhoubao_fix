# ── Worker 镜像：API 镜像 + LibreOffice + 中文字体 + 解析工具 ──
FROM python:3.13-slim-bookworm AS worker

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUTF8=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# bookworm-backports 提供 LibreOffice 25.2 系列
RUN echo "deb http://deb.debian.org/debian bookworm-backports main" \
      > /etc/apt/sources.list.d/bookworm-backports.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      libpq5 \
      libmagic1 \
      ca-certificates \
      fontconfig \
      poppler-utils \
      fonts-noto-cjk \
      fonts-noto-core \
      fonts-liberation \
      fonts-crosextra-carlito \
      fonts-crosextra-caladea \
 && apt-get install -y --no-install-recommends \
      -t bookworm-backports \
      libreoffice-nogui \
      libreoffice-l10n-zh-cn \
 && fc-cache -f \
 && soffice --headless --version \
 && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 app \
 && useradd --uid 10001 --gid app --create-home app

WORKDIR /app
COPY pyproject.toml .
COPY backend/ backend/
RUN pip install --no-cache-dir -e .

USER app
CMD ["celery", "-A", "config", "worker", "-Q", "default,preview,ai", "--loglevel=INFO"]
