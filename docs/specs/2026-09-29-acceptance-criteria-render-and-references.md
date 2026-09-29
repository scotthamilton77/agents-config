# Acceptance-criteria rendering and references

**Date:** 2026-09-29
**Status:** Draft child spec. Not yet attacked.
**Work item:** `agents-config-9k9.405.4.1`, the design child of `agents-config-9k9.405.4`
(AC lifecycle rendering and references).
**Parent:** `docs/specs/2026-09-18-acceptance-criteria-lifecycle.md`, slice S1. Its decisions
LIFE-D1 to LIFE-D8 and its criteria stand as settled.
**Quality contract:** `docs/specs/2026-09-18-acceptance-criteria-quality.md`, ACQ-D2 and ACQ-D5.
**Repositories:** workcli, which is the `work` facade's source, and agents-config.

## Problem statement

Parent slice S1 owns LIFE-A1 to LIFE-A5, LIFE-A23, LIFE-A27, LIFE-A28, LIFE-A39, LIFE-A42
and LIFE-A45. The parent fixes their observable constraints. It leaves the mechanisms to this
spec: how an item names its spec, the rendering's exact bytes, the generated-ID spelling, the
refusal payloads, the shared grammar's home, and whether a symlink can lead a spec path out
of the repository.

Today `work acceptance` offers only `set` and `history`. No item records the spec its
criteria cite. `work deliver --spec` copies each manifest bullet's AC text onto the item it
mints, and records the spec path only on the placeholder as a `[work] spec:` note. Spec-lint's
entry grammar is private to its lint, and it does not recognise an entry holding no text. The
verdict poster's criteria reader in prgroom takes bullets from the whole file and ignores
fenced blocks.

## Decisions

### ACR-D1: An item names its spec through a facade marker

The tracker has no field for a named spec, and the parent rules out adding one. The named
spec is therefore a note marker, `[work] acceptance spec: <path>`. The payload of the item's
last such marker is its named spec. An item without one names no spec. The last marker wins
because notes are append-only, and a rename under LIFE-D3 must be able to move the reference.

Two verbs write the marker. `work acceptance set ID TEXT --spec PATH` records or changes it.
`work deliver --spec` writes it under ACR-D8. A change to the named spec is an amendment. It
passes the started-work gate that a text change passes, needs `--why` when that gate does, and
appends the same trail marker first. A set that changes neither the text nor the named spec
writes nothing. Both verbs read PATH relative to the working directory, as a shell user
expects, and record it relative to the repository root. A path outside the root is recorded in
its root-relative form, which begins with `..`, so every rendering refuses it under ACR-D2.

This marker is the "named spec" input that LIFE-D1 lists. No other note affects a rendering.
Three alternatives were rejected. A spec line inside the acceptance field is not a citation,
so LIFE-D2 would make every citing item tracker-born. A pointer inside the description would
let a description edit change a spec-born item's attacked document, which LIFE-D4 says a
description edit never does. Reusing `[work] spec:` would give one marker two readers with
opposite rules, since deliver's drift guard reads its first occurrence and a rename needs the
last. Items created before the renderer ships carry no marker. One call of
`work acceptance set --spec` names their spec without changing their text. No slice rewrites
existing items.

### ACR-D2: Spec paths resolve inside the repository root, symlinks included

The repository root is the nearest ancestor of the resolved working directory holding a
`.git` entry. `work` already uses this bound to find its config. In a linked worktree it is
that worktree's root. A rendering refuses its named spec when any of these holds:

- the recorded path is absolute;
- the recorded path, normalized lexically, begins with `..`;
- the path, resolved with every symlink followed, lies outside the resolved root.

The lexical rule refuses a path that climbs out and re-enters through the checkout
directory's name, because that name differs between checkouts. A symlink whose target stays
inside the root is followed. A symlink whose target lies outside is refused. The parent
refuses outside paths because another checkout cannot reproduce those bytes, and a symlink to
outside has the same flaw. This settles the open question in the note on
`agents-config-9k9.405.4.1`. A spec-naming item rendered outside any git repository is
refused. An item naming no spec renders without a root.

### ACR-D3: The rendering's exact form

