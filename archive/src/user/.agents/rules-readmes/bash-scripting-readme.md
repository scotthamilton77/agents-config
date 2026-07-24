# Bash Effectful Operations — Context

## The trap

```bash
# WRONG — under set -e, the redirect failure is silently swallowed:
[ -n "$cid" ] && printf '%s\n' "$cid" >> "$STATE_FILE"

# RIGHT:
if [ -n "$cid" ]; then
  if ! printf '%s\n' "$cid" >> "$STATE_FILE"; then
    echo "WARNING: state-write failed" >&2
    any_failed=1
  fi
fi
```

## When it matters

Read-only/pure tests on the RHS are fine — the rule applies when the RHS has a side effect an invariant depends on (idempotency record, audit log, anti-duplicate sidecar, network call).
