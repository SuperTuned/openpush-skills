"""Extract OpenPush SDK vocabulary from Swift, Kotlin/Java, and C# source."""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path
import re
from typing import Any, Iterable


SKIP_DIRS = {
    ".git", "node_modules", "Pods", "DerivedData", "build", ".gradle",
    "Library", "Temp", "obj", "bin",
}
LITERAL = r'(?P<lit>"(?:[^"\\]|\\.)*")'
ANALYTICS_ARGUMENT = r'(?P<arg>"(?:[^"\\]|\\.)*"|[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)'
# An app-owned analytics wrapper: any method named Track…Event or Send…Event
# (TrackEvent, trackGameEvent, SendAnalyticsEvent). The name must end in Event.
WRAPPER_METHOD = r"(?:[Tt]rack|[Ss]end)[A-Za-z0-9_]*Event"
# Provider SDK methods that a wrapper forwards an event name to.
SINK_METHODS = r"logEvent|LogEvent|CustomData|RecordEvent"
# OpenPush's own trackEvent/TrackEvent calls are counted by PATTERNS["events"].
NOT_OPENPUSH = r"(?<!OpenPush\.)"


def _patterns(*expressions: str) -> list[re.Pattern[str]]:
    return [re.compile(expression, re.MULTILINE) for expression in expressions]


PATTERNS: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    "events": [
        ("ios", _patterns(r"\bOpenPush\.trackEvent\(\s*" + LITERAL)[0]),
        ("android", _patterns(r"\bOpenPush\.trackEvent\(\s*" + LITERAL)[0]),
        ("unity", _patterns(r"\bOpenPush\.TrackEvent\(\s*" + LITERAL)[0]),
    ],
    "tags": [
        ("ios", _patterns(r"\b(?:OpenPush|OneSignal)\.User\.addTag\(\s*key:\s*" + LITERAL)[0]),
        ("android", _patterns(r"\b(?:OpenPush|OneSignal)\.User\.addTag\(\s*" + LITERAL)[0]),
        ("unity", _patterns(r"\b(?:OpenPush|OneSignal)\.User\.AddTag\(\s*" + LITERAL)[0]),
    ],
    "triggers": [
        ("ios", _patterns(r"\b(?:OpenPush|OneSignal)\.InAppMessages\.addTrigger\(\s*" + LITERAL)[0]),
        ("android", _patterns(r"\b(?:OpenPushInAppMessages|(?:OpenPush|OneSignal)\.InAppMessages)\.addTrigger\(\s*" + LITERAL)[0]),
        ("unity", _patterns(r"\b(?:OpenPush|OneSignal)\.InAppMessages\.AddTrigger\(\s*" + LITERAL)[0]),
    ],
    "outcomes": [
        (platform, _patterns(r"\bOneSignal\.Session\.(?P<method>addOutcome|addUniqueOutcome|addOutcomeWithValue)\(\s*" + LITERAL)[0])
        for platform in ("ios", "android", "unity")
    ],
    "aliases": [
        ("ios", _patterns(r"\bOpenPush\.User\.addAlias\(\s*label:\s*" + LITERAL)[0]),
        ("android", _patterns(r"\bOpenPush\.User\.addAlias(?:es)?\(\s*" + LITERAL)[0]),
        ("unity", _patterns(r"\bOpenPush\.User\.AddAlias(?:es)?\(\s*" + LITERAL)[0]),
    ],
}

