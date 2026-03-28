"""Per-session investigation state — persists findings across chat turns.

Each turn the agent appends its tool findings and final answer to an
``InvestigationState``.  On the next turn that state is injected into the
system prompt so the LLM has context without the full message history being
replayed (which would exhaust the context window on small local models).

The store is in-process and keyed by ``session_id``, consistent with
``SessionStore``.  State is lost on restart; for durable history back this
with Redis or a SQLite table.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)

# Keep at most this many tool findings across all turns.
# Each finding is already compacted (~200 chars), so 20 × 200 ≈ 4 000 chars
# ≈ 1 000 tokens — a reasonable budget for prior context.
_MAX_FINDINGS = 20


@dataclass
class ToolFinding:
    """One tool call and its (already-compressed) result."""
    tool:    str
    summary: str


@dataclass
class InvestigationState:
    """Accumulated knowledge from previous turns in this session."""
    findings:    list[ToolFinding] = field(default_factory=list)
    last_answer: str               = ""
    turn_count:  int               = 0


def extract_findings(messages: list[dict]) -> list[ToolFinding]:
    """Pull ``(tool_name, result)`` pairs from a completed message list.

    Walks the message history pairing each assistant ``tool_calls`` block
    with the ``role=tool`` messages that immediately follow it.  Results are
    already compacted by the time they reach the message list, so they are
    stored as-is.
    """
    findings: list[ToolFinding] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            tool_calls: list[dict] = msg["tool_calls"]
            j = i + 1
            for call in tool_calls:
                if j < len(messages) and messages[j].get("role") == "tool":
                    fn   = call.get("function") or {}
                    name = str(fn.get("name", "unknown"))
                    findings.append(ToolFinding(tool=name, summary=messages[j]["content"]))
                    j += 1
            i = j
        else:
            i += 1
    return findings


class InvestigationStore:
    """Thread-safe in-memory store for per-session investigation state."""

    def __init__(self) -> None:
        self._states: dict[str, InvestigationState] = {}
        self._lock   = asyncio.Lock()

    async def get(self, session_id: str) -> InvestigationState | None:
        async with self._lock:
            return self._states.get(session_id)

    async def update(
        self,
        session_id:  str,
        new_findings: list[ToolFinding],
        last_answer:  str,
    ) -> None:
        """Append *new_findings* to the session's state and record *last_answer*.

        Older findings are evicted once the total exceeds ``_MAX_FINDINGS``
        so the injected block stays within budget regardless of session length.
        """
        async with self._lock:
            state = self._states.get(session_id)
            if state is None:
                state = InvestigationState()
                self._states[session_id] = state

            state.findings.extend(new_findings)
            if len(state.findings) > _MAX_FINDINGS:
                state.findings = state.findings[-_MAX_FINDINGS:]

            state.last_answer = last_answer
            state.turn_count += 1

        logger.info(
            "investigation_state_updated",
            session_id=session_id,
            turn=state.turn_count,
            total_findings=len(state.findings),
        )

    async def delete(self, session_id: str) -> None:
        async with self._lock:
            self._states.pop(session_id, None)


# Module-level singleton — injected via FastAPI Depends
_store = InvestigationStore()


def get_investigation_store() -> InvestigationStore:
    """FastAPI dependency that returns the singleton InvestigationStore."""
    return _store
