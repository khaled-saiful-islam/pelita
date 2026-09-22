# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl git \
 && rm -rf /var/lib/apt/lists/*

# Dependencies first so application edits do not invalidate the layer.
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . \
 && pip install --no-cache-dir pytest pytest-asyncio pytest-cov ruff

# Chromium, for exporting a poster as a picture. It is the largest thing in
# this image by some way; set ARTIFACT_EXPORT_PNG=false and skip this line if a
# deployment only ever needs the HTML.
RUN playwright install --with-deps chromium

# The news MCP server, pinned by commit. It imports mcp.server.fastmcp, which
# only exists in mcp<2, while the backend client runs mcp 2.x — verified to
# interoperate over stdio. Its own virtualenv keeps the two versions apart
# instead of holding the whole backend back a major version.
ARG MCP_NEWS_REF=a454db6295776f936146472d660c595f9b9449a1
RUN python -m venv /opt/mcp-news \
 && /opt/mcp-news/bin/pip install --no-cache-dir \
      "google-news-mcp @ git+https://github.com/moltrus/google-news-mcp@${MCP_NEWS_REF}" \
      "mcp<2" \
 && /opt/mcp-news/bin/python -c "import google_news_mcp.server"

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY tests ./tests
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
