# Claude Code CLI — Context Primer

> Use this document to orient yourself to Claude Code's CLI surface before
> tuning what a launch sends to the model, or before debugging why an isolated
> profile will not authenticate.

---

## Seed Context

**Seed context** is everything Claude Code sends to the model before the user's
first token: the built-in system prompt, tool schemas, settings-derived
instructions, `CLAUDE.md`/`AGENTS.md` content, MCP server definitions, and
hook- or plugin-injected text.

It is paid on every conversation and it is the one cost a launch controls
completely. Tool *schemas* dominate it — not prose. Reducing the instruction
text while leaving the default tool set intact moves the number very little.

### Measuring it

`--output-format json` reports usage. Sum the three input fields; a run that
creates cache and a run that reads it both charge for the same underlying
prompt, so any one of them alone understates the total.

```bash
claude --output-format json -p "hi" </dev/null | python3 -c "
import json,sys; u=json.load(sys.stdin)['usage']
print(u['input_tokens']+u['cache_creation_input_tokens']+u['cache_read_input_tokens'])
"
```

Run it from a directory with no project config, or project discovery becomes a
variable in the measurement.

---

## The Levers

| Flag | Effect |
|---|---|
| `--tools "<list>"` | Restrict the built-in tool set. `""` = none, `"default"` = all, or a list: `"Bash,Read,Edit,Write,Grep,Glob"`. **The largest single lever.** |
| `--setting-sources "<list>"` | Comma-separated sources to load from `user,project,local`. `""` loads none — settings, hooks, and the instruction files they pull in all drop out. |
| `--system-prompt "<text>"` | **Replaces** the built-in system prompt. `--system-prompt-file` takes a path. |
| `--append-system-prompt "<text>"` | **Adds to** the built-in prompt. Does not replace it, and so does not reduce seed context. |
| `--strict-mcp-config` | Ignore all MCP configuration except `--mcp-config`. With no `--mcp-config`, no servers load. |
| `--restricted` | Removes command-running tools and WebFetch, and ignores user/project/local settings. Managed settings and `--settings` still apply. A blunt bundle — the explicit flags above reach a lower floor. |
| `--system-prompt-snapshot on\|off` | Records the rendered prompt once per conversation and reuses it verbatim. Defaults to `on` for the built-in prompt; passing `--system-prompt` or `--append-system-prompt` turns it off. |
| `--no-chrome` | Drops the Claude in Chrome integration. |
| `--no-session-persistence` | Sessions are not written to disk and cannot be resumed. `--print` only. |

`--append-system-prompt` is the trap in that list: it reads like a sibling of
`--system-prompt` and does the opposite of what a context-reduction pass wants.

---

## Measured Ladder

Claude Code 2.1.261, macOS, `-p "hi"` from a directory with no project config.
All rows also carry `--strict-mcp-config`.

| Configuration | Seed tokens |
|---|---:|
| baseline, no flags | 31,420 |
| `--setting-sources ""` | 16,393 |
| `--restricted` | 14,182 |
| `--tools "" --system-prompt "…"` (settings still loaded) | 5,230 |
| `--setting-sources "" --tools "Bash,Read,Edit,Write,Grep,Glob" --system-prompt "…"` | 4,374 |
| `--setting-sources "" --tools "Read,Grep,Glob" --system-prompt "…"` | 2,709 |
| `--setting-sources "" --tools "" --system-prompt "…"` | 264 |
| `--setting-sources "" --tools "" --system-prompt ""` | 254 |

The floor reproduces exactly across runs.

**The baseline is profile-specific.** 31,420 reflects one particular
`~/.claude` — its instruction files, hooks, plugins and MCP servers. A leaner
profile starts lower and has less to win. The *deltas* transfer; the absolute
starting number does not.

Two readings worth carrying:

- Tool schemas are roughly two-thirds of a default launch. `--tools ""` alone
  is worth more than every prose-trimming flag combined.
- `--setting-sources ""` is worth ~5,000 tokens *on top of* `--tools ""`
  (5,230 → 264), because it drops instruction files the tool cut leaves behind.

`ENABLE_TOOL_SEARCH=true` defers tool schemas rather than sending them upfront,
which is the other way to attack the dominant cost. `--setting-sources ""`
discards it along with the rest of settings; passing it as an environment
variable keeps it. Its combined effect with these flags is unmeasured.