ANALYTICS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("amplitude", re.compile(
        r"\b(?:[A-Za-z_]\w*[Aa]mplitude[A-Za-z_]\w*|Amplitude\.Instance)\."
        r"(?:logEvent|LogEvent)\s*\(\s*" + ANALYTICS_ARGUMENT,
        re.MULTILINE,
    )),
    ("firebase", re.compile(
        r"\bFirebaseAnalytics\.LogEvent\s*\(\s*" + ANALYTICS_ARGUMENT,
        re.MULTILINE,
    )),
    ("unity-analytics", re.compile(
        r"\b(?:Analytics\.CustomEvent|AnalyticsService\.Instance\."
        r"(?:CustomData|RecordEvent))\s*\(\s*" + ANALYTICS_ARGUMENT,
        re.MULTILINE,
    )),
    ("gameanalytics", re.compile(
        r"\bGameAnalytics\.NewDesignEvent\s*\(\s*" + ANALYTICS_ARGUMENT,
        re.MULTILINE,
    )),
    ("analytics", re.compile(
        NOT_OPENPUSH + r"\b" + WRAPPER_METHOD + r"\s*\(\s*" + ANALYTICS_ARGUMENT,
        re.MULTILINE,
    )),
]


PLATFORM_EXTENSIONS = {".swift": "ios", ".kt": "android", ".java": "android", ".cs": "unity"}


