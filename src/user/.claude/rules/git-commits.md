# Git Commits

Sandbox mode: heredocs fail with "can't create temp file."

1. Simple: `git commit -m "fix(scope): message"`
2. Multi-line: `git commit -m "fix(scope): summary" -m "Co-Authored-By: ..."`
3. Complex: use `dangerouslyDisableSandbox: true` (git is safe)

**NEVER use heredoc syntax** (`<<EOF`, `<<'EOF'`) for commit messages.
