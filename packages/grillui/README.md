# grillui

The backend behind a grilling session's user interface: it serves the UI,
folds the session's decision log into the images the UI and the agents read,
and drives the grilling tiers.

**Under construction.** Only the packaging skeleton exists — the console
script resolves, `grillui --help` and `grillui --version` answer, and nothing
else is built yet. The design it is being built to is
`docs/specs/2026-08-18-grilling-ui-v1.md`.

## Development

```bash
make ci-grillui     # the full gate: lint, format, types, coverage, audit, entry
make test-grillui   # faster inner loop
```
