"""Local JSON-backed access provider used for Maker/test environments."""

import json
import logging
import os
import uuid
from pathlib import Path
from threading import Lock
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple


logger = logging.getLogger(__name__)


class LocalProvider:
    """JSON-backed provider for Maker Access Control + simulator flows."""

    def __init__(self) -> None:
        """Initialise in-memory data from configured JSON stores."""
        self._lock = Lock()
        self._store_path = self._path_from_env("CARDSYS_TEST_STORE")
        self._users_path = self._path_from_env("CARDSYS_TEST_USERS")
        self._tools_path = self._path_from_env("CARDSYS_TEST_TOOLS")
        self._assignments_path = self._path_from_env("CARDSYS_TEST_ASSIGNMENTS")

        self._users: List[Dict[str, Any]] = []
        self._tools: List[Dict[str, Any]] = []
        self._assignments: List[Tuple[str, str]] = []

        self._load_initial_state()
        logger.info(
            "Loaded %s users, %s tools, %s assignments",
            len(self._users),
            len(self._tools),
            len(self._assignments),
        )

    # ------------------------------------------------------------------
    # Loading and persistence helpers
    # ------------------------------------------------------------------
    def _path_from_env(self, env_var: str) -> Path | None:
        """Return a Path sourced from the environment when present."""
        value = os.getenv(env_var)
        if value:
            return Path(value)
        return None

    def _load_initial_state(self) -> None:
        """Populate state from combined store or legacy fixture files."""
        if self._store_path:
            payload = self._read_json(self._store_path, {})
            self._users = [
                self._normalize_user(entry) for entry in payload.get("users", [])
            ]
            self._tools = [
                self._normalize_tool(entry) for entry in payload.get("tools", [])
            ]
            self._assignments = [tuple(item) for item in payload.get("assignments", [])]
            return

        users_raw = self._read_json(self._users_path, [])
        tools_raw = self._read_json(self._tools_path, [])
        assignments_raw = self._read_json(self._assignments_path, [])

        self._users = [self._normalize_user(entry) for entry in users_raw]
        self._tools = [self._normalize_tool(entry) for entry in tools_raw]
        self._assignments = [tuple(item) for item in assignments_raw]

    def _normalize_user(self, user: Dict[str, Any]) -> Dict[str, Any]:
        """Return a user mapping with required default fields populated."""
        mapped = dict(user)
        mapped.setdefault("id", mapped.get("user_id") or mapped.get("uuid") or "")
        mapped.setdefault("uuid", mapped.get("uuid") or str(uuid.uuid4()))
        mapped.setdefault("card_serial", mapped.get("card_serial") or "")
        mapped.setdefault("first_name", mapped.get("first_name") or "")
        mapped.setdefault("last_name", mapped.get("last_name") or "")
        mapped.setdefault("email", mapped.get("email") or "")
        return mapped

    def _normalize_tool(self, tool: Dict[str, Any]) -> Dict[str, Any]:
        """Return a tool mapping with reader/activator defaults applied."""
        mapped = dict(tool)
        reader_id = (
            mapped.get("reader_device_id")
            or mapped.get("reader_id")
            or mapped.get("reader_device")
        )
        activator_id = (
            mapped.get("activator_device_id")
            or mapped.get("device_id")
            or mapped.get("activator_device")
        )
        mapped["reader_device_id"] = reader_id or activator_id or ""
        mapped["activator_device_id"] = activator_id or reader_id or ""
        mapped["device_id"] = mapped.get("device_id") or mapped["activator_device_id"]
        mapped.setdefault(
            "badge_name",
            mapped.get("permission")
            or mapped.get("badge")
            or mapped.get("badge_id")
            or mapped.get("id")
            or "",
        )
        mapped.setdefault("name", mapped.get("name") or "")
        return mapped

    def _read_json(self, path: Path | None, default: Any) -> Any:
        """Read JSON data from ``path`` returning ``default`` on failure."""
        if not path:
            return default
        try:
            if not path.exists():
                return default
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to read JSON from %s: %s", path, exc)
            return default

    def _persist(self) -> None:
        """Write the current state to any configured storage targets."""
        payload = {
            "users": self._users,
            "tools": self._tools,
            "assignments": [list(item) for item in self._assignments],
        }

        if self._store_path:
            self._write_json(self._store_path, payload)
            return

        self._write_json(self._users_path, payload["users"])
        self._write_json(self._tools_path, payload["tools"])
        self._write_json(self._assignments_path, payload["assignments"])

    def _write_json(self, path: Path | None, data: Any) -> None:
        """Persist JSON ``data`` to ``path`` safely when configured."""
        if not path:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.parent / f".{path.name}.tmp"
            with tmp_path.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=False)
                handle.write("\n")
            tmp_path.replace(path)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to write JSON to %s: %s", path, exc)

    def import_store_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Replace the current state with ``payload`` coming from a remote store."""
        if not isinstance(payload, dict):
            raise ValueError("Payload must be a JSON object.")
        users_raw = payload.get("users", [])
        tools_raw = payload.get("tools", [])
        assignments_raw = payload.get("assignments", [])

        if not isinstance(users_raw, list):
            raise ValueError("'users' must be a list.")
        if not isinstance(tools_raw, list):
            raise ValueError("'tools' must be a list.")
        if not isinstance(assignments_raw, list):
            raise ValueError("'assignments' must be a list.")

        normalized_users = [
            self._normalize_user(entry)
            for entry in users_raw
            if isinstance(entry, dict)
        ]
        normalized_tools = [
            self._normalize_tool(entry)
            for entry in tools_raw
            if isinstance(entry, dict)
        ]
        normalized_assignments: List[Tuple[str, str]] = []
        for pair in assignments_raw:
            if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                user_id = str(pair[0]).strip()
                tool_id = str(pair[1]).strip()
                if user_id and tool_id:
                    normalized_assignments.append((user_id, tool_id))

        with self._lock:
            self._users = normalized_users
            self._tools = normalized_tools
            self._assignments = normalized_assignments
            summary = {
                "users": len(self._users),
                "tools": len(self._tools),
                "assignments": len(self._assignments),
            }
            self._persist()
            return summary

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------
    def list_people(self) -> List[Dict[str, Any]]:
        """Return shallow copies of all user records."""
        with self._lock:
            return [dict(user) for user in self._users]

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return shallow copies of all tool records."""
        with self._lock:
            return [dict(tool) for tool in self._tools]

    def list_assignments(self) -> List[Tuple[str, str]]:
        """Return current permission assignments as tuples."""
        with self._lock:
            return list(self._assignments)

    def get_person(self, user_id: str) -> Dict[str, Any] | None:
        """Look up a user by identifier."""
        with self._lock:
            for user in self._users:
                if user.get("id") == user_id:
                    return dict(user)
        return None

    def get_tool(self, tool_id: str) -> Dict[str, Any] | None:
        """Look up a tool by identifier."""
        with self._lock:
            for tool in self._tools:
                if tool.get("id") == tool_id:
                    return dict(tool)
        return None

    def as_state(self) -> Dict[str, Any]:
        """Return the provider state in a serialisable structure."""
        with self._lock:
            return {
                "users": [dict(user) for user in self._users],
                "tools": [dict(tool) for tool in self._tools],
                "assignments": [list(item) for item in self._assignments],
            }

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------
    def upsert_person(
        self,
        user_id: str,
        rfid: str,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
        user_uuid: str | None = None,
        email: str | None = None,
    ) -> None:
        """Insert or update a user entry and persist changes."""
        with self._lock:
            for user in self._users:
                if user.get("id") == user_id:
                    user["card_serial"] = rfid
                    if first_name is not None:
                        user["first_name"] = first_name
                    if last_name is not None:
                        user["last_name"] = last_name
                    if email is not None:
                        user["email"] = email
                    if user_uuid:
                        user["uuid"] = user_uuid
                    self._persist()
                    return
            self._users.append(
                self._normalize_user(
                    {
                        "id": user_id,
                        "card_serial": rfid,
                        "first_name": first_name or "",
                        "last_name": last_name or "",
                        "uuid": user_uuid or str(uuid.uuid4()),
                        "email": email or "",
                    }
                )
            )
            self._persist()

    def upsert_tool(
        self,
        tool_id: str,
        device_id: str,
        name: str | None = None,
        *,
        reader_device_id: str | None = None,
        activator_device_id: str | None = None,
        badge_name: str | None = None,
    ) -> None:
        """Insert or update a tool entry and persist changes."""
        reader_value = reader_device_id or device_id
        activator_value = activator_device_id or device_id
        with self._lock:
            for tool in self._tools:
                if tool.get("id") == tool_id:
                    tool["device_id"] = activator_value
                    tool["activator_device_id"] = activator_value
                    tool["reader_device_id"] = reader_value
                    if name is not None:
                        tool["name"] = name
                    if badge_name is not None:
                        tool["badge_name"] = badge_name
                    if tool.get("badge_name") is None:
                        tool["badge_name"] = ""
                    self._persist()
                    return
            self._tools.append(
                self._normalize_tool(
                    {
                        "id": tool_id,
                        "device_id": activator_value,
                        "name": name or "",
                        "reader_device_id": reader_value,
                        "activator_device_id": activator_value,
                        "badge_name": badge_name or "",
                    }
                )
            )
            self._persist()

    def delete_person(self, user_id: str) -> None:
        """Remove a user and any associated assignments."""
        with self._lock:
            changed = False
            filtered_users = [user for user in self._users if user.get("id") != user_id]
            if len(filtered_users) != len(self._users):
                self._users = filtered_users
                changed = True

            filtered_assignments = [
                pair for pair in self._assignments if pair[0] != user_id
            ]
            if len(filtered_assignments) != len(self._assignments):
                self._assignments = filtered_assignments
                changed = True

            if changed:
                self._persist()

    def delete_tool(self, tool_id: str) -> None:
        """Remove a tool and any associated assignments."""
        with self._lock:
            changed = False
            filtered_tools = [tool for tool in self._tools if tool.get("id") != tool_id]
            if len(filtered_tools) != len(self._tools):
                self._tools = filtered_tools
                changed = True

            filtered_assignments = [
                pair for pair in self._assignments if pair[1] != tool_id
            ]
            if len(filtered_assignments) != len(self._assignments):
                self._assignments = filtered_assignments
                changed = True

            if changed:
                self._persist()

    def grant(self, user_id: str, tool_id: str) -> None:
        """Grant a permission by recording an assignment."""
        with self._lock:
            if (user_id, tool_id) not in self._assignments:
                self._assignments.append((user_id, tool_id))
                self._persist()

    def revoke(self, user_id: str, tool_id: str) -> None:
        """Revoke a permission by removing an assignment."""
        with self._lock:
            if (user_id, tool_id) in self._assignments:
                self._assignments.remove((user_id, tool_id))
                self._persist()

    def delete_assignment(self, user_id: str, tool_id: str) -> None:
        """Compatibility wrapper for ``revoke`` used by the protocol."""
        self.revoke(user_id, tool_id)

    # ------------------------------------------------------------------
    # Access helpers
    # ------------------------------------------------------------------
    def check_access(self, rfid: str, device_id: str) -> bool:
        """Return True when the given card is assigned to the requested device."""
        with self._lock:
            user_id = next(
                (
                    user.get("id")
                    for user in self._users
                    if user.get("card_serial") == rfid
                ),
                None,
            )
            if not user_id:
                logger.warning("User with rfid %s not found", rfid)
                return False

            tool_id = next(
                (
                    tool.get("id")
                    for tool in self._tools
                    if tool.get("device_id") == device_id
                ),
                None,
            )
            if not tool_id:
                logger.warning("Tool with device_id %s not found", device_id)
                return False

            has_access = (user_id, tool_id) in self._assignments
            logger.info(
                "check_access for user %s and tool %s: %s", user_id, tool_id, has_access
            )
            return has_access

    def find_user_by_card(self, card_serial: str) -> Dict[str, Any] | None:
        """Return a user record matching the given card serial.

        Matched case-insensitively. Drupal stores serials in MySQL, whose
        default collation is case-insensitive, and cardsystem uppercases every
        serial via ``sanitize_card_id`` before the lookup. An exact-match
        comparison here silently denies every member whose stored serial is
        not already uppercase.
        """
        needle = (card_serial or "").strip().lower()
        if not needle:
            return None
        with self._lock:
            for user in self._users:
                value = (user.get("card_serial") or "").strip().lower()
                if value and value == needle:
                    return dict(user)
        return None

    def find_user_by_email(self, email: str) -> Dict[str, Any] | None:
        """Return a user record matching the given email (case-insensitive)."""
        needle = (email or "").strip().lower()
        if not needle:
            return None
        with self._lock:
            for user in self._users:
                value = (user.get("email") or "").strip().lower()
                if value and value == needle:
                    return dict(user)
        return None

    def find_user_by_uuid(self, user_uuid: str) -> Dict[str, Any] | None:
        """Return a user record matching the given UUID (case-insensitive)."""
        needle = (user_uuid or "").strip().lower()
        if not needle:
            return None
        with self._lock:
            for user in self._users:
                value = (user.get("uuid") or "").strip().lower()
                if value and value == needle:
                    return dict(user)
        return None

    def list_permissions(self) -> List[str]:
        """Return sorted permission identifiers derived from tools."""
        with self._lock:
            return sorted(
                {
                    tool.get("badge_name", "").lower()
                    for tool in self._tools
                    if tool.get("badge_name")
                }
            )

    def _tool_ids_for_permission(self, permission_id: str) -> List[str]:
        """Translate a permission id into concrete tool identifiers."""
        permission_lower = (permission_id or "").lower()
        tool_ids: List[str] = []
        for tool in self._tools:
            if tool.get("badge_name", "").lower() == permission_lower:
                tool_id = tool.get("id")
                if isinstance(tool_id, str):
                    tool_ids.append(tool_id)
        return tool_ids

    def has_permission(self, user_id: str, permission_id: str) -> bool:
        """Check whether ``user_id`` has access to ``permission_id``."""
        tool_ids = self._tool_ids_for_permission(permission_id)
        if not tool_ids:
            return False
        with self._lock:
            return any((user_id, tool_id) in self._assignments for tool_id in tool_ids)

    def find_tools_for_reader(self, reader_name: str) -> List[Dict[str, Any]]:
        """Return tools served by the specified reader device id."""
        reader_lower = reader_name.lower()
        with self._lock:
            return [
                dict(tool)
                for tool in self._tools
                if tool.get("reader_device_id", "").lower() == reader_lower
            ]

    def find_tool_by_badge(self, permission_id: str) -> Dict[str, Any] | None:
        """Return the first tool that matches a badge/permission identifier."""
        permission_lower = (permission_id or "").lower()
        with self._lock:
            for tool in self._tools:
                if tool.get("badge_name", "").lower() == permission_lower:
                    return dict(tool)
        return None
