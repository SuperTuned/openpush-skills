# CI setup

Run `openpush-scan ci --print-workflow` and show the complete workflow before writing it to `.github/workflows/openpush-scan.yml`. Explain that pull requests only compare with a read-only key, while the main-branch job uses `share --ci --on-version-change` and therefore needs a full-scope key. Wait for approval before writing.
