# Design: Fix DYNAMIC-INCLUDE-RULES — Decouple Rule List from Rule File Set

**Bead:** agents-config-abn9.16  
**Date:** 2026-05-15

---

## Summary

Replace the hardcoded `DYNAMIC-INCLUDE-RULES` marker (comma-separated list) with a directory convention and a new `DYNAMIC-INCLUDE-ALL-RULES` marker (no args, auto-globs). General rules move to `src/user/.agents/rules/`; Claude-specific rules stay in `src/user/.claude/rules/` with unambiguous `claude-*` names. New files in either folder are picked up on the next install without touching any template.

---

## Background

The current mechanism has five compounding problems:

1. **Stale list** — `completion-gate.md` and `codex-routing.md` exist in `src/user/.claude/rules/` but are absent from the hardcoded list; they silently never reach non-Claude tools.
2. **Plugin rules never reach non-Claude tools** — the beads plugin adds `beads.md`, `beads-labels.md`, and `delivery.md` to `staging/<tool>/rules/` via Phase 6, but the hardcoded list never includes them. *Note: this bead enables the MECHANISM for future agnostic plugin rules via `src/plugins/<name>/.agents/rules/`; it does NOT migrate existing beads plugin rules from `.claude/rules/` — those remain Claude-only until explicitly relocated.*
3. **Codex and Gemini receive zero rules** — their templates have no `DYNAMIC-INCLUDE-RULES` marker at all.
4. **Claude double-loads rules** — Claude's template inlines rules via `DYNAMIC-INCLUDE-RULES`, then native `rules/` directory loading loads the same files again at session start. Fix: remove the marker from Claude's template entirely.
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

*Note: `delegation.md`, `delivery.md`, and `completion-gate.md` reference `superpowers:` skill names — a Claude plugin namespace. This bleed is accepted per the requirement that rule content is semantically unchanged. Future tightening is out of scope for this bead.*

*Note: `delegation.md:11` contains a cross-reference to `codex-routing.md`. This filename is being renamed; the citation must be updated to `claude-to-codex-routing.md` as part of this bead. This is a mechanical citation update required by the rename, not a semantic content change — the Out-of-Scope clause below covers semantic changes only.*

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
| `src/user/.opencode/AGENTS.md.template` | Replace `DYNAMIC-INCLUDE-RULES: delegation,delivery,...` with `<!-- DYNAMIC-INCLUDE-ALL-RULES -->` |
| `src/user/.codex/AGENTS.md.template` | Add `<!-- DYNAMIC-INCLUDE-ALL-RULES -->` marker (currently no rules marker) |
| `src/user/.gemini/GEMINI.md.template` | Add `<!-- DYNAMIC-INCLUDE-ALL-RULES -->` marker (currently no rules marker) |

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

There is a single call site at Phase 6.5 (inside `stage_and_install_tool`); all tools pass the 4th arg uniformly after the migration. No partial-arg invocations exist.

**New marker handler (add after the existing `DYNAMIC-INCLUDE-RULES` block):**
```bash
# Handle <!-- DYNAMIC-INCLUDE-ALL-RULES -->
if [[ "$line" == "<!-- DYNAMIC-INCLUDE-ALL-RULES -->" ]]; then
    # NOTE: reuses existing `first_rule` local declared at the top of the function.
    # Do NOT re-declare with `local` here — that would shadow the outer declaration
    # in bash and silently break the sentinel.
    first_rule=true
    while IFS= read -r rule_file; do
        [[ -f "$rule_file" ]] || continue
        if [[ "$first_rule" == true ]]; then
            first_rule=false
        else
            printf '\n---\n' >> "$output"
        fi
        cat "$rule_file" >> "$output"
    done < <(find "$staging_tool_dir/rules" -maxdepth 1 -type f -name '*.md' -print 2>/dev/null | LC_ALL=C sort)
    if [[ "$first_rule" == true ]]; then
        warn "DYNAMIC-INCLUDE-ALL-RULES: no rules found in $staging_tool_dir/rules/"
    fi
    continue
fi
```

Note: `find` is used rather than `ls *.md` glob because `install.sh` sets `shopt -s nullglob` (line 28), which causes an empty glob to expand to nothing and `ls` would then list the CWD — a silent correctness bug. `find` with `2>/dev/null` handles missing directories cleanly.

**Call site update** (in `stage_and_install_tool`, Phase 6.5):
```bash
flatten_agents_md "$template" "$flattened" "$PROJECT_ROOT" "$staging"
```

### Resolution order at flatten time

