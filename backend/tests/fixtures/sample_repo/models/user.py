"""User model and permission management.

Intentional bugs:
  - UserManager.get_permission: KeyError — no default on dict lookup
  - UserManager.update_profile: AttributeError — mutates immutable dict field
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ROLE_PERMISSIONS: dict[str, list[str]] = {
    "admin": ["read", "write", "delete", "manage_users"],
    "editor": ["read", "write"],
    "viewer": ["read"],
}


@dataclass
class User:
    """Represents an application user."""

    user_id: str
    username: str
    email: str
    role: str = "viewer"
    metadata: dict[str, Any] = field(default_factory=dict)


class UserManager:
    """Manages user creation, lookup, and permissions."""

    def __init__(self) -> None:
        self._users: dict[str, User] = {}

    def create_user(self, user_id: str, username: str, email: str, role: str = "viewer") -> User:
        """Create and register a new user."""
        user = User(user_id=user_id, username=username, email=email, role=role)
        self._users[user_id] = user
        return user

    def get_user(self, user_id: str) -> User | None:
        """Return the user with *user_id*, or ``None`` if not found."""
        return self._users.get(user_id)

    def get_permission(self, user_id: str, action: str) -> bool:
        """Check whether *user_id* has permission to perform *action*.

        BUG: ``self._users[user_id]`` raises KeyError when *user_id* is not
        registered instead of returning False.  Should use ``.get()``.
        """
        user = self._users[user_id]         # BUG: KeyError for unknown user_id
        allowed = ROLE_PERMISSIONS.get(user.role, [])
        return action in allowed

    def update_profile(self, user_id: str, updates: dict[str, Any]) -> User:
        """Apply *updates* to the user profile.

        BUG: Directly mutates ``user.metadata`` after the dataclass ``field``
        creates a shared default — can pollute other User instances in certain
        test setups; also raises AttributeError if user not found.
        """
        user = self._users[user_id]         # BUG: KeyError if not found
        for key, value in updates.items():
            if hasattr(user, key):
                setattr(user, key, value)
            else:
                user.metadata[key] = value  # silently swallowed unknown fields
        return user

    def list_users_by_role(self, role: str) -> list[User]:
        """Return all users with the given *role*."""
        return [u for u in self._users.values() if u.role == role]
