"""Extract deep-link declarations and matching URL literals."""

from __future__ import annotations

from pathlib import Path
import plistlib
import re
from typing import Any, Iterable
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET


ANDROID = "{http://schemas.android.com/apk/res/android}"
SKIP_DIRS = {".git", "node_modules", "Pods", "DerivedData", "build", ".gradle", "Library", "Temp", "obj", "bin"}


class DeepLinkResults(list[dict[str, Any]]):
    def __init__(self, values: Iterable[dict[str, Any]] = (), warnings: list[str] | None = None):
        super().__init__(values)
        self.warnings = warnings or []


def scan_deep_links(root: Path) -> DeepLinkResults:
    root = Path(root).resolve()
    warnings: list[str] = []
    items: dict[tuple[Any, ...], dict[str, Any]] = {}

    for path in root.rglob("Info.plist"):
        if _skip(path, root) or any("Tests" in part for part in path.relative_to(root).parts):
            continue
        try:
            with path.open("rb") as stream:
                data = plistlib.load(stream)
        except (OSError, plistlib.InvalidFileException, ValueError) as exc:
            warnings.append(f"{path.relative_to(root)}: could not parse plist ({exc})")
            continue
        for url_type in data.get("CFBundleURLTypes", []):
            for scheme in url_type.get("CFBundleURLSchemes", []):
                _merge(items, _item("custom_scheme", str(scheme), None, None, "ios", path, root))

    for path in root.rglob("*.entitlements"):
        if _skip(path, root):
            continue
        try:
            with path.open("rb") as stream:
                data = plistlib.load(stream)
        except (OSError, plistlib.InvalidFileException, ValueError) as exc:
            warnings.append(f"{path.relative_to(root)}: could not parse entitlements ({exc})")
            continue
        for domain in data.get("com.apple.developer.associated-domains", []):
            if str(domain).startswith("applinks:"):
                host = str(domain)[len("applinks:"):].split("?mode=", 1)[0]
                _merge(items, _item("universal_link", "https", host, None, "ios", path, root))

    for path in root.rglob("AndroidManifest.xml"):
        relative = path.relative_to(root).as_posix()
        if _skip(path, root) or not (
            "/src/main/" in f"/{relative}" or relative.startswith("src/main/")
            or relative.endswith("Assets/Plugins/Android/AndroidManifest.xml")
        ):
            continue
        try:
            tree = ET.parse(path)
        except (OSError, ET.ParseError) as exc:
            warnings.append(f"{path.relative_to(root)}: could not parse Android manifest ({exc})")
            continue
        for intent_filter in tree.findall(".//intent-filter"):
            actions = {action.get(ANDROID + "name") for action in intent_filter.findall("action")}
            if "android.intent.action.VIEW" not in actions:
                continue
            verified = intent_filter.get(ANDROID + "autoVerify") == "true"
            for data in intent_filter.findall("data"):
                scheme = data.get(ANDROID + "scheme")
                host = data.get(ANDROID + "host")
                path_value = (
                    data.get(ANDROID + "path")
                    or data.get(ANDROID + "pathPrefix")
                    or data.get(ANDROID + "pathPattern")
                )
                kind = "app_link" if verified and scheme in ("http", "https") else "custom_scheme"
                _merge(items, _item(kind, scheme, host, path_value, "android", path, root))

    settings = root / "ProjectSettings" / "ProjectSettings.asset"
    if settings.exists():
        try:
            text = settings.read_text(encoding="utf-8", errors="replace")
            match = re.search(r"(?m)^\s*iOSURLSchemes:\s*\n((?:\s+-\s+.+\n?)+)", text)
            if match:
                for scheme in re.findall(r"(?m)^\s+-\s+(.+?)\s*$", match.group(1)):
                    line = text.count("\n", 0, match.start()) + 1
                    _merge(items, _item("custom_scheme", scheme.strip('"\''), None, None, "ios", settings, root, line))
        except OSError as exc:
            warnings.append(f"{settings.relative_to(root)}: could not read ({exc})")

    known = {item.get("scheme") for item in items.values() if item.get("scheme")}
    for path in _code_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        platform = {".swift": "ios", ".kt": "android", ".java": "android", ".cs": "unity"}[path.suffix]
        for match in re.finditer(r'["\'](?P<url>[A-Za-z][A-Za-z0-9+.-]*://[^"\'\s]+)["\']', text):
            url = match.group("url")
            scheme = url.split(":", 1)[0]
            if scheme not in known:
                continue
            parsed = urlsplit(url)
            if scheme in ("http", "https"):
                host, path_value = parsed.hostname, parsed.path or None
                kind = "app_link" if any(
                    item["kind"] == "app_link" and item.get("scheme") == scheme and item.get("host") == host
                    for item in items.values()
                ) else "universal_link"
            else:
                host = None
                path_value = "/" + parsed.netloc + (parsed.path or "") if parsed.netloc else (parsed.path or None)
                kind = "custom_scheme"
            line = text.count("\n", 0, match.start()) + 1
            item = _item(kind, scheme, host, path_value, platform, path, root, line)
            item["full_urls"] = [url]
            _merge(items, item)

    result = sorted(items.values(), key=lambda item: (
        item["kind"], item.get("scheme") or "", item.get("host") or "", item.get("path") or ""
    ))
    return DeepLinkResults(result, warnings)


def _item(kind: str, scheme: str | None, host: str | None, path_value: str | None,
          platform: str, source_path: Path, root: Path, line: int = 1) -> dict[str, Any]:
    return {
        "kind": kind,
        "scheme": scheme,
        "host": host,
        "path": path_value,
        "platforms": [platform],
        "full_urls": [],
        "source": [{"file": source_path.relative_to(root).as_posix(), "line": line}],
    }


def _merge(items: dict[tuple[Any, ...], dict[str, Any]], item: dict[str, Any]) -> None:
    key = (item["kind"], item.get("scheme"), item.get("host"), item.get("path"))
    existing = items.get(key)
    if existing is None:
        items[key] = item
        return
    existing["platforms"] = sorted(set(existing["platforms"]) | set(item["platforms"]))
    existing["full_urls"] = sorted(set(existing["full_urls"]) | set(item["full_urls"]))
    existing["source"].extend(item["source"])


def _skip(path: Path, root: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1])


def _code_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in {".swift", ".kt", ".java", ".cs"} and not _skip(path, root):
            yield path
