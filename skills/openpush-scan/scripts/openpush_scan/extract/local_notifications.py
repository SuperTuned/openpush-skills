"""Extract local-notification triggers and opt-in copy."""

from __future__ import annotations

from pathlib import Path
import plistlib
import re
from typing import Any, Iterable
import xml.etree.ElementTree as ET


SKIP_DIRS = {".git", "node_modules", "Pods", "DerivedData", "build", ".gradle", "Library", "Temp", "obj", "bin"}


def scan_local_notifications(root: Path) -> list[dict[str, Any]]:
    root = Path(root).resolve()
    strings = _load_default_strings(root)
    results: list[dict[str, Any]] = []
    for path in _code_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        platform = {".swift": "ios", ".kt": "android", ".java": "android", ".cs": "unity"}[path.suffix]
        if platform == "ios":
            results.extend(_ios_notifications(text, path, root, strings))
        elif platform == "android":
            item = _android_notification(text, path, root, strings)
            if item:
                results.append(item)
        else:
            results.extend(_unity_notifications(text, path, root))
    return _merge(results)


def _ios_notifications(text: str, path: Path, root: Path,
                       strings: dict[str, str]) -> list[dict[str, Any]]:
    trigger_types = {
        "UNTimeIntervalNotificationTrigger": "time_interval",
        "UNCalendarNotificationTrigger": "calendar",
        "UNLocationNotificationTrigger": "location",
    }
    matches = [(match, trigger) for symbol, trigger in trigger_types.items()
               for match in re.finditer(symbol, text)]
    if not matches and "UNMutableNotificationContent" in text:
        content_match = re.search("UNMutableNotificationContent", text)
        matches = [(content_match, "unknown")] if content_match else []
    output = []
    lines = text.splitlines()
    for match, trigger in sorted(matches, key=lambda pair: pair[0].start()):
        line = text.count("\n", 0, match.start()) + 1
        window = "\n".join(lines[max(0, line - 41):min(len(lines), line + 40)])
        title, title_key = _swift_assignment(window, "title")
        body, body_key = _swift_assignment(window, "body")
        output.append(_notification(
            trigger, title or strings.get(title_key), body or strings.get(body_key),
            title_key, body_key, "ios", path, root, line,
        ))
    return output


def _android_notification(text: str, path: Path, root: Path,
                          strings: dict[str, str]) -> dict[str, Any] | None:
    if "NotificationCompat.Builder" not in text:
        return None
    trigger_match = re.search(r"AlarmManager\s*\.?.*?set\w*\s*\(|WorkManager.*?enqueue\s*\(", text, re.DOTALL)
    if not trigger_match:
        return None
    title, title_key = _android_copy(text, "setContentTitle")
    body, body_key = _android_copy(text, "setContentText")
    line = text.count("\n", 0, trigger_match.start()) + 1
    return _notification(
        "time_interval", title or strings.get(title_key), body or strings.get(body_key),
        title_key, body_key, "android", path, root, line,
    )


def _unity_notifications(text: str, path: Path, root: Path) -> list[dict[str, Any]]:
    results = []
    for match in re.finditer(r"new\s+(?:iOS|Android)Notification\b", text):
        window = text[match.start():match.start() + 2500]
        calendar = re.search(r"CalendarTrigger", window)
        timed = re.search(r"TimeTrigger|FireTime", window)
        trigger = "calendar" if calendar and (not timed or calendar.start() < timed.start()) else "time_interval" if timed else "unknown"
        title_match = re.search(r"\bTitle\s*=\s*\"([^\"\\]*)\"", window)
        body_match = re.search(r"\bBody\s*=\s*\"([^\"\\]*)\"", window)
        line = text.count("\n", 0, match.start()) + 1
        results.append(_notification(
            trigger,
            title_match.group(1) if title_match else None,
            body_match.group(1) if body_match else None,
            None, None, "unity", path, root, line,
        ))
    return results


def _swift_assignment(text: str, field: str) -> tuple[str | None, str | None]:
    literal = re.search(rf"\.{field}\s*=\s*\"([^\"\\]*)\"", text)
    localized = re.search(rf"\.{field}\s*=\s*NSLocalizedString\(\s*\"([^\"\\]+)\"", text)
    return (
        literal.group(1) if literal else None,
        localized.group(1) if localized else None,
    )


def _android_copy(text: str, method: str) -> tuple[str | None, str | None]:
    literal = re.search(rf"{method}\(\s*\"([^\"\\]*)\"", text)
    key = re.search(rf"{method}\(\s*(?:context\.)?getString\(R\.string\.(\w+)\)", text)
    return literal.group(1) if literal else None, key.group(1) if key else None


def _notification(trigger: str, title: str | None, body: str | None,
                  title_key: str | None, body_key: str | None, platform: str,
                  path: Path, root: Path, line: int) -> dict[str, Any]:
    return {
        "trigger": trigger,
        "title": title,
        "body": body,
        "title_key": title_key,
        "body_key": body_key,
        "platforms": [platform],
        "source": [{"file": path.relative_to(root).as_posix(), "line": line}],
    }


def _merge(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in items:
        key = (item["trigger"], item.get("title"), item.get("body"), item.get("title_key"), item.get("body_key"))
        if key not in merged:
            merged[key] = item
        else:
            merged[key]["platforms"] = sorted(set(merged[key]["platforms"]) | set(item["platforms"]))
            merged[key]["source"].extend(item["source"])
    return sorted(merged.values(), key=lambda item: (item["trigger"], item.get("title") or ""))


def _load_default_strings(root: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    candidates = sorted(root.rglob("en.lproj/Localizable.strings")) + sorted(root.rglob("values/strings.xml"))
    for path in candidates:
        if _skip(path, root):
            continue
        if path.suffix == ".strings":
            text = path.read_text(encoding="utf-8", errors="replace")
            for key, value in re.findall(r'^\s*"([^"\\]+)"\s*=\s*"([^"\\]*)"\s*;', text, re.MULTILINE):
                values.setdefault(key, value)
        else:
            try:
                tree = ET.parse(path)
            except ET.ParseError:
                continue
            for node in tree.findall(".//string"):
                if node.get("name") and node.text:
                    values.setdefault(node.get("name"), node.text.strip())
    return values


def _code_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in {".swift", ".kt", ".java", ".cs"} and not _skip(path, root):
            yield path


def _skip(path: Path, root: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1])
