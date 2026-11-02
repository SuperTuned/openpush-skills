# Inline scanner fallback

Run the scanner locally. Before summarizing events, inspect app-owned analytics entry points, forwarding wrappers, and manager/transport gates. The effective event set is the intersection of real call-site usage and the active gates on the transport it reaches: ignore declarations without calls and commented-out, disabled, denied, or unreachable entries. Apply a transport allowlist only to that transport; preserve direct OpenPush calls and independent providers.

The deterministic scanner handles common literal gates. If repository semantics change the effective set, edit only the `events` array in `openpush-manifest.local.json`, preserve its local source evidence and every other field, and run `openpush-scan validate --manifest openpush-manifest.local.json`. Never invent or remove an event without local call-site and routing evidence. Report each applied gate and its included/excluded counts. Leave unresolved dynamic or remote-configured gates unchanged and report the uncertainty. Never edit source, configuration, or profile files and never upload.

Then inspect source locations named by the reconciled manifest, summarize platforms and named signals, list dynamic call sites, and propose only closed-enum category or lifecycle inferences.

Return `## PLATFORMS`, `## SIGNALS`, `## UNREADABLE`, `## INFERENCES`, and `## WARNINGS` in that order.

End `## WARNINGS` with the exact line: `ROUTER HANDOFF: scan complete; continue immediately with the local review playbook.` The scan result is an intermediate handoff, never the end of the user's scan workflow.

For local-notification wrappers, follow the immediate app-owned callers and
referenced localization keys to identify existing reminder purposes. Summarize
coverage in WARNINGS so suggestions do not duplicate existing lives, daily-reward, store or
streak reminders. Keep this context local unless explicitly approved for sharing.

⚠️ DEGRADED: single-context (no sub-agent tool exposed)
