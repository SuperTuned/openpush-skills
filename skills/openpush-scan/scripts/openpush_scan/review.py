"""Terminal consent review for an OpenPush app manifest."""

from __future__ import annotations

import json
from pathlib import Path
import shlex
from typing import Any, Callable

from . import share


MOMENTS = ("all", "onboarding", "activation", "purchase", "trial", "churn_risk", "milestone", "content_new", "cart", "permission", "retention")


def render(profile: dict[str, Any], local: dict[str, Any], *, include_guidance: bool = True) -> str:
    lines = [
        "## OpenPush sharing review",
        "",
        "Local review only. Nothing has been uploaded.",
        "Selecting categories or saving choices does not authorize sign-in or upload.",
        "",
        "Detected counts are before exclusions; the final upload preview shows what will be sent.",
        "",
        "| Selection | Category | Detected | Default | What OpenPush uses it for |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for category, on, count, explain, default in share.summary(profile, local):
        label = category.replace("_", " ").capitalize().replace("Sdk", "SDK").replace("urls", "URLs")
        lines.append(
            f"| {'Selected' if on else 'Not selected'} | {label} (`{category}`) | {count} | "
            f"{'On' if default else 'Off'} | {explain} |"
        )
    dropped = local.get("redactions", {}).get("dropped", 0)
    dynamic = local.get("dynamic_counts", {})
    lines.extend([
        "",
        "### Privacy and scan coverage",
        "",
        f"Never shared: file paths, source code, anything that matched a redaction rule ({dropped} dropped).",
        "Dynamic calls not readable: " + ", ".join(f"{key} {dynamic.get(key, 0)}" for key in ("events", "tags", "triggers")) + ".",
    ])
    goal = profile.get("goal")
    if goal and goal["moment"] == "all":
        lines.append("Goal: all moments (no single lifecycle priority).")
    else:
        lines.append(f"Goal: {goal['moment']} ({goal.get('event') or 'no event'})" if goal else "Goal: not set — suggestions will be ranked by fireability only.")
    if include_guidance:
        lines.extend([
            "",
            "### Review choices",
            "",
            "Reply `save` or `looks good` to keep these choices. You can also use:",
            "",
            "- `include <category>` or `exclude <category>`",
            "- `show <category>`",
            "- `exclude <category> <pattern>`",
            "- `goal <moment> [event]` or `goal all`",
            "- `defaults`",
        ])
    return "\n".join(lines)


def run(manifest_path: Path, profile_path: Path, *, non_interactive: bool = False,
        goal: str | None = None, input_fn: Callable[[str], str] | None = None,
        output_fn: Callable[[str], None] = print) -> int:
    input_fn = input_fn or input
    local = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    profile = share.load(profile_path)
    if non_interactive and profile is None:
        output_fn('No share profile. Run "openpush-scan review" once to choose what to share.')
        return 2
    profile = profile or share.new_profile()
    if goal and not _set_goal(profile, goal, local, input_fn, output_fn):
        return 2
    output_fn(render(profile, local))
    if non_interactive:
        return 0

    if not profile.get("goal") and not goal:
        answer = input_fn("Which moment matters most for this app right now? (" + ", ".join(MOMENTS[1:]) + ", all for no single priority, or skip) ").strip()
        if answer and answer != "skip":
            if answer.startswith("goal "):
                _set_goal(profile, answer[len("goal "):], local, input_fn, output_fn)
            else:
                _set_goal(profile, answer, local, input_fn, output_fn)

    while True:
        try:
            command = input_fn("review (type 'save' to keep these choices, or 'help')> ").strip()
        except EOFError:
            return 0
        if not command:
            continue
        parts = shlex.split(command)
        action = parts[0].lower()
        if action == "toggle" and len(parts) == 2 and parts[1] in share.DEFAULTS:
            key = parts[1]
            profile["categories"][key] = not profile["categories"].get(key, share.DEFAULTS[key])
            output_fn(f"{key}: {'on' if profile['categories'][key] else 'off'}")
        elif action == "include" and len(parts) == 2 and parts[1] in share.DEFAULTS:
            key = parts[1]
            profile["categories"][key] = True
            output_fn(f"{key}: on")
        elif action == "exclude" and len(parts) == 2 and parts[1] in share.DEFAULTS:
            key = parts[1]
            profile["categories"][key] = False
            output_fn(f"{key}: off")
        elif action == "exclude" and len(parts) == 3 and parts[1] in profile["exclude"]:
            profile["exclude"][parts[1]].append(parts[2])
            output_fn(f"excluded {parts[2]} from {parts[1]}")
        elif action == "show" and len(parts) == 2:
            _show(parts[1], local, output_fn)
        elif action == "goal" and len(parts) in (2, 3):
            _set_goal(profile, " ".join(parts[1:]), local, input_fn, output_fn)
        elif action == "defaults":
            profile["categories"] = dict(share.DEFAULTS)
            output_fn("defaults restored")
        elif action == "save" or command.lower() in ("looks good", "looks_good"):
            share.save(profile_path, profile)
            output_fn(f"Saved {profile_path}")
            output_fn(render(profile, local, include_guidance=False))
            output_fn("Do you want to share this final selection with OpenPush?")
            return 0
        elif action == "quit":
            return 0
        elif action == "help":
            output_fn("Commands: include <category>, exclude <category>, exclude <category> <pattern>, show <category>, goal <moment> [event], defaults, save, quit")
        else:
            output_fn("Commands: include <category>, exclude <category>, exclude <category> <pattern>, show <category>, goal <moment> [event], defaults, save, quit")


def _set_goal(profile: dict[str, Any], value: str, local: dict[str, Any],
              input_fn: Callable[[str], str], output_fn: Callable[[str], None]) -> bool:
    pieces = value.replace(":", " ", 1).split()
    moment = pieces[0] if pieces else ""
    event = pieces[1] if len(pieces) > 1 else None
    if moment not in MOMENTS:
        output_fn("Goal must be one of: " + ", ".join(MOMENTS))
        return False
    if moment == "all":
        event = None
    known = {item["name"] for item in local.get("events", [])}
    if event and event not in known:
        answer = input_fn(f'Event "{event}" is not in the scan; keep it anyway? [y/N] ').strip().lower()
        if answer not in ("y", "yes"):
            return False
    profile["goal"] = {"moment": moment, "event": event}
    return True


def _show(category: str, local: dict[str, Any], output_fn: Callable[[str], None]) -> None:
    values = local.get(category, [])
    if not isinstance(values, list):
        output_fn(json.dumps(values, sort_keys=True))
        return
    for item in values:
        if isinstance(item, str):
            output_fn(item)
            continue
        name = item.get("name") or item.get("key") or item.get("label") or item.get("scheme") or "item"
        providers = ", ".join(item.get("providers", []))
        locations = ", ".join(f"{source['file']}:{source['line']}" for source in item.get("source", []))
        details = "  ".join(value for value in (
            f"via {providers}" if providers else "", locations,
        ) if value)
        output_fn(f"{name}  {details}".rstrip())
