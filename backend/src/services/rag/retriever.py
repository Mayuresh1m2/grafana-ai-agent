"""Retrieve and render relevant query examples for the agent system prompt."""
from __future__ import annotations

import structlog

from src.models.example import PlaceholderKey, QueryCategory, QueryExample
from src.services.rag.store import ExampleStore

logger = structlog.get_logger(__name__)

# Maps each PlaceholderKey to where its value lives in the agent context dict
_PLACEHOLDER_SOURCES: dict[PlaceholderKey, str] = {
    PlaceholderKey.namespace:   "namespace",
    PlaceholderKey.app:         "services",      # first entry if comma-separated
    PlaceholderKey.environment: "environment",
}


def _substitute(template: str, context: dict[str, str]) -> str:
    """Replace {{key}} tokens in template with values from context."""
    def resolve(key: PlaceholderKey) -> str:
        ctx_key = _PLACEHOLDER_SOURCES.get(key, key.value)
        raw = context.get(ctx_key, "")
        # If the value is a comma-separated list, take the first item
        return raw.split(",")[0].strip() if raw else f"{{{{{key.value}}}}}"

    result = template
    for key in PlaceholderKey:
        result = result.replace(f"{{{{{key.value}}}}}", resolve(key))
    return result


def _format_example(example: QueryExample, context: dict[str, str], score: float) -> str:
    resolved = _substitute(example.template, context)
    tags = ", ".join(example.tags) if example.tags else "—"
    return (
        f"### {example.title} ({example.query_type}, category={example.category.value})\n"
        f"# {example.description}\n"
        f"# Tags: {tags}  |  relevance: {score:.2f}\n"
        f"{resolved}"
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
