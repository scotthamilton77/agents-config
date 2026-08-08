# CONTEXT — domain glossary

> This file defines what the words mean. It does not define how the machinery
> works. An entry states a term's meaning and points at whatever owns its
> mechanics; the moment an entry starts enumerating fields, thresholds or
> steps, it has taken on a maintenance obligation it will not honour, and the
> pointer should carry that instead.
>
> Terms used consistently everywhere still belong here — an agent is told to
> use this glossary's terminology, so it has to be able to look a word up.
> What does not belong here is a second copy of a contract that lives in code.

## Acceptance criterion

A statement of observable behaviour that is false today and true when the work
is done, phrased so a reader can convert it directly into a failing test. A
spec's set of them is its contract: they are what review judges against, and
they are what lets a review round terminate rather than generating findings
indefinitely.

Criteria carry short IDs so that slices and tests can cite them. The ID format
and the per-slice citation requirement are mechanically enforced.

Contract: `packages/installer/src/installer/core/spec_lint.py`, run as
`make spec-lint` over `docs/specs/`.

## Admission record

The front-matter block that earns a rule, skill, command or agent its place in
the deployed surface. It states what the artifact is worth, what it costs, and
what observation would justify removing it. Worth is stated either as the
failure the artifact prevents or as the capability it provides, never both —
forcing an assistive artifact into failure language produces a fiction rather
than a justification.

An artifact whose record is absent or incomplete is dropped at deploy time
wherever it sits, and the drop is reported rather than silent. Records are
repo-side bookkeeping and are stripped from the deployed bytes.

Contract: `packages/installer/src/installer/core/admission.py`.

## Gate

A mechanical check that decides whether work may proceed, with no judgement in
the loop. A gate's verdict is its exit status, which is why a gate must be run
standalone and read directly — piping one into another command replaces its
verdict with the other command's.

`make ci` is the whole-repo gate. Individual packages and content surfaces have
their own; membership changes, so the `Makefile` is the only reliable statement
of what currently runs.

Contract: the `ci` target in `Makefile`.

## Grooming

The triage ceremony that reviews the tracker backlog and confirms what is ready
to be worked. It is mechanical where it can be: a nag fires on elapsed time
since the last completed pass, and the lint and trigger reports it consumes are
generated rather than judged.

Documents written before 2026-08 call this **Backlog Grooming**, to distinguish
it from a second, Idea-scoped ceremony that no longer exists. The qualifier is
now redundant but harmless, and the persisted state field still carries it.

Contract: `packages/workcli/src/workcli/verbs/groom.py`; thresholds in
`project-config.toml` under `[operating-model]`.

## Milestone

The largest container in the tracker: a body of work with a charter document
behind it and children that are the live statement of progress. A milestone
tracks no progress itself — its charter states decisions and acceptance
criteria, and the children say where things stand.

Work items are expected to have a milestone ancestor; `work lint` reports non-milestone orphans unless they carry the `lint-exempt:no-milestone` label.

## Park

The state of a work item whose pull request will not merge, recorded with a
typed reason rather than a free-text note, so that a later reader can tell
whether a person or the machine is the one holding it up.

Parking is a disengagement, not a retry: the machine takes no further action on
a parked item of its own accord, and there is no automatic expiry. Moving an
item out of a park is a human verb.

The reason vocabulary is closed, and it is split along two axes — whether the
cause was a failure or a scheduling choice, and whether a machine or a person
must act.

Contract: `PARK_REASONS` in `packages/grind/src/grind/model.py`.

## Scaffold

**Designed, not built.** The intended replacement for the prose plan: a
frontier model materialises a slice's acceptance criteria in the repository as
compilable stubs and failing tests, plus a short dispatch brief. The executing
agent's job is then to make those tests pass without changing the contract.

Nothing implements this today. The word also appears in
`packages/prgroom/` in its ordinary sense of a code skeleton, which is
unrelated.

Design: `docs/specs/2026-07-21-harness-rework-way-forward.md`.

## Slice

The smallest change that flips a defined set of acceptance criteria from red to
green and is separately mergeable. A slice carries its own criteria and cites
them; it is the unit that gets dispatched, reviewed and merged.

Decomposing a spec into an ordered slice list is the spec author's deliverable,
not a later step — a spec is not ready until it is sliced.

## Spec

A dated design document under `docs/specs/`, describing a change's full intent
and carrying its acceptance criteria and slice list.

