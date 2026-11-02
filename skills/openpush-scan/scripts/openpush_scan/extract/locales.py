"""Extract locales, selected strings, release notes, and app versions."""

from __future__ import annotations

from pathlib import Path
import plistlib
import re
from typing import Any
import xml.etree.ElementTree as ET


PREFERRED = re.compile(r"welcome|onboard|reminder|streak|cart|offer|trial|update|new|back", re.I)
SKIP_DIRS = {".git", "node_modules", "Pods", "DerivedData", "build", ".gradle", "Library", "Temp", "obj", "bin"}


def scan_locales(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    warnings: list[str] = []
    locales: set[str] = set()
    default_strings: dict[str, str] = {}

    for path in root.rglob("*.lproj"):
        if not path.is_dir() or _skip(path, root):
            continue
        locale = path.stem
        if locale != "Base":
            locales.add(locale)
        if locale in ("en", "en-US"):
            strings_path = path / "Localizable.strings"
            if strings_path.exists():
                for key, value in _parse_apple_strings(strings_path).items():
                    default_strings.setdefault(key, value)

    for path in root.rglob("strings.xml"):
        if _skip(path, root):
            continue
        folder = path.parent.name
        if folder == "values":
            locale = "en"
            warnings.append(f"{path.relative_to(root)}: treating unqualified values as locale en")
            for key, value in _parse_android_strings(path).items():
                default_strings.setdefault(key, value)
        elif folder.startswith("values-"):
            locale = folder[len("values-"):].replace("-r", "-")
        else:
            continue
        locales.add(locale)

    if any("Localization" in path.parts for path in root.rglob("*") if path.is_dir()):
        warnings.append("Unity Localization tables are not parsed; locale inventory may be incomplete")

    versions = _versions(root, warnings)
    app_version = versions.get("ios") or versions.get("android") or versions.get("unity")
    distinct = set(versions.values())
    if len(distinct) > 1:
        warnings.append("App versions disagree across platforms: " + ", ".join(f"{key}={value}" for key, value in sorted(versions.items())))

    strings = [
        {"key": key, "value": value[:200]}
        for key, value in sorted(default_strings.items(), key=lambda item: (not bool(PREFERRED.search(item[0])), item[0]))[:50]
    ]
    return {
        "locales": sorted(locales),
        "strings": strings,
        "release_notes": _release_notes(root, app_version),
        "app_version": app_version,
        "warnings": warnings,
    }


def _parse_apple_strings(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return dict(re.findall(r'^\s*"([^"\\]+)"\s*=\s*"([^"\\]*)"\s*;', text, re.MULTILINE))


def _parse_android_strings(path: Path) -> dict[str, str]:
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return {}
    return {
        node.get("name"): (node.text or "").strip()
        for node in tree.findall(".//string") if node.get("name")
    }


def _versions(root: Path, warnings: list[str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for path in sorted(root.rglob("*.pbxproj")):
        if _skip(path, root):
            continue
        match = re.search(r"MARKETING_VERSION\s*=\s*([^;\s]+)", path.read_text(encoding="utf-8", errors="replace"))
        if match:
            versions.setdefault("ios", match.group(1).strip('"'))
    for path in sorted(root.rglob("Info.plist")):
        if "ios" in versions or _skip(path, root):
            continue
        try:
            with path.open("rb") as stream:
                value = plistlib.load(stream).get("CFBundleShortVersionString")
            if value and not str(value).startswith("$("):
                versions["ios"] = str(value)
        except (OSError, plistlib.InvalidFileException, ValueError):
            pass
    for path in sorted(list(root.rglob("build.gradle")) + list(root.rglob("build.gradle.kts"))):
        if _skip(path, root):
            continue
        match = re.search(r'versionName\s*=?\s*"([^"]+)"', path.read_text(encoding="utf-8", errors="replace"))
        if match:
            versions.setdefault("android", match.group(1))
    settings = root / "ProjectSettings" / "ProjectSettings.asset"
    if settings.exists():
        match = re.search(r"(?m)^\s*bundleVersion:\s*(.+?)\s*$", settings.read_text(encoding="utf-8", errors="replace"))
        if match:
            versions["unity"] = match.group(1).strip('"')
    return versions


def _release_notes(root: Path, app_version: str | None) -> dict[str, Any] | None:
    fastlane = sorted(root.glob("**/fastlane/metadata/*/release_notes.txt"))
    whatsnew = sorted(root.glob("**/distribution/whatsnew/whatsnew-*"))
    for path in fastlane + whatsnew:
        if _skip(path, root):
            continue
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            continue
        if path.name.startswith("whatsnew-"):
            locale = path.name[len("whatsnew-"):]
        else:
            locale = path.parent.name
        return {"version": app_version, "locale": locale, "text": text[:1200]}
    for path in sorted(root.rglob("CHANGELOG.md")):
        if _skip(path, root):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"(?ms)^##\s+([^\n]+)\n(.*?)(?=^##\s+|\Z)", text)
        if not match:
            continue
        version_match = re.search(r"\d+\.\d+(?:\.\d+)?", match.group(1))
        return {
            "version": version_match.group(0) if version_match else app_version,
            "locale": "en",
            "text": match.group(2).strip()[:1200],
        }
    return None


def _skip(path: Path, root: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1])
