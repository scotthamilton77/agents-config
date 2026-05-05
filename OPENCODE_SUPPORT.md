# OpenCode Configuration Reference

> Researched from source: `opencode` v-current (`packages/opencode/src/`).
> Last updated: 2026-05-05.

---

## File System Layout

OpenCode follows the [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/latest/).

| Purpose | Path |
|---------|------|
| **Config** (shareable, version-controllable) | `~/.config/opencode/` |
| **State** (runtime preferences, theme, model) | `~/.local/state/opencode/` |
| **Data** (session transcripts, plans, logs) | `~/.local/share/opencode/` |
| **Cache** (binaries, downloads) | `~/.cache/opencode/` |

Override config directory: `OPENCODE_CONFIG_DIR=<path>`

---

## Configuration Files

### Global Config

OpenCode reads **all three** and deep-merges them (last wins):

```
~/.config/opencode/config.json      ← legacy (auto-migrated)
~/.config/opencode/opencode.json
~/.config/opencode/opencode.jsonc   ← preferred (supports comments)
```

Add `"$schema": "https://opencode.ai/config.json"` for IDE validation (added automatically on first write).

### Project Config

Placed in `.opencode/` at the project root (or any ancestor directory):

```
.opencode/opencode.json
.opencode/opencode.jsonc
```

Project config is **merged on top of** global config.

### TUI-specific Config

Theme and appearance settings that differ from the main config:

```
~/.config/opencode/tui.json
~/.config/opencode/tui.jsonc
.opencode/tui.json              ← project-level TUI overrides
```

> **Note**: `theme`, `keybinds`, and `tui` keys in `opencode.json` are deprecated — put them in `tui.json` instead.

---

## Runtime State Files

These are written by opencode at runtime — do not edit manually.

| File | Contains |
|------|----------|
| `~/.local/state/opencode/kv.json` | Active theme, theme mode, theme mode lock |
| `~/.local/state/opencode/model.json` | Recent models, favorites, variant selections |

### What's in `kv.json`

```json
{
  "theme": "catppuccin-mocha",
  "theme_mode": "dark",
  "theme_mode_lock": false
}
```

### What's in `model.json`

```json
{
  "recent": [
    { "providerID": "anthropic", "modelID": "claude-sonnet-4-5" }
  ],
  "favorite": [],
  "variant": {}
}
```

The **active model** is `recent[0]` — no separate "current model" key.

---

## Session Storage

```
~/.local/share/opencode/opencode.db          ← primary (SQLite via Drizzle)
~/.local/share/opencode/storage/session/     ← legacy JSON (being migrated away)
~/.local/share/opencode/plans/               ← plan files (global)
.opencode/plans/                             ← plan files (project, if in worktree)
~/.local/share/opencode/log/                 ← log files
```

---

## Instruction / Prompt Files

OpenCode injects these as system context. Priority order (first match wins):

### Global instructions (pick ONE):

1. `~/.config/opencode/AGENTS.md` — checked first
2. `~/.claude/CLAUDE.md` — fallback if #1 doesn't exist

> **Critical**: This is a **fallback chain**, not a merge. If `~/.config/opencode/AGENTS.md`
> exists, `~/.claude/CLAUDE.md` is **never read**.

### Project-level instructions (pick ONE, walk up from cwd):

Search order: `AGENTS.md` → `CLAUDE.md` → `CONTEXT.md` (deprecated)

The first file found walking up to the worktree root wins. Files from every
ancestor directory are **not** stacked — only the closest match is used.

### Additional instructions via config:

```jsonc
{
  "instructions": [
    "~/path/to/extra-instructions.md",    // absolute with ~/
    "./relative/to/project.md",           // relative to project
    "https://example.com/instructions.md" // remote URL
  ]
}
```

### @ references are NOT followed

OpenCode reads instruction files as raw text. `@AGENTS.md`-style references
(as used by Claude Code) are passed through as literal text — referenced files
are **not** loaded. If your `CLAUDE.md` uses `@` includes, create a flat
`~/.config/opencode/AGENTS.md` with the expanded content instead.

---

## Skills

OpenCode scans for `SKILL.md` files (using frontmatter + markdown body).

### Scan locations (in order):

1. **Global** `~/.claude/skills/**/SKILL.md` — Claude Code skill compat
2. **Global** `~/.agents/skills/**/SKILL.md` — agents-style skills
3. **Project** `.claude/skills/**/SKILL.md` — walks up from cwd to worktree
4. **Project** `.agents/skills/**/SKILL.md` — walks up from cwd to worktree
5. **Config dirs** — `skill/**/SKILL.md` and `skills/**/SKILL.md`
6. **Explicit paths** via `skills.paths` in config
7. **Remote URLs** via `skills.urls` in config