`work acceptance render ID` answers in the facade's JSON envelope, whose `data` is
`{"id": ID, "markdown": M}`. The rendering is the UTF-8 encoding of M, and a consumer writes
those bytes verbatim. M joins these lines with LF and ends with one LF:

1. `## Description`.
2. When the description has lines: a blank line, then each description line prefixed with
   `> `, or `>` alone for an empty line. Lines split as Python's `str.splitlines` splits them.
3. A blank line, then `## Acceptance criteria`.
4. When there is a criterion: a blank line, then one `- **ID** TEXT` line per criterion, in
   field order.

M holds nothing else: no title, item ID line, spec path or time. Every description line
starts with `>`, so neither consumer's line grammar can read one as a heading, a fence marker
or a list item. A fenced description was rejected. The verdict poster's reader ignores fences,
and a description line of backticks can close a fence early. Leaving out the spec path keeps a
rename from changing a tracker-born item's rendering, as LIFE-D3 and LIFE-D4 need.

### ACR-D4: The acceptance field's line grammar

Each nonblank line of the field is one unit. A line holding only whitespace is blank. On an
item naming a spec, a citation line matches `^\s*ID(\s*,\s*ID)*\s*$`, where ID is spec-lint's
criterion-ID pattern `[A-Z0-9]+-[A-Z]\d+|AC\d+`. It cites its IDs in order. Every other
nonblank line is a text line. On an item naming no spec, every line is a text line. Cited text
is never read again as citations.

A text line matching spec-lint's entry form `- **ID** text` states its ID explicitly, and it
renders with that ID and text. Any other text line renders as `- **P-Tn** ` followed by the
line with surrounding whitespace removed. P is the item ID's ASCII letters and digits,
uppercased, with every other character dropped; an item ID holding neither gives `ITEM`. The
letter T marks text. The number n is the line's 1-based position among the field's nonblank
lines. Item `agents-config-9k9.405.4`'s third nonblank line therefore gets
`AGENTSCONFIG9K94054-T3`. A criterion wrapped over two field lines renders as two criteria.
That follows LIFE-D1's line rule, and `work acceptance set` is the remedy.

### ACR-D5: One entry grammar, in two marked copies

The grammar is spec-lint's existing one, widened once. Its scope is every heading whose text
contains "acceptance criteria", case-insensitively, up to the next heading at the same or a
shallower level. Fenced lines are inert. A line `- **ID** text` opens an entry. The widening
lets a line `- **ID**` with nothing after the ID open one too. Each following line joins the
entry, stripped and space-separated, until a blank line, a bullet, a heading or a fence line.
An entry whose text is still empty is an empty entry.

Spec-lint exposes `parse_criteria_entries(text)`, which returns every entry in document order
as an ID and text pair, empty and repeated entries included. Spec-lint's own checks keep
counting only entries with text, so no lint result changes. Workcli carries a counterpart
module. Each copy's source names the other's path.

A citation resolves to the one entry defining its ID. An ID that no entry defines is
unresolved, and one that two entries define is ambiguous. An empty entry contributes no
criterion. A spec whose bytes are not valid UTF-8 is unparseable.

### ACR-D6: Refusals

A refused rendering returns error code `E_RENDER`. Its `detail.cause` comes from a closed
vocabulary. Its `detail.id` and `detail.path` carry the offending ID and the recorded spec
path where the cause has them. An unknown item keeps the existing `E_NOT_FOUND`. Rendering
never writes, whether it succeeds or is refused.

| Cause | Condition |
| --- | --- |
| `notes-unreadable` | The backend cannot answer the item's notes |
| `no-repository-root` | A spec is named and no root exists |
| `spec-path-absolute` | ACR-D2's absolute rule |
| `spec-path-escapes` | ACR-D2's lexical or symlink rule |
| `spec-missing`, `spec-unreadable`, `spec-not-utf8` | The file is absent, unreadable, or not UTF-8 |
| `unresolved-id`, `ambiguous-id` | ACR-D5's resolution |
| `duplicate-id` | Two units yield one ID, whether or not the cited entry is empty |

Checks run in the table's order, and units are checked in field order. The first failure is
the one reported, so equal input always gets the same refusal.

