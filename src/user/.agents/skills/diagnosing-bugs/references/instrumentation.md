# Instrumentation

Two different jobs, and confusing them is how a multi-layer bug gets fixed in
the wrong component. Boundary instrumentation (Phase 3) runs *before* you have a
hypothesis, to find out which layer fails. Probe instrumentation (Phase 4) runs
*after*, to test one prediction at a time.

## Boundary instrumentation — Phase 3, multi-layer bugs only

The trigger is a bug that spans components: CI → build → signing, API → service
→ database, client → gateway → worker. Reading the source of all of them is
slower and less conclusive than one instrumented run.

For each component boundary:

- log what data **enters** the component;
- log what data **exits** it;
- verify environment and configuration actually propagated across the boundary;
- capture state at the transition itself.

Then run **once** and read the evidence before touching anything. The output
tells you which boundary the data was still correct at and which one it was not,
which is a different question from why.

```bash
# Layer 1: workflow
echo "=== secrets visible in workflow ==="
echo "IDENTITY: ${IDENTITY:+SET}${IDENTITY:-UNSET}"

# Layer 2: build script
echo "=== env in build script ==="
env | grep IDENTITY || echo "IDENTITY not in environment"

# Layer 3: signing script
echo "=== keychain state ==="
security find-identity -v
```

Only once the failing layer is identified do you investigate it in depth. The
failure this prevents is fixing the first component that looks suspicious when
the break is one boundary earlier — and every fix you make upstream of the real
break creates a new symptom rather than removing one.

## Probe instrumentation — Phase 4

Each probe maps to one prediction from the ranked hypotheses. Change one
variable at a time, in this order of preference:

1. **Debugger / REPL inspection**, wherever the environment supports it. One
   breakpoint that lets you inspect the whole frame beats ten log lines chosen
   in advance by someone who did not yet know what mattered.
2. **Targeted logs**, placed at the boundaries that actually distinguish the
   competing hypotheses — not everywhere the value appears.
3. Never "log everything and grep". The volume hides the signal, and the cleanup
   is unbounded.

**Tagging.** Give every debug log a unique prefix for this investigation, e.g.
`[DEBUG-a4f2]`. Cleanup then becomes a single grep for that tag, which is what
makes Phase 6's removal step mechanical rather than a memory exercise. Untagged
debug logs survive into the commit; tagged ones die.

## Performance regressions

Logs are usually the wrong instrument. A regression is a change in a
distribution, and a log line tells you an event happened, not how long it took
relative to before.

1. Establish a **baseline measurement** first: a timing harness, a profiler run,
   an EXPLAIN/query plan, or the runtime's own high-resolution clock
   (`performance.now()` and equivalents).
2. Then **bisect** against that measurement — across commits, across input
   sizes, or across the stages of the request — until one stage owns the delta.

Measure first, fix second. A perf fix without a before-and-after measurement is
indistinguishable from no fix.
