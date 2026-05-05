# @file Inclusion Marker Consistency Analysis

## Summary
This analysis inventories how instruction-file inclusion currently works across Claude Code, Codex CLI, Gemini CLI, and OpenCode in this repository. It evaluates three forward paths (status quo, full flattening, hybrid canonical startup contract), then recommends a path that improves consistency without introducing unnecessary installer complexity or runtime ambiguity.

Recommendation: adopt a hybrid canonical startup contract as the cross-tool standard, keep OpenCode flattening where required, and avoid broad conversion to install-time flattening for all tools.

## Scope and Method
Source of truth is the repository templates and installer behavior:
- `src/user/.claude/AGENTS.md.template`
- `src/user/.codex/AGENTS.md.template`
- `src/user/.gemini/GEMINI.md.template`
- `src/user/.opencode/AGENTS.md.template`
- `src/user/.opencode/OPENCODE-EXTENSIONS.md.template`
- `src/user/.opencode/README.md`
- `scripts/install.sh` (flattening implementation)

No assumptions are made about undocumented tool internals beyond what is represented in these files.

## Current-State Inventory

### Claude Code
File: `src/user/.claude/AGENTS.md.template`

Pattern:
- Uses direct `@file` references:
  - `@AGENT-PERSONA.md`
  - `@USER-PERSONA.md`
  - `@INSTRUCTIONS.md`
  - `@CLAUDE-EXTENSIONS.md`

Interpretation:
- This is a runtime include-style instruction pattern. Whether resolution is tool-native vs prompt-level behavior is external to this repo; in-repo it is authored as a declarative include instruction.

### Gemini CLI
File: `src/user/.gemini/GEMINI.md.template`

Pattern:
- Mirrors Claude’s `@file` style:
  - `@AGENT-PERSONA.md`
  - `@USER-PERSONA.md`
  - `@INSTRUCTIONS.md`
  - `@GEMINI-EXTENSIONS.md`

Interpretation:
- Same mechanism class as Claude template authoring: include-style instruction text at runtime.

### Codex CLI
File: `src/user/.codex/AGENTS.md.template`

Pattern:
- No `@file` markers.
- Explicit startup contract requiring reads from absolute `~/.codex/` paths before any action:
  - `~/.codex/AGENT-PERSONA.md`
  - `~/.codex/USER-PERSONA.md`
  - `~/.codex/INSTRUCTIONS.md`
  - `~/.codex/CODEX-EXTENSIONS.md`

Interpretation:
- This is explicit behavioral contract text (honor-system instruction), not token include syntax.

### OpenCode
Files:
- `src/user/.opencode/AGENTS.md.template`
- `src/user/.opencode/README.md`
- `scripts/install.sh` (`flatten_agents_md`)

Pattern:
- Source template uses installer markers, not runtime includes:
  - `<!-- DYNAMIC-INCLUDE: path -->`
  - `<!-- DYNAMIC-INCLUDE-RULES: rule1,... -->`
- Installer resolves these markers at install time in `flatten_agents_md` and writes a single flat AGENTS file.
- OpenCode extension notes explicitly state OpenCode reads raw text and does not follow `@` includes.

Interpretation:
- This is deterministic install-time generation (token replacement/flattening), not runtime include resolution.

## Mechanism Classification (Resolved vs Assumed)

### Mechanism Types
1. Runtime include-style instruction text (`@file`)
- Present in Claude and Gemini templates.
- Authored as include directives but relies on tool runtime behavior.

2. Explicit startup behavioral contract
- Present in Codex template.
- No include token semantics; explicit required read order and paths.

3. Install-time flattening/token replacement
- Present in OpenCode template + installer.
- Fully resolved before runtime; produces static file content.

### Resolved vs Assumed in this repo
- Resolved by repository code:
  - OpenCode dynamic markers are resolved by installer (`scripts/install.sh`).
- Assumed/instructional at runtime:
  - Claude/Gemini `@file` behavior (as authored in templates).
  - Codex startup read contract compliance.

## Option Analysis

### Option A: Keep Status Quo
Description:
- Keep mixed approaches as-is: `@file` for Claude/Gemini, explicit startup contract for Codex, flattening for OpenCode.

Benefits:
- Zero migration cost.
- Preserves existing per-tool idioms.
- Avoids touching installer logic beyond OpenCode path.

Risks/Tradeoffs:
- Cross-tool semantics remain heterogeneous.
- Documentation burden stays high (contributors must remember mechanism differences).
- Harder to reason about behavior equivalence across tools.

