# ── Stage 1: builder ────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies into a separate prefix so we can copy cleanly
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL maintainer="ML Engineering"
LABEL org.opencontainers.image.title="Agentic Escalation Detector API"
LABEL org.opencontainers.image.description="REST API for the two-tier escalation detection pipeline"

# Non-root user for security
RUN groupadd --gid 1001 appgroup && \
    useradd  --uid 1001 --gid appgroup --no-create-home appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy the escalation library
COPY escalation_detector/ ./escalation_detector/

# Copy the API entrypoint
COPY deploy/api/app.py ./app.py

# Hugging Face cache inside the container (model downloaded at cold-start or
# pre-baked via a separate model-warm image)
ENV HF_HOME=/app/.hf_cache \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

RUN mkdir -p /app/.hf_cache && chown -R appuser:appgroup /app

USER appuser

EXPOSE 8080

# Tini not available in slim; use exec form directly so PID 1 handles signals
CMD ["python", "-m", "uvicorn", "app:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--workers", "2", \
     "--log-level", "info"]
