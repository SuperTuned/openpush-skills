"""Creation and validation helpers for the OpenPush app manifest."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from importlib.resources import files
from typing import Any


SCHEMA = json.loads(files("openpush_scan").joinpath("manifest.schema.json").read_text(encoding="utf-8"))


def empty(scanner_version: str) -> dict[str, Any]:
    """Return an empty, valid local manifest."""
    return {
        "manifest_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        ),
        "scanner_version": scanner_version,
        "platforms": [],
        "app_version": None,
        "sdk": {},
        "events": [],
        "tags": [],
        "triggers": [],
        "outcomes": [],
        "aliases": [],
        "identity": {"login": False, "logout": False, "auth_hash": False},
        "deep_links": [],
        "screens": [],
        "local_notifications": [],
        "locales": [],
        "strings": [],
        "release_notes": None,
        "capabilities": {
            "in_app_messages": False,
            "live_activities": False,
            "click_listener": False,
            "foreground_listener": False,
            "permission_pre_prompt": None,
            "onesignal_compat": False,
        },
        "inferences": [],
        "goal": None,
        "shared_categories": {},
        "redactions": {"dropped": 0, "by_rule": {}},
        "dynamic_counts": {"events": 0, "tags": 0, "triggers": 0},
    }


def validate(doc: dict[str, Any]) -> list[str]:
    """Validate a manifest using the dependency-free schema subset we publish."""
    errors: list[str] = []
    _validate_node(doc, SCHEMA, "", errors)
    return errors


def strip_sources(local: dict[str, Any]) -> dict[str, Any]:
    """Copy a local manifest while recursively removing source locations."""

    def strip(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: strip(item) for key, item in value.items() if key != "source"}
        if isinstance(value, list):
            return [strip(item) for item in value]
        return copy.deepcopy(value)

    return strip(local)


def digest(doc: dict[str, Any]) -> str:
    """Return the SHA-256 digest of canonical manifest JSON."""
    encoded = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_node(value: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    if value is None and schema.get("nullable"):
        return

    expected = schema.get("type")
    if expected and not _is_type(value, expected):
        errors.append(f"{path or '$'}: expected {expected}")
        return

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path or '$'}: not in enum")
        return

    if isinstance(value, str):
        if len(value) > schema.get("maxLength", len(value)):
            errors.append(f"{path or '$'}: longer than {schema['maxLength']} characters")
        pattern = schema.get("pattern")
        if pattern and re.fullmatch(pattern, value) is None:
            errors.append(f"{path or '$'}: does not match pattern")

    if isinstance(value, list):
        if len(value) > schema.get("maxItems", len(value)):
            errors.append(f"{path or '$'}: more than {schema['maxItems']} items")
        item_schema = schema.get("items", {})
        for index, item in enumerate(value):
            _validate_node(item, item_schema, f"{path}[{index}]", errors)

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{_join(path, key)}: required")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", {})
        for key, item in value.items():
            child_schema = properties.get(key)
            if child_schema is None and isinstance(additional, dict):
                child_schema = additional
            if child_schema:
                _validate_node(item, child_schema, _join(path, key), errors)


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _is_type(value: Any, expected: str) -> bool:
    checks = {
        "object": lambda candidate: isinstance(candidate, dict),
        "array": lambda candidate: isinstance(candidate, list),
        "string": lambda candidate: isinstance(candidate, str),
        "integer": lambda candidate: isinstance(candidate, int)
        and not isinstance(candidate, bool),
        "number": lambda candidate: isinstance(candidate, (int, float))
        and not isinstance(candidate, bool),
        "boolean": lambda candidate: isinstance(candidate, bool),
        "null": lambda candidate: candidate is None,
    }
    return checks.get(expected, lambda _candidate: True)(value)
