"""Closed, deterministic redaction rules applied before share review."""

from __future__ import annotations

import copy
import re
from typing import Any


RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("secret-shaped", re.compile(r"(?i)\b(sk|pk|rk)[-_](live|test)?[-_]?[A-Za-z0-9]{16,}|\bAKIA[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9]{36}\b|\b[A-Fa-f0-9]{32,}\b|\b[A-Za-z0-9+/]{40,}={0,2}\b"), "drop"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "drop"),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "drop"),
    ("phone", re.compile(r"\+?\d[\d\s().-]{8,}\d"), "drop"),
    ("url-query", re.compile(r"\?[^\s\"']+"), "strip"),
    ("absolute-path", re.compile(r"(?:^|[\s\"'])(?:/Users/|/home/|[A-Za-z]:\\)[^\s\"']+"), "drop"),
]


def apply(doc: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    cleaned = copy.deepcopy(doc)
    counts: dict[str, int] = {}

    def clean(value: str) -> tuple[str | None, str | None]:
        for name, pattern, action in RULES:
            if not pattern.search(value):
                continue
            counts[name] = counts.get(name, 0) + 1
            if action == "strip":
                return pattern.sub("", value), name
            return None, name
        return value, None

    for category in ("tags", "triggers"):
        for item in cleaned.get(category, []):
            kept = []
            for value in item.get("value_samples", []):
                new_value, _ = clean(value)
                if new_value is not None:
                    kept.append(new_value)
            item["value_samples"] = kept

    kept_strings = []
    for item in cleaned.get("strings", []):
        value, _ = clean(item.get("value", ""))
        if value is not None:
            item["value"] = value
            kept_strings.append(item)
    cleaned["strings"] = kept_strings

    kept_screens = []
    for item in cleaned.get("screens", []):
        name, _ = clean(item.get("name", ""))
        route, _ = clean(item["route"]) if isinstance(item.get("route"), str) else (item.get("route"), None)
        if name is not None:
            item["name"] = name
            item["route"] = route
            kept_screens.append(item)
    cleaned["screens"] = kept_screens

    for item in cleaned.get("local_notifications", []):
        for field in ("title", "body"):
            if isinstance(item.get(field), str):
                item[field], _ = clean(item[field])

    for item in cleaned.get("deep_links", []):
        urls = []
        for value in item.get("full_urls", []):
            new_value, _ = clean(value)
            if new_value is not None:
                urls.append(new_value)
        item["full_urls"] = urls

    notes = cleaned.get("release_notes")
    if isinstance(notes, dict) and isinstance(notes.get("text"), str):
        notes_text, _ = clean(notes["text"])
        if notes_text is None:
            cleaned["release_notes"] = None
        else:
            notes["text"] = notes_text

    report = {"dropped": sum(counts.values()), "by_rule": dict(sorted(counts.items()))}
    return cleaned, report
