"""Top-level API router — aggregates all sub-routers."""

from fastapi import APIRouter

from src.api.agent import router as agent_router
from src.api.grafana import router as grafana_router
from src.api.health import router as health_router
from src.api.llm import router as llm_router
from src.api.report import router as report_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(agent_router, prefix="/agent", tags=["agent"])
api_router.include_router(report_router, prefix="/agent", tags=["agent"])
api_router.include_router(llm_router, prefix="/llm", tags=["llm"])
api_router.include_router(grafana_router, prefix="/grafana", tags=["grafana"])
