# @file Inclusion Marker Consistency Analysis

## Summary
This analysis inventories how instruction-file inclusion currently works across Claude Code, Codex CLI, Gemini CLI, and OpenCode in this repository. It evaluates three forward paths (status quo, full flattening, hybrid canonical startup contract), then recommends a path that maximizes deterministic behavior and reduces the testing surface across all platforms.

Recommendation: adopt **Option B (Universal Install-Time Flattening)**. This approach treats instruction files as source code and the installer as a compiler, ensuring that every agent receives a fully resolved, flat context regardless of tool-native include capabilities.

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
- This is a runtime include-style instruction pattern. It relies on the tool's runtime behavior to resolve these references.

### Gemini CLI
File: `src/user/.gemini/GEMINI.md.template`

Pattern:
- Mirrors Claude’s `@file` style:
  - `@AGENT-PERSONA.md`
  - `@USER-PERSONA.md`
  - `@INSTRUCTIONS.md`
  - `@GEMINI-EXTENSIONS.md`

Interpretation:
- Same mechanism class as Claude: runtime include directives.

### Codex CLI
File: `src/user/.codex/AGENTS.md.template`

Pattern:
- No `@file` markers.
- Explicit startup contract requiring reads from absolute `~/.codex/` paths before any action.

Interpretation:
- This is an "honor system" behavioral contract. It assumes the agent is disciplined enough to follow instructions to read other files.

### OpenCode
Files:
- `src/user/.opencode/AGENTS.md.template`
- `src/user/.opencode/README.md`
- `scripts/install.sh` (`flatten_agents_md`)

Pattern:
- Source template uses installer markers:
  - `<!-- DYNAMIC-INCLUDE: path -->`
  - `<!-- DYNAMIC-INCLUDE-RULES: rule1,... -->`
- Installer resolves these at install time to produce a single flat file.

Interpretation:
- This is deterministic install-time generation.

## Mechanism Classification (Resolved vs Assumed)

### Mechanism Types
1. Runtime include-style instruction text (`@file`)
- Present in Claude and Gemini. Relies on tool runtime.

2. Explicit startup behavioral contract
- Present in Codex. Relies on agent discipline.

3. Install-time flattening/token replacement
- Present in OpenCode. Resolved by repository code (`install.sh`).

### Resolved vs Assumed in this repo
- **Resolved**: OpenCode dynamic markers.
- **Assumed**: Claude/Gemini `@file` behavior and Codex startup contract compliance.

## Option Analysis

### Option A: Keep Status Quo
Description:
- Keep mixed approaches as-is.

Benefits:
- Zero migration cost.
- Preserves tool-specific idioms.

Risks/Tradeoffs:
- Heterogeneous semantics.
- Higher testing surface (must verify resolution vs contract compliance).

### Option B: Standardize on Install-Time Flattening for All Tools (Recommended)
Description:
- Convert Claude, Codex, and Gemini templates to use `<!-- DYNAMIC-INCLUDE -->` markers.
- Update `install.sh` to flatten `AGENTS.md` for all tools during installation.

Benefits:
- **Deterministic Context**: Agents receive fully resolved text; no "resolution" required at runtime.
- **Reduced Testing Surface**: One delivery mechanism to verify instead of four.
- **Eliminates Honor System**: Removes the risk of agents failing to follow startup read instructions.
- **Scalability**: New tools can be added by simply providing a marker-based template.

Risks/Tradeoffs:
- **Installer Complexity**: Requires moving `flatten_agents_md` from a tool-specific phase to a universal phase in `install.sh`.
- **Read-only Artifacts**: The installed `AGENTS.md` files become generated blobs, making them harder for humans to scan compared to a list of includes.

Migration impact:
- Update templates for Claude/Gemini/Codex.
- Modify `install.sh` to run flattening for all tools.

### Option C: Hybrid Canonical Startup Contract
Description:
- Standardize the *logical* contract (what to read and when) but keep tool-specific *delivery* (`@file` vs contract text).

Benefits:
- Improves consistency with minimal installer churn.

Risks/Tradeoffs:
- Technical mechanisms still differ.
- Does not address the "honor system" weakness in Codex.
- Testing permutations remain high (still 4 different ways to fail delivery).

## Recommendation
Adopt **Option B (Universal Install-Time Flattening)**.

Rationale:
- It provides the highest degree of behavioral predictability. By inlining all instructions at install time, we ensure the agent's primary context is complete and correct from the first turn.
- It simplifies the repository's long-term maintenance by unifying the delivery mechanism, treating the installer as a compiler for our agent configurations.

## Migration Plan
1. **Bead A**: Modify `scripts/install.sh` to make `flatten_agents_md` a universal installation phase rather than an OpenCode-specific one.
2. **Bead B**: Update `src/user/.claude/AGENTS.md.template`, `src/user/.gemini/GEMINI.md.template`, and `src/user/.codex/AGENTS.md.template` to use `<!-- DYNAMIC-INCLUDE -->` markers.
3. **Bead C**: Remove the explicit startup "honor system" instructions from the Codex template, as they are superseded by the flattened content.
4. **Bead D**: Update smoke tests to verify the presence of inlined content in the installed files across all tools.

## Conclusion
Universal flattening is the superior architectural choice. It moves complexity into the installer (where it can be tested once) and out of the agent's runtime (where it manifests as flaky behavior or context loss).