---

## Recipes

Minimal working agent — file and shell tools, no project instructions:

```bash
claude --strict-mcp-config --setting-sources "" \
       --tools "Bash,Read,Edit,Write,Grep,Glob" \
       --system-prompt "You are a coding agent."
```

Chat-only floor. No tools, so this answers questions and does nothing else:

```bash
claude --strict-mcp-config --setting-sources "" --tools "" \
       --system-prompt "You are a helpful assistant."
```

Verifying isolation — ask the model whether specific instructions reached it,
and compare against an unflagged control run:

```bash
claude --setting-sources "" --tools "" --system-prompt "You are a helpful assistant." \
  -p 'Answer only yes/no: do your instructions mention <a phrase unique to your AGENTS.md>?'
```

---

## `--bare` and Authentication

`--bare` skips hooks, LSP, plugin sync, attribution, auto-memory, background
prefetches, keychain reads and `CLAUDE.md` discovery, and sets
`CLAUDE_CODE_SIMPLE=1`.

**It cannot use subscription authentication.** Under `--bare`, credentials come
only from `ANTHROPIC_API_KEY` or an `apiKeyHelper` supplied via `--settings`,
and both are transmitted as `x-api-key`. A subscription OAuth token
(`sk-ant-oat01-…`) is a bearer token, so it is delivered intact and rejected
with `401 API key invalid`. `CLAUDE_CODE_OAUTH_TOKEN` is ignored. Setting
`CLAUDE_CODE_SIMPLE=1` without `--bare` blocks keychain reads identically — the
environment variable is the switch, not the flag.

So `--bare` means pay-per-token billing. For subscription billing with a small
seed context, use `--setting-sources ""` and the tool and prompt flags above,
which reach a lower floor anyway.

Two operational notes:

- With a credential present but rejected, `claude --bare -p` produces **no
  output on stdout or stderr and does not exit**. The 401 surfaces only in an
  interactive terminal. Wrap non-interactive `--bare` calls in a timeout; a bad
  key is indistinguishable from a hang.
- `claude setup-token` requires a TTY and cannot be driven from automation.

---

## Config-Dir Isolation

`CLAUDE_CONFIG_DIR` points Claude Code at a different profile directory,
isolating settings, hooks, plugins, skills, commands, agents and instruction
files. It is dominated by `--setting-sources ""` for context reduction — more
setup, more failure modes, and a higher floor (17,800 vs 264) — but it remains
the right tool when the goal is a genuinely separate profile with its own
sessions and history.

Credentials are keyed **per config directory**. The default `~/.claude` uses
keychain service `Claude Code-credentials`; any other directory uses
`Claude Code-credentials-<hash of its path>`. A new config dir therefore starts
unauthenticated, which presents as `Not logged in · Please run /login` even
though the default profile is working.

`/login` inside the new profile is the supported fix. Copying the default
profile's credential into `<config-dir>/.credentials.json` (mode 600) also
authenticates, but fails in a way that resists repair:

- The copied credential works until something triggers a token refresh.
- At the refresh attempt Claude Code writes a keychain entry for that config
  dir's path hash. If the shared refresh token has since been rotated by the
  default profile, the refresh fails and the entry is written with
  `expiresAt = 0`.
- That keychain entry then **shadows** `.credentials.json` permanently.
  Re-copying the file has no effect, because the file is no longer read.
- The entry outlives the directory. Recreating a config dir at the same path
  inherits the tombstone.

Symptom: `Failed to authenticate: OAuth session expired and could not be
refreshed`, on a credential file that is demonstrably current. Recovery is
`security delete-generic-password -s "Claude Code-credentials-<hash>"` followed
by a re-copy, or `/login`. A copied credential is also plaintext on disk rather
than in the keychain.

Enumerate what exists with:

```bash
security dump-keychain 2>/dev/null \
  | grep -o '"svce"<blob>="Claude Code-credentials[^"]*"' | sort -u
```

---

## Refreshing These Numbers

The measurements are version-specific and profile-specific. Re-run the ladder
after a Claude Code upgrade or a significant change to `~/.claude`. The method
in **Measuring it** is the durable part; the table is a snapshot.
