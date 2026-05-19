# ── Stage 1: builder ────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create a venv so packages are self-contained and Python can always find them
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL maintainer="ML Engineering"
LABEL org.opencontainers.image.title="Agentic Escalation Detector API"
LABEL org.opencontainers.image.description="REST API for the two-tier escalation detection pipeline"

# Non-root user for security
RUN groupadd --gid 1001 appgroup && \
    useradd  --uid 1001 --gid appgroup --no-create-home appuser

WORKDIR /app

# Copy the entire venv from builder — Python finds all packages automatically
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH" \
    VIRTUAL_ENV="/venv" \
    HF_HOME=/app/.hf_cache \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# Copy the escalation library
COPY escalation_detector/ ./escalation_detector/

# Copy the API entrypoint
COPY deploy/api/app.py ./app.py

RUN mkdir -p /app/.hf_cache && chown -R appuser:appgroup /app

USER appuser

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "app:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--workers", "2", \
     "--log-level", "info"]
