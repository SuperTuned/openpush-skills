---
name: openpush-scan
description: Use when the user wants OpenPush to suggest push templates, journeys, in-app messages or segments for their app, wants to scan their codebase for OpenPush signals, review what is shared with OpenPush, instrument missing events, document their OpenPush setup, or set up the scan in CI.
license: Apache-2.0
compatibility: Requires Python 3.9 or later. The openpush-scan command-line tool is bundled in scripts/.
argument-hint: "[scan · review · login · workspace · share · suggest · instrument · document · ci] [root]"
allowed-tools:
  - Bash(openpush-scan *)
  - Bash(python3 -m openpush_scan *)
  - Bash(python3 *scripts/openpush-scan *)
  - Bash(py *scripts/openpush-scan *)
  - Bash(python *scripts/openpush-scan *)
---

# OpenPush Scan

Turn the app vocabulary already present in a repository into reviewed, evidence-backed OpenPush draft programs. Code stays local. Only the consent-filtered manifest may be uploaded.

## Setup

Choose the scanner command once, in this order. Use it wherever this skill or an agent packet says `openpush-scan`, and pass it to agents as `scanner command`.

1. `openpush-scan --version` works: use `openpush-scan`.
2. Else pick Python: try `python3`, then `py -3` (the Windows launcher), then `python`, and take the first whose `--version` prints Python 3.9 or later. One that prints nothing, like the Microsoft Store stub, counts as missing. Use `<python> <skill-dir>/scripts/openpush-scan`, where `<skill-dir>` is the folder holding this file, written with forward slashes. Always run the script through that interpreter, never directly. It needs nothing else for scan, review, validate and `share --print`.
3. For `login`, `workspace`, `share` uploads and `logout`, if that command reports that keyring is missing: use `uvx --from "git+https://github.com/SuperTuned/openpush-skills" openpush-scan` when `uv` is installed, else `pipx run --spec "git+https://github.com/SuperTuned/openpush-skills" openpush-scan` when `pipx` is.
4. Otherwise print this and stop: `Install Python 3.9 or later (python3, or py on Windows), or run: pipx install "git+https://github.com/SuperTuned/openpush-skills"`

Choose the requested command before checking profiles. For `scan`, create the local manifest first, then always continue directly into the local consent review. A missing profile routes to local consent review, not authentication.

## Default scan flow

For a normal first run, `openpush-scan scan .` is the only command the user needs to invoke. Do not ask them to run `review` or `share` separately; guide them through review and offer sharing as part of the same conversation. The standalone commands remain available for resuming a specific stage.

Treat `openpush-scan scan [root]` as one guided workflow:

1. Scan the requested root, reconcile analytics call sites with their active transport gates, and show the local findings.
2. Automatically open the local sharing review, whether or not a saved profile already exists.
3. Explain the available review actions in plain language and collect the user's choices. Do not leave the user at an unexplained `review>` prompt or require them to know CLI commands.
4. Save the choices, rerun the local review, and show the final selection and counts.
5. Ask exactly: `Do you want to share this final selection with OpenPush?`

Stop after that question. Continue to the explicit share/upload flow only if the user answers yes. Never infer consent to share from starting a scan, completing review, or saving a profile.

### Router completion invariant

The `openpush-scanner` result is an intermediate handoff, not a completed `scan` command. After the scanner returns, the router must validate its five contract sections and the reconciled local manifest (`openpush-scan validate --manifest openpush-manifest.local.json`), read [reference/review.md](reference/review.md), and immediately execute the local review procedure. Do not send a final response containing only scan findings.

JSON mode exists only so the scanner agent can consume deterministic scan output; it does not satisfy the review requirement. A `scan` request may finish only when the user is looking at the review table and deciding what to change, when the saved final selection has been shown and the router is asking whether to share it, or when a real scan/review error prevents progress.

## Commands

