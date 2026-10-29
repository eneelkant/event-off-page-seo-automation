FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MCP_TRANSPORT=streamable-http \
    MCP_HTTP_HOST=0.0.0.0 \
    MCP_HTTP_PORT=8000 \
    MCP_ALLOW_REMOTE_BIND=true \
    AI_PROVIDER=template \
    DRY_RUN_DEFAULT=true \
    REQUIRE_PUBLICATION_AUTHORIZATION=true \
    REPO_ROOT=/app \
    DATABASE_PATH=/app/data/runtime/event_seo.db \
    PLATFORMS_CONFIG_PATH=/app/config/platforms.json

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY config ./config
COPY data ./data
COPY scripts ./scripts

RUN pip install --upgrade pip && pip install ".[browser]" \
    && mkdir -p /app/data/runtime /app/data/evidence /app/data/browser-sessions \
    && python scripts/init_db.py

# MCP_AUTH_TOKEN must be provided at runtime for non-localhost production binds.
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

CMD ["python", "-m", "event_seo_mcp.server", "--http"]
