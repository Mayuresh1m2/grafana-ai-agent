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
from src.models.service_graph import ServiceGraph
from src.services.entity_store import EntityStore
from src.services.investigation_store import InvestigationState
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
        "Rules for datasource selection:\n"
        "- Logs (query_loki): use the uid where type=loki\n"
        "- Metrics (query_prometheus / query_prometheus_range): use the uid where type=prometheus\n"
        "- Never use a tempo, elasticsearch, or other non-prometheus uid for metric queries."
    )


def _context_block(context: dict[str, str]) -> str:
    lines = "\n".join(f"  {k}: {v}" for k, v in context.items())
    return f"\n\nSession context:\n{lines}"


def _investigation_block(state: InvestigationState) -> str:
    """Summarise what was found in previous turns of this session.

    Injected between the base instruction and the current user question so the
    LLM can continue a multi-turn investigation without replaying raw history.
    Truncated to keep the block within budget on small context windows.
    """
    if not state.findings and not state.last_answer:
        return ""

    lines = [f"Previous investigation findings (turns 1–{state.turn_count}):"]
    for f in state.findings:
        # Each summary is already compact (≤180 chars from compactor), but
        # guard against edge cases by capping here too.
        lines.append(f"  [{f.tool}] {f.summary[:300]}")

    if state.last_answer:
        lines.append(f"\nLast conclusion: {state.last_answer[:500]}")

    lines.append("\nContinue the investigation based on the new question below.")
    return "\n\n" + "\n".join(lines)


def _service_graph_block(graph: ServiceGraph) -> str:
    """Describe the service topology so the agent can reason about call paths."""
    if not graph.nodes:
        return ""

    node_map = {n.id: n for n in graph.nodes}

    lines = ["\n\nService topology (use this to trace call paths and understand dependencies):"]
    for n in graph.nodes:
        parts = [f"  [{n.node_type.value.upper()}] {n.name}"]
        if n.tech:
            parts.append(f"tech={n.tech}")
        if n.description:
            parts.append(f"— {n.description}")
        lines.append(" ".join(parts))

    if graph.edges:
        lines.append("\nInteractions:")
        for e in graph.edges:
            src_name = node_map[e.source].name if e.source in node_map else e.source
            tgt_name = node_map[e.target].name if e.target in node_map else e.target
            detail = f" ({e.label})" if e.label else ""
            lines.append(f"  {src_name} --[{e.edge_type.value}]--> {tgt_name}{detail}")

    return "\n".join(lines)


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
        "\n\nResolved entities mentioned in the query (for context only — "
        "use the query examples above for the correct label selectors):\n"
        + "\n".join(lines)
    )


async def build(
    request:       AgentQueryRequest,
    datasources:   list[DatasourceInfo] | None,
    examples:      ExampleStore,
    entities:      EntityStore,
    investigation: InvestigationState | None = None,
    graph:         ServiceGraph | None = None,
) -> tuple[str, int, int]:
    """Return ``(system_prompt, rag_chars, entity_count)`` for the given request.

    *rag_chars* and *entity_count* are returned so the caller can log them
    without duplicating the resolution work.
    """
    prompt = _BASE

    if graph:
        graph_block = _service_graph_block(graph)
        if graph_block:
            prompt += graph_block

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

    if investigation and investigation.turn_count > 0:
        prompt += _investigation_block(investigation)

    entity_count = len(resolve_entities(request.query, entities.list_all()))
    return prompt, len(rag_block), entity_count
