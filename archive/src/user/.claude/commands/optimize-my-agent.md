# Optimize Agent

Audit and improve an agent persona file via the `optimize-my-agent` skill.

## Argument

`$ARGUMENTS` is the path to an agent persona file — an `agents/*.md` with required frontmatter fields `name` and `description` (optional: `model`, `color`, `tools`).

## Scope

This command targets **agent persona files only**. It is not for:

- `AGENTS.md` configuration files (use `/refresh-agents-md`)
- `SKILL.md` files (use `/optimize-my-skill`)

If `$ARGUMENTS` is empty or does not point to a file with at least `name` and `description` frontmatter fields, stop and ask the user for a valid path.

## Invoke the skill

Pass `$ARGUMENTS` to the `optimize-my-agent` skill. The skill owns the full methodology (read, assess, identify problems, propose improvements, collaborative refinement, apply).

## Report

After the skill completes, surface its assessment, the approved changes, and the diff against the original file.
