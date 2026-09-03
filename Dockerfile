# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Stage 1: builder — install Python deps into a venv using uv
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# build-essential is required by some wheels (e.g. psycopg2-binary fallbacks)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv (pin via release script; uv itself manages its own version)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv

WORKDIR /app

# Copy lockfile + manifest first so dep layer caches independently of source
COPY pyproject.toml uv.lock ./

# Materialize .venv at /app/.venv from the frozen lockfile
RUN uv sync --no-dev --frozen --no-install-project


# ---------------------------------------------------------------------------
# Stage 2: runtime — minimal image with the Python venv and source
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src"

# Runtime libs only (libpq for psycopg2, ca-certs for outbound TLS)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1001 app \
    && useradd  --system --uid 1001 --gid app --home /app --shell /usr/sbin/nologin app

WORKDIR /app

# Python venv from the builder stage
COPY --from=builder --chown=app:app /app/.venv /app/.venv

# Application source
COPY --chown=app:app src/ /app/src/
COPY --chown=app:app pyproject.toml /app/pyproject.toml

# Writable working dirs the app expects to create at runtime
RUN mkdir -p /app/logs && chown -R app:app /app/logs

USER app

EXPOSE 8000

# Container-level healthcheck mirrors what docker-compose / k8s probes hit
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status==200 else 1)"

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
