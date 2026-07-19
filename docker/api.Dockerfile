# ── API 镜像：Python + Django，不含 LibreOffice ─────────────────
FROM python:3.13-slim-bookworm AS runtime

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUTF8=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      libpq5 \
      libmagic1 \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 app \
 && useradd --uid 10001 --gid app --create-home app

WORKDIR /app
COPY --chown=app:app backend/ /app/
RUN pip install --no-cache-dir -e /app/..

USER app
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
