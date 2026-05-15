# Design: Fix DYNAMIC-INCLUDE-RULES — Decouple Rule List from Rule File Set

**Bead:** agents-config-abn9.16  
**Date:** 2026-05-15

---

## Summary

Replace the hardcoded `DYNAMIC-INCLUDE-RULES` marker (comma-separated list) with a directory convention and a new `DYNAMIC-INCLUDE-ALL-RULES` marker (no args, auto-globs). General rules move to `src/user/.agents/rules/`; Claude-specific rules stay in `src/user/.claude/rules/` with unambiguous `claude-*` names. New files in either folder are picked up on the next install without touching any template.

---

## Background

The current mechanism has four compounding problems:

1. **Stale list** — `completion-gate.md` and `codex-routing.md` exist in `src/user/.claude/rules/` but are absent from the hardcoded list; they silently never reach non-Claude tools.
2. **Plugin rules never reach non-Claude tools** — the beads plugin adds `beads.md`, `beads-labels.md`, and `delivery.md` to `staging/<tool>/rules/` via Phase 6, but the hardcoded list never includes them.
3. **Codex and Gemini receive zero rules** — their templates have no `DYNAMIC-INCLUDE-RULES` marker at all.
4. **Claude double-loads rules** — Claude's template inlines rules via `DYNAMIC-INCLUDE-RULES`, then native `rules/` directory loading loads the same files again at session start.
5. **Misleading filenames** — `git-commits.md` (content: Claude sandbox constraints) and `codex-routing.md` (content: Claude→Codex plugin delegation) have names that imply general applicability.

---

## Directory Convention

| Directory | Contents |
|-----------|----------|
| `src/user/.agents/rules/` | Tool-agnostic rules — apply to all tools |
| `src/user/.claude/rules/` | Claude-specific rules only — `claude-*` prefix naming convention |
| `src/user/.codex/rules/` | Codex-specific rules (future; not created by this bead) |
| `src/plugins/<name>/.agents/rules/` | Plugin-contributed agnostic rules |
| `src/plugins/<name>/.<tool>/rules/` | Plugin-contributed tool-specific rules (existing) |

---

## Rule Classification

### General → `src/user/.agents/rules/`

| File | Why general |
|------|-------------|
| `delegation.md` | Mandatory delegation principles apply to any tool with subagent/skill support |
| `delivery.md` | PR action-category framework and `gh` CLI workflow are tool-agnostic |
| `completion-gate.md` | Review→simplify→verify is a universal quality gate |
| `subagents.md` | Dispatch hygiene applies wherever subagents exist |
| `worktrees.md` | Worktree location convention; `.claude/worktrees/` path pools all tools into one location (intentional) |

*Note: `delegation.md`, `delivery.md`, and `completion-gate.md` reference `superpowers:` skill names — a Claude plugin namespace. This bleed is accepted per the requirement that rule content is unchanged. Future tightening is out of scope for this bead.*

### Claude-specific → `src/user/.claude/rules/` (renamed)

| Old name | New name | Why Claude-specific |
|----------|----------|---------------------|
| `git-commits.md` | `claude-sandbox.md` | Content is about Claude Code's Bash tool sandbox constraints (heredoc failure, `dangerouslyDisableSandbox`), not git broadly |
| `codex-routing.md` | `claude-to-codex-routing.md` | Delegates from Claude to Codex via the Claude Code Codex plugin; irrelevant outside Claude |

---

## Template Changes

| Template | Change |
|----------|--------|
| `src/user/.claude/AGENTS.md.template` | Remove `DYNAMIC-INCLUDE-RULES` marker entirely — native `rules/` loading already provides all rules to Claude |
| `src/user/.opencode/AGENTS.md.template` | Replace `DYNAMIC-INCLUDE-RULES: delegation,delivery,...` with `DYNAMIC-INCLUDE-ALL-RULES` |
| `src/user/.codex/AGENTS.md.template` | Add `DYNAMIC-INCLUDE-ALL-RULES` marker (currently no rules marker) |
| `src/user/.gemini/GEMINI.md.template` | Add `DYNAMIC-INCLUDE-ALL-RULES` marker (currently no rules marker) |

---

## install.sh Changes

### Phase 2 — Stage shared rules for all tools
```bash
stage_content_from_dir "$SRC_SHARED" "$staging" "rules"   # ADD THIS LINE
```
Currently Phase 2 only stages `skills` and `agents` from `.agents/`. Rules must also be staged.

### Phase 6 — Plugin `.agents/rules/` support
Extend the `plugin_agents_dir` loop from `for subdir in skills agents` to `for subdir in rules skills agents`. This enables `src/plugins/<name>/.agents/rules/` for tool-agnostic plugin rules (one-line diff; zero current consumers in the beads plugin, but symmetric with existing `.agents/skills` and `.agents/agents`).

### `flatten_agents_md` — Add 4th arg and new marker handler

**Signature change:**
```bash
flatten_agents_md() {
    local template="$1"
    local output="$2"
    local project_root="$3"
    local staging_tool_dir="$4"   # ADD: path to staging/<tool>/
    ...
}
```

**New marker handler (after existing DYNAMIC-INCLUDE-RULES block):**
```bash
# Handle <!-- DYNAMIC-INCLUDE-ALL-RULES -->
if [[ "$line" == "<!-- DYNAMIC-INCLUDE-ALL-RULES -->" ]]; then
    first_rule=true
    # Glob staging/<tool>/rules/*.md sorted alphabetically (LC_COLLATE=C for determinism)
    while IFS= read -r rule_file; do
        [[ -f "$rule_file" ]] || continue
        if [[ "$first_rule" == true ]]; then
            first_rule=false
        else
            printf '\n---\n' >> "$output"
        fi
        cat "$rule_file" >> "$output"
    done < <(LC_COLLATE=C ls "$staging_tool_dir/rules/"*.md 2>/dev/null | sort)
    continue
fi
```

**Call site update** (in `stage_and_install_tool`, Phase 6.5):
```bash
flatten_agents_md "$template" "$flattened" "$PROJECT_ROOT" "$staging"
```

### Resolution order at flatten time

`DYNAMIC-INCLUDE-ALL-RULES` resolves at Phase 6.5 — after Phase 6 plugin overlay. At that point `staging/<tool>/rules/` contains:
1. General rules (Phase 2, from `.agents/rules/`)
2. Tool-specific rules (Phase 3/4, from `.<tool>/rules/`; append-merged on collision)
3. Plugin rules (Phase 6, from `plugins/<name>/.<tool>/rules/` and `plugins/<name>/.agents/rules/`)

Alphabetical ordering is deterministic and sufficient — rules are mutually independent.

---

## Migration Notes

- Running `install.sh --prune` after this change will remove the old-name files (`git-commits.md`, `codex-routing.md`) from `~/.claude/rules/`. Without `--prune`, they persist as orphans but do no harm (Claude loads all `*.md` files in `rules/`).
- Codex and Gemini users will receive rule content for the first time after this install. No behavioral regression expected — they were previously operating without rules context.

---

## Out of Scope

- Changing rule file content (renames only for the two Claude-specific files)
- Abstracting Claude-named skill references in general rules
- Adding new rules or changing rule semantics
- Changes to `INSTRUCTIONS.md.template` or the non-rules `DYNAMIC-INCLUDE` mechanism