```jsonc
// ~/.config/opencode/opencode.jsonc
{
  "skills": {
    "paths": ["~/my-custom-skills/"],
    "urls": ["https://example.com/.well-known/skills/"]
  }
}
```

Disable all external skills: `OPENCODE_DISABLE_EXTERNAL_SKILLS=1`
Disable Claude Code skill scanning only: `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1`

### SKILL.md format (same as Claude Code):

```markdown
---
name: my-skill-name
description: What this skill does
---

Skill content here...
```

---

## Agents

Custom agents are defined as markdown files with YAML frontmatter.

### Scan locations:

```
~/.config/opencode/agents/**/*.md
~/.config/opencode/agent/**/*.md
.opencode/agents/**/*.md
.opencode/agent/**/*.md
```

### Agent file format:

```markdown
---
name: my-agent
description: When to use this agent
model: anthropic/claude-sonnet-4-5
temperature: 0.7
mode: subagent   # subagent | primary | all
hidden: false
color: "#FF5733"
steps: 50
permission:
  bash: ask
  edit: allow
---

Agent system prompt goes here...
```

### Built-in agents:

- `plan` — planning agent (primary)
- `build` — implementation agent (primary, default)
- `general` — general-purpose subagent
- `explore` — exploration/search subagent
- `title` — session title generation
- `summary` — session summarization
- `compaction` — context compaction

### Per-agent config in opencode.json:

```jsonc
{
  "agent": {
    "build": {
      "model": "anthropic/claude-opus-4-7",
      "steps": 100,
      "permission": {
        "bash": "ask",
        "edit": "allow"
      }
    },
    "my-custom-agent": {
      "model": "openai/gpt-4o",
      "mode": "subagent",
      "prompt": "You are a specialist in..."
    }
  },
  "default_agent": "build"
}
```

---

## Commands (Slash Commands)

Custom slash commands (analogous to Claude Code `/commands`).

### Scan locations:

```
~/.config/opencode/commands/**/*.md
~/.config/opencode/command/**/*.md
.opencode/commands/**/*.md
.opencode/command/**/*.md
```

### Command file format:

```markdown
---
description: What this command does
agent: build          # optional: which agent runs it
model: anthropic/...  # optional: model override
subtask: false        # optional: run as subtask
---

Command template content. Can reference {env:MY_VAR} and {file:./path.md}.
```

> **Unlike Claude Code**, opencode commands are invoked inline in the chat, not
> as slash-prefixed menu items. They're submitted as message templates.

---

## MCP Servers

```jsonc
{
  "mcp": {
    "my-local-server": {
      "type": "local",
      "command": ["node", "/path/to/server.js"],
      "environment": {
        "API_KEY": "{env:MY_API_KEY}"
      },
      "enabled": true,
      "timeout": 10000
    },
    "my-remote-server": {
      "type": "remote",
      "url": "https://mcp.example.com/sse",
      "headers": {
        "Authorization": "Bearer {env:TOKEN}"
      },
      "oauth": {
        "clientId": "...",
        "scope": "read write"
      },
      "enabled": true
    },
    "disabled-server": {
      "enabled": false
    }
  }
}
```

---

## Permissions

```jsonc
{
  "permission": {
    "bash": "ask",          // ask | allow | deny
    "read": "allow",
    "edit": "ask",
    "glob": "allow",
    "grep": "allow",
    "list": "allow",
    "task": "ask",
    "webfetch": "ask",
    "websearch": "ask",
    "external_directory": "deny",
    "skill": "allow",
    "doom_loop": "deny"
  }
}
```

Shorthand (applies to all targets of that tool):
```jsonc
{ "permission": "ask" }   // ask for everything
```

Per-target within a permission:
```jsonc
{
  "permission": {
    "bash": {
      "*": "ask",
      "git status": "allow"
    }
  }
}
```

---

## Model Configuration

```jsonc
{
  "model": "anthropic/claude-sonnet-4-5",
  "small_model": "anthropic/claude-haiku-4-5-20251001",
  "disabled_providers": ["openai"],
  "enabled_providers": ["anthropic", "openai"]  // if set, ONLY these are active
}
```

### Custom provider / model overrides:

```jsonc
{
  "provider": {
    "my-openai-compat": {
      "name": "My LLM",
      "models": {
        "my-model": {
          "name": "My Model",
          "context": 128000
        }
      }
    }
  }
}
```

---

## Variable Substitution in Config

OpenCode supports two substitution forms in config values:

```
{env:VAR_NAME}       → replaced with $VAR_NAME at load time
{file:./path.md}     → replaced with file contents at load time
```

Example:
```jsonc
{
  "instructions": ["{file:~/my-shared-instructions.md}"]
}
```

---

## Tool Output Limits

```jsonc
{
  "tool_output": {
    "max_lines": 2000,    // default: 2000
    "max_bytes": 51200    // default: 51200 (50KB)
  }
}
```

---

## Compaction

