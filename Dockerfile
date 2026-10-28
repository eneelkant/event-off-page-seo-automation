FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MCP_TRANSPORT=streamable-http \
    MCP_HTTP_HOST=127.0.0.1 \
    MCP_HTTP_PORT=8000 \
    AI_PROVIDER=template \
    DRY_RUN_DEFAULT=true

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY config ./config
COPY data ./data
COPY scripts ./scripts

RUN pip install --upgrade pip && pip install ".[browser,dev]"

# Optional Playwright browsers — install when browser extras are needed at runtime:
# RUN playwright install --with-deps chromium

RUN mkdir -p /app/data/runtime /app/data/evidence /app/data/browser-sessions \
    && python scripts/init_db.py

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/mcp')" || exit 1

CMD ["python", "-m", "event_seo_mcp.server", "--http"]