### ACR-D7: Existing consumers keep their parsers

Only spec-lint's grammar changes. The verdict poster is unchanged, because ACR-D3 already
keeps description lines out of its bullet grammar. A change to prgroom's source obligates a
release and a human reinstall, and a rendering needs neither. The poster's section scoping in
LIFE-D6 lands with S6, which changes the poster anyway. The review-panel and ac-attack emitters
parse no entries.

### ACR-D8: Delivery names the spec it expands

When `work deliver --spec PATH` reconciles a placeholder, it writes the ACR-D1 marker for PATH
on the reconciled placeholder. On an expanding placeholder it writes the marker on every
manifest child, whether this run minted the child or an interrupted run did. It skips an item
whose last marker already names that path. Each item keeps its manifest AC text, so a manifest
AC that is an ID list becomes citations. A completed reconciliation short-circuits as it does
today, so earlier trees gain no marker. A manifest AC with trailing punctuation or prose stays
text, as LIFE-D1 requires.

### ACR-D9: The shared round-trip fixture

The fixture lives in agents-config at `packages/installer/tests/fixtures/acceptance-render/`.
Workcli vendors a byte-identical copy at `tests/fixtures/acceptance-render/`. The fixture holds
a `repo/` directory that each harness materializes as a repository root, and an `outside/`
directory beside it holding a readable spec. `cases.json` lists each case: item ID,
description, acceptance field, recorded spec path or none, working directory, symlinks to
create, the rules exercised, and either a golden rendering under `expected/` or a refusal with
its cause and ID or path. `entries.json` lists the entries expected from each spec and each
golden rendering. The rules are:

- F1: blank field lines are ignored.
- F2: comma-separated and one-per-line citations are equal, whitespace around IDs ignored.
- F3: other lines are text, and an item naming no spec has only text lines.
- F4: entries keep their continuation, criterion-shaped lines open entries, fences are inert.
- F5: citations resolve once, in field order.
- F6: explicit IDs survive, and generated IDs follow ACR-D4.
- F7: unresolved, ambiguous and duplicate IDs are refused, and the first failure wins.
- F8: a missing, unreadable or non-UTF-8 spec is refused.
- F9: an empty cited entry contributes nothing.
- F10: relative paths resolve from the root, whatever the working directory.
- F11: absolute and lexically escaping paths are refused, readable or not.
- F12: an escaping symlink is refused, and an internal one is followed.
- F13: the description is quoted whole, criterion-shaped text included.

## Testing decisions

Workcli tests drive `main()` with the fake backend and an injected working directory, over
the fixture materialized in a temporary directory with real symlinks and file modes.
Agents-config tests call spec-lint's parser and prgroom's `load_criteria` on fixture files. No
test runs the tracker's own CLI or writes the user's tracker. Existing spec-lint and prgroom
tests pass unchanged. Every check below is mechanical, its acceptance authority is the named
suite's pass or fail, and the delivery of the slice owning the criterion waits on it.

## Acceptance criteria

- **ACR-A1** After `work acceptance set ID TEXT --spec PATH`, run from any directory of the
  checkout, rendering resolves the item's citations against the file PATH names from there. A
  later set naming another path moves resolution to that file, even when TEXT is unchanged.
- **ACR-A2** The trail records exactly the real changes to an item's named spec. A set that
  changes only the named spec appends one trail marker, and is refused without `--why` once
  work has started. A set repeating both text and path writes nothing.
- **ACR-A3** For each citation of a nonempty entry, in field order, a rendering holds one
  bullet whose text is that entry's full text, continuation lines joined by single spaces. A
  cited entry whose own text is an ID list appears verbatim.
- **ACR-A4** Items whose fields differ only in writing the same citations comma-separated, one
  per line, or with extra whitespace around IDs render byte-identical output. This includes an
  item whose field was stored before its spec was named.
- **ACR-A5** An item rendered from the repository root and from a subdirectory of the same
  checkout yields byte-identical output.
- **ACR-A6** A text line without an explicit ID renders as `- **P-Tn** ` and the stripped
  line, with P and n as ACR-D4 defines them, and every such ID matches spec-lint's
  criterion-ID pattern.
