# Internal package registry: names, publishing and installs

## Problem

Teams share internal command-line tools by copying binaries between machines. Nobody can tell which version a colleague runs, and two teams have shipped different tools under the same name.

## What changes

- A team claims a package name with `pkg claim <name>`. A claimed name belongs to that team, and only that team can publish under it.
- The owning team publishes a version with `pkg publish <name> <version> <archive>`. The registry then serves that version.
- Anyone installs a package with `pkg install <name>`, which puts its tool on their PATH.

## Decisions

- **D1 Names.** A name belongs to the first team to claim it. Claiming a name another team holds exits 4, prints `name taken: <name> (owner <team>)` to stderr and changes nothing.
- **D2 Publishing.** Only the owning team may publish under a name. A publish by any other team exits 3 and publishes nothing.
- **D3 Immutable versions.** A published version never changes. Publishing a name and version that already exist exits 5 and leaves the served archive and its recorded checksum as they were.
- **D4 Install.** `pkg install <name>` downloads the highest published version, verifies its SHA-256 against the registry's recorded checksum, and links its binary into `~/.pkg/bin`. A checksum mismatch exits 6 and installs nothing.
- **D5 Info.** `pkg info <name>` prints the owning team and every published version.

## Acceptance criteria

Every criterion is checked by an automated test in the registry's end-to-end suite. The suite starts a fresh registry and two client containers: `author`, signed in as team `infra`, and `user`, signed in as team `web`, with `~/.pkg/bin` on its PATH. A criterion passes when its test passes in CI on the pull request's head. The CI result decides, and the pull request does not merge until every criterion passes.

- **REG-A1** Given the name `acme-lint` claimed by `infra`, when `user` runs `pkg claim acme-lint`, the command exits 4, prints `name taken: acme-lint (owner infra)` to stderr, and `pkg info acme-lint` still shows owner `infra`.
- **REG-A2** Given `acme-lint` claimed by `infra`, when `user` runs `pkg publish acme-lint 1.0.0` with an archive, the command exits 3 and `pkg info acme-lint` lists no version.
- **REG-A3** Given `acme-lint` 1.0.0 published by `infra`, when `author` publishes 1.0.0 again with a different archive, the command exits 5, `pkg info acme-lint` lists 1.0.0 exactly once, the registry serves the original archive byte for byte, and the recorded checksum for 1.0.0 is unchanged.
- **REG-A4** Given `acme-lint` 1.0.0 published and its archive in the registry's storage then overwritten with other bytes, when `user` runs `pkg install acme-lint`, the command exits 6 and `~/.pkg/bin/acme-lint` does not exist.
- **REG-A5** Given a fresh registry, when `author` runs `pkg claim acme-lint`, the command exits 0 and `pkg info acme-lint` shows owner `infra` and no versions.
- **REG-A6** Given `acme-lint` claimed by `infra`, when `author` publishes `acme-lint` 1.0.0 and then 1.2.0, each publish exits 0, `pkg info acme-lint` lists versions 1.0.0 and 1.2.0, and downloading each version from the registry returns the archive published for it, byte for byte.
- **REG-A7** Given `acme-lint` 1.0.0 and 1.2.0 published, when `user` runs `pkg install acme-lint`, the command exits 0 and `acme-lint --version` on `user` prints `1.2.0`.

## Out of scope

- Uninstalling a package, and installing a version other than the highest.
- Transferring a name between teams.
- Mirroring the registry outside the company network.
