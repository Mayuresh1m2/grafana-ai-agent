"""HTTP request handlers for the sample microservice.

Intentional bugs:
  - handle_user_request: KeyError — accesses config without .get()
  - batch_process: IndexError — accesses first element without length check
"""

from __future__ import annotations

from typing import Any

from api.app import calculate_stats, parse_request_body
from config import get_config_value


class HandlerError(Exception):
    """Raised when a handler encounters an unrecoverable error."""


def handle_user_request(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Handle an authenticated user request.

    BUG: ``get_config_value("max_requests_per_user")`` raises KeyError
    because that key is not in the config dict.
    """
    limit = get_config_value("max_requests_per_user")   # BUG: KeyError
    if not user_id:
        raise HandlerError("user_id must not be empty")
    return {
        "user_id": user_id,
        "processed": True,
        "limit_applied": limit,
        "payload_keys": list(payload.keys()),
    }


def batch_process(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Process a batch of items and return aggregate statistics.

    BUG: Accesses ``items[0]`` without checking if the list is empty —
    raises IndexError when an empty batch is submitted.
    """
    first = items[0]                        # BUG: IndexError if items is empty
    prices = [item.get("price", 0.0) for item in items]
    stats = calculate_stats(prices)
    return {
        "first_item": first,
        "count": len(items),
        "stats": repr(stats),
    }


def parse_and_validate(raw_json: str, required_fields: list[str]) -> dict[str, Any]:
    """Parse *raw_json* and validate that all *required_fields* are present."""
    data = parse_request_body(raw_json)
    missing = [f for f in required_fields if f not in data]
    if missing:
        raise HandlerError(f"Missing required fields: {missing}")
    return data