- **ACR-A7** A text line in the form `- **ID** text`, where ID matches spec-lint's pattern,
  renders with that ID and that text unchanged.
- **ACR-A8** Only a whole citation line on an item naming a spec resolves. An ID-only line on
  an item naming no spec, and a line holding an ID among other words on any item, render as
  text criteria.
- **ACR-A9** A citation of an ID that the named spec defines in no entry, or in two, is
  refused with `E_RENDER`, the ID, the spec path, and cause `unresolved-id` or `ambiguous-id`.
- **ACR-A10** Two units yielding one ID are refused with `E_RENDER`, that ID, and cause
  `duplicate-id`, for every pairing of citation, explicit ID and generated ID, and for one ID
  cited twice.
- **ACR-A11** A named spec that is missing, unreadable, or not valid UTF-8 is refused with
  `E_RENDER`, its path, and the matching `spec-` cause, and is never rendered as a spec without
  criteria.
- **ACR-A12** A rendering whose named spec cannot be established is refused with `E_RENDER`:
  cause `notes-unreadable` when the backend cannot answer the item's notes, and
  `no-repository-root` when a spec-naming item is rendered outside any git repository.
- **ACR-A13** Every rendering matches ACR-D3's layout byte for byte, including an item with an
  empty description and an empty field.
- **ACR-A14** Removing the quote prefix from each line of a rendering's description section
  yields the item's description lines in order, when the description holds criterion-shaped
  bullets, an acceptance-criteria heading, a fence opener, blank lines and CRLF breaks.
- **ACR-A15** Two renders of an item are byte-identical when its title, labels, priority and
  status change between them and a note other than a named-spec marker is appended.
- **ACR-A16** A rendering, successful or refused, makes no mutating backend call and writes no
  file.
- **ACR-A17** Repointing an item to a byte-identical copy of its spec at another path leaves
  its rendering byte-identical.
- **ACR-A18** After `work deliver --spec PATH` expands a manifest, every item it reconciled or
  minted keeps its manifest AC text and names the spec by its root-relative path, also when
  deliver ran from a subdirectory. An item whose manifest AC is an ID list renders the cited
  entries.
- **ACR-A19** Across replays, delivery writes each manifest item's named-spec marker exactly
  once. A replay after an interruption between minting a child and marking it adds the missing
  marker. A replay of a completed reconciliation, including one completed before this change,
  adds none.
- **ACR-A20** After a cited entry's text changes in the spec file, with no tracker write, every
  item citing it renders the new text.
- **ACR-A21** Spec-lint's `parse_criteria_entries`, applied to each fixture spec and each
  golden rendering, returns the entries `entries.json` lists for that file.
- **ACR-A22** Workcli's counterpart grammar, applied to each fixture spec, returns the entries
  `entries.json` lists for that file.
- **ACR-A23** For every fixture case, `work acceptance render` returns the golden rendering
  byte for byte, or the listed refusal with its cause and its ID or path.
- **ACR-A24** The fixture lists rules F1 to F13 with at least one case for each, and the
  agents-config harness fails when a listed rule has no case.
- **ACR-A25** At the commits delivering Slices A to C, the fixture files are byte-identical
  across the two repositories, and both repositories' suites pass over them.
- **ACR-A26** The installed `work` renders a tracker item that cites this spec, and spec-lint's
  parser recovers from that output exactly the cited nonempty entries, in field order.
- **ACR-A27** Spec-lint's parser and prgroom's `load_criteria`, applied to each golden
  rendering, recover exactly its acceptance-criteria entries, including renderings whose
  description holds criterion-shaped bullets, an acceptance-criteria heading or a fence opener.
- **ACR-A28** Spec-lint's parser returns an entry with empty text for a `- **ID**` line that no
  continuation text follows.
- **ACR-A29** Spec-lint's checks treat an empty entry as defining nothing. A spec whose
  criteria sections hold only empty entries is still reported as defining none, a slice citing
  only an empty entry is still reported, and an empty entry needs no evidence row.
- **ACR-A30** A rendering citing an empty entry emits no bullet for it, emits its other
  criteria in field order, and is not refused.
