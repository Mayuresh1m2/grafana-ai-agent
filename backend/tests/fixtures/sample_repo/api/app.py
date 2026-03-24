"""Main application module for the sample microservice.

Intentional bugs:
  - calculate_stats: ZeroDivisionError when `numbers` is empty
  - parse_request_body: AttributeError — treats dict as object
"""

from __future__ import annotations

import json
from typing import Any


class RequestError(Exception):
    """Raised for malformed incoming requests."""


class StatsResult:
    """Holds computed statistics."""

    def __init__(self, mean: float, minimum: float, maximum: float) -> None:
        self.mean = mean
        self.minimum = minimum
        self.maximum = maximum

    def __repr__(self) -> str:
        return f"StatsResult(mean={self.mean}, min={self.minimum}, max={self.maximum})"


def calculate_stats(numbers: list[float]) -> StatsResult:
    """Return mean, min, and max of *numbers*.

    BUG: ZeroDivisionError when *numbers* is an empty list.
    The guard ``if not numbers`` is missing.
    """
    total = sum(numbers)
    mean = total / len(numbers)          # BUG: ZeroDivisionError if empty
    return StatsResult(mean=mean, minimum=min(numbers), maximum=max(numbers))


def parse_request_body(raw_body: str) -> dict[str, Any]:
    """Parse a JSON request body string.

    BUG: AttributeError — the return annotation says dict but callers later
    call ``.user_id`` (attribute access) instead of ``["user_id"]`` (dict access).
    """
    try:
        return json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise RequestError(f"Invalid JSON body: {exc}") from exc


def process_order(order_data: str) -> dict[str, Any]:
    """Process an incoming order request.

    BUG: Calls ``body.user_id`` where ``body`` is a dict returned by
    ``parse_request_body`` — triggers AttributeError at runtime.
    """
    body = parse_request_body(order_data)
    # BUG: AttributeError — body is a dict, not an object
    user_id = body.user_id                  # type: ignore[attr-defined]
    items: list[dict[str, Any]] = body.get("items", [])
    prices = [item.get("price", 0.0) for item in items]
    stats = calculate_stats(prices)         # BUG: ZeroDivisionError if no items
    return {
        "user_id": user_id,
        "order_total": sum(prices),
        "price_stats": repr(stats),
    }
