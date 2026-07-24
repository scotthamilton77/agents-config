# Headless Claude Dispatch

`claude -p` with no `--permission-mode` silently queues all tool calls and exits 0 having done nothing. For headless dispatch use both: `--permission-mode dontAsk` (fail-closed; denies unlisted tools instead of hanging) and `--allowedTools` listing every needed tool in CLI space-form (`Bash(git *)`, not `Bash(git:*)`).