A spec is a point-in-time proposal, not a progress report. One describing
behaviour nobody has implemented yet is the normal case, not a defect. Where
a spec and the code disagree about what exists, the code wins; where they
disagree about what was decided, the spec does.

## Track

A partition of the tracker that says which subsystem a work item belongs to.
Every item must carry one — an item whose track cannot be derived is refused at
creation rather than accepted untracked.

Track names are declared in configuration, and that declaration is
authoritative: a name that no longer corresponds to anything real is a defect
in the configuration, not a licence to invent a new one.

Contract: `[tracks]` in `project-config.toml`, read by
`packages/workcli/src/workcli/verbs/tracks.py`.

## Verdict artifact

The machine-readable result of one review round, keyed to the git head commit
it reviewed. It records what was looked at, through which lenses, and what
remains outstanding — so a later reader can tell whether a verdict is stale, or
whether a lens was silently skipped.

A finding is either **mechanical**, which blocks and must carry evidence, or
**advisory**, which never blocks and routes to the backlog. There is no third
class.

Contract: `src/user/.agents/skills/review-verdict/` — the skill and its JSON
schema are authoritative for fields, validation and lens rules.

## Work item

The unit the tracker holds: one piece of intent with an identifier, a parent, a
track and a status. Work items are addressed through the `work` facade, never
through the storage backend directly — the facade is what keeps the backend
replaceable, so reaching past it is a defect even when it works.

Where the facade cannot express an operation, the gap is recorded against the
milestone rather than worked around silently.

Contract: `packages/workcli/`.

## Worktree branch

The isolated checkout a change is implemented on. Work is never committed to
the default branch.

A worktree is its own tree with its own root, which matters more than it
sounds: build and gate commands resolve paths relative to where they are
invoked, so a gate run from the main checkout while a branch is checked out
elsewhere reports on code that was never changed.

---

## Retired vocabulary

These terms appear in documents dated before 2026-08 and in the archived
history. They describe machinery that has been removed from this repository.
They are listed so that an older document still resolves — not to reinstate
them, and not as a description of anything current.

- **Objective**, **Candidate UoW**, **Agent-Worthy**, **Agent-Ready**,
  **Design Workspace** — lifecycle stages of the PDLC Orchestrator, a state
  machine that was never completed. Its milestone closed as superseded.
- **Idea**, **Capture**, **Shaped Idea**, **Bucket**, **Holding Place**
  (working name *Icebox*), **Epitaph** — the pre-specification pipeline, a peer
  subsystem to the Orchestrator rather than a stage inside it. Its package was
  retired alongside the Orchestrator's.
- **The CA-8 split** — the rule that Idea and Objective were distinct
  primitives, and that Bucket was a property of the former only. Retired with
  both primitives. Where a document cites it to justify keeping bucket labels
  off work items, that exclusion still holds; `deferred` status remains the
  parking mechanism it names.
- **Grooming** in its Idea-scoped sense, with its **Last-Groomed Timestamp**
  (`last_groomed`) and **Grooming Nag** — the ceremony that triaged Ideas into
  Buckets, and the elapsed-time prompt that surfaced it. The tracker ceremony
  defined above kept the shape and carries its own timestamp and its own nag;
  documents that distinguish the two are guarding against a collision that can
  no longer happen.
- **Green Gate**, **Red Gate**, **Sizing Gate**, **Test-Author Agent**,
  **Implementer Agent**, **3-Strike Circuit Breaker** — the execution pipeline
  and its separation-of-authorities discipline. Never built.
- **Autopsy**, **RCA Agent**, **Autopsy Resolution Routes** — the failure
  diagnosis state that a third strike routed to. Never built.
- **Atomic AT**, **Child-Level AT**, **Container-Level AT**, **Scaffold AT**,
  **Cleanup AT**, **Container Closure** — the acceptance-test vocabulary that
  preceded *acceptance criterion*. Do not use it: spec lint requires an
  **Acceptance criteria** section with structured, ID-bearing entries, so using
  this vocabulary *instead of that structure* will fail `make spec-lint`.
- **Proposed Rule** — a third review finding class. The verdict schema accepts
  two; see *Verdict artifact*.
- **Decomposition**, **Decomposition Architect**, **Decomposition Plan**,
  **Assembly Graph** — the container-slicing design. Superseded by *slice*.
- **Dreaming Process** — a speculative background capability. Never designed
  beyond the name.
