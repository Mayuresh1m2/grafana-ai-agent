#!/usr/bin/env python3
"""Manage query examples: dump from Qdrant to JSON, or load JSON into Qdrant.

Usage (from repo root):
    uv run python backend/scripts/examples.py dump
    uv run python backend/scripts/examples.py dump --out examples/seed.json

    uv run python backend/scripts/examples.py load
    uv run python backend/scripts/examples.py load --file examples/seed.json
    uv run python backend/scripts/examples.py load --file examples/seed.json --replace

Requires Ollama (for embeddings) and Qdrant to be running.
Configure via backend/.env or environment variables.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Allow running from anywhere in the repo
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_settings
from src.models.example import ExampleCreate, PlaceholderKey, QueryCategory
from src.services.rag.embedder import OllamaEmbedder
from src.services.rag.store import ExampleStore

_DEFAULT_SEED = Path(__file__).parent.parent.parent / "examples" / "seed.json"


def _make_store() -> ExampleStore:
    settings = get_settings()
    embedder = OllamaEmbedder(settings)
    return ExampleStore(
        qdrant_url=settings.qdrant_url,
        collection=settings.qdrant_collection,
        embedder=embedder,
        vector_size=settings.embedding_vector_size,
    )


# ── dump ──────────────────────────────────────────────────────────────────────

async def cmd_dump(out: Path) -> None:
    store = _make_store()
    examples = store.list_all()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        [ex.model_dump(mode="json") for ex in examples],
        indent=2,
        default=str,
    ))
    print(f"Dumped {len(examples)} example(s) → {out}")


# ── load ──────────────────────────────────────────────────────────────────────

async def cmd_load(file: Path, replace: bool) -> None:
    if not file.exists():
        print(f"File not found: {file}", file=sys.stderr)
        sys.exit(1)

    raw: list[dict] = json.loads(file.read_text())
    store = _make_store()

    existing_ids = {ex.id for ex in store.list_all()}

    loaded = skipped = 0
    for item in raw:
        item_id: str | None = item.get("id")

        if item_id and item_id in existing_ids:
            if replace:
                store.delete(item_id)
            else:
                skipped += 1
                continue

        body = ExampleCreate(
            title=item["title"],
            description=item["description"],
            query_type=item["query_type"],
            category=QueryCategory(item.get("category", QueryCategory.service.value)),
            template=item["template"],
            tags=item.get("tags", []),
            placeholders=[PlaceholderKey(p) for p in item.get("placeholders", [])],
        )
        await store.add(body)
        loaded += 1

    msg = f"Loaded {loaded} example(s)"
    if skipped:
        msg += f", skipped {skipped} already-existing (use --replace to overwrite)"
    print(msg)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dump or load Grafana AI agent query examples.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_dump = sub.add_parser("dump", help="Export all examples from Qdrant to a JSON file")
    p_dump.add_argument(
        "--out", type=Path, default=_DEFAULT_SEED,
        help=f"Output file (default: {_DEFAULT_SEED})",
    )

    p_load = sub.add_parser("load", help="Import examples from a JSON file into Qdrant")
    p_load.add_argument(
        "--file", type=Path, default=_DEFAULT_SEED,
        help=f"Input file (default: {_DEFAULT_SEED})",
    )
    p_load.add_argument(
        "--replace", action="store_true",
        help="Re-embed and overwrite examples whose ID already exists (default: skip)",
    )

    args = parser.parse_args()

    if args.cmd == "dump":
        asyncio.run(cmd_dump(args.out))
    elif args.cmd == "load":
        asyncio.run(cmd_load(args.file, args.replace))


if __name__ == "__main__":
    main()
