# Optimize Skill

Audit and improve existing SKILL.md files via the `optimize-my-skill` skill.

> **Tip**: For *creating* new skills from scratch, prefer the `writing-skills` skill. This command is for *auditing and improving* existing skills.

## Arguments

`$ARGUMENTS` accepts one non-flag target and optional flags:

```
/optimize-my-skill [<target>] [--deep] [--max-iterations N] [--model <name>]
```

| Token | Meaning |
|-------|---------|
| `<target>` | skill name (e.g. `bugfix`), directory path (e.g. `~/.claude/skills/`), or empty (resolved via the probe below) |
| `--deep` | opt into Phase 4 (empirical description loop + output review) and Phase 5 (iterate). Absent → naked invocation = today's audit-and-apply behavior |
| `--max-iterations N` | override the description-loop iteration cap (default 5). Ignored without `--deep` |
| `--model <name>` | model id for the description-improver loop. Default `claude-haiku-4-5-20251001`. Ignored without `--deep` |

Parse by splitting `$ARGUMENTS` on whitespace and walking tokens left-to-right:

- `--deep` is a boolean flag (consumes no value).
- `--max-iterations` and `--model` are value-taking flags: the **next token**
  after the flag is its value and MUST NOT be considered as `<target>`. Treat
  `--max-iterations=N` / `--model=<name>` (equals-form) as a single token.
- The first unclaimed (non-flag, non-value) token is `<target>`. Any further
  unclaimed tokens are an error — reject with a usage message.
- Unknown `--flags` are an error — reject with a usage message.

Collect flags separately from `<target>` and pass both to the skill. Empty
`<target>` (no unclaimed token after flag/value consumption) triggers the
probe in the next section.

## Empty-argument resolution

When `$ARGUMENTS` is empty, probe in this order and pick the first that satisfies the predicate:

**Predicate**: directory exists AND contains at least one immediate (depth-1) subdirectory that contains a `SKILL.md` file (case-sensitive; regular file or symlink to regular file). An empty-but-existing `SKILL.md` satisfies the predicate (file presence, not content validity). A non-existent directory fails the predicate.

1. `~/.claude/skills/`
2. `.claude/skills/`

If both probes fail, emit exactly:

```
No skills found. Pass a path: /optimize-my-skill <path>
```

and stop.

## Invoke the skill

With the resolved target and any flags, invoke the `optimize-my-skill` skill
and pass them in its invocation context. The skill owns the full methodology
(discover, assess, propose, optionally empirical-optimize + iterate, then
confirm/apply).

Quick mode (no `--deep`) is unchanged from prior behavior. Deep mode
prompts the user for a cost confirmation before invoking model-heavy phases.

## Report

After the skill completes, surface its summary table and the list of files modified (with diffs already shown by the skill).
