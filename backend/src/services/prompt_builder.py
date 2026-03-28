"""Assembles the system prompt for each agent query.

Combines the base instruction, Grafana datasource list, user-supplied context,
RAG examples, and resolved entities into a single string that is passed to the
LLM as the system message.  Nothing in here performs I/O except the async RAG
retrieval — everything else is pure string construction.
"""
from __future__ import annotations

import structlog

from src.models.entity import resolve_entities
from src.models.requests import AgentQueryRequest
from src.models.responses import DatasourceInfo
from src.services.entity_store import EntityStore
from src.services.rag.retriever import retrieve_examples
from src.services.rag.store import ExampleStore

logger = structlog.get_logger(__name__)

_BASE = (
    "You are an on-call AI assistant for a Kubernetes environment monitored by "
    "Grafana, Loki, and Prometheus. "
    "You have tools to fetch live data: active alerts, logs (LogQL), and metrics (PromQL). "
    "Always look up real data before answering questions about incidents, errors, or performance. "
    "Be concise and actionable. When uncertain, say so."
)


def _datasource_block(datasources: list[DatasourceInfo]) -> str:
    lines = "\n".join(
        f"  - {ds.name}  type={ds.type}  uid={ds.uid}{' [default]' if ds.is_default else ''}"
        for ds in datasources
    )
    return (
        f"\n\nAvailable Grafana datasources (use these UIDs directly in tool calls):\n{lines}\n"
        "When querying logs use the uid of the datasource with type=loki. "
        "When querying metrics use the uid of the datasource with type=prometheus."
    )


def _context_block(context: dict[str, str]) -> str:
    lines = "\n".join(f"  {k}: {v}" for k, v in context.items())
    return f"\n\nSession context:\n{lines}"


def _entity_block(query: str, entities: EntityStore) -> str:
    matched = resolve_entities(query, entities.list_all())
    if not matched:
        return ""
    lines = [
        f"  - {e.name}  namespace={e.namespace}  type={e.entity_type.value}"
        + (f"  # {e.description}" if e.description else "")
        for e in matched
    ]
    return (
        "\n\nResolved entities from your query "
        "(use these exact names and namespaces in tool calls):\n"
        + "\n".join(lines)
    )


async def build(
    request: AgentQueryRequest,
    datasources: list[DatasourceInfo] | None,
    examples: ExampleStore,
    entities: EntityStore,
) -> tuple[str, int, int]:
    """Return ``(system_prompt, rag_chars, entity_count)`` for the given request.

    *rag_chars* and *entity_count* are returned so the caller can log them
    without duplicating the resolution work.
    """
    prompt = _BASE

    if datasources:
        prompt += _datasource_block(datasources)
    if request.context:
        prompt += _context_block(request.context)

    rag_block = await retrieve_examples(
        query=request.query,
        context=request.context or {},
        store=examples,
    )
    if rag_block:
        prompt += rag_block

    entity_block = _entity_block(request.query, entities)
    if entity_block:
        prompt += entity_block

    entity_count = len(resolve_entities(request.query, entities.list_all()))
    return prompt, len(rag_block), entity_count