| Command | Procedure |
|---|---|
| `scan [root]` | Default with no command. Read [reference/review.md](reference/review.md), spawn `openpush-scanner`, validate its result and reconciled manifest, then immediately run the guided local review. Scanner completion is not command completion. End by asking whether to share the final selection. Never automatically continue to `share` or remote `suggest`. |
| `review` | Read [reference/review.md](reference/review.md), guide the user through the available actions, save their choices, show the final selection, then ask whether to share it. |
| `login` | Only when the user asks to sign in or explicitly proceeds to sharing: run `openpush-scan login`. Browser authorization grants discovery access only. |
| `workspace use <name-or-id>` | Select the local workspace context after login. This does not authorize an app upload. |
| `share` | Only on an explicit share/upload request, follow the share procedure in [reference/review.md](reference/review.md). |
| `suggest` | Read [reference/suggest.md](reference/suggest.md), then spawn `openpush-program-reviewer`. |
| `instrument` | Read [reference/instrument.md](reference/instrument.md), then spawn `openpush-instrumenter`. |
| `document` | Read [reference/document.md](reference/document.md), then spawn `openpush-documenter`. |
| `ci` | Read [reference/ci.md](reference/ci.md). No agent is needed. |

## Recommendation quality

Read [reference/recommendation-quality.md](reference/recommendation-quality.md) when shaping or reviewing suggestions. Also read [reference/message-best-practices.md](reference/message-best-practices.md) for channel-specific copy, relevance, timing and measurement rules. Prioritize new user value over event coverage; preserve the contextual card visuals and meaningful stop paths.

## Analytics event invariant

The event manifest represents effective emitted events, not a catalog of declarations. The deterministic pass follows recognized call sites, simple forwarding wrappers, and literal transport allowlists. The scanner model must also inspect app-owned analytics wrappers and managers for allowlists, denylists, feature flags, unconditional returns, and other gates. Commented-out or otherwise inactive entries do not survive. A gate affects only the transport it controls; direct OpenPush calls and independent providers remain.

If semantic inspection finds a deterministic miss, the scanner may edit only the local manifest's `events` array, must retain local source evidence, and must validate the result before review. It never edits app source or shares the manifest. Unresolved runtime or remote-configured gates remain in place with an explicit warning rather than a guessed removal.

## Authentication boundary

`scan` and consent `review` are entirely local: never request login, an API key, or an OpenPush connection, and never probe remote tools or endpoints. A scan request, category selection, goal choice, saved profile, or approval of the consent review does not authorize authentication or upload.

Require authentication only when the user explicitly proceeds to `share`/upload or separately asks to sign in. `openpush-scan login` grants discovery access for listing workspaces and apps; it grants no upload access. `workspace use` saves a non-secret local selection and grants no upload access. The first explicit `share` requests a separate app-bound grant. `share --print` is a local preview and requires no authentication. Suggestions must use a manifest the user has explicitly shared; never upload or initiate authentication merely to obtain suggestions.

## Agent routing

Spawn each agent fresh with exactly the input packet named in its playbook. When installed as a Claude Code plugin the agents are namespaced: spawn `openpush-scan:<agent>` (for example `openpush-scan:openpush-scanner`) when the bare name is not available. Codex names them with underscores (for example `openpush_scanner`). Never read `agents/*.md` before spawning. Wait once, then verify that the response contains that agent's contract sections in order. If it is empty or malformed, respawn once with the same packet.

When no subagent tool is exposed, or the named agent is not installed (for example after a skills-only install), load `degraded/<agent>.md` and run it inline. End with this exact disclosure:

`⚠️ DEGRADED: single-context (no sub-agent tool exposed)`

## Hard stops

- Show the share review to the user verbatim, explain how to respond, then **STOP** for their choices.
- After saving the final review choices, ask whether the user wants to share them with OpenPush; do not share until they answer yes.
- Upload only after the user approves the preview.
- Apply instrumentation patches one at a time, each after an explicit yes.
- Never run `share` without a saved profile.
- Keep API keys out of chat, commands, files, manifests, profiles, and agent packets. Never read, echo, copy, or interpolate a key; let the existing client consume credentials privately.
- Never upload `openpush-manifest.local.json`; upload only `openpush-scan share --print` output or the CLI-filtered equivalent.

## User-facing language

Use OpenPush terminology in suggestions, explanations, previews and review reports. Do not name or link external messaging providers or research vendors in user-facing output. Keep research attribution internal.
