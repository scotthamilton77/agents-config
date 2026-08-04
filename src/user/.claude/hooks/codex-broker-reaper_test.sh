#!/usr/bin/env bash
# Tests for codex-broker-reaper.py.
#
# The fixtures are real processes: the hook classifies by command line and by
# live socket state, so nothing short of an actual listening process exercises
# it honestly. The stub is therefore named after what it stands in for — the
# hook looks for `app-server-broker.mjs serve`, so the fixture's command line
# has to be exactly that shape.
#
# Every run is scoped to its own temp directory via CODEX_BROKER_REAPER_SCOPE,
# so no test can reach a broker belonging to a real session, and the age gate
# is lowered so a freshly spawned fixture is judged rather than deferred.
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOK="$SCRIPT_DIR/codex-broker-reaper.py"
PASS=0; FAIL=0

assert_contains() { case "$3" in *"$2"*) PASS=$((PASS+1));; *) FAIL=$((FAIL+1)); echo "FAIL: $1"; echo "  expected to contain: $2"; echo "  got: $3";; esac; }
assert_missing()  { case "$3" in *"$2"*) FAIL=$((FAIL+1)); echo "FAIL: $1"; echo "  expected NOT to contain: $2"; echo "  got: $3";; *) PASS=$((PASS+1));; esac; }
assert_rc()       { if [ "$2" -eq "$3" ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); echo "FAIL: $1 (expected rc=$2, got $3)"; fi; }
assert_alive()    { if kill -0 "$2" 2>/dev/null; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); echo "FAIL: $1 (pid $2 died)"; fi; }
assert_dead()     { if wait_until "! kill -0 $2 2>/dev/null"; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); echo "FAIL: $1 (pid $2 still alive)"; fi; }

# Poll a condition for up to ~5s. A bare spin loop is not a wait: it retries
# faster than a process can bind a socket or exit, and reports a false verdict.
wait_until() { local n=0; while [ $n -lt 100 ]; do if eval "$1"; then return 0; fi; sleep 0.05; n=$((n+1)); done; return 1; }

WORK="$(mktemp -d)"

# Every stub this suite starts is recorded here and its process group signalled
# on the way out. The stubs are deliberately given sessions of their own, so
# they are in no group this script could sweep wholesale — a suite for a leak
# reaper that leaked its own fixtures would be a poor advertisement.
STARTED="$WORK/started.pids"; : > "$STARTED"
cleanup() {
  while read -r pid; do kill -TERM -- "-$pid" 2>/dev/null; done < "$STARTED"
  command rm -rf "$WORK"
}
trap cleanup EXIT

export CODEX_BROKER_REAPER_SCOPE="$WORK"
export CODEX_BROKER_REAPER_MIN_AGE_SECONDS=0
export CLAUDE_PLUGIN_DATA="$WORK/plugin-data"
STATE="$CLAUDE_PLUGIN_DATA/state"; mkdir -p "$STATE"

# Stands in for the plugin's broker: binds the endpoint socket, writes its pid
# file, then idles. Its filename is load-bearing — see the header.
STUB="$WORK/app-server-broker.mjs"
cat > "$STUB" <<'PY'
import os, socket, sys, threading, time
argv = sys.argv[1:]
def value_of(flag): return argv[argv.index(flag) + 1]
path = value_of("--endpoint").removeprefix("unix:")
open(value_of("--pid-file"), "w").write(str(os.getpid()))
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
server.bind(path); server.listen(8)

# Accept and hold, as the real broker does. An unaccepted connection sits in the
# backlog and the server holds no descriptor for it, so a stub that only listens
# would look idle to the hook however many clients were waiting.
accepted = []
def serve():
    while True:
        try: accepted.append(server.accept()[0])
        except OSError: return
threading.Thread(target=serve, daemon=True).start()

sys.stdout.write("ready\n"); sys.stdout.flush()
time.sleep(120)
PY

# Each stub leads its own process group, exactly as the plugin's detached
# broker does — the hook declines to signal anything that does not.
start_stub() { # $1 = name; echoes "pid sockpath"
  local dir="$WORK/$1"; mkdir -p "$dir"
  local sock="$dir/broker.sock"
  setsid python3 "$STUB" serve --endpoint "unix:$sock" --cwd "$dir" --pid-file "$dir/broker.pid" \
    > "$dir/out" 2>&1 &
  wait_until "[ -S '$sock' ]" || echo "stub $1 never bound its socket" >&2
  # The stub's own pid file, not $!. Where setsid is emulated, the job pid is the
  # wrapper's and the process that survives the exec is a different one — the
  # pid the hook will see, and the only one worth tracking or asserting on.
  local pid; pid="$(cat "$dir/broker.pid" 2>/dev/null || echo 0)"
  echo "$pid" >> "$STARTED"
  echo "$pid $sock"
}

record_broker() { # $1 = state slug, $2 = pid, $3 = sockpath
  mkdir -p "$STATE/$1"
  printf '{"endpoint":"unix:%s","pid":%s}\n' "$3" "$2" > "$STATE/$1/broker.json"
}

