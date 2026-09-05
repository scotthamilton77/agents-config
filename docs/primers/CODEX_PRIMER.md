# Codex CLI — Minimal Seed Context Primer

> Use this document when launching a non-interactive Codex agent with the
> smallest supported initial context, especially for work that is not tied to
> the current repository.

---

## Seed Context

**Seed context** is what Codex sends before the task prompt: Codex's built-in
instructions, tool definitions, user and project configuration, discovered
`AGENTS.md` files, skills metadata, MCP tools, hooks, plugins, and—when
present—host-managed developer instructions.

The user-controlled part can be reduced substantially. A managed host's own
developer messages are a higher-precedence layer: Codex CLI cannot replace or
remove them. A normal standalone `codex exec` launch does not inherit the
surrounding application's conversation context.

## The Levers

| Flag or setting | Effect |
|---|---|
| `--ignore-user-config` | Do not load `$CODEX_HOME/config.toml`; authentication still uses `CODEX_HOME`. This removes user-configured MCP servers, plugins, inline hooks, and other user defaults, but does not itself suppress project configuration or `hooks.json`. |
| `-c 'model_instructions_file="/path/file"'` | Replaces Codex's built-in instructions with the file's content instead of loading `AGENTS.md`. This is the primary built-in-prompt reduction lever. |
| `-c 'project_doc_max_bytes=0'` | Suppresses discovered global and project `AGENTS.md` instructions. |
| `-c 'skills.max_context_tokens=1'` | Reduces the available-skills catalog to its empty header. The default budget is 2% of the context window, capped at 10,000 tokens. |
| `--disable hooks` | Disables lifecycle hooks loaded from `hooks.json` or inline configuration. |
| `--disable apps` | Disables app and connector integrations. |
| `--disable plugins` | Disables installed plugin capabilities. |
| `--disable multi_agent` | Disables multi-agent collaboration tools. |
| `--disable shell_tool` | Disables the default shell tool. Use only when the task needs no local command execution. |

`--ignore-rules` is unrelated to instruction context: it skips user and project
exec-policy `.rules` files only.

Codex has no single `--no-mcp` or Claude-style `--strict-mcp-config` switch.
For a named top-level server, use:

```bash
-c 'mcp_servers.server_name.enabled=false'
```

Run outside a project to avoid a project `.codex/config.toml` layer. Combined
with `--ignore-user-config` and disabled plugins, that is the supported way to
remove configured MCP sources wholesale.

## Minimal Recipe

Create a small instruction file, for example:

```text
You are a focused assistant. Complete the user's task directly and concisely.
```

Then run from an empty directory:

```bash
codex exec --ignore-user-config \
  --disable hooks \
  --disable apps \
  --disable plugins \
  --disable multi_agent \
  --disable shell_tool \
  -c 'model_instructions_file="/absolute/path/minimal-instructions.md"' \
  -c 'project_doc_max_bytes=0' \
  -c 'skills.max_context_tokens=1' \
  'your task'
```

Keep only the capabilities the task needs. In particular, remove
`--disable shell_tool` for work that needs local files or commands.

## What Cannot Be Cut

Codex's transport and tool protocol still require a base agent envelope. When
Codex runs inside a managed product or harness, that host can inject
permissions, app, plugin, collaboration, and developer instructions. Those
messages are outside user `config.toml`; neither `model_instructions_file` nor
the context settings above override them.

This distinction matters when measuring. A prompt renderer launched from inside
another Codex conversation can show the parent's host messages even after every
user-controlled lever has been applied. Measure the actual launch environment,
not an embedded agent session.

## Inspecting the Result

Codex CLI can render the model-visible input without starting an agent:

```bash
codex debug prompt-input \
  -c 'model_instructions_file="/absolute/path/minimal-instructions.md"' \
  -c 'project_doc_max_bytes=0' \
  -c 'skills.max_context_tokens=1' \
  'ping'
```

Review the JSON for unexpected `AGENTS.md`, skills, app, plugin, or host
messages. The renderer is an inspection tool, not a usage report; do not infer
token billing from its byte count.

## Sources

- [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
- [Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
