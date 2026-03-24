"""Health-check endpoints."""

from __future__ import annotations

import structlog
from fastapi import APIRouter

from src.models.responses import HealthResponse

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.get(
    "/",
    response_model=HealthResponse,
    summary="Liveness probe",
    description="Returns 200 when the service process is alive.",
)
async def health_check() -> HealthResponse:
    logger.debug("health_check")
    return HealthResponse(status="ok", version="0.1.0")


@router.get(
    "/ready",
    response_model=HealthResponse,
    summary="Readiness probe",
    description="Returns 200 when the service is ready to accept traffic.",
)
async def readiness_check() -> HealthResponse:
    logger.debug("readiness_check")
    return HealthResponse(status="ok", version="0.1.0")
