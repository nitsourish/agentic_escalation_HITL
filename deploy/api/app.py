"""
FastAPI REST API for the Agentic Escalation Detector.

Endpoints:
  POST /v1/escalation/check  — evaluate a conversation history
  GET  /health               — ALB / readiness health check
  GET  /v1/config            — return active runtime configuration
"""

from __future__ import annotations

import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Bootstrap: make the escalation package importable.
#
# Two layouts need to work:
#   Container : /app/app.py  +  /app/escalation_detector/   → parent / "escalation_detector"
#   Local dev : deploy/api/app.py  +  escalation_detector/  → parents[1] / "escalation_detector"
_here = Path(__file__).resolve().parent
_REPO_ROOT = _here / "escalation_detector"                      # container path (checked first)
if not _REPO_ROOT.exists() and len(_here.parents) >= 2:
    _REPO_ROOT = _here.parents[1] / "escalation_detector"       # local dev path

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from escalation import EscalationDetector, Message  # noqa: E402
from escalation.config import load_llm_config  # noqa: E402
from escalation.llm_classifier import create_classifier  # noqa: E402
from escalation.rules import RuleEngine, load_intent_classifier  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("escalation_api")

# ---------------------------------------------------------------------------
# Shared detector — held in a single-item list to avoid module-level mutation
# ---------------------------------------------------------------------------
_detector_holder: list[EscalationDetector] = []


def _get_detector() -> EscalationDetector | None:
    """Return the initialised detector, or None if startup has not finished."""
    return _detector_holder[0] if _detector_holder else None


def _build_detector() -> EscalationDetector:
    """Construct the two-tier detector from environment config."""
    skip_nli = os.getenv("SKIP_NLI", "false").lower() == "true"
    llm_only = os.getenv("LLM_ONLY", "false").lower() == "true"
    intent = None if (skip_nli or llm_only) else load_intent_classifier()
    rule_engine = None if llm_only else RuleEngine(intent_classifier=intent)
    llm = create_classifier(load_llm_config())
    return EscalationDetector(rule_engine=rule_engine, llm_classifier=llm)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Initialise the detector on startup; clean up on shutdown."""
    logger.info("Initialising escalation detector …")
    _detector_holder.append(_build_detector())
    logger.info("Escalation detector ready.")
    yield
    _detector_holder.clear()
    logger.info("Shutting down.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Agentic Escalation Detector API",
    description=(
        "Predict whether a customer support conversation "
        "should be escalated to a human agent."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
class MessageIn(BaseModel):
    """A single conversation turn."""

    role: Literal["user", "bot"]
    message: str = Field(..., min_length=1, max_length=4096)


class CheckRequest(BaseModel):
    """Payload for POST /v1/escalation/check."""

    conversation_id: str | None = Field(
        None, description="Optional caller-supplied identifier for logging."
    )
    history: list[MessageIn] = Field(
        ..., min_length=1, description="Full conversation history, oldest first."
    )


class EscalationResult(BaseModel):
    """Escalation decision returned by the detector."""

    escalate: bool
    tier: Literal["rules", "llm"]
    reason: str
    confidence: float
    latency_ms: float


class HealthResponse(BaseModel):
    """Response for GET /health."""

    status: Literal["ok"]
    version: str


class ConfigResponse(BaseModel):
    """Response for GET /v1/config."""

    llm_provider: str
    llm_only: bool
    skip_nli: bool
    confidence_threshold: float


# ---------------------------------------------------------------------------
# Middleware — request logging
# ---------------------------------------------------------------------------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log method, path, status code and wall-clock latency for every request."""
    t0 = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "%s %s → %d  %.1f ms",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse, tags=["ops"])
async def health() -> HealthResponse:
    """ALB health-check endpoint. Returns 200 while the detector is loaded."""
    detector = _get_detector()
    if detector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Detector not ready",
        )
    return HealthResponse(status="ok", version=app.version)


@app.get("/v1/config", response_model=ConfigResponse, tags=["ops"])
async def get_config() -> ConfigResponse:
    """Return active runtime configuration (no secrets)."""
    return ConfigResponse(
        llm_provider=os.getenv("LLM_PROVIDER", "openai"),
        llm_only=os.getenv("LLM_ONLY", "false").lower() == "true",
        skip_nli=os.getenv("SKIP_NLI", "false").lower() == "true",
        confidence_threshold=float(os.getenv("LLM_CONFIDENCE_THRESHOLD", "0.7")),
    )


@app.post("/v1/escalation/check", response_model=EscalationResult, tags=["escalation"])
async def check_escalation(body: CheckRequest) -> EscalationResult:
    """
    Evaluate the conversation history and decide whether to escalate.

    The full history must be provided on every call (stateless service).
    Pass the history up to and including the latest user message.
    """
    detector = _get_detector()
    if detector is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Detector not ready",
        )

    if not any(m.role == "user" for m in body.history):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="History must contain at least one user message.",
        )

    messages = [Message(role=m.role, message=m.message) for m in body.history]

    t0 = time.perf_counter()
    try:
        decision = detector.check(messages)
    except Exception as exc:
        logger.exception("Detector error for conversation %s", body.conversation_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Detector error: {exc}",
        ) from exc
    latency_ms = (time.perf_counter() - t0) * 1000

    logger.info(
        "conv=%s escalate=%s tier=%s conf=%.2f latency=%.1fms",
        body.conversation_id or "—",
        decision.escalate,
        decision.tier,
        decision.confidence,
        latency_ms,
    )

    return EscalationResult(
        escalate=decision.escalate,
        tier=decision.tier,
        reason=decision.reason,
        confidence=decision.confidence,
        latency_ms=round(latency_ms, 1),
    )


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, _exc: Exception):
    """Catch-all handler — log and return a generic 500."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        workers=int(os.getenv("WORKERS", "2")),
        log_level="info",
    )
