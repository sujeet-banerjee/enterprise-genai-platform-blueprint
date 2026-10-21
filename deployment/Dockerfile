# syntax=docker/dockerfile:1
#
# Enterprise GenAI Platform - hardened multi-stage image (issue #65 / G0).
#
# Build:  docker build -f deployment/Dockerfile -t enterprise-genai-platform:local .
# Run:    docker run -p 8000:8000 -v genai-hf-cache:/app/.cache/huggingface enterprise-genai-platform:local
#
# Variants (build args):
#   INSTALL_EXTRAS=""            # default: core runtime only (lean)
#   INSTALL_EXTRAS=".[observability]"   # + Prometheus client + OTel OTLP export
#   TORCH_INDEX_URL="https://download.pytorch.org/whl/cpu"  # CPU default; override for CUDA
#
# Config is read from /app/config by default; mount a ConfigMap and point
# GENAI_CONFIG_DIR at it to override without rebuilding.

# ---------------------------------------------------------------------------
# Builder: install dependencies into an isolated virtualenv.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

ARG INSTALL_EXTRAS=""
ARG TORCH_INDEX_URL="https://download.pytorch.org/whl/cpu"

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv

RUN python -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /build
COPY requirements.txt pyproject.toml README.md ./
# Install the app's declared dependencies (CPU wheels by default).
RUN pip install --upgrade pip && \
    pip install --extra-index-url "$TORCH_INDEX_URL" -r requirements.txt && \
    pip install --extra-index-url "$TORCH_INDEX_URL" ${INSTALL_EXTRAS:-.} || \
    pip install --extra-index-url "$TORCH_INDEX_URL" -r requirements.txt

# ---------------------------------------------------------------------------
# Runtime: slim image, non-root, healthchecked.
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    HF_HOME=/app/.cache/huggingface \
    GENAI_CONFIG_DIR=/app/config

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 10001 appuser && \
    useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin appuser

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY app ./app
COPY core ./core
COPY config ./config
COPY data ./data
COPY pyproject.toml README.md ./

# Writable caches for the non-root user (model downloads + OTel/HF).
RUN mkdir -p "$HF_HOME" && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