```jsonc
{
  "compaction": {
    "auto": true,                    // default: true
    "prune": true,                   // default: true
    "tail_turns": 2,                 // recent turns to keep verbatim
    "preserve_recent_tokens": 8000,  // max tokens from recent turns
    "reserved": 4000                 // token buffer to avoid overflow
  }
}
```

---

## Experimental Options

```jsonc
{
  "experimental": {
    "batch_tool": false,            // enable batch tool
    "openTelemetry": false,         // enable OTel spans for AI SDK
    "primary_tools": [],            // tools restricted to primary agents only
    "continue_loop_on_deny": false, // continue agent loop when tool denied
    "mcp_timeout": 5000,           // global MCP timeout in ms
    "disable_paste_summary": false
  }
}
```

---

## Misc Config Options

```jsonc
{
  "shell": "/bin/zsh",            // shell for bash tool and terminal
  "logLevel": "INFO",             // DEBUG | INFO | WARN | ERROR
  "snapshot": true,               // enable file snapshot/undo tracking
  "autoupdate": "notify",         // true | false | "notify"
  "share": "manual",              // manual | auto | disabled
  "username": "Scott",            // display name in conversations
  "watcher": {
    "ignore": ["*.log", "dist/"]
  },
  "enterprise": {
    "url": "https://api.mycompany.com"
  }
}
```

---

## Relationship with Claude Code / Codex / Gemini

| Feature | Claude Code | Codex | Gemini | OpenCode |
|---------|-------------|-------|--------|----------|
| Global instructions | `~/.claude/CLAUDE.md` (with `@` includes) | `AGENTS.md` | `GEMINI.md` | `~/.config/opencode/AGENTS.md` **or** `~/.claude/CLAUDE.md` (fallback, no `@` resolution) |
| Project instructions | `CLAUDE.md` / `.claude/CLAUDE.md` | `AGENTS.md` | `GEMINI.md` | `AGENTS.md` → `CLAUDE.md` → `CONTEXT.md` (first found wins) |
| Skills/tools | `~/.claude/skills/**/SKILL.md` | N/A | N/A | Same path supported + `~/.agents/skills/` |
| Agents | `~/.claude/agents/*.md` | N/A | N/A | `~/.config/opencode/agents/*.md` |
| Commands | `~/.claude/commands/*.md` | N/A | N/A | `~/.config/opencode/commands/*.md` |
| Rules | `~/.claude/rules/*.md` (loaded via `@` in CLAUDE.md) | N/A | N/A | **Not supported** — must inline in AGENTS.md |
| MCP | `~/.claude/claude_desktop_config.json` (settings) | N/A | via config | `opencode.jsonc` → `mcp` key |
| Permissions | `~/.claude/settings.json` → `permissions` | N/A | N/A | `opencode.jsonc` → `permission` key |
| Config file | `~/.claude/settings.json` | `~/.codex/config.yaml` | `~/.gemini/settings.json` | `~/.config/opencode/opencode.jsonc` |

### Key differences vs. Claude Code

1. **No `@` include resolution** — flatten your `CLAUDE.md` include chain into a single `~/.config/opencode/AGENTS.md`.
2. **No `rules/` directory** — rules must be inlined into your `AGENTS.md`.
3. **No `agents/` from `~/.claude/`** — only `~/.config/opencode/agents/` is scanned.
4. **No `commands/` from `~/.claude/`** — only `~/.config/opencode/commands/` is scanned.
5. **Skills ARE shared** — `~/.claude/skills/**/SKILL.md` is read by both tools.
6. **`CLAUDE.md` is only used as a fallback** — if `~/.config/opencode/AGENTS.md` exists, `CLAUDE.md` is ignored.

### Recommended setup for Claude Code users

Create `~/.config/opencode/AGENTS.md` with the fully-expanded content of your
instruction chain (no `@` references). This ensures opencode gets your full
instructions regardless of what files exist in `~/.claude/`.

```bash
# Example: build a flat AGENTS.md from your Claude Code config chain
cat ~/.claude/CLAUDE.md \
    ~/.claude/AGENTS.md \
    ~/.claude/INSTRUCTIONS.md \
    ~/.claude/rules/*.md \
    > ~/.config/opencode/AGENTS.md
```

---

## Environment Variable Flags

| Variable | Effect |
|----------|--------|
| `OPENCODE_CONFIG_DIR` | Override config directory |
| `OPENCODE_DISABLE_EXTERNAL_SKILLS` | Disable all external skill scanning |
| `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS` | Skip `~/.claude/skills/` scan |
| `OPENCODE_DISABLE_CLAUDE_CODE_PROMPT` | Skip `~/.claude/CLAUDE.md` loading |
| `OPENCODE_DISABLE_PROJECT_CONFIG` | Skip project-level config (`.opencode/`) |
| `OPENCODE_TEST_HOME` | Override home directory (for testing) |
