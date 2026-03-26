"""LLM provider info endpoints."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.config import get_settings
from src.services.llm.base import LLMProvider
from src.services.llm.factory import get_llm_provider

router = APIRouter()


class ModelsResponse(BaseModel):
    provider: str
    default_model: str
    models: list[str]


@router.get("/models", response_model=ModelsResponse)
async def list_models(
    llm: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> ModelsResponse:
    """Return available models for the active provider."""
    settings = get_settings()
    models = await llm.list_models()
    return ModelsResponse(
        provider=settings.llm_provider,
        default_model=llm.default_model,
        models=models,
    )
