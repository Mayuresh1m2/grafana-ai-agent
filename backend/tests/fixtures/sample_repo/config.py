"""Application configuration.

Intentional bug:
  - get_config_value: KeyError — no default for missing keys.
"""

from __future__ import annotations

_CONFIG: dict[str, object] = {
    "host": "localhost",
    "port": 5432,
    "database": "app_db",
    "debug": False,
    "max_connections": 10,
}


def get_config_value(key: str) -> object:
    """Return the configuration value for *key*.

    BUG: Raises KeyError for any key not in ``_CONFIG`` instead of returning
    a sensible default or raising a descriptive ConfigError.
    """
    return _CONFIG[key]                     # BUG: KeyError for unknown keys


def get_config_value_safe(key: str, default: object = None) -> object:
    """Safe version — returns *default* for missing keys."""
    return _CONFIG.get(key, default)


def all_config() -> dict[str, object]:
    """Return a copy of the full configuration dict."""
    return dict(_CONFIG)