run_hook() { OUT="$(printf '{}' | python3 "$HOOK" "$@" 2>&1)"; RC=$?; }

# --- setsid must be available, or the fixtures are not group leaders ---------
if ! command -v setsid >/dev/null 2>&1; then
  # macOS has no setsid(1); python can do the same thing.
  setsid() { python3 -c 'import os,sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' "$@"; }
fi

# --- an unreferenced broker with no client is terminated ---------------------
read -r ORPHAN_PID ORPHAN_SOCK <<< "$(start_stub orphan)"
run_hook --verbose
assert_rc      "hook always exits 0"                       0 "$RC"
assert_contains "unreferenced idle broker is reaped"       "REAP $ORPHAN_PID" "$OUT"
assert_contains "and says why"                             "no client connected" "$OUT"
assert_dead    "unreferenced idle broker is gone"          "$ORPHAN_PID"

# --- a broker named by a session record is left alone ------------------------
read -r KEPT_PID KEPT_SOCK <<< "$(start_stub recorded)"
record_broker recorded-workspace "$KEPT_PID" "$KEPT_SOCK"
run_hook --verbose
assert_contains "recorded broker is kept"                  "keep $KEPT_PID" "$OUT"
assert_contains "and says why"                             "named by a session record" "$OUT"
assert_missing  "recorded broker is never reaped"          "REAP $KEPT_PID" "$OUT"
assert_alive    "recorded broker survives"                 "$KEPT_PID"

# --- an unreferenced broker with a live client is left alone -----------------
# This is the race loser: absent from every record, yet serving a real task.
read -r BUSY_PID BUSY_SOCK <<< "$(start_stub busy)"
python3 -c 'import socket,sys,time
c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); c.connect(sys.argv[1])
sys.stdout.write("connected\n"); sys.stdout.flush(); time.sleep(60)' "$BUSY_SOCK" > "$WORK/client-out" &
CLIENT_PID=$!
wait_until "grep -q connected '$WORK/client-out' 2>/dev/null" || echo "client never connected" >&2
run_hook --verbose
assert_contains "in-use orphan is kept"                    "keep $BUSY_PID" "$OUT"
assert_contains "and counts the client"                    "1 client(s) connected" "$OUT"
assert_alive    "in-use orphan survives"                   "$BUSY_PID"
kill "$CLIENT_PID" 2>/dev/null

# --- a record that will not parse confers no protection ----------------------
# Deliberate, not incidental: the plugin reads these the same way and treats a
# parse failure as no session, so it will never reuse the broker such a record
# names. The age gate, not this lookup, is what protects a record mid-write.
read -r CORRUPT_PID CORRUPT_SOCK <<< "$(start_stub corrupt)"
mkdir -p "$STATE/corrupt-workspace"
printf '{"endpoint":"unix:%s","pid":' "$CORRUPT_SOCK" > "$STATE/corrupt-workspace/broker.json"
run_hook --verbose
assert_contains "broker behind a truncated record is reaped"  "REAP $CORRUPT_PID" "$OUT"
assert_dead     "and is gone"                                 "$CORRUPT_PID"

# A record that parses but names no pid is likewise no protection.
read -r NOPID_PID NOPID_SOCK <<< "$(start_stub nopid)"
mkdir -p "$STATE/nopid-workspace"
printf '{"endpoint":"unix:%s"}\n' "$NOPID_SOCK" > "$STATE/nopid-workspace/broker.json"
run_hook --verbose
assert_contains "broker behind a pid-less record is reaped"   "REAP $NOPID_PID" "$OUT"
assert_dead     "and is gone"                                 "$NOPID_PID"

# --- a broker younger than the age gate is deferred --------------------------
read -r YOUNG_PID YOUNG_SOCK <<< "$(start_stub young)"
CODEX_BROKER_REAPER_MIN_AGE_SECONDS=3600 run_hook --verbose
assert_contains "young broker is deferred"                 "too young to judge" "$OUT"
assert_alive    "young broker survives"                    "$YOUNG_PID"

# --- an unreferenced broker whose socket is gone is terminated ---------------
rm -f "$YOUNG_SOCK"
run_hook --verbose
assert_contains "socket-less orphan is reaped"             "socket removed" "$OUT"
assert_dead     "socket-less orphan is gone"               "$YOUNG_PID"

# --- dry run decides but does not act ----------------------------------------
read -r DRY_PID DRY_SOCK <<< "$(start_stub dryrun)"
run_hook --dry-run --verbose
assert_contains "dry run reports the verdict"              "would terminate" "$OUT"
assert_alive    "dry run leaves the process running"       "$DRY_PID"

# --- silence when there is nothing to do -------------------------------------
record_broker dryrun-workspace "$DRY_PID" "$DRY_SOCK"
run_hook
assert_rc       "quiet run exits 0"                        0 "$RC"
assert_contains "quiet run says nothing"                   "" "$OUT"
if [ -n "$OUT" ]; then FAIL=$((FAIL+1)); echo "FAIL: hook spoke when it had nothing to report: $OUT"; else PASS=$((PASS+1)); fi

echo "----"
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
