# Local consent review

`review` is entirely local. Never request login, an API key, or an OpenPush connection, and never call remote tools during consent review.

After a local manifest exists, always continue into this review automatically. Run `openpush-scan review --non-interactive` to detect and render a saved profile. If no profile exists, start `openpush-scan review` and show its initial table before entering any choices. A saved profile is not a reason to skip review.

Show the complete Markdown output directly, without a code fence, so the share list renders as a table. Preserve every category, selection, count, default, explanation, and privacy note. Immediately follow the table with this plain-language guidance:

- `save` or `looks good` keeps the displayed choices.
- `include <category>` or `exclude <category>` changes whether a whole category is shared.
- `show <category>` lists the scanned items in that category.
- `exclude <category> <pattern>` removes matching items from a selected category.
- `goal <moment> [event]` changes which lifecycle moment should shape suggestions; `goal all` uses every matched moment with no single priority.
- `defaults` restores the recommended category choices.

Tell the user they can reply in those words or describe the changes naturally; translate their response into the interactive CLI commands. Do not expose a bare review prompt and expect the user to discover the command grammar. If the goal is unset, ask which lifecycle moment matters and optionally which scanned event represents it. Accept `all` when the user wants every repository-matched moment with no single lifecycle priority. Use the interactive `openpush-scan review` commands (`include`, `exclude`, `show`, `goal`, `defaults`, `save`) for every choice; do not edit the profile JSON.

The share review is a hard stop: show the table, the guidance above, and **STOP** for the user's choices. After saving those choices, rerun the local review and show the complete final selection and category counts. Then ask exactly: `Do you want to share this final selection with OpenPush?` Stop for the answer. Approval of categories or a saved profile does not authorize authentication or upload. A yes answer to this question explicitly proceeds to the share/upload flow below; a no answer ends the workflow.

# Explicit share/upload

Only after an explicit share/upload request, require a saved profile and generate the consent-filtered body with `openpush-scan share --print` (supply the destination app with `--app` if needed). This command is local and requires no authentication. Show the selected categories, counts, exclusions, goal, and destination as an upload preview, clearly separate from consent choices.

Preferred CLI path: run `openpush-scan login` if the user is not signed in, then `openpush-scan workspace use <name-or-id>`. Login only lists accessible workspaces and apps. Workspace selection is local context. Neither authorizes upload. Run `openpush-scan share --app <app-name-or-id>` only after the explicit share request. On first share to that app, browser consent requests an app-bound upload grant. The CLI prepares the upload, renders a formatted preview with destination, categories, counts, version diff, removals, and affected content, then **STOP**s at `Upload this reviewed manifest? [y/N]`. Confirm only after the user approves that exact preview; declining discards its single-use token and uploads nothing.

Connected-agent path: use an existing OpenPush connection, or request its connection flow now that the user has explicitly chosen to share. Call `openpush_prepare_manifest` with the applied upload body. Show its complete preview—categories, counts, diff, and affected items—and **STOP** for final upload-preview confirmation before `openpush_confirm_action`.

Automation fallback: CI may use the existing private environment credential. Never request its value or read, display, interpolate, or write it. Keep API keys out of chat, commands, files, manifests, profiles, and agent packets. If the body or destination changes, show a fresh preview and obtain confirmation again.

Packet fields for any `openpush-scanner` continuation: root, local manifest path, share profile path, goal, category choices, and exclusions. Never include credentials.
