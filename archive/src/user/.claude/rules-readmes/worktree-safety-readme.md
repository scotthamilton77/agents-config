# Worktree Safety — Context

## Verifying isolation by path

```bash
# Insufficient — branch can be correct while main folder gets switched:
git branch --show-current

# Correct — worktree path proves isolation:
git rev-parse --show-toplevel   # must contain .claude/worktrees/
```

## Write/Edit path trap

`Bash` cwd protects shell commands only. `Write`/`Edit` use the absolute path you pass regardless of cwd — a path like `<repo>/docs/plan.md` writes to the main tree even when every shell command runs correctly in the worktree. Always build `Write`/`Edit` paths under the worktree root.

## Parallel isolated subagents pattern

```
EnterWorktree(name: "worker-A")
→ spawn subagentA (no isolation arg)
→ ExitWorktree  # keep; do not remove worktree
EnterWorktree(name: "worker-B")
→ spawn subagentB (no isolation arg)
→ ExitWorktree  # keep; do not remove worktree
```
Subagents inherit orchestrator cwd at spawn — entering the worktree first means the subagent starts there.

## Agent(isolation: "worktree") is broken

Bug #33045: silently ignored for named/team agents; agents land at repo root on main. `Workflow agent(isolation: "worktree")` is a distinct runtime that works correctly. Do not rely on the Agent tool's isolation flag.

## Phantom-cwd

Deleting a worktree while a subagent's shell holds the inode: `pwd` still reports the old path but writes become non-deterministic (some land in the stale inode, some fall through). Always exit the worktree without removing it before proceeding; only remove after all occupying subagents complete.

## Cleanup after merge

```bash
cd <repo-root>                               # never from inside the worktree
git worktree remove .claude/worktrees/<name>
git branch -D <branch>                       # -d fails after a squash-merge: branch reads as unmerged
git worktree list                            # verify: only main remains
```

`ExitWorktree` hits the same squash-merge trap — it sees the pre-squash commit as unmerged and refuses; pass `discard_changes: true` only after confirming the work is on main.
