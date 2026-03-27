"""Shared Server-Sent Events serialisation helper."""
from __future__ import annotations

import json


def sse_event(event: dict) -> str:
    """Serialise *event* as a single SSE data line."""
    return f"data: {json.dumps(event)}\n\n"
