# Review suggestions

Read [recommendation-quality.md](recommendation-quality.md) before reviewing. Include a locally supplied send-history summary in the reviewer packet when available; never upload it implicitly.

Use only a manifest the user has explicitly shared. A local scan, category selection, or saved profile is not evidence of sharing. Never route `scan` automatically into remote suggestions, upload a manifest to obtain suggestions, or request login, an API key, or an OpenPush connection from this procedure.

If no explicitly shared manifest is established, explain that remote suggestions require the user to choose `share`/upload and stop. If access would require authentication, stop and explain that limitation; do not initiate authentication. With an explicitly shared manifest and existing authenticated access, fetch `openpush_list_suggestions`. If MCP is unavailable, use `GET /v1/apps/{app}/suggestions` only through an existing client that privately consumes the user's environment. Never put API keys in chat, commands, files, manifests, profiles, or agent packets; do not read or interpolate a key to construct a request.

Build the `openpush-program-reviewer` packet with: goal; summary of the explicitly shared manifest containing counts and names (not newer unshared local findings); suggestions JSON; recommendation-quality contract; available send-history summary (mark unknown if absent); existing journey names; existing template names. Spawn the reviewer and present all five contract sections.

For each approved suggestion call `openpush_prepare_suggestion_decision`, show the returned preview, wait for confirmation, then call `openpush_confirm_action`. Route instrumentation suggestions to the instrument procedure.

Choose suggestion type from intended behavior before assessing data readiness; apply the type table in `reference/recommendation-quality.md`. A missing completion signal leaves a journey incomplete, not converted to a push.