def scan_sdk_calls(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    ignores = _ignore_patterns(root)
    sources = list(_source_files(root, ignores))
    versions = _sdk_versions(root, ignores)
    # Lockfiles are a useful signal on their own. A wrapper repository may
    # intentionally contain no native source while still pinning OpenPush.
    platforms = sorted({PLATFORM_EXTENSIONS[path.suffix] for path in sources} | set(versions))
    if (root / "ProjectSettings").is_dir() and "unity" not in platforms:
        platforms.append("unity")
        platforms.sort()

    merged: dict[str, dict[str, dict[str, Any]]] = {
        "events": {}, "tags": {}, "triggers": {}, "outcomes": {}, "aliases": {}
    }
    identity = {"login": False, "logout": False, "auth_hash": False}
    capabilities = {
        "in_app_messages": False,
        "live_activities": False,
        "click_listener": False,
        "foreground_listener": False,
        "permission_pre_prompt": None,
        "onesignal_compat": False,
    }
    dynamic_counts = {"events": 0, "tags": 0, "triggers": 0}
    modules: dict[str, set[str]] = {platform: set() for platform in platforms}
    saw_permission_request = False
    constants = _string_constants(sources)

    for path in sources:
        platform = PLATFORM_EXTENSIONS[path.suffix]
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        relative = path.relative_to(root).as_posix()
        if "OneSignal." in text:
            capabilities["onesignal_compat"] = True
            modules.setdefault(platform, set()).add("OpenPushOneSignal")
        if "OpenPush" in text:
            modules.setdefault(platform, set()).add("OpenPush")
        if "OpenPushInAppMessages" in text or ".InAppMessages." in text:
            capabilities["in_app_messages"] = True
            modules.setdefault(platform, set()).add("OpenPushInAppMessages")
        if re.search(r"OpenPush\.LiveActivities\.", text):
            capabilities["live_activities"] = True
            modules.setdefault(platform, set()).add("OpenPushLiveActivities")
        if re.search(r"Notifications\.addClickListener|Notifications\.Clicked\s*\+=", text):
            capabilities["click_listener"] = True
        if re.search(r"addForegroundLifecycleListener|ForegroundWillDisplay", text):
            capabilities["foreground_listener"] = True
        if re.search(r"requestPermission|RequestPermission", text):
            saw_permission_request = True

        _scan_named_calls(text, relative, platform, merged)
        _scan_batch_calls(text, relative, platform, merged)
        _scan_dynamic_calls(text, platform, dynamic_counts)
        _scan_analytics_calls(text, relative, platform, constants, merged["events"])

        if re.search(r"\bOpenPush\.(?:login|Login)\(", text):
            identity["login"] = True
            if re.search(r"authHash\s*[:=]", text):
                identity["auth_hash"] = True
        if re.search(r"\bOpenPush\.(?:logout|Logout)\s*\(", text):
            identity["logout"] = True

    filtered_events = _apply_analytics_event_allowlists(
        merged["events"], _analytics_event_allowlists(sources, constants)
    )
    warnings = []
    if filtered_events:
        warnings.append(
            "Analytics event allowlist applied: excluded "
            f"{filtered_events} called event{'s' if filtered_events != 1 else ''} "
            f"that {'are' if filtered_events != 1 else 'is'} not currently enabled."
        )

    trigger_names = merged["triggers"]
    if saw_permission_request and not any("prompt" in key.lower() for key in trigger_names):
        capabilities["permission_pre_prompt"] = False

    sdk = {
        platform: {
            "version_hint": versions.get(platform),
            "modules": sorted(modules.get(platform, set())),
        }
        for platform in platforms
    }
    return {
        category: sorted(items.values(), key=lambda item: item.get("name", item.get("key", item.get("label", ""))))
        for category, items in merged.items()
    } | {
        "identity": identity,
        "capabilities": capabilities,
        "sdk": sdk,
        "dynamic_counts": dynamic_counts,
        "platforms": platforms,
        "warnings": warnings,
    }


def _scan_named_calls(
    text: str,
    relative: str,
    platform: str,
    merged: dict[str, dict[str, dict[str, Any]]],
) -> None:
    for category, variants in PATTERNS.items():
        for expected_platform, pattern in variants:
            if expected_platform != platform:
                continue
            for match in pattern.finditer(text):
                name = _literal(match.group("lit"))
                source = {"file": relative, "line": text.count("\n", 0, match.start()) + 1}
                statement = _call_expression(text, match.start())
                if category == "events":
                    item = {
                        "name": name,
                        "property_keys": sorted(_property_keys(statement, platform)),
                        "call_count": 1,
                        "platforms": [platform],
                        "providers": ["openpush"],
                        "dynamic": False,
                        "source": [source],
                    }
                elif category in ("tags", "triggers"):
                    item = {
                        "key": name,
                        "value_samples": _argument_value(statement, match.end() - match.start()),
                        "platforms": [platform],
                        "source": [source],
                    }
                elif category == "outcomes":
                    item = {
                        "name": name,
                        "has_value": match.group("method") == "addOutcomeWithValue",
                        "platforms": [platform],
                        "source": [source],
                    }
                else:
                    item = {"label": name, "platforms": [platform], "source": [source]}
                _merge(merged[category], name, item)


def _scan_batch_calls(text: str, relative: str, platform: str,
                      merged: dict[str, dict[str, dict[str, Any]]]) -> None:
    variants = {
        "tags": ("addTags", "AddTags"),
        "triggers": ("addTriggers", "AddTriggers"),
    }
    for category, method_names in variants.items():
        for method in method_names:
            for match in re.finditer(rf"\b(?:OpenPush|OneSignal|OpenPushInAppMessages)(?:\.User|\.InAppMessages)?\.{method}\s*\(", text):
                statement = _call_expression(text, match.start())
                if platform == "ios":
                    pairs = re.findall(r'"([^"\\]+)"\s*:\s*"([^"\\]*)"', statement)
                elif platform == "android":
                    pairs = re.findall(r'"([^"\\]+)"\s+to\s+"([^"\\]*)"', statement)
                else:
                    pairs = re.findall(r'(?:\{|\[)\s*"([^"\\]+)"\s*(?:,|\]\s*=)\s*"([^"\\]*)"', statement)
                line = text.count("\n", 0, match.start()) + 1
                for key, value in pairs:
                    _merge(merged[category], key, {
                        "key": key, "value_samples": [value], "platforms": [platform],
                        "source": [{"file": relative, "line": line}],
                    })


def _scan_dynamic_calls(text: str, platform: str, counts: dict[str, int]) -> None:
    event_method = "TrackEvent" if platform == "unity" else "trackEvent"
    candidates = {
        "events": rf"\bOpenPush\.{event_method}\((?P<arg>[^)\n]*)",
        "tags": r"\b(?:OpenPush|OneSignal)\.User\.(?:addTag|AddTag)\((?P<arg>[^)\n]*)",
        "triggers": r"\b(?:OpenPushInAppMessages|(?:OpenPush|OneSignal)\.InAppMessages)\.(?:addTrigger|AddTrigger)\((?P<arg>[^)\n]*)",
    }
    for category, pattern in candidates.items():
        for match in re.finditer(pattern, text):
            argument = re.sub(r"^\s*(?:key:\s*)?", "", match.group("arg"))
            if not argument.startswith('"'):
                counts[category] += 1


def _scan_analytics_calls(text: str, relative: str, platform: str,
                          constants: dict[str, str], target: dict[str, dict[str, Any]]) -> None:
    """Collect literal analytics vocabulary without treating it as OpenPush-ready."""
    clean = _without_comments(text)
    if _vendored_analytics_path(relative):
        return
    for provider, pattern in ANALYTICS_PATTERNS:
        for match in pattern.finditer(clean):
            name = _analytics_name(match.group("arg"), constants)
            if not name or not re.fullmatch(r"[a-zA-Z0-9_\-. ]{1,128}", name):
                continue
            statement = _call_expression(clean, match.start())
            _merge(target, name, {
                "name": name,
                "property_keys": sorted(_analytics_property_keys(statement, platform, constants)),
                "call_count": 1,
                "platforms": [platform],
                "providers": [provider],
                "dynamic": False,
                "source": [{"file": relative, "line": clean.count("\n", 0, match.start()) + 1}],
            })

    _scan_local_analytics_wrapper_calls(
        clean, relative, platform, constants, target
    )

    # Custom analytics wrappers often assign a named constant to `eventName`
    # before forwarding it through a shared Track…Event or Send…Event method.
    assignment = re.compile(
        r"\b(?:const\s+)?string\s+eventName\s*=\s*" + ANALYTICS_ARGUMENT,
        re.MULTILINE,
    )
    for match in assignment.finditer(clean):
        tail = clean[match.end():match.end() + 4000]
        forwarding = re.search(
            r"\b" + WRAPPER_METHOD + r"\s*\(\s*eventName\b",
            tail,
        )
        if not forwarding:
            continue
        name = _analytics_name(match.group("arg"), constants)
        if not name or not re.fullmatch(r"[a-zA-Z0-9_\-. ]{1,128}", name):
            continue
        fragment = clean[match.start():match.end() + forwarding.end()]
        _merge(target, name, {
            "name": name,
            "property_keys": sorted(_analytics_property_keys(fragment, platform, constants)),
            "call_count": 1,
            "platforms": [platform], "providers": ["analytics"], "dynamic": False,
            "source": [{"file": relative, "line": clean.count("\n", 0, match.start()) + 1}],
        })


def _scan_local_analytics_wrapper_calls(
    text: str,
    relative: str,
    platform: str,
    constants: dict[str, str],
    target: dict[str, dict[str, Any]],
) -> None:
    """Follow small C# helpers that pass an event name to an analytics sink."""
    if platform != "unity":
        return
    declaration = re.compile(
        r"\b(?:public|private|internal|protected|static|async|sealed|virtual|override|new\s+)*"
        r"(?:void|Task|ValueTask|bool)\s+(?P<method>[A-Za-z_]\w*)\s*"
        r"\((?P<params>[^)]*)\)\s*\{",
        re.MULTILINE,
    )
    for definition in declaration.finditer(text):
        method = definition.group("method")
        # Track…Event/Send…Event calls are already matched directly, so
        # following them here as well would count each call twice.
        if re.fullmatch(WRAPPER_METHOD, method) or re.fullmatch(SINK_METHODS, method):
            continue
        parameter = re.search(
            r"\bstring\s+(?P<name>[A-Za-z_]\w*)\b", definition.group("params")
        )
        if not parameter:
            continue
        event_parameter = parameter.group("name")
        body = _balanced_body(text, definition.end() - 1)
        if body is None or not re.search(
            r"\b(?:" + WRAPPER_METHOD + "|" + SINK_METHODS + r")\s*\(\s*"
            + re.escape(event_parameter) + r"\b",
            body,
        ):
            continue
        call = re.compile(
            rf"\b{re.escape(method)}\s*\(\s*" + ANALYTICS_ARGUMENT,
            re.MULTILINE,
        )
        for match in call.finditer(text):
            name = _analytics_name(match.group("arg"), constants)
            if not name or not re.fullmatch(r"[a-zA-Z0-9_\-. ]{1,128}", name):
                continue
            statement = _call_expression(text, match.start())
            _merge(target, name, {
                "name": name,
                "property_keys": sorted(
                    _analytics_property_keys(statement, platform, constants)
                ),
                "call_count": 1,
                "platforms": [platform],
                "providers": ["analytics"],
                "dynamic": False,
                "source": [{
                    "file": relative,
                    "line": text.count("\n", 0, match.start()) + 1,
                }],
            })


def _string_constants(sources: list[Path]) -> dict[str, str]:
    found: dict[str, set[str]] = {}
    pattern = re.compile(
        r"\b(?:(?:public|private|internal|protected|static|readonly|const)\s+)*"
        r"string\s+(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<lit>\"(?:[^\"\\]|\\.)*\")"
    )
    for path in sources:
        try:
            text = _without_comments(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        for match in pattern.finditer(text):
            found.setdefault(match.group("name"), set()).add(_literal(match.group("lit")))
    return {name: next(iter(values)) for name, values in found.items() if len(values) == 1}


def _analytics_name(argument: str, constants: dict[str, str]) -> str | None:
    if argument.startswith('"'):
        return _literal(argument)
    return constants.get(argument.rsplit(".", 1)[-1])


def _analytics_event_allowlists(
    sources: list[Path], constants: dict[str, str]
) -> dict[str, set[str]]:
    """Find event allowlists that demonstrably gate an analytics transport.

    A declaration is not enough: the same file must test membership using the
    collection and forward the tested event to a recognized analytics method.
    This keeps unrelated gameplay allowlists from silently deleting events.
    If any entry cannot be resolved to a stable string, that collection is
    ignored rather than applying a partial, destructive filter.
    """
    found: dict[str, set[str]] = {}
    declaration = re.compile(
        r"\b(?P<name>[A-Za-z_]\w*)\s*(?::\s*[^=\n]+)?=\s*"
        r"(?:new\s+[A-Za-z_][\w.<> ,]*\s*)?"
        r"(?:(?:setOf|Set\.of|Arrays\.asList)\s*)?"
        r"(?P<open>[{[(])",
        re.MULTILINE,
    )
    transport = re.compile(
        NOT_OPENPUSH + r"\b(?:" + WRAPPER_METHOD + "|" + SINK_METHODS + r")\s*"
        r"\(\s*(?P<event>[A-Za-z_]\w*)\b"
    )

    for path in sources:
        try:
            clean = _without_comments(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        relative = path.as_posix()
        if _vendored_analytics_path(relative):
            continue
        for match in declaration.finditer(clean):
            collection = match.group("name")
            normalized = collection.lower().replace("_", "")
            if "event" not in normalized or not (
                "allow" in normalized or "whitelist" in normalized
            ):
                continue
            gated_names = {
                gated.group("event")
                for gated in re.finditer(
                    rf"\b{re.escape(collection)}\.(?:Contains|contains)\s*"
                    r"\(\s*(?P<event>[A-Za-z_]\w*)\s*\)",
                    clean,
                )
            }
            gated_names.update(
                gated.group("event")
                for gated in re.finditer(
                    rf"\b(?P<event>[A-Za-z_]\w*)\s+in\s+{re.escape(collection)}\b",
                    clean,
                )
            )
            if not gated_names or not any(
                call.group("event") in gated_names for call in transport.finditer(clean)
            ):
                continue
            body = _balanced_body(clean, match.start("open"))
            if body is None:
                continue
            values = _resolved_allowlist_entries(body, constants)
            if values is None:
                continue
            provider = _analytics_provider_for_gate(path, clean)
            found.setdefault(provider, set()).update(values)
    return found


def _balanced_body(text: str, opening: int) -> str | None:
    pairs = {"{": "}", "[": "]", "(": ")"}
    opener = text[opening]
    closer = pairs[opener]
    depth = 0
    quote = False
    escaped = False
    for index in range(opening, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = False
            continue
        if char == '"':
            quote = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[opening + 1:index]
    return None


def _resolved_allowlist_entries(
    body: str, constants: dict[str, str]
) -> set[str] | None:
    values: set[str] = set()
    for raw in body.split(","):
        entry = raw.strip()
        if not entry:
            continue
        if re.fullmatch(r'"(?:[^"\\]|\\.)*"', entry):
            values.add(_literal(entry))
            continue
        reference = re.fullmatch(
            r"(?:[A-Za-z_]\w*\.)+(?P<member>[A-Za-z_]\w*)", entry
        )
        if reference and reference.group("member") in constants:
            values.add(constants[reference.group("member")])
            continue
        return None
    return values


def _analytics_provider_for_gate(path: Path, text: str) -> str:
    context = (path.name + "\n" + text[:2000]).lower()
    if "amplitude" in context:
        return "amplitude"
    if "firebase" in context:
        return "firebase"
    if "gameanalytics" in context:
        return "gameanalytics"
    if "unityanalytics" in context or "analyticsservice" in context:
        return "unity-analytics"
    return "analytics"


def _apply_analytics_event_allowlists(
    events: dict[str, dict[str, Any]], allowlists: dict[str, set[str]]
) -> int:
    if not allowlists:
        return 0
    removed = 0
    generic_allowed = set().union(*allowlists.values())
    for name in list(events):
        item = events[name]
        providers = set(item.get("providers", []))
        kept: set[str] = set()
        for provider in providers:
            if provider == "analytics":
                if name in generic_allowed:
                    kept.add(provider)
            elif provider in allowlists:
                if name in allowlists[provider]:
                    kept.add(provider)
            else:
                kept.add(provider)
        if kept:
            item["providers"] = sorted(kept)
        else:
            del events[name]
            removed += 1
    return removed


def _analytics_property_keys(statement: str, platform: str,
                             constants: dict[str, str]) -> set[str]:
    keys = set(_property_keys(statement, platform))
    if platform != "unity":
        return keys
    for index_literal, index_member, pair_literal, pair_member in re.findall(
            r"(?:\[\s*(?:\"([^\"\\]+)\"|(?:[A-Za-z_]\w*\.)*([A-Za-z_]\w*))\s*\]\s*=|"
            r"\{\s*(?:\"([^\"\\]+)\"|(?:[A-Za-z_]\w*\.)*([A-Za-z_]\w*))\s*,)",
            statement):
        # The alternation yields four captures; normalize without exposing values.
        candidate = index_literal or index_member or pair_literal or pair_member
        if not candidate:
            continue
        keys.add(constants.get(candidate, candidate))
    return {key for key in keys if len(key) <= 128}


def _vendored_analytics_path(relative: str) -> bool:
    parts = {part.lower() for part in Path(relative).parts[:-1]}
    return bool(parts & {"plugins", "thirdparty", "third_party", "googlepackages"})


def _without_comments(text: str) -> str:
    """Blank C-style comments while preserving offsets and line numbers."""
    pattern = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
    return pattern.sub(lambda match: "".join("\n" if char == "\n" else " "
                                              for char in match.group(0)), text)


def _merge(target: dict[str, dict[str, Any]], key: str, item: dict[str, Any]) -> None:
    existing = target.get(key)
    if existing is None:
        target[key] = item
        return
    existing["platforms"] = sorted(set(existing.get("platforms", [])) | set(item.get("platforms", [])))
    existing["source"].extend(item.get("source", []))
    if "call_count" in existing:
        existing["call_count"] += item.get("call_count", 0)
    if "property_keys" in existing:
        existing["property_keys"] = sorted(set(existing["property_keys"]) | set(item.get("property_keys", [])))
    if "providers" in existing or "providers" in item:
        existing["providers"] = sorted(set(existing.get("providers", [])) | set(item.get("providers", [])))
    if "value_samples" in existing:
        existing["value_samples"] = sorted(set(existing["value_samples"]) | set(item.get("value_samples", [])))[:20]
    if "has_value" in existing:
        existing["has_value"] = existing["has_value"] or item.get("has_value", False)


def _property_keys(statement: str, platform: str) -> set[str]:
    if platform == "ios":
        return set(re.findall(r'"(\w+)"\s*:', statement))
    if platform == "android":
        return set(re.findall(r'"(\w+)"\s+to\b', statement))
    return {
        left or right for left, right in re.findall(r'(?:\{\s*"(\w+)"\s*,|\["(\w+)"\]\s*=)', statement)
    }


def _argument_value(statement: str, _offset: int) -> list[str]:
    values = re.findall(r',\s*(?:withValue:\s*)?"([^"\\]*)"', statement[:500])
    return values[:1]


def _literal(value: str) -> str:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value[1:-1]


def _call_expression(text: str, start: int, limit: int = 4000) -> str:
    """Return one call expression, respecting nested brackets and strings."""
    opening = text.find("(", start, min(len(text), start + 300))
    if opening < 0:
        return text[start:start + limit]
    depth = 0
    quote = False
    escaped = False
    for index in range(opening, min(len(text), start + limit)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = False
            continue
        if char == '"':
            quote = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return text[start:start + limit]


def _source_files(root: Path, ignores: list[str]) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in PLATFORM_EXTENSIONS:
            continue
        relative = path.relative_to(root)
        if any(part in SKIP_DIRS for part in relative.parts[:-1]):
            continue
        if any(fnmatch.fnmatch(relative.as_posix(), pattern) for pattern in ignores):
            continue
        yield path


def _ignore_patterns(root: Path) -> list[str]:
    path = root / ".openpush-scan-ignore"
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def _sdk_versions(root: Path, ignores: list[str]) -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for path in root.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        relative = path.relative_to(root).as_posix()
        if any(fnmatch.fnmatch(relative, pattern) for pattern in ignores):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if path.name == "Package.resolved" and "openpush-ios" in text:
            try:
                data = json.loads(text)
                pins = data.get("pins") or data.get("object", {}).get("pins", [])
                for pin in pins:
                    if "openpush-ios" in str(pin.get("location") or pin.get("repositoryURL") or "").lower():
                        version = pin.get("state", {}).get("version")
                        if version:
                            versions["ios"] = str(version)
            except (json.JSONDecodeError, TypeError):
                pass
        elif path.name == "Podfile.lock":
            match = re.search(r"^\s*-\s+OpenPush\s+\(([^)]+)\)", text, re.MULTILINE)
            if match:
                versions["ios"] = match.group(1)
        elif path.name.startswith("build.gradle"):
            match = re.search(r"ai\.openpush[^:'\"]*:[^:'\"]+:(?P<v>[\d.]+)", text)
            if match:
                versions["android"] = match.group("v")
        elif relative == "Packages/manifest.json":
            try:
                dependencies = json.loads(text).get("dependencies", {})
                for key, value in dependencies.items():
                    if key.startswith("ai.openpush"):
                        versions["unity"] = _unity_version_hint(value)
                        break
            except (json.JSONDecodeError, TypeError):
                pass
    return versions


def _unity_version_hint(dependency: Any) -> str | None:
    if not isinstance(dependency, str):
        return None
    candidate = dependency.rsplit("#", 1)[1] if "#" in dependency else dependency
    return candidate if re.fullmatch(r"[0-9A-Za-z.+-]{1,64}", candidate) else None
