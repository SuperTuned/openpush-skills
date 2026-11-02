"""Install and uninstall the OpenPush Scan skill for coding agents.

Each target copies the skill (without its `agents/` folder, with the bundled
scanner in `scripts/`) into a directory the agent reads skills from, and writes
the four subagents in that agent's own format where it has one. Agents without
file-based subagents run the same steps one after another from `degraded/`.

A skill folder is changed only when it is ours: it holds our install record
(install_record.MARKER) or, failing that, its SKILL.md is named openpush-scan.
A folder `npx skills` manages (its lock lists openpush-scan) is never replaced or
removed; only our agent files and a record beside it change. Agent files are
deleted only when the record lists them. Replacing a folder is atomic
(folder_swap).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import stat
from typing import Callable, Iterable

from . import __version__, bundle
from . import folder_swap, portable
from . import install_record as record


SHARED_SKILLS = ".agents/skills"
ASK = "ask it to use the openpush-scan skill"


@dataclass(frozen=True)
class Target:
    label: str
    skills: str                      # skills root, relative to the project or home
    invoke: str
    agents: str | None = None        # subagent directory in the project
    user_agents: str | None = None   # subagent directory in the home directory
    render: Callable[[Path], tuple[str, str]] | None = None
    detect: tuple[str, ...] = ()     # home-relative paths and commands that mean "installed"


def _claude_agent(path: Path) -> tuple[str, str]:
    return path.name, path.read_text(encoding="utf-8")


def _codex_agent(path: Path) -> tuple[str, str]:
    fields, body = _agent_parts(path)
    name = fields["name"].replace("-", "_")
    content = (
        f"name = {json.dumps(name)}\n"
        f"description = {json.dumps(fields['description'])}\n"
        f"developer_instructions = {_toml_multiline(_with_tool_limits(fields, body))}\n"
    )
    return f"{name}.toml", content


def _cursor_agent(path: Path) -> tuple[str, str]:
    fields, body = _agent_parts(path)
    front = [f"name: {fields['name']}", f"description: {json.dumps(fields['description'])}"]
    if not _tools(fields) & {"Edit", "Write", "Bash"}:
        front.append("readonly: true")
    return path.name, _markdown(front, _with_tool_limits(fields, body))


COPILOT_TOOLS = {"Read": "read", "Grep": "search", "Glob": "search", "Edit": "edit", "Write": "edit", "Bash": "execute"}


def _copilot_agent(path: Path) -> tuple[str, str]:
    fields, body = _agent_parts(path)
    tools = _mapped(fields, COPILOT_TOOLS)
    front = [
        f"name: {fields['name']}",
        f"description: {json.dumps(fields['description'])}",
        f"tools: {json.dumps(tools)}",
    ]
    return f"{path.stem}.agent.md", _markdown(front, _with_tool_limits(fields, body))


GEMINI_TOOLS = {
    "Read": "read_file", "Grep": "grep_search", "Glob": "glob",
    "Edit": "replace", "Write": "write_file", "Bash": "run_shell_command",
}


def _gemini_agent(path: Path) -> tuple[str, str]:
    fields, body = _agent_parts(path)
    front = [f"name: {fields['name']}", f"description: {json.dumps(fields['description'])}", "tools:"]
    front += [f"  - {tool}" for tool in _mapped(fields, GEMINI_TOOLS)]
    return path.name, _markdown(front, _with_tool_limits(fields, body))


def _opencode_agent(path: Path) -> tuple[str, str]:
    fields, body = _agent_parts(path)
    tools = _tools(fields)
    front = [
        f"description: {json.dumps(fields['description'])}",
        "mode: subagent",
        "permission:",
        f"  edit: {'allow' if tools & {'Edit', 'Write'} else 'deny'}",
        "  webfetch: deny",
    ]
    patterns = _bash_patterns(fields)
    if patterns:
        front.append("  bash:")
        front.append('    "*": deny')
        front += [f"    {json.dumps(pattern)}: allow" for pattern in patterns]
    else:
        front.append("  bash: deny")
    return path.name, _markdown(front, _with_tool_limits(fields, body))


TARGETS: dict[str, Target] = {
    "claude": Target(
        "Claude Code", ".claude/skills", "run /openpush-scan",
        ".claude/agents", ".claude/agents", _claude_agent, (".claude", "claude"),
    ),
    "codex": Target(
        "Codex", SHARED_SKILLS, "run $openpush-scan",
        ".codex/agents", ".codex/agents", _codex_agent, (".codex", "codex"),
    ),
    "cursor": Target(
        "Cursor", SHARED_SKILLS, "run /openpush-scan",
        ".cursor/agents", ".cursor/agents", _cursor_agent, (".cursor", "cursor", "cursor-agent"),
    ),
    "copilot": Target(
        "GitHub Copilot", SHARED_SKILLS, "run /openpush-scan",
        ".github/agents", ".copilot/agents", _copilot_agent, (".copilot", "copilot"),
    ),
    "gemini": Target(
        "Gemini CLI", SHARED_SKILLS, ASK,
        ".gemini/agents", ".gemini/agents", _gemini_agent, (".gemini", "gemini"),
    ),
    "opencode": Target(
        "OpenCode", SHARED_SKILLS, ASK,
        ".opencode/agents", ".config/opencode/agents", _opencode_agent, (".config/opencode", "opencode"),
    ),
    "amp": Target(
        "Amp", SHARED_SKILLS, ASK,
        detect=(".config/amp", "amp"),
    ),
    "windsurf": Target(
        "Windsurf", SHARED_SKILLS, ASK,
        detect=(".codeium/windsurf", ".config/devin", "windsurf", "devin"),
    ),
    "kiro": Target(
        "Kiro", ".kiro/skills", ASK,
        detect=(".kiro", "kiro", "kiro-cli"),
    ),
}
HARNESSES = tuple(TARGETS)


def detect(home: Path | None = None) -> list[str]:
    """Agents whose home-directory config or command is present on this machine."""
    home = home or Path.home()
    found = []
    for harness, target in TARGETS.items():
        if any((home / marker).exists() if ("/" in marker or marker.startswith("."))
               else shutil.which(marker) for marker in target.detect):
            found.append(harness)
    return found


class InstallRefused(Exception):
    """A skill folder that `install-skill` did not write and that is not this skill."""


def install(harnesses: str | Iterable[str], *, project: bool, source: Path | None = None,
            force: bool = False) -> list[str]:
    names = _names(harnesses)
    source_root = _source_root(source)
    base = Path.cwd() if project else Path.home()
    skill_files: list[tuple[Path, Callable[[], str] | Path]] = [
        (path.relative_to(source_root), path) for path in sorted(source_root.rglob("*"))
        if path.is_file() and path.relative_to(source_root).parts[0] not in ("agents", "scripts")
        and "__pycache__" not in path.relative_to(source_root).parts
        and path.name != record.MARKER]
    skill_files += [(Path("scripts") / relative, path) for relative, path in bundle.files()]
    skill_files.append((Path("scripts") / bundle.ENTRY, _constant(bundle.ENTRY_SOURCE)))
    agents = sorted((source_root / "agents").glob("*.md"))

    # Plan everything and refuse foreign folders before the first write.
    folders = _folders(names, base)
    states = {root: record.ownership(root, base, not project) for root in folders}
    for root, state in states.items():
        if state == record.FOREIGN:
            raise InstallRefused(
                f"Refusing to change {root}: it has no {record.MARKER} and its SKILL.md is not "
                f"named {record.SKILL_NAME}. Move it away, then install again.")
    agent_files: dict[str, list[tuple[Path, str]]] = {}
    for name in names:
        target = TARGETS[name]
        agent_dir = target.agents if project else target.user_agents
        agent_files[name] = []
        if agent_dir and target.render:
            for agent in agents:
                filename, content = target.render(agent)
                agent_files[name].append((base / agent_dir / filename, content))
    pending = [record.record_path(root, state) for root, state in states.items()]
    for root, state in states.items():
        if _rewrites(state, force):
            area = folder_swap.work_area(root)
            pending += [area / f"{folder_swap.STAGING_PREFIX}check" / relative for relative, _ in skill_files]
            pending.append(root.parent / f"{folder_swap.STAGING_PREFIX}check")
    for name in names:
        pending += [path for path, _ in agent_files[name] if force or not path.exists()]
    _preflight(pending)

    messages = [f"Removed leftover: {path}"
                for path in folder_swap.clean_leftovers(folder_swap.work_area(root) for root in folders)]
    for root, members in folders.items():
        state = states[root]
        previous = record.load(root, state)
        marker = previous
        if _rewrites(state, force):
            marker = record.new(__version__)
            marker["targets"] = {name: list(paths) for name, paths in previous["targets"].items()}
        else:
            messages.append(_managed(root, "update", project) if state == record.NPX
                            else f"Exists: {root} (use --force to replace)")
        plans = {name: _plan_agents(name, agent_files[name], previous, base, force) for name in members}
        for name, plan in plans.items():
            marker["targets"][name] = plan["record"]
        # The folder and its record first, so the record never misses a file written below.
        if _rewrites(state, force):
            def finish(staging: Path, marker: dict = marker) -> None:
                bundle.make_executable(staging / "scripts" / bundle.ENTRY)
                record.write(staging / record.MARKER, marker)

            if folder_swap.replace(root, skill_files, finish):
                messages.append(f"Replaced: {root}")
            messages.extend(f"Wrote: {root / relative}" for relative, _ in skill_files)
        else:
            record.write(record.record_path(root, state), marker)
        for plan in plans.values():
            _apply_agents(plan, messages)
    python = portable.choose_python()
    for root in folders:
        if python:
            messages.append(f"Bundled scanner: {' '.join(python)} {(root / 'scripts' / bundle.ENTRY).as_posix()}")
        else:
            messages.append("Bundled scanner: needs Python 3.9 or later (python3, or py on Windows)")
    for name in names:
        target = TARGETS[name]
        if target.render:
            mode = "Its four agents run as subagents."
        else:
            mode = "It has no subagent files, so the skill runs the four steps one after another."
        messages.append(f"{target.label}: {target.invoke}. {mode}")
    return messages


def _rewrites(state: str, force: bool) -> bool:
    """Whether install writes the skill folder: new, or ours with --force (never npx's)."""
    return state == record.ABSENT or (force and state in (record.RECORDED, record.SKILL_ONLY))


def _plan_agents(name: str, files: list[tuple[Path, str]], previous: dict, base: Path,
                 force: bool) -> dict:
    """What to write, skip and delete for one target, and what its record will list."""
    keep = set(record.listed(previous, name))
    plan: dict = {"write": [], "skip": [], "delete": [], "record": []}
    for path, content in files:
        rel = record.relative(path, base)
        if path.exists() and not force:
            plan["skip"].append(path)
            if rel in keep:
                plan["record"].append(rel)
        else:
            plan["write"].append((path, content))
            plan["record"].append(rel)
    if force:
        shipped = {record.relative(path, base) for path, _ in files}
        plan["delete"] = [base / rel for rel in sorted(keep - shipped)]
    else:
        plan["record"] += [rel for rel in record.listed(previous, name) if rel not in plan["record"]]
    return plan


def _apply_agents(plan: dict, messages: list[str]) -> None:
    for path in plan["skip"]:
        messages.append(f"Exists: {path} (use --force to replace)")
    for path, content in plan["write"]:
        path.parent.mkdir(parents=True, exist_ok=True)
        portable.write_text(path, content)
        messages.append(f"Wrote: {path}")
    for stale in plan["delete"]:
        if stale.is_file() or stale.is_symlink():
            stale.unlink()
            messages.append(f"Removed: {stale}")


def _managed(root: Path, command: str, project: bool) -> str:
    scope = "" if project else " -g"
    return (f"Managed by npx skills: {root} was left as it is; "
            f"run npx skills {command} {record.SKILL_NAME}{scope}")


def uninstall(harnesses: str | Iterable[str], *, project: bool) -> tuple[list[str], bool]:
    """Remove what install-skill recorded. Returns the messages and whether all went cleanly."""
    names = _names(harnesses)
    base = Path.cwd() if project else Path.home()
    folders = _folders(names, base)
    messages = [f"Removed leftover: {path}"
                for path in folder_swap.clean_leftovers(folder_swap.work_area(root) for root in folders)]
    clean = True
    for root, members in folders.items():
        state = record.ownership(root, base, not project)
        if state == record.ABSENT:
            messages.append(f"Not installed: {root}")
            continue
        if state == record.FOREIGN:
            messages.append(f"Not removed: {root} has no {record.MARKER} and its SKILL.md is not "
                            f"named {record.SKILL_NAME}.")
            clean = False
            continue
        if state == record.SKILL_ONLY:
            record.remove_folder(root)
            messages.append(f"Removed: {root}")
            for name in members:
                target = TARGETS[name]
                agent_dir = target.agents if project else target.user_agents
                if agent_dir and target.render:
                    messages.append(f"Left alone: {base / agent_dir} (no install record, so "
                                    f"{target.label} agent files were not removed)")
            continue
        marker = record.load(root, state)
        for name in members:
            for rel in record.listed(marker, name):
                path = base / rel
                if path.is_file() or path.is_symlink():
                    path.unlink()
                    messages.append(f"Removed: {path}")
            marker["targets"].pop(name, None)
        others = [TARGETS[name].label if name in TARGETS else name for name in marker["targets"]]
        if state == record.NPX:
            sidecar = record.sidecar(root)
            if others:
                record.write(sidecar, marker)
            elif sidecar.exists():
                sidecar.unlink()
            messages.append(_managed(root, "remove", project))
        elif others:
            record.write(root / record.MARKER, marker)
            messages.append(f"Kept: {root} (still installed for {', '.join(others)})")
        else:
            record.remove_folder(root)
            messages.append(f"Removed: {root}")
    return messages, clean


def _names(harnesses: str | Iterable[str]) -> list[str]:
    names = [harnesses] if isinstance(harnesses, str) else list(dict.fromkeys(harnesses))
    for name in names:
        if name not in TARGETS:
            raise ValueError(f"unsupported harness {name}")
    if not names:
        raise ValueError("no harness given")
    return names


def _folders(names: list[str], base: Path) -> dict[Path, list[str]]:
    """Skill folder -> the targets that read it, in the order given."""
    folders: dict[Path, list[str]] = {}
    for name in names:
        folders.setdefault(base / TARGETS[name].skills / record.SKILL_NAME, []).append(name)
    return folders


def _constant(content: str) -> Callable[[], str]:
    return lambda: content


def _preflight(destinations: list[Path]) -> None:
    """Refuse a read-only target before writing the first installed file."""
    for destination in destinations:
        parent = destination.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        mode = parent.stat().st_mode
        if not mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
            raise PermissionError(f"Cannot write {destination}: {parent} is read-only")


def _source_root(source: Path | None) -> Path:
    if source:
        candidate = Path(source)
        if candidate.name != "openpush-scan":
            candidate = candidate / "openpush-scan"
    else:
        candidate = bundle.skill_dir() or bundle.package_dir() / "skills" / "openpush-scan"
    if not (candidate / "SKILL.md").exists():
        raise FileNotFoundError(f"OpenPush skill sources not found at {candidate}; pass --from <skills-dir>")
    return candidate


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        return {}, text
    front, body = text[4:].split("\n---\n", 1)
    fields = {}
    for line in front.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields, body


def _agent_parts(path: Path) -> tuple[dict[str, str], str]:
    fields, body = _frontmatter(path.read_text(encoding="utf-8"))
    fields.setdefault("name", path.stem)
    fields.setdefault("description", "")
    return fields, body.lstrip("\n")


def _tool_list(fields: dict[str, str]) -> list[str]:
    return [tool.strip() for tool in fields.get("tools", "").split(",") if tool.strip()]


def _tools(fields: dict[str, str]) -> set[str]:
    """Base tool names, so `Bash(git status)` counts as `Bash`."""
    return {tool.split("(", 1)[0] for tool in _tool_list(fields)}


def _bash_patterns(fields: dict[str, str]) -> list[str]:
    return [tool[5:-1] for tool in _tool_list(fields) if tool.startswith("Bash(") and tool.endswith(")")]


def _mapped(fields: dict[str, str], names: dict[str, str]) -> list[str]:
    known = sorted((tool for tool in _tools(fields) if tool in names), key=list(names).index)
    return list(dict.fromkeys(names[tool] for tool in known))


def _with_tool_limits(fields: dict[str, str], body: str) -> str:
    if not fields.get("tools"):
        return body
    return f"Use only these tools: {fields['tools']}. Do not use any other tool.\n\n{body}"


def _markdown(front: list[str], body: str) -> str:
    return "---\n" + "\n".join(front) + "\n---\n\n" + body


def _toml_multiline(text: str) -> str:
    if "'''" not in text:
        return "'''\n" + text + "'''"
    return json.dumps(text)