- **ACR-A31** A recorded spec path that is absolute, or whose lexical normalization begins with
  `..`, is refused with `E_RENDER`, the path, and cause `spec-path-absolute` or
  `spec-path-escapes`, even when a readable spec exists there. A relative path whose
  normalization stays inside the root renders.
- **ACR-A32** A spec path reached through a symlink resolving outside the resolved root is
  refused with the path and cause `spec-path-escapes`. One resolving inside the root renders
  from its target's bytes.

### Checks

| Criteria | Setup | Observation and pass rule |
| --- | --- | --- |
| ACR-A1, ACR-A2 | Fake backend and fixture root; open and in-progress items; sets run from the root and a subdirectory | Render resolves against the named file; notes and the write log show one trail marker per change, a refusal without `--why` once started, and no write on a repeat |
| ACR-A3 to ACR-A12, ACR-A30 to ACR-A32 | Fixture cases tagged with the rule each criterion names | Output equals the golden bytes, or the envelope equals the listed refusal |
| ACR-A13, ACR-A14 | Golden layout cases; description round-trips over the listed shapes | Byte equality; unquoted lines equal the input's `splitlines` |
| ACR-A15 to ACR-A17, ACR-A20 | One item rendered, the named change applied, rendered again | Byte equality or the new text; the fake backend log and a snapshot of the root and home directories show no write |
| ACR-A18, ACR-A19 | Single-unit and multi-unit deliveries on the fake backend, with a fault injected after a child mint | One marker per item; renders show the cited entries; completed trees gain nothing |
| ACR-A21, ACR-A24, ACR-A27 to ACR-A29 | Agents-config suites over the fixture and the spec-lint corpus | Parsed entries equal `entries.json`; lint results over the corpus and `docs/specs/` are unchanged |
| ACR-A22, ACR-A23 | Workcli suite over its vendored copy | Parsed entries and renderings equal the fixture's expectations |
| ACR-A25, ACR-A26 | The delivered commits; the installed `work` once the human installs it | Fixture digests match and both suites pass; the live rendering parses to the cited entries. Evidence is the transcript on the verification item |

### What-if questions

| Criteria | Fails, empty or at a limit | Dependency missing | Twice, or nothing changed |
| --- | --- | --- | --- |
| ACR-A1, ACR-A2 | An empty PATH records the root directory, refused as `spec-unreadable` by ACR-A11 | Unreadable notes: ACR-A12 | A repeated set writes nothing: ACR-A2 |
| ACR-A3 to ACR-A8, ACR-A30 | A null field renders an empty section: ACR-A13; an empty entry: ACR-A30 | Spec absent: ACR-A11 | Repeat renders are equal: ACR-A15 |
| ACR-A9 to ACR-A12, ACR-A31, ACR-A32 | Several failures report the first: ACR-D6, fixture rule F7 | No root: ACR-A12 | Refusals write nothing: ACR-A16 |
| ACR-A13 to ACR-A17, ACR-A20 | Empty description: ACR-A13 | Not applicable: the rendering is a function of its inputs | Equal input gives equal bytes: ACR-A15 |
| ACR-A18, ACR-A19 | An out-of-root `--spec` is recorded, then refused at render by ACR-A31 | Interrupted mint: ACR-A19 | Replays converge: ACR-A19 |
| ACR-A21 to ACR-A29 | A rule without a case fails: ACR-A24 | An uninstalled `work` leaves ACR-A26 pending | Suites over fixed files are repeatable |

### Traceability

| Parent criterion | Child criteria |
| --- | --- |
| LIFE-A1 | ACR-A1, ACR-A3, ACR-A4, ACR-A5, ACR-A8 |
| LIFE-A2 | ACR-A6, ACR-A7, ACR-A8 |
| LIFE-A3 | ACR-A9, ACR-A10, ACR-A11, ACR-A12 |
| LIFE-A4 | ACR-A13, ACR-A14 |
| LIFE-A5 | ACR-A15, ACR-A16 |
| LIFE-A23 | ACR-A18, ACR-A19 |
| LIFE-A27 | ACR-A20, ACR-A16 |
| LIFE-A28 | ACR-A21, ACR-A22, ACR-A23, ACR-A24; verified by ACR-A25, ACR-A26 |
| LIFE-A39 | ACR-A27, ACR-A23; verified by ACR-A25, ACR-A26 |
| LIFE-A42 | ACR-A28, ACR-A29, ACR-A30; verified by ACR-A25 |
| LIFE-A45 | ACR-A31, ACR-A32 |

