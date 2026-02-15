# Install Script Design

## Goal

Create `scripts/install.sh` to copy `src/user/.claude/` contents into `~/.claude/` with intelligent sync logic.

## Approach

Bash + `jq` hybrid. Bash handles file operations, `jq` handles JSON merge.

## Components

### 1. Prerequisites
- Requires `jq` (checked upfront)
- Resolves paths relative to script location
- Color output for interactive prompts

### 2. Template Files (`*.md.template`)
- Strip `.template` suffix for target name
- Compare size + mtime if target exists
- Prompt before overwrite with diff preview

### 3. Directory Sync (agents/, skills/, commands/)
- Recursive SHA-256 hash per item (agent/skill/command)
- Hash mismatch → prompt → remove dest folder → fresh copy
- New items copied without prompt
- Extra items in dest warned but preserved

### 4. Settings JSON Merge
- Union merge: objects deep-merged, arrays unioned (no duplicates)
- Template doesn't overwrite existing user keys
- Diff preview before applying

### 5. Summary
- Report of installed/skipped/updated items