`DYNAMIC-INCLUDE-ALL-RULES` resolves at Phase 6.5 — after Phase 6 plugin overlay. At that point `staging/<tool>/rules/` contains:
1. General rules (Phase 2, from `.agents/rules/`)
2. Tool-specific rules (Phase 3/4, from `.<tool>/rules/`; append-merged on same-name collision)
3. Plugin rules (Phase 6, from `plugins/<name>/.<tool>/rules/` and `plugins/<name>/.agents/rules/`)

Alphabetical ordering is deterministic and sufficient — rules are mutually independent.

### Claude Phase 1–7 trace (confirming no orphans from the 5 moved files)

The 5 general rules moving from `src/user/.claude/rules/` to `src/user/.agents/rules/` do **not** need prune-list entries because they still deploy to `~/.claude/rules/` via a different source path:

| Phase | Action |
|-------|--------|
| Phase 2 | `stage_content_from_dir "$SRC_SHARED" "$staging" "rules"` stages `delegation.md`, `delivery.md`, `completion-gate.md`, `subagents.md`, `worktrees.md` from `.agents/rules/` → `staging/claude/rules/` |
| Phase 3 | `stage_content_from_dir "$src_tool" "$staging" "rules"` stages `claude-sandbox.md`, `claude-to-codex-routing.md` from `.claude/rules/` → `staging/claude/rules/` |
| Phase 6 | Beads plugin's `src/plugins/beads/.claude/rules/delivery.md` append-merges into `staging/claude/rules/delivery.md` (general delivery.md + plugin beads-aware addendum = correct intended output) |
| Phase 7 | `sync_directory "rules"` syncs `staging/claude/rules/` → `~/.claude/rules/` |

Result: `~/.claude/rules/` contains all 7 rules (5 general + 2 Claude-specific) plus plugin append-merges. No files are lost; no prune-list entries needed for the moved files.

---

## Migration Notes

- The renamed files (`git-commits.md` → `claude-sandbox.md`, `codex-routing.md` → `claude-to-codex-routing.md`) must be added to `scripts/prune-list` so that `install.sh --prune` removes the old-name files from `~/.claude/rules/`:
  ```
  # Retired in <commit>: abn9.16 — renamed to claude-sandbox.md (content is Claude Code sandbox constraints)
  claude/rules/git-commits.md
  # Retired in <commit>: abn9.16 — renamed to claude-to-codex-routing.md
  claude/rules/codex-routing.md
  ```
  Without the prune-list entries, old-name files persist as orphans in `~/.claude/rules/` and Claude double-loads both the old and new name.
- Codex and Gemini users will receive rule content for the first time after this install. No behavioral regression expected — they were previously operating without rules context.

---

## Additional Required Changes

Several files outside the main install.sh / templates scope contain filename references that become stale after the rename. These are in scope for this bead:

| File | Change |
|------|--------|
| `src/user/.claude/rules/delegation.md:11` | `codex-routing.md` → `claude-to-codex-routing.md` |
| `src/user/.agents/skills/wait-for-pr-comments/SKILL.md:657` | `git-commits.md` → `claude-sandbox.md` |
| `src/user/.claude/README.md:16-18` | Update filenames in the rules/ inventory comment |
| `AGENTS.md:64` | Remove 5 general rule names from `.claude/rules/` bullet (they move to `.agents/rules/`); update `git-commits` → `claude-sandbox` and `codex-routing` → `claude-to-codex-routing`; add a new `src/user/.agents/rules/` row listing the 5 general files |
| `src/user/.opencode/OPENCODE-EXTENSIONS.md.template:32-34` | Update stale prose: `codex-routing.md` → `claude-to-codex-routing.md`; note that `completion-gate.md` is now general (included, not omitted) |
| `scripts/smoke/verify-artifacts.sh:123` | Extend ERE regex to also catch the new no-colon marker. Current: `grep -qE '<!-- DYNAMIC-INCLUDE(-RULES)?:'`. Updated: `grep -qE '<!-- DYNAMIC-INCLUDE((-RULES)?:|-ALL-RULES)'`. Note: `DYNAMIC-INCLUDE-ALL-RULES` has no trailing colon (the old markers embed their payload after `:`; the new marker has no payload). ERE alternation uses unescaped `\|` — `\|` in ERE is not alternation. |

---

## Out of Scope

- **Semantic** changes to rule file content (mechanical citation updates required by renaming are in scope — see "Additional Required Changes")
- Abstracting Claude-named skill references in general rules
- Adding new rules or changing rule semantics
- Changes to `INSTRUCTIONS.md.template` or the non-rules `DYNAMIC-INCLUDE` mechanism
- Migrating existing beads plugin rules (under `src/plugins/beads/.claude/rules/`) to `.agents/rules/` — those remain Claude-only until a future bead explicitly relocates them
