# Golden-master plugin fixtures

Synthetic plugin trees consumed **only** by the golden-master parity harness.
They never ship: the installers read them via the default-inert
`INSTALLER_PLUGINS_SRC` override (`install.sh` / `installer.config.resolve_plugins_root`),
which the harness sets to one of these dirs.

Each fixture reuses the **`beads`** plugin identity — the one plugin name both
installers already recognize — so the comparison has a bash oracle. Real beads
content is archived out of `src/plugins/`; these fakes exist to exercise the
plugin code paths (routes, overlays, merges) without resurrecting it.

- `basic/` — formulas + scripts (route parity, G2) plus non-colliding overlay
  files (clean overlay parity).
- `collision/` — an overlay rule named `delegation.md` that collides with the
  shared rule of the same name (append-merge parity).
