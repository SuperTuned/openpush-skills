"""Persist consent choices and build the manifest that may leave the machine."""

from __future__ import annotations

import copy
import fnmatch
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone
from typing import Any

from . import portable
from .manifest import strip_sources


DEFAULTS: dict[str, bool] = {
    "platforms": True,
    "sdk": True,
    "app_version": True,
    "events": True,
    "event_property_keys": True,
    "tags": True,
    "tag_value_samples": False,
    "triggers": True,
    "trigger_value_samples": False,
    "outcomes": True,
    "aliases": True,
    "identity": True,
    "deep_links": True,
    "deep_links_full_urls": False,
    "capabilities": True,
    "locales": True,
    "local_notifications": True,
    "local_notification_copy": False,
    "screens": False,
    "strings": False,
    "release_notes": False,
    "inferences": True,
    "goal": True,
}

EXPLAIN = {
    "platforms": "Selects platform-specific programs and instrumentation snippets.",
    "sdk": "Checks which OpenPush modules and version hints are already installed.",
    "app_version": "Detects releases and keeps version-specific suggestions current.",
    "events": "Matches OpenPush and recognized analytics event names to program ideas; analytics-only events still require OpenPush instrumentation.",
    "event_property_keys": "Shows which event properties can safely power filters and personalization.",
    "tags": "Shows which user facts can safely power segments and personalization.",
    "tag_value_samples": "Provides example tag values for draft targeting; values remain optional.",
    "triggers": "Matches in-app messages to trigger keys the app already sets.",
    "trigger_value_samples": "Provides example trigger values for draft rules; values remain optional.",
    "outcomes": "Connects existing outcome names to measurable draft programs.",
    "aliases": "Shows which external identity labels are already available for targeting.",
    "identity": "Avoids suggesting identity-dependent programs when login is not integrated.",
    "deep_links": "Limits draft calls to action to destinations the app declares.",
    "deep_links_full_urls": "Provides exact example destinations, with URL query strings removed.",
    "capabilities": "Avoids suggesting channels and features the installed SDK cannot render.",
    "locales": "Creates locale-aware drafts only for languages the app already ships.",
    "local_notifications": "Shows reminder trigger kinds so push suggestions do not duplicate them.",
    "local_notification_copy": "Shares existing reminder copy as optional tone and overlap evidence.",
    "screens": "Provides app screen names and routes as optional journey evidence.",
    "strings": "Used only as tone and vocabulary examples when AI writes copy; never shown to other tenants.",
    "release_notes": "Becomes the text of a suggested What's-new in-app message for this version; nothing else.",
    "inferences": "Adds closed category and lifecycle hints reviewed from local code context.",
    "goal": "Ranks suggestions so the ones serving this moment come first.",
}


def load(path: Path) -> dict[str, Any] | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def save(path: Path, profile: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    profile["reviewed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    profile["reviewed_by"] = _reviewer()
    portable.write_text(path, json.dumps(profile, indent=2, sort_keys=True) + "\n")


def new_profile(app: str | None = None, server: str = "https://app.openpush.ai") -> dict[str, Any]:
    return {
        "version": 1,
        "app": app,
        "server": server,
        "categories": dict(DEFAULTS),
        "exclude": {"events": [], "tags": [], "triggers": [], "deep_links": [], "strings": []},
        "goal": None,
        "reviewed_at": None,
        "reviewed_by": None,
    }


def apply(profile: dict[str, Any], local_manifest: dict[str, Any]) -> dict[str, Any]:
    doc = copy.deepcopy(local_manifest)
    categories = {**DEFAULTS, **profile.get("categories", {})}
    excludes = profile.get("exclude", {})

    list_categories = ("events", "tags", "triggers", "outcomes", "aliases", "deep_links", "locales", "local_notifications", "screens", "strings", "inferences")
    for category in list_categories:
        if not categories.get(category, False):
            doc[category] = []
    for category in ("events", "tags", "triggers", "deep_links", "strings"):
        patterns = excludes.get(category, [])
        if patterns:
            doc[category] = [item for item in doc.get(category, []) if not _excluded(category, item, patterns)]

    if not categories["platforms"]:
        doc["platforms"] = []
    if not categories["sdk"]:
        doc["sdk"] = {}
    if not categories["app_version"]:
        doc["app_version"] = None
    if not categories["event_property_keys"]:
        for item in doc["events"]:
            item["property_keys"] = []
    if not categories["tag_value_samples"]:
        for item in doc["tags"]:
            item["value_samples"] = []
    if not categories["trigger_value_samples"]:
        for item in doc["triggers"]:
            item["value_samples"] = []
    if not categories["identity"]:
        doc["identity"] = {"login": False, "logout": False, "auth_hash": False}
    if not categories["deep_links_full_urls"]:
        for item in doc["deep_links"]:
            item["full_urls"] = []
    if not categories["capabilities"]:
        doc["capabilities"] = {key: None if key == "permission_pre_prompt" else False for key in doc["capabilities"]}
    if not categories["local_notification_copy"]:
        for item in doc["local_notifications"]:
            item["title"] = None
            item["body"] = None
            item.pop("title_key", None)
            item.pop("body_key", None)
    if not categories["release_notes"]:
        doc["release_notes"] = None
    doc["goal"] = copy.deepcopy(profile.get("goal")) if categories["goal"] else None
    doc["shared_categories"] = categories
    doc.pop("warnings", None)
    return strip_sources(doc)


def summary(profile: dict[str, Any], local: dict[str, Any]) -> list[tuple[str, bool, int, str, bool]]:
    categories = {**DEFAULTS, **profile.get("categories", {})}
    return [
        (category, categories[category], _count(category, local), EXPLAIN[category], DEFAULTS[category])
        for category in DEFAULTS
    ]


def _count(category: str, doc: dict[str, Any]) -> int:
    if category in ("platforms", "events", "tags", "triggers", "outcomes", "aliases", "deep_links", "locales", "local_notifications", "screens", "strings", "inferences"):
        return len(doc.get(category, []))
    if category == "sdk":
        return len(doc.get("sdk", {}))
    if category in ("app_version", "release_notes", "goal"):
        return int(bool(doc.get(category)))
    if category == "event_property_keys":
        return sum(len(item.get("property_keys", [])) for item in doc.get("events", []))
    if category == "tag_value_samples":
        return sum(len(item.get("value_samples", [])) for item in doc.get("tags", []))
    if category == "trigger_value_samples":
        return sum(len(item.get("value_samples", [])) for item in doc.get("triggers", []))
    if category == "deep_links_full_urls":
        return sum(len(item.get("full_urls", [])) for item in doc.get("deep_links", []))
    if category == "local_notification_copy":
        return sum(bool(item.get("title")) + bool(item.get("body")) for item in doc.get("local_notifications", []))
    if category == "identity":
        return sum(bool(value) for value in doc.get("identity", {}).values())
    if category == "capabilities":
        return sum(value is True for value in doc.get("capabilities", {}).values())
    return 0


def _excluded(category: str, item: Any, patterns: list[str]) -> bool:
    if isinstance(item, str):
        value = item
    elif category == "events":
        value = item.get("name", "")
    elif category in ("tags", "triggers", "strings"):
        value = item.get("key", "")
    else:
        value = "{}://{}{}".format(item.get("scheme") or "", item.get("host") or "", item.get("path") or "")
    return any(fnmatch.fnmatch(value, pattern) for pattern in patterns)


def _reviewer() -> str:
    try:
        name = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        name = ""
    return name or os.environ.get("USER") or "unknown"
