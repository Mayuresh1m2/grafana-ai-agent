"""Tool result compaction.

Verbose tool outputs (e.g. 50 Loki log lines) are summarised into a few
bullet points before being added to the message history.  This keeps the
context window shallow regardless of how many tool rounds have elapsed,
which is especially important for locally-hosted models with small windows.

Compaction is skipped for results that are already short — there is no value
in summarising a three-line datasource list.
"""
from __future__ import annotations

import structlog

from src.services.llm.base import LLMProvider

logger = structlog.get_logger(__name__)

# Results at or below this length (chars) are kept verbatim.
THRESHOLD = 400

# Token cap for the summary LLM call — tight by design so it adds minimal
# latency and does not itself consume significant context budget.
_SUMMARY_MAX_TOKENS = 180


async def compress(raw: str, tool_name: str, llm: LLMProvider) -> str:
    """Return a bullet-point summary of *raw* if it exceeds ``THRESHOLD`` chars.

    Falls back to *raw* unchanged when the LLM returns an empty response,
    so the agent loop always gets usable content.
    """
    if len(raw) <= THRESHOLD:
        return raw

    msg = await llm.chat(
        messages=[{"role": "user", "content": (
            f"Summarise the key findings from this {tool_name} result "
            f"in 3-5 concise bullet points. Preserve specific values "
            f"(numbers, service names, error messages). Be terse.\n\n{raw}"
        )}],
        tools=None,
        temperature=0.0,
        max_tokens=_SUMMARY_MAX_TOKENS,
    )
    summary = (msg.get("content") or "").strip()
    if summary:
        logger.debug("tool_result_compressed", tool=tool_name,
                     raw_chars=len(raw), compressed_chars=len(summary))
        return summary

    logger.warning("tool_result_compression_empty", tool=tool_name)
    return raw