ACR-A2 rests on LIFE-D4's amendment trail. ACR-A17 rests on LIFE-D3 and LIFE-D4, and S2's
LIFE-A10 and LIFE-A46 depend on it. LIFE-A28, LIFE-A39 and LIFE-A42 span Slices A to C, so
their parent evidence stays open until the verification item closes on ACR-A25 and ACR-A26.

## Ordered slice list

- **Slice A: shared entry grammar and fixture** (ACR-A21, ACR-A24, ACR-A27, ACR-A28,
  ACR-A29). Agents-config. Expose and widen spec-lint's grammar, and author the fixture with
  its golden renderings. It depends on nothing.
- **Slice B: render verb and named spec** (ACR-A1 to ACR-A8, ACR-A13 to ACR-A17, ACR-A20,
  ACR-A22, ACR-A30). Workcli. Vendor the fixture, and add the marker, `acceptance set --spec`,
  the counterpart grammar and the verb. It depends on Slice A.
- **Slice C: render refusals and path rules** (ACR-A9 to ACR-A12, ACR-A23, ACR-A31, ACR-A32).
  Workcli. It depends on Slice B. The release that later consumers name under LIFE-D8 is the
  first one holding Slices B and C.
- **Slice D: delivery citations** (ACR-A18, ACR-A19). Workcli. It depends on Slice B.
- **Slice E: cross-repository verification** (ACR-A25, ACR-A26). Both repositories, with no
  new code. It depends on Slices A to C and on the human installing that release.

## Continuations

Deliver `agents-config-9k9.405.4.1` with `--spec` naming this file, and the placeholder
expands into the leaves below. Delivery mints no dependency edges, so record the slice list's
dependencies with `work dep add`. These leaves are minted before the renderer ships. Once
Slice B is installed, name this spec on each with `work acceptance set --spec` before its
first claim. Delivering this design does not discharge the parent criteria.

- feat: AC render shared entry grammar and fixture — AC: ACR-A21, ACR-A24, ACR-A27, ACR-A28,
  ACR-A29
- feat: AC render verb and named spec — AC: ACR-A1, ACR-A2, ACR-A3, ACR-A4, ACR-A5, ACR-A6,
  ACR-A7, ACR-A8, ACR-A13, ACR-A14, ACR-A15, ACR-A16, ACR-A17, ACR-A20, ACR-A22, ACR-A30
- feat: AC render refusals and path rules — AC: ACR-A9, ACR-A10, ACR-A11, ACR-A12, ACR-A23,
  ACR-A31, ACR-A32
- feat: AC render citations from spec delivery — AC: ACR-A18, ACR-A19
- chore: AC render cross-repository verification — AC: ACR-A25, ACR-A26

## Out of scope

Attestation, spec-born classification, the attack workflow, the claim and delivery gates, and
review emission and posting belong to parent slices S2 to S6. Removing a named spec, naming one
at `work create`, and rewriting existing items are outside this spec.

## Evidence

- ACR-A1 | open
- ACR-A2 | open
- ACR-A3 | open
- ACR-A4 | open
- ACR-A5 | open
- ACR-A6 | open
- ACR-A7 | open
- ACR-A8 | open
- ACR-A9 | open
- ACR-A10 | open
- ACR-A11 | open
- ACR-A12 | open
- ACR-A13 | open
- ACR-A14 | open
- ACR-A15 | open
- ACR-A16 | open
- ACR-A17 | open
- ACR-A18 | open
- ACR-A19 | open
- ACR-A20 | open
- ACR-A21 | open
- ACR-A22 | open
- ACR-A23 | open
- ACR-A24 | open
- ACR-A25 | open
- ACR-A26 | open
- ACR-A27 | open
- ACR-A28 | open
- ACR-A29 | open
- ACR-A30 | open
- ACR-A31 | open
- ACR-A32 | open
