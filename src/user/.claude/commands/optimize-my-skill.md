# Optimize Skill

Audit and improve existing SKILL.md files via the `optimize-my-skill` skill.

> **Tip**: For *creating* new skills from scratch, prefer `superpowers:writing-skills` if available. This command is for *auditing and improving* existing skills.

## Argument

`$ARGUMENTS` specifies the target:

- **Skill name** (e.g. `bugfix`, `writing-unit-tests`) — optimize that single skill
- **Directory path** (e.g. `~/.claude/skills/` or `.claude/skills/`) — optimize all skills in that directory
- **Empty** — resolve a default location (see below)

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

With the resolved target, invoke the `optimize-my-skill` skill and pass the target as its scope. The skill owns the full methodology (discover, assess, propose, test, confirm, apply).

## Report

After the skill completes, surface its summary table and the list of files modified (with diffs already shown by the skill).
