# Git Commits (sandbox)

Heredocs fail in sandbox mode ("can't create temp file") — never use `<<EOF`/`<<'EOF'` for commit messages. Use `-m` (repeat for multi-line); for complex messages set `dangerouslyDisableSandbox: true` (git is safe).
