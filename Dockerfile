FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8501 \
    FRIC_WORKSPACE=/data \
    FRIC_AUTH_REQUIRED=1 \
    FRIC_HOSTED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 fric \
    && useradd --uid 10001 --gid fric --create-home fric \
    && mkdir -p /data \
    && chown fric:fric /data

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/requirements.txt

# Only application sources enter the image. Local databases, .env and OAuth files
# are excluded both here and by the restrictive .dockerignore allowlist.
COPY app.py core.py research.py public_search.py publication_dates.py settings.py \
    google_docs_sync.py visuals.py access_control.py ai_client.py STYLE_GUIDE.md /app/
COPY deploy/entrypoint.py /app/deploy/entrypoint.py

USER 10001:10001
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8501') + '/_stcore/health', timeout=3)"
CMD ["python", "/app/deploy/entrypoint.py"]
