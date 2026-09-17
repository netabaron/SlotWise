# SlotWise — API image.
#
# Serves the catalog. Does not scrape: wsgi.py pins allow_network=False and the
# live-scrape endpoints are gone (HOSTING_NOTES.md §1). That is what lets this
# image install requirements.txt alone and skip Playwright entirely.
#
#     docker build -t slotwise .
#     docker run --rm -p 8000:8000 slotwise
#
# See DEPLOY.md for env vars and for mounting a rebuilt catalog.

FROM python:3.12-slim

# Hebrew is everywhere in this codebase, including file contents and log lines.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    SLOTWISE_CATALOG_DIR=/app/data/catalog

WORKDIR /app

# Requirements first, as their own layer: application edits should not force a
# full dependency reinstall on every build.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code. .dockerignore keeps out data/raw (16 MB of scraped HTML),
# data/db (21 MB of one machine's store), data/.browser_profile (29 MB, and it
# holds live session cookies), data/profile.json, tests, and the shnaton PDFs.
# What does come in is data/catalog/ — catalog.jsonl + catalog.meta.json, the
# 572-course catalog this image serves — plus the curriculum/program JSONs.
COPY . .

# Non-root. Created after COPY so the chown covers everything in one layer.
# data/db must exist and be writable even though the hosted app only reads it:
# Store builds its paths at construction time, and a missing directory turns
# into a startup failure rather than an empty database.
RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 slotwise \
    && mkdir -p /app/data/db /app/data/raw /app/data/catalog \
    && chown -R slotwise:slotwise /app

USER slotwise

EXPOSE 8000

# Fails the container if the app stops serving. Uses urllib rather than curl so
# the slim image does not need another package. /api/catalog/meta is the right
# probe: it touches the catalog, so it fails if the data did not load, not just
# if the port is open.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/api/catalog/meta', timeout=4)"]

CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
