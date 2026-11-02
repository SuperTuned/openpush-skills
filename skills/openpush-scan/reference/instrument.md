# Instrument missing events

Build the `openpush-instrumenter` packet with: instrumentation suggestions including event, property keys, and per-platform snippets; the local manifest source list; platforms. Spawn it and present `PATCHES` one at a time with each proposed diff.

For each patch, wait for an explicit yes, then continue the same agent with `apply <id>`. After all approved patches, run `openpush-scan scan` again, show the event delta, and suggest another reviewed share. The instrumenter never stages or commits changes.
