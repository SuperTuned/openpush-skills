# OpenPush skills

The OpenPush codebase scanner and its agent skill.

`openpush-scan` reads your app repository on your machine and lists the OpenPush signals it already has: platforms, SDK modules, events, tags, in-app triggers, deep links, locales and local notifications. You review that list and choose what to share. OpenPush turns the shared summary into draft push templates, journeys, in-app messages and segments. The skill guides the scan, the review and the optional share from your coding agent.

## What's here

| Path | What it is |
| --- | --- |
| `skills/openpush-scan/` | The `openpush-scan` agent skill: the scanner in `scripts/`, its four agents, and a fallback that runs their steps one after another |
| `pyproject.toml` | Builds the `openpush-scan` command-line tool (Python 3.9+) from `skills/openpush-scan/` |
| `.claude-plugin/`, `agents/` | Claude Code marketplace and plugin: the repository root is the plugin, so it loads `skills/openpush-scan/`, plus its four agents from `agents/` |
| `tests/` | Tests for the command-line tool |

## Install

```bash
npx skills add SuperTuned/openpush-skills
```

This works for Claude Code, Codex, Cursor, GitHub Copilot, Gemini CLI, OpenCode, Amp, Windsurf, Kiro and other agents. The scanner is bundled in the skill and runs with Python 3.9 or later (`python3`, or `py` on Windows), including the Python that ships with macOS, so scanning and review need nothing else. Then ask your agent to scan the repository with the openpush-scan skill.

This installs the skill but not its four agents, so the skill runs their steps one after another. To add the agents, run the bundled installer from the installed skill folder, for example:

```bash
python3 .agents/skills/openpush-scan/scripts/openpush-scan install-skill --codex
```

On Windows:

```powershell
py -3 .agents\skills\openpush-scan\scripts\openpush-scan install-skill --codex
```

### Claude Code plugin

```text
/plugin marketplace add SuperTuned/openpush-skills
/plugin install openpush-scan@openpush-skills
```

Then run `/openpush-scan:openpush-scan` in your app repository. The four agents run as subagents.

### install-skill flags

`install-skill` copies the skill, its bundled scanner and, where the agent supports them, the four agents. It installs into the current repository. Add `--user` to install into your home directory instead. You can name several agents at once, or use `--all` for every agent found on this machine.

| Agent | Flag | Skill | Agents | Steps run |
| --- | --- | --- | --- | --- |
| Claude Code | `--claude` | `.claude/skills/` | `.claude/agents/` | as subagents |
| Codex | `--codex` | `.agents/skills/` | `.codex/agents/` | as subagents |
| Cursor | `--cursor` | `.agents/skills/` | `.cursor/agents/` | as subagents |
| GitHub Copilot | `--copilot` | `.agents/skills/` | `.github/agents/` (`~/.copilot/agents/` with `--user`) | as subagents |
| Gemini CLI | `--gemini` | `.agents/skills/` | `.gemini/agents/` | as subagents |
| OpenCode | `--opencode` | `.agents/skills/` | `.opencode/agents/` (`~/.config/opencode/agents/` with `--user`) | as subagents |
| Amp | `--amp` | `.agents/skills/` | none | one after another |
| Windsurf | `--windsurf` | `.agents/skills/` | none | one after another |
| Kiro | `--kiro` | `.kiro/skills/` | none | one after another |

To update, run `install-skill` again with `--force`: it replaces the skill folder and removes agent files the new version no longer ships. To remove it, run `openpush-scan uninstall-skill --<agent>` (or `--all`), with `--user` for a home-directory install. Both change only what `install-skill` recorded in the skill folder, or a folder whose `SKILL.md` is this skill. A skill folder that `npx skills` installed stays under its control: update or remove it with `npx skills update openpush-scan` or `npx skills remove openpush-scan` (add `-g` for a global install), while `install-skill` and `uninstall-skill` change only the agent files they wrote.

### Sharing and CI

Signing in and sharing store a token in your system keychain through the `keyring` package, which the bundled scanner does not include. When you choose to share, the skill runs the full tool for that step with `uvx` or `pipx`:

```bash
uvx --from "git+https://github.com/SuperTuned/openpush-skills" openpush-scan share --app <app>
```

To install the command for CI or everyday use:

```bash
pipx install "git+https://github.com/SuperTuned/openpush-skills"
```

Once the package is on PyPI, `pipx install openpush-scan` will work too.

## Command-line use

```bash
openpush-scan scan .        # scan the repository and write openpush-manifest.local.json
openpush-scan review        # choose which categories to share
openpush-scan share --print # preview the exact upload body, locally
openpush-scan share --app <app>
```

Run `openpush-scan --help` for every command. Without the package, use `python3 skills/openpush-scan/scripts/openpush-scan` in the same way, or on Windows `py -3 skills\openpush-scan\scripts\openpush-scan scan .`

## Privacy

- The scan runs locally. Your source code never leaves your machine.
- You review each category, and can exclude single items, before anything is shared. Secret-shaped values, file paths and source text are removed.
- Nothing is uploaded until you explicitly choose to share and confirm the upload preview.

## Documentation

[Codebase scan guide](https://www.openpush.ai/docs/guides/codebase-scan)

## Contributing

This repository is published from OpenPush's main repository. Issues are welcome. Pull requests are reviewed and ported there, then published back here.

Run the tests with Python 3.9 or later (`python3`, or `py` on Windows):

```bash
PYTHONPATH=skills/openpush-scan/scripts python3 -m unittest discover -s tests
```

## License

Apache-2.0. See [LICENSE](LICENSE).
