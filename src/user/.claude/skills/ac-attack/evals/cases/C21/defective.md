# Release notes from change entries

## Problem

Each pull request adds one entry file to `changes/`. At release time a maintainer copies the entries into `CHANGELOG.md` by hand, and entries get lost or pasted twice.

The purpose of this change is that each release's section in `CHANGELOG.md` lists exactly the entries in `changes/` at release time, once each, and that the command never leaves `CHANGELOG.md` half-written.

## What changes

- A new command, `relnotes build`, reads the version from `VERSION` and the entry files in `changes/`, and writes a section for that version at the top of `CHANGELOG.md`.
- The command exits 0 only when it wrote the section, so the release job can stop before tagging on any other status.

## Decisions

- **D1 Entry format.** An entry file is a regular file directly in `changes/` whose name ends in `.md`. Its first line must start with `# `. The rest of that line, with surrounding whitespace, including any line ending, removed, is the entry's title, and it must not be empty. Everything else in `changes/`, including subdirectories and what they hold, is ignored.
- **D2 Version format.** `VERSION` holds exactly one line; a file with more than one is not in this form. With surrounding whitespace, including any line ending, removed, that line is the version, and it has the form `MAJOR.MINOR.PATCH`: three non-negative integers separated by dots, each written without leading zeros. Two versions are equal when their text is equal.
- **D3 Section format.** A section is the line `## <version>` followed by one line `- <title>` per entry file, in byte order of the file names. Two entries with the same title give two lines. The new `CHANGELOG.md` is the section, then one empty line, then every byte of the old `CHANGELOG.md` unchanged. A missing `CHANGELOG.md` counts as an empty one. A line of `CHANGELOG.md` is a section heading when it starts with `## `, and the first word after `## ` is that section's version, so `## 2.4.0 (2026-10-01)` is a heading for `2.4.0`.
- **D4 Whole files only.** The command replaces `CHANGELOG.md` in one atomic step, so a reader sees the old file or the new one, never part of one.
- **D5 Entries stay.** The command never modifies or deletes anything in `changes/`.
- **D6 One caller.** Only the release job runs the command, and CI runs at most one release job at a time.
- **D7 Faults.** The command checks all of its inputs before it writes anything. It prints one line to stderr for each fault it finds, writes nothing when it finds any, and then exits 2. It never prints to stdout. A criterion's stated stderr line is therefore present whatever other faults the same run finds.

## Acceptance criteria

Every criterion is checked by an automated test that builds a temporary repository holding the stated `VERSION`, `changes/` and `CHANGELOG.md`, runs `relnotes build` in it, and compares the repository's files, stderr and the exit status with the expected values, and checks that stdout is empty. A criterion passes when its test passes in CI on the pull request's head. The CI result decides, and the pull request does not merge until every criterion passes.

- **REL-A1** Given `VERSION` holding `2.4.0`, `changes/` holding `b-fix.md` titled `Fix timeout`, `a-add.md` titled `Add export`, `c-fix.md` also titled `Fix timeout`, a file `notes.txt`, and a subdirectory `old.md/` holding `d-old.md` titled `Old entry`, and a `CHANGELOG.md` holding a `## 2.3.0` section whose last line has no line ending, when `relnotes build` runs, `CHANGELOG.md` is the lines `## 2.4.0`, `- Add export`, `- Fix timeout`, `- Fix timeout` and an empty line, followed by the old file's bytes unchanged, no other file in the repository changes, and the command exits 0.

### What-if answers

**What if it fails?**

- **REL-A2** Given a run that cannot complete, because `changes` exists but is not a directory or cannot be listed, because one entry file cannot be read or breaks D1, by being empty, by a first line that does not start with `# `, or by an empty title, or because `CHANGELOG.md` cannot be read, written or created, when `relnotes build` runs, no file in the repository changes, stderr names the file at fault, and the command exits 2.
- **REL-A3** Given a run whose writing of the new `CHANGELOG.md` fails partway, which the test forces with a file-size limit smaller than the new file, the run exits with a status other than 0 and no file in the repository changes, so no temporary file is left behind.

**What if the input is empty or at a limit?**

- **REL-A4** Given a `changes/` that is missing or holds no entry file, when `relnotes build` runs, no file in the repository changes, stderr holds `no change entries`, and the command exits 2.
- **REL-A5** Given a first release, with no `CHANGELOG.md` or an empty one, `VERSION` holding `0.0.0`, the smallest version D2 admits, and `changes/` as in REL-A1, when `relnotes build` runs, `CHANGELOG.md` then holds exactly the `0.0.0` section and the empty line after it, and the command exits 0.
- The command sets no limit on the number of entries, the length of a title or the size of a version's numbers, because it handles the version and the titles only as text.

**What if something it relies on is missing?**

- **REL-A6** Given no `VERSION` file, or a `VERSION` file that cannot be read, is empty or does not hold a version in D2's form, when `relnotes build` runs, no file in the repository changes, stderr holds `no valid version in VERSION`, and the command exits 2.
- **REL-A7** Given a `VERSION` holding `next` and a `changes/` holding no entry file, when `relnotes build` runs, stderr holds both `no valid version in VERSION` and `no change entries`, no file in the repository changes, and the command exits 2.
- A missing `CHANGELOG.md` is REL-A5, and a missing `changes/` is REL-A4.

**What if it runs twice, or at the same time?** Two runs at once do not apply, because only the release job runs the command and CI runs one release job at a time (D6).

## Out of scope

- Grouping entries by kind, such as features and fixes.
- A run killed by a signal or a power loss. The release job runs the command in a fresh checkout each time, so nothing a killed run leaves behind reaches a later run.
- Adding the command to the release job and stopping the job on a failed run. The release team does that once the command exists.
- Symlinks and other special files among `VERSION`, `CHANGELOG.md` and `changes/`. The repository's pre-commit check refuses them, and the release job builds from a fresh checkout.
- Clearing `changes/` after a release. The release job does that after tagging.
- Checking that `VERSION` is newer than the versions already in `CHANGELOG.md`. The release job's version bump owns that.
- Publishing the release notes anywhere other than `CHANGELOG.md`.