Migration impact:
- None.

Compatibility risk:
- None immediate.

Rollback posture:
- Not applicable (no change).

### Option B: Standardize on Install-Time Flattening for All Tools
Description:
- Move Claude, Codex, and Gemini templates toward token markers and generate fully flattened runtime files for all tools via installer.

Benefits:
- Deterministic installed instruction files.
- Single mechanism class for content composition.
- Reduces ambiguity between runtime include and behavioral contracts.

Risks/Tradeoffs:
- Higher installer complexity and maintenance burden.
- Loses readability of human-authored top-level templates (more marker-driven wiring).
- Potential friction with tool ecosystems that already support preferred native patterns.
- Broader migration blast radius and higher regressions risk.

Migration impact:
- Update template format conventions for Claude/Gemini/Codex.
- Expand `install.sh` flatten logic beyond OpenCode path.
- Update docs and contributor guidance.

Compatibility risk:
- Medium. Requires validating generated outputs across all tool installs.

Rollback posture:
- Revert installer/template changes; restore prior templates. Straightforward but broad.

### Option C: Hybrid Canonical Startup Contract (Recommended)
Description:
- Standardize the logical startup contract across tools (same required artifacts, same sequencing intent), but keep tool-appropriate delivery:
  - OpenCode keeps install-time flattening (required by platform behavior).
  - Codex keeps explicit startup contract style.
  - Claude/Gemini retain `@file` authoring but align wording and referenced artifact set to the same canonical contract.

Benefits:
- Improves behavioral consistency without forcing one technical mechanism everywhere.
- Minimizes installer churn and migration risk.
- Preserves each tool’s practical authoring model.

Risks/Tradeoffs:
- Mechanisms still differ technically.
- Requires discipline to keep contract text aligned across templates.

Migration impact:
- Moderate template edits; minimal installer changes.
- Add a small contract checklist in docs to prevent drift.

Compatibility risk:
- Low-to-medium; mostly textual/template alignment.

Rollback posture:
- Easy rollback by reverting template wording-only changes.

## Recommendation
Adopt Option C (Hybrid Canonical Startup Contract).

Rationale:
- It raises consistency where it matters (behavioral contract) while respecting unavoidable platform differences.
- It avoids unnecessary expansion of installer flattening into tools that do not require it.
- It keeps OpenCode’s deterministic flattening where technically required.

## Proposed Canonical Contract Elements
Use the same conceptual startup requirements across all top-level instruction templates:
- Required artifacts to load:
  - agent persona
  - user persona
  - shared instructions
  - tool-specific extensions
- Mandatory timing: before responding/acting.
- Explicit blocker behavior when required artifacts are missing.

Delivery per tool can remain tool-specific (`@file`, explicit absolute paths, or install-time flattening).

## Migration Plan
1. Define canonical startup contract language in one shared reference doc.
2. Align these templates to that contract:
- `src/user/.claude/AGENTS.md.template`
- `src/user/.gemini/GEMINI.md.template`
- `src/user/.codex/AGENTS.md.template`
3. Keep OpenCode flattening model unchanged; only align semantics in source markers/content where needed:
- `src/user/.opencode/AGENTS.md.template`
- `src/user/.opencode/OPENCODE-EXTENSIONS.md.template`
4. Add a lightweight verification check in installer smoke scripts to detect startup-contract drift.

## Breaking Changes and Compatibility
Expected breaking change level: low.
- No required change to OpenCode flattening mechanism.
- No required cross-tool tokenization migration.
- Primary change is textual/contract alignment in templates.

Potential compatibility concern:
- If contract wording becomes more strict for a specific tool, behavior can shift in edge cases; validate with smoke checks after install.

## Rollback Posture
Rollback is low risk:
- Revert template edits in one commit.
- Re-run installer to restore prior generated outputs.
- No data migration or schema transitions involved.

## Follow-on Beads
If recommendation is adopted:
- Bead A: Canonical startup-contract wording and template alignment pass.
- Bead B: Smoke-check enhancement to detect startup-contract drift across tool templates.
- Bead C: Optional doc pass describing mechanism classes (runtime include, explicit contract, install-time flattening).

If recommendation is rejected:
- Close this bead as no-op with documented rationale and no further implementation beads.

## Conclusion
Token replacement/flattening is the correct mechanism for OpenCode, but it is not automatically the best universal mechanism for every tool in this repo. Standardizing the startup contract semantics while preserving tool-appropriate implementation yields the best consistency-to-risk ratio.
