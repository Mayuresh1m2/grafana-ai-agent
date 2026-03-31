"""Retrieve and render relevant query examples for the agent system prompt."""
from __future__ import annotations

import re
import structlog

from src.models.example import QueryCategory, QueryExample
from src.services.rag.store import ExampleStore

logger = structlog.get_logger(__name__)

# Keys whose context name differs from the placeholder name.
# e.g. {{app}} is filled from context["services"] (first comma-separated entry).
# Common Kubernetes label placeholders are mapped to setup-page fields so that
# templates resolve automatically without requiring alert labels each time.
_CONTEXT_ALIASES: dict[str, str] = {
    "app":       "services",
    "service":   "services",
    "container": "services",
    "job":       "services",
    "workload":  "services",
}

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def _substitute(template: str, context: dict[str, str]) -> str:
    """Replace every {{key}} token in *template* with the matching context value.

    Looks up each placeholder name in *context* directly, falling back to
    ``_CONTEXT_ALIASES`` for keys whose context name differs.  Tokens with no
    matching context value are left unchanged so the LLM can fill them in.
    """
    def resolve(match: re.Match[str]) -> str:
        key     = match.group(1)
        ctx_key = _CONTEXT_ALIASES.get(key, key)
        raw     = context.get(ctx_key, "")
        # Comma-separated lists (e.g. services) → take the first entry
        return raw.split(",")[0].strip() if raw else match.group(0)

    return _PLACEHOLDER_RE.sub(resolve, template)


def _format_example(example: QueryExample, context: dict[str, str], score: float) -> str:
    resolved  = _substitute(example.template, context)
    remaining = _PLACEHOLDER_RE.findall(resolved)
    tags      = ", ".join(example.tags) if example.tags else "—"

    missing_note = (
        f"# Missing values: {', '.join(remaining)} — ask the user to provide "
        "these before running the query.\n"
    ) if remaining else ""

    return (
        f"### {example.title} ({example.query_type}, category={example.category.value})\n"
        f"# {example.description}\n"
        f"# Tags: {tags}  |  relevance: {score:.2f}\n"
        f"{missing_note}{resolved}"
    )


async def retrieve_examples(
    query: str,
    context: dict[str, str],
    store: ExampleStore,
    top_k: int = 3,
    min_score: float = 0.3,
    category: QueryCategory | None = None,
) -> str:
    """Return a formatted block of relevant examples for the system prompt.

    Returns empty string if nothing is found above the score threshold.
    Pass ``category`` to restrict results to a specific query domain.
    """
    hits = await store.search(query, top_k=top_k, category=category)
    relevant = [(ex, sc) for ex, sc in hits if sc >= min_score]

    if not relevant:
        logger.debug("rag_no_examples", query_preview=query[:60], hits=len(hits))
        return ""

    logger.info("rag_examples_retrieved", count=len(relevant),
                titles=[ex.title for ex, _ in relevant])

    blocks = [_format_example(ex, context, sc) for ex, sc in relevant]
    return (
        "\n\nWorking query examples for this Grafana setup "
        "(use these as templates — they are known to work):\n\n"
        + "\n\n".join(blocks)
    )
