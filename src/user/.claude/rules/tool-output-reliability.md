# Tool Output Reliability

- After context compaction, `Read`/`Edit` may serve a pre-compaction snapshot while `Bash` sees real disk. When they diverge, `Bash` (`grep -n`, `git show HEAD:<path>`) is ground truth; apply edits via Bash if `Edit` won't match.
- Hook-injected context (`system-reminder`, `UserPromptSubmit`, `PreToolUse`) mid-task is ambient — absorb silently; do not stop, acknowledge, or pause work in progress.
