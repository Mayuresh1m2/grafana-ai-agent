"""Incident report generation endpoint — SSE streaming."""

from __future__ import annotations

from typing import Annotated, AsyncIterator

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from src.api._sse import sse_event as _sse
from src.models.requests import ReportRequest
from src.services.llm.base import LLMProvider
from src.services.llm.factory import get_llm_provider

logger = structlog.get_logger(__name__)
router = APIRouter()

_REPORT_SYSTEM = (
    "You are an expert SRE writing a post-incident report. "
    "Use only information from the provided investigation transcript — do not invent facts. "
    "Write in a clear, professional tone suitable for a post-mortem document. "
    "Use Markdown. Keep each section concise and actionable."
)

_REPORT_TEMPLATE = """\
Generate a post-incident report from the investigation transcript below.

Use exactly these sections (Markdown headings):

## Summary
One paragraph: what happened, when, and the user/business impact.

## Timeline
Bullet-point chronology inferred from the investigation (include approximate times if mentioned).

## Root Cause
What caused the incident. Be specific — reference service names, error messages, or metrics found.

## Impact
Which services, namespaces, or users were affected and to what degree.

## Evidence
Key log lines, metric readings, or error patterns discovered during the investigation.

## Remediation
Steps taken or recommended to resolve the incident.

## Action Items
- [ ] Checkbox list of concrete follow-up tasks to prevent recurrence.

---

Session context:
{context_block}

Investigation transcript:
{transcript}
"""


def _build_prompt(request: ReportRequest) -> str:
    ctx = request.context
    context_lines = [
        f"- Environment: {ctx.get('environment', 'unknown')}",
        f"- Namespace: {ctx.get('namespace', 'unknown')}",
        f"- Services: {ctx.get('services', 'unknown')}",
        f"- Grafana URL: {ctx.get('grafana_url', 'unknown')}",
        f"- Active alerts at session start: {ctx.get('active_alerts', 'none')}",
    ]
    context_block = "\n".join(context_lines)

    turns = []
    for turn in request.conversation:
        label = "User" if turn.role == "user" else "Assistant"
        # Truncate very long assistant answers to keep prompt manageable
        content = turn.content[:3000] if turn.role == "assistant" else turn.content
        turns.append(f"{label}: {content}")
    transcript = "\n\n".join(turns)

    return _REPORT_TEMPLATE.format(context_block=context_block, transcript=transcript)


async def _stream_report(
    request: ReportRequest,
    llm: LLMProvider,
) -> AsyncIterator[str]:
    log = logger.bind(turns=len(request.conversation), model=request.model)
    log.info("report_generate_start")

    prompt = _build_prompt(request)
    try:
        async for token in llm.stream(
            prompt=prompt,
            system=_REPORT_SYSTEM,
            model=request.model,
            temperature=0.3,  # low temp for factual, consistent reports
        ):
            yield _sse({"type": "content", "chunk": token})
    except Exception as exc:
        log.error("report_generate_failed", error=str(exc), exc_info=True)
        yield _sse({"type": "error", "message": f"Report generation failed: {exc}"})
        return

    log.info("report_generate_done")
    yield _sse({"type": "done"})


@router.post(
    "/report",
    summary="Generate a post-incident report from the investigation transcript",
    description=(
        "Streams a Markdown incident report as SSE content events. "
        "Provide the full Q&A conversation and session context. "
        "Event types: content (chunk), done, error."
    ),
)
async def generate_report(
    request: ReportRequest,
    llm: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> StreamingResponse:
    return StreamingResponse(
        _stream_report(request, llm),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
