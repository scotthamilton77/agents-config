# Beads CLI — Context

## Parentage: edge vs. dotted ID

`bd list --parent X` matches the dotted ID string (`X.n`); removing the dependency edge via `bd dep remove` orphans the bead for edge-walking tools (whats-next shows blank parent) but `bd list --parent` still returns it. There is no deferred/hidden state — `bd close` + a reason is the only honest park.

## Sync pattern

```bash
bd dolt commit -m "session close"
bd dolt push
# Successful push = not behind. Investigate only if push rejects.
```

## label remove

```bash
# WRONG — labelA parsed as a second issue ID:
bd label remove BEAD-1 labelA labelB

# RIGHT — one label per call:
bd label remove BEAD-1 labelA
bd label remove BEAD-1 labelB
```

## Close-walk verification

```bash
bd close <last-child>
bd show <parent-epic>          # verify status == closed
# If still open with all children closed:
bd dep list <epic> --direction up   # enumerate true children (edge, not dotted ID)
bd close <parent-epic>
```
