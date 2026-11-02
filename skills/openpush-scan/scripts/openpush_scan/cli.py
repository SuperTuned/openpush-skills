"""Command-line interface for OpenPush Scan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import os
import subprocess
from typing import Any

from . import __version__, portable
from .extract.deep_links import scan_deep_links
from .extract.local_notifications import scan_local_notifications
from .extract.locales import scan_locales
from .extract.sdk_calls import scan_sdk_calls
from .manifest import empty, strip_sources, validate as validate_manifest
from .redact import apply as redact
from . import review as reviewmod
from . import share as sharemod
from .client import Client, ClientError
from .client import OAuthManifestClient
from .auth import AuthError, OAuthClient, Session
from .installer import (HARNESSES, TARGETS, InstallRefused, detect as detect_agents,
                        install as install_skill, uninstall as uninstall_skill)
from importlib.resources import files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openpush-scan")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    scan = commands.add_parser("scan", help="scan an app repository")
    scan.add_argument("root", nargs="?", default=".")
    scan.add_argument("--out", default="openpush-manifest.local.json")
    scan.add_argument("--profile", default=".openpush/scan-share.json")
    scan.add_argument("--json", action="store_true")
    review = commands.add_parser("review", help="review and persist sharing choices")
    review.add_argument("--manifest", default="openpush-manifest.local.json")
    review.add_argument("--profile", default=".openpush/scan-share.json")
    review.add_argument("--non-interactive", action="store_true")
    review.add_argument("--goal")
    share = commands.add_parser("share", help="upload the reviewed manifest")
    _remote_arguments(share)
    share.add_argument("--ci", action="store_true")
    share.add_argument("--allow-branch", action="store_true")
    share.add_argument("--on-version-change", action="store_true")
    share.add_argument("--print", dest="print_only", action="store_true")
    login = commands.add_parser("login", help="sign in to OpenPush")
    login.add_argument("--server")
    auth = commands.add_parser("auth", help="inspect local authentication state")
    auth_commands = auth.add_subparsers(dest="auth_command", required=True)
    auth_commands.add_parser("status", help="show the signed-in account")
    commands.add_parser("logout", help="remove locally stored OpenPush authorization")
    workspace = commands.add_parser("workspace", help="select an OpenPush workspace")
    workspace_commands = workspace.add_subparsers(dest="workspace_command", required=True)
    workspace_commands.add_parser("list", help="list accessible workspaces")
    workspace_commands.add_parser("current", help="show the selected workspace")
    workspace_use = workspace_commands.add_parser("use", help="select a workspace")
    workspace_use.add_argument("workspace")
    ci = commands.add_parser("ci", help="compare the reviewed manifest without storing it")
    _remote_arguments(ci)
    ci.add_argument("--fail-on-broken-links", action="store_true")
    ci.add_argument("--print-workflow", action="store_true")
    commands.add_parser("explain", help="explain every share category")
    validate_cmd = commands.add_parser(
        "validate", help="validate a local manifest without sharing it"
    )
    validate_cmd.add_argument("--manifest", default="openpush-manifest.local.json")
    installer = commands.add_parser(
        "install-skill", help="install the skill into one or more coding agents"
    )
    for name in HARNESSES:
        installer.add_argument(f"--{name}", action="store_true",
                               help=f"install for {TARGETS[name].label}")
    installer.add_argument("--all", action="store_true",
                           help="install for every agent found on this machine, plus any named")
    scope = installer.add_mutually_exclusive_group()
    scope.add_argument("--project", action="store_true")
    scope.add_argument("--user", action="store_true")
    installer.add_argument("--from", dest="source")
    installer.add_argument("--force", action="store_true",
                           help="replace an earlier install of this skill, removing files it no longer ships")
    remover = commands.add_parser(
        "uninstall-skill", help="remove what install-skill wrote for one or more coding agents"
    )
    for name in HARNESSES:
        remover.add_argument(f"--{name}", action="store_true",
                             help=f"uninstall for {TARGETS[name].label}")
    remover.add_argument("--all", action="store_true", help="uninstall for every agent")
    remove_scope = remover.add_mutually_exclusive_group()
    remove_scope.add_argument("--project", action="store_true")
    remove_scope.add_argument("--user", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    portable.safe_console()
    args = build_parser().parse_args(argv)
    if args.command == "scan":
        return _scan(args)
    if args.command == "review":
        return reviewmod.run(
            Path(args.manifest), Path(args.profile),
            non_interactive=args.non_interactive, goal=args.goal,
        )
    if args.command == "share":
        return _share(args)
    if args.command == "login":
        return _login(args)
    if args.command == "auth":
        return _auth_status()
    if args.command == "logout":
        return _logout()
    if args.command == "workspace":
        return _workspace(args)
    if args.command == "ci":
        if args.print_workflow:
            print(files("openpush_scan").joinpath("templates/openpush-scan.yml").read_text(encoding="utf-8"), end="")
            return 0
        return _ci(args)
    if args.command == "explain":
        print(reviewmod.render(sharemod.new_profile(), empty(__version__)))
        return 0
    if args.command == "validate":
        return _validate(Path(args.manifest))
    if args.command == "install-skill":
        harnesses = [name for name in HARNESSES if getattr(args, name)]
        if args.all:
            harnesses = list(dict.fromkeys([*harnesses, *detect_agents()]))
        if not harnesses:
            flags = ", ".join(f"--{name}" for name in HARNESSES)
            print(f"No coding agent found. Name one: {flags}", file=sys.stderr)
            return 2
        try:
            messages = install_skill(
                harnesses, project=not args.user,
                source=Path(args.source) if args.source else None, force=args.force,
            )
        except (OSError, InstallRefused) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print("\n".join(messages))
        return 0
    if args.command == "uninstall-skill":
        harnesses = list(HARNESSES) if args.all else [name for name in HARNESSES if getattr(args, name)]
        if not harnesses:
            flags = ", ".join(f"--{name}" for name in HARNESSES)
            print(f"Name an agent ({flags}) or use --all.", file=sys.stderr)
            return 2
        try:
            messages, clean = uninstall_skill(harnesses, project=not args.user)
        except OSError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print("\n".join(messages))
        return 0 if clean else 1
    return 2


def _remote_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--app")
    parser.add_argument("--server")
    parser.add_argument("--profile", default=".openpush/scan-share.json")
    parser.add_argument("--manifest", default="openpush-manifest.local.json")


def _validate(path: Path) -> int:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"Could not read manifest: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"Manifest is not valid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(doc, dict):
        print("Manifest error: root must be an object", file=sys.stderr)
        return 1
    issues = validate_manifest(strip_sources(doc))
    if issues:
        for issue in issues:
            print(f"Manifest error: {issue}", file=sys.stderr)
        return 1
    print(f"Manifest valid: {path}")
    return 0


def _scan(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    sdk = scan_sdk_calls(root)
    deep_links = scan_deep_links(root)
    notifications = scan_local_notifications(root)
    locale_data = scan_locales(root)
    platforms = set(sdk["platforms"])
    for item in [*deep_links, *notifications]:
        platforms.update(item.get("platforms", []))
    if not platforms:
        print(
            f"No OpenPush SDK calls or app manifests found under {root}. Is this the app repo?",
            file=sys.stderr,
        )
        return 1

    doc = empty(__version__)
    for key in ("events", "tags", "triggers", "outcomes", "aliases", "identity", "capabilities", "sdk", "dynamic_counts"):
        doc[key] = sdk[key]
    doc["platforms"] = sorted(platforms)
    doc["deep_links"] = list(deep_links)
    doc["local_notifications"] = notifications
    for key in ("locales", "strings", "release_notes", "app_version"):
        doc[key] = locale_data[key]
    warnings = [*sdk.get("warnings", []), *deep_links.warnings, *locale_data["warnings"]]
    if warnings:
        doc["warnings"] = warnings
    doc, report = redact(doc)
    doc["redactions"] = report
    issues = validate_manifest(strip_sources(doc))
    if issues:
        for issue in issues:
            print(f"Manifest error: {issue}", file=sys.stderr)
        return 1

    out = Path(args.out)
    portable.write_text(out, json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    summary = _summary(doc, warnings)
    if args.json:
        print(json.dumps(summary, sort_keys=True))
        return 0

    print(_summary_line(summary))
    for warning in warnings:
        print(f"warning: {warning}")
    return reviewmod.run(out, Path(args.profile))


def _summary(doc: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    return {
        "platforms": doc["platforms"],
        "events": len(doc["events"]),
        "tags": len(doc["tags"]),
        "triggers": len(doc["triggers"]),
        "deep_links": len(doc["deep_links"]),
        "local_notifications": len(doc["local_notifications"]),
        "locales": len(doc["locales"]),
        "app_version": doc["app_version"],
        "release_notes_version": (doc["release_notes"] or {}).get("version"),
        "dynamic_counts": doc["dynamic_counts"],
        "redactions_dropped": doc["redactions"]["dropped"],
        "warnings": warnings,
    }


def _summary_line(summary: dict[str, Any]) -> str:
    dynamic = summary["dynamic_counts"]
    dynamic_parts = []
    for category in ("events", "tags", "triggers"):
        count = dynamic[category]
        if count:
            noun = {"events": "event call", "tags": "tag call", "triggers": "trigger call"}[category]
            dynamic_parts.append(f"{count} {noun}{'' if count == 1 else 's'}")
    return " · ".join([
        "platforms " + ",".join(summary["platforms"]),
        f"events {summary['events']}",
        f"tags {summary['tags']}",
        f"triggers {summary['triggers']}",
        f"deep links {summary['deep_links']}",
        f"local notifications {summary['local_notifications']}",
        f"locales {summary['locales']}",
        f"app version {summary['app_version'] or 'unknown'}",
        f"release notes {summary['release_notes_version'] or 'none'}",
        "dynamic: " + (", ".join(dynamic_parts) if dynamic_parts else "none"),
        f"redactions {summary['redactions_dropped']}",
    ])


def _share(args: argparse.Namespace) -> int:
    loaded = _reviewed(args)
    if loaded is None:
        return 2
    profile, local, doc, app, server = loaded
    if args.print_only:
        print(json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    key = os.environ.get("OPENPUSH_API_KEY")
    if args.ci and not args.allow_branch:
        branch = _branch()
        if branch not in ("main", "master"):
            print(f'Refusing to share from branch "{branch}" in CI; pass --allow-branch to override.', file=sys.stderr)
            return 2
    if not key:
        if args.ci:
            print("Set OPENPUSH_API_KEY (a full-scope key) to share in CI.", file=sys.stderr)
            return 2
        return _share_with_login(args, doc, app, server)
    client = Client(server, key)
    try:
        if args.on_version_change and client.latest_version(app) == doc.get("app_version"):
            print(f"App version {doc.get('app_version')} already shared; nothing to do.")
            return 0
        response = client.put_manifest(app, doc)
    except ClientError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    categories = sum(value is True for value in doc["shared_categories"].values())
    item_count = sum(len(doc.get(name, [])) for name in ("events", "tags", "triggers", "outcomes", "aliases", "deep_links", "local_notifications", "locales", "strings", "inferences"))
    print(
        f"Shared {categories} categories ({item_count} items) to {server} as manifest "
        f"{response.get('manifest_id', response.get('id', 'unknown'))}. "
        f"{response.get('suggestions_generated', 0)} suggestions generated "
        f"({response.get('ready_to_fire', 0)} ready to fire). Open: {server}/a/{app}/suggestions"
    )
    return 0


def _share_with_login(args: argparse.Namespace, doc: dict[str, Any], requested_app: str,
                      server: str) -> int:
    try:
        session = Session()
        if session.server != server:
            raise AuthError(
                f"Signed in to {session.server}, but this share targets {server}. "
                f"Run `openpush-scan login --server {server}`.")
        oauth_client = OAuthClient(session)
        catalog = oauth_client.catalog()
        workspace = _selected_workspace(session, catalog)
        app = _resolve_app(workspace, requested_app)
        if not app.get("can_share"):
            raise AuthError(f"Your {app.get('role', 'current')} role cannot share to {app['name']}.")
        token = oauth_client.app_token(app["id"])
        client = OAuthManifestClient(session.server, token)
        prepared = client.prepare(app["id"], doc)
    except (AuthError, ClientError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(_upload_preview(workspace, app, prepared.get("preview") or {}))
    confirm_token = prepared.get("confirm_token")
    if not confirm_token:
        print("OpenPush did not return a confirmation token; nothing was uploaded.", file=sys.stderr)
        return 2
    try:
        answer = input("\nUpload this reviewed manifest? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    try:
        if answer not in ("y", "yes"):
            client.discard(app["id"], confirm_token)
            print("Upload cancelled. Nothing was shared.")
            return 0
        response = client.confirm(app["id"], confirm_token)
    except ClientError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    result = response.get("result") or {}
    suggestions = result.get("suggestions") or {}
    print(
        f"Shared with {app['name']} ({app['id']}) in {workspace['name']}.\n"
        f"Manifest: {result.get('manifest_id', result.get('id', 'unknown'))}\n"
        f"Suggestions generated: {suggestions.get('generated', 0)}"
    )
    return 0


def _upload_preview(workspace: dict[str, Any], app: dict[str, Any], preview: dict[str, Any]) -> str:
    categories = [name.replace("_", " ") for name, enabled in
                  (preview.get("shared_categories") or {}).items() if enabled]
    counts = preview.get("counts") or {}
    version = preview.get("app_version") or {}
    goal = preview.get("goal") or {}
    diff = preview.get("diff") or {}
    lines = [
        "OpenPush share preview",
        "======================",
        f"Workspace: {workspace.get('name')} ({workspace.get('id')})",
        f"App:       {app.get('name')} ({app.get('id')})",
        f"Version:   {version.get('from') or 'none'} → {version.get('to') or 'none'}",
        f"Goal:      {goal.get('moment', 'not set')}"
        + (f" via {goal['event']}" if goal.get("event") else ""),
        "",
        f"Shared categories ({len(categories)}):",
    ]
    lines.extend(f"  • {name}" for name in categories)
    if not categories:
        lines.append("  • none")
    nonzero = [(name.replace("_", " "), value) for name, value in counts.items() if value]
    lines.extend(["", "Included items:"])
    lines.extend(f"  • {name}: {value}" for name, value in nonzero)
    if not nonzero:
        lines.append("  • none")
    added = diff.get("added") or {}
    removed = diff.get("removed") or {}
    additions = sum(len(values) for values in added.values())
    removals = sum(len(values) for values in removed.values())
    added_detail = ", ".join(f"{name.replace('_', ' ')} {len(values)}"
                             for name, values in added.items() if values) or "none"
    removed_detail = ", ".join(f"{name.replace('_', ' ')} {len(values)}"
                               for name, values in removed.items() if values) or "none"
    affected = preview.get("affected") or []
    lines.extend(["", "Changes on OpenPush:",
                  f"  • additions: {additions} ({added_detail})",
                  f"  • removals: {removals} ({removed_detail})",
                  f"  • affected saved content: {len(affected)}"])
    lines.extend(f"    - {item.get('type', 'item')}: {item.get('name') or item.get('id')}"
                 for item in affected[:10] if isinstance(item, dict))
    if len(affected) > 10:
        lines.append(f"    - and {len(affected) - 10} more")
    lines.append("  • suggestions will be generated after upload")
    return "\n".join(lines)


def _selected_workspace(session: Session, catalog: dict[str, Any]) -> dict[str, Any]:
    selected = session.config.get("workspace") or {}
    for workspace in catalog.get("workspaces") or []:
        if workspace.get("id") == selected.get("id"):
            return workspace
    raise AuthError("No workspace selected. Run `openpush-scan workspace use <name-or-id>`.")


def _resolve_named(items: list[dict[str, Any]], value: str, kind: str) -> dict[str, Any]:
    lowered = value.casefold()
    exact = [item for item in items if item.get("id") == value
             or str(item.get("name") or "").casefold() == lowered]
    if len(exact) == 1:
        return exact[0]
    prefixes = [item for item in items if str(item.get("id") or "").casefold().startswith(lowered)
                or str(item.get("name") or "").casefold().startswith(lowered)]
    if len(prefixes) == 1:
        return prefixes[0]
    if not exact and not prefixes:
        raise AuthError(f"No accessible {kind} matches {value!r}.")
    raise AuthError(f"{kind.title()} {value!r} is ambiguous; use its full ID.")


def _resolve_app(workspace: dict[str, Any], value: str) -> dict[str, Any]:
    return _resolve_named(workspace.get("apps") or [], value, "app")


def _login(args: argparse.Namespace) -> int:
    try:
        session = Session()
        target = args.server.rstrip("/") if args.server else session.server
        if target != session.server:
            _clear_authorizations(session)
            session.config["server"] = target
            session.save()
        catalog = OAuthClient(session).login()
    except AuthError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    account = catalog.get("account") or {}
    count = len(catalog.get("workspaces") or [])
    print(f"Signed in as {account.get('email', 'unknown')} at {session.server}.\nAccessible workspaces: {count}")
    return 0


def _auth_status() -> int:
    try:
        session = Session()
        signed_in = session.token_bundle(session.account_name()) is not None
    except AuthError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not signed_in:
        print("Not signed in. Run `openpush-scan login`.")
        return 1
    account = session.config.get("account") or {}
    workspace = session.config.get("workspace") or {}
    print(f"Signed in as {account.get('email', 'unknown')}\nServer: {session.server}\nWorkspace: {workspace.get('name') or 'not selected'}")
    return 0


def _workspace(args: argparse.Namespace) -> int:
    try:
        session = Session()
        if args.workspace_command == "current":
            current = session.config.get("workspace") or {}
            if not current:
                print("No workspace selected.")
                return 1
            print(f"{current.get('name')} ({current.get('id')})")
            return 0
        catalog = OAuthClient(session).catalog()
        workspaces = catalog.get("workspaces") or []
        if args.workspace_command == "list":
            selected = (session.config.get("workspace") or {}).get("id")
            for workspace in workspaces:
                marker = "*" if workspace.get("id") == selected else " "
                print(f"{marker} {workspace.get('name')} ({workspace.get('id')}) — {len(workspace.get('apps') or [])} apps")
            return 0
        chosen = _resolve_named(workspaces, args.workspace, "workspace")
        session.config["workspace"] = {"id": chosen["id"], "name": chosen["name"]}
        session.save()
        print(f"Using workspace {chosen['name']} ({chosen['id']}).")
        return 0
    except AuthError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def _logout() -> int:
    try:
        session = Session()
        _clear_authorizations(session)
    except AuthError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print("Signed out of OpenPush on this machine.")
    return 0


def _clear_authorizations(session: Session) -> None:
    oauth_client = OAuthClient(session)
    oauth_client.revoke(session.account_name())
    for app in list(session.config.get("app_grants") or []):
        oauth_client.revoke(session.app_name(app))
    for key in ("account", "workspace", "app_grants"):
        session.config.pop(key, None)
    session.save()


def _ci(args: argparse.Namespace) -> int:
    loaded = _reviewed(args)
    if loaded is None:
        return 2
    _profile, _local, doc, app, server = loaded
    key = os.environ.get("OPENPUSH_API_KEY")
    if not key:
        print("Set OPENPUSH_API_KEY to compare a manifest.", file=sys.stderr)
        return 2
    try:
        result = Client(server, key).diff_manifest(app, doc)
    except ClientError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    added, removed = result.get("added", {}), result.get("removed", {})
    for label, values in (("Added events", added.get("events", [])), ("Removed events", removed.get("events", [])), ("Added deep links", added.get("deep_links", [])), ("Removed deep links", removed.get("deep_links", []))):
        print(f"{label} ({len(values)})" + (": " + ", ".join(_display(value) for value in values) if values else ""))
    version = result.get("version", {})
    print(f"Version: {version.get('old') or 'none'} → {version.get('new') or doc.get('app_version') or 'none'}")
    affected = result.get("affected", [])
    for item in affected:
        print("Affected: " + (item if isinstance(item, str) else item.get("label", json.dumps(item, sort_keys=True))))
    return 1 if args.fail_on_broken_links and affected else 0


def _reviewed(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str, str] | None:
    profile = sharemod.load(Path(args.profile))
    if profile is None:
        print('No share profile. Run "openpush-scan review" once to choose what to share.', file=sys.stderr)
        return None
    try:
        local = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read manifest: {exc}", file=sys.stderr)
        return None
    doc = sharemod.apply(profile, local)
    issues = validate_manifest(doc)
    if issues:
        print("Manifest is not valid:\n" + "\n".join(issues), file=sys.stderr)
        return None
    app = args.app or profile.get("app")
    server = (args.server or profile.get("server") or "https://app.openpush.ai").rstrip("/")
    if not app:
        print("Set --app or save an app slug in the share profile.", file=sys.stderr)
        return None
    return profile, local, doc, app, server


def _branch() -> str:
    try:
        return subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _display(value: Any) -> str:
    if isinstance(value, str):
        return value
    return value.get("name") or value.get("key") or value.get("url") or json.dumps(value, sort_keys=True)


if __name__ == "__main__":
    raise SystemExit(main())
