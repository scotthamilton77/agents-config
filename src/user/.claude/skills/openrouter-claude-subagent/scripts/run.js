#!/usr/bin/env node
// Launcher for an OpenRouter-backed `claude` subagent.
//
// Starts the SSE-repair proxy IN-PROCESS on a kernel-assigned port, spawns
// `claude` against it, forwards every CLI argument but its own clock flags
// through, and exits with the child's status.
//
// The clock flags bound the run. `--timeout SECONDS` ends it that long after
// the child starts. `--idle-timeout SECONDS` ends it once that long passes
// with no completion request forwarded upstream. A SIGTERM or SIGINT to the
// launcher ends it too. Each of these ends the child's whole process group,
// closes the proxy, prints `[run] reason=timeout|idle|signal` on stderr and
// exits 75.
//
// The proxy runs in-process rather than as a spawned sibling on purpose: the
// listener dies with this process no matter how it dies. A spawn-plus-trap
// design only cleans up if the wrapper survives long enough to run the trap,
// and gets no say at all under SIGKILL — leaving an orphaned proxy squatting
// a port, which poisons every later run with nobody watching.
//
// Usage:
//   node run.js --model <id> --effort <level> --permission-mode dontAsk \
//               --allowedTools Read Grep [--timeout SECONDS] \
//               [--idle-timeout SECONDS] -p "<prompt>"
//
// All four of those flags are required — see REQUIRED_FLAGS for why each one
// is refused rather than defaulted. Everything else is passed through verbatim.

const { spawn } = require("child_process");
const path = require("path");
const proxy = require("./proxy.js");

/** Launcher-level failure (bad config), distinct from any `claude` exit code. */
const EXIT_CONFIG_ERROR = 78;

/** The launcher ended the run before the child finished: a clock expired or
 *  the launcher was signalled. A `[run] reason=` line on stderr says which. */
const EXIT_ROUTE = 75;

/** How often the run is checked on. It bounds how late an expiry, a signal or
 *  the child's exit is noticed. */
const POLL_MS = 100;

/** How long the child's process group has to exit after SIGTERM before it is
 *  sent SIGKILL. Short enough that a run ends within ten seconds of the
 *  moment the launcher decides to end it. */
const KILL_GRACE_MS = 5000;

/** Flags this launcher refuses to run without, each as its accepted spellings.
 *
 *  Every one of them fails invisibly when omitted, which is why the check is
 *  here rather than in prose the caller may not have read:
 *
 *  - `--permission-mode`: the nested process has no terminal to prompt at, so
 *    it queues every tool call and exits 0 having done nothing.
 *  - `--allowedTools`: the proxy strips the deferred-tool declaration for
 *    non-Anthropic models, so this list is the entire tool grant.
 *  - `--model`: without it the redirect points at whatever default the client
 *    picks, which the OpenRouter account may not serve at all. It is also the
 *    model the whole run is pinned to — see resolveModel and buildChildEnv.
 *  - `--effort`: the harness otherwise picks a reasoning level the task never
 *    asked for, at a cost nobody chose.
 */
const REQUIRED_FLAGS = [
  ["--model"],
  ["--effort"],
  ["--permission-mode"],
  ["--allowedTools", "--allowed-tools"],
];

/** Argv with the prompt's value dropped.
 *
 *  Every other argument is written by whoever launched the run. The prompt
 *  carries task text, which routinely comes from the material being worked on,
 *  so a prompt beginning `--effort` would otherwise read as that flag being
 *  present — and the checks below exist precisely because a missing one fails
 *  silently rather than loudly. */
function configArgv(argv) {
  const out = [];
  for (let i = 0; i < argv.length; i++) {
    out.push(argv[i]);
    if (argv[i] === "-p" || argv[i] === "--print") i++;
  }
  return out;
}

/** The launcher's own flags, each mapped to the key it sets. They bound the
 *  run in seconds and are never passed on to the child. */
const CLOCK_FLAGS = { "--timeout": "timeoutMs", "--idle-timeout": "idleMs" };

/** Take the clock flags out of argv, accepting both `--flag v` and `--flag=v`.
 *
 *  The prompt's value is copied through untouched, so task text that happens
 *  to read `--timeout 5` stays task text and bounds nothing.
 *
 *  @returns {{argv: string[], timeoutMs?: number, idleMs?: number}|{error: string}} */
function takeClockFlags(argv) {
  const out = { argv: [] };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    const [name, inline] = arg.split(/=(.*)/s, 2);
    if (!Object.hasOwn(CLOCK_FLAGS, name)) {
      out.argv.push(arg);
      if ((arg === "-p" || arg === "--print") && i + 1 < argv.length) out.argv.push(argv[++i]);
      continue;
    }
    const value = inline ?? argv[++i];
    if (value === undefined) {
      return { error: `${name} was given no value. It takes a number of seconds.` };
    }
    const seconds = Number(value);
    if (!Number.isFinite(seconds) || seconds <= 0) {
      return { error: `${name} was given ${JSON.stringify(value)}, which is not a positive number of seconds.` };
    }
    out[CLOCK_FLAGS[name]] = seconds * 1000;
  }
  return out;
}

/** Check argv for the required flags, accepting both `--flag v` and `--flag=v`.
 *  @returns {string|null} a message naming every missing flag, or null if none. */
function validateArgv(argv) {
  const present = new Set(
    configArgv(argv)
      .filter((arg) => arg.startsWith("--"))
      .map((arg) => arg.split("=", 1)[0])
  );
  const missing = REQUIRED_FLAGS.filter(
    (spellings) => !spellings.some((flag) => present.has(flag))
  ).map((spellings) => spellings[0]);

  if (missing.length === 0) return null;
  return (
    `missing required flag(s): ${missing.join(", ")}. This launcher requires ` +
    "--model, --effort, --permission-mode, and --allowedTools, because " +
    "omitting any of them fails silently rather than loudly."
  );
}

/** Read the single model id this run is pinned to out of argv.
 *
 *  Every model the run reaches bills one account, so the launcher has to know
 *  which one was asked for before it starts anything. Two values for the same
 *  flag is refused rather than guessed at: which one the child would honour is
 *  the client's business, and a wrong guess pins the wrong model.
 *
 *  @returns {{model: string}|{error: string}} */
function resolveModel(argv) {
  const args = configArgv(argv);
  const values = [];
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === "--model") {
      const next = args[i + 1];
      // A model id never starts with a dash, so the next token being a flag
      // means this one was left without a value.
      values.push(next === undefined || next.startsWith("-") ? "" : next);
    } else if (arg.startsWith("--model=")) {
      values.push(arg.slice("--model=".length));
    }
  }

  const distinct = [...new Set(values.map((v) => v.trim()))];
  if (distinct.length > 1) {
    return {
      error:
        "--model was given more than one value (" +
        distinct.map((v) => v || "<empty>").join(", ") +
        "). This launcher pins the run to one model and cannot choose between them.",
    };
  }
  const model = distinct[0] || "";
  if (!model) {
    return {
      error:
        "--model was given no value. This launcher pins the run to the model " +
        "you name, so the name cannot be empty.",
    };
  }
  return { model };
}

/** Build the child environment. The launcher owns every variable that decides
 *  WHERE the traffic goes and WHICH model answers, so a caller cannot
 *  half-configure the redirect and silently bill the wrong account. */
function buildChildEnv(parentEnv, proxyUrl, model) {
  const apiKey = parentEnv.OPENROUTER_API_KEY;
  if (!apiKey) {
    throw new Error(
      "OPENROUTER_API_KEY is not set. This launcher does not create or store " +
      "credentials — export the key, or ask where to find it."
    );
  }
  if (!model) {
    throw new Error("buildChildEnv requires the model this run is pinned to.");
  }
  return {
    ...parentEnv,
    // Its own config dir, so the nested process neither collides with nor
    // inherits state from the parent session's ~/.claude.
    CLAUDE_CONFIG_DIR:
      parentEnv.CLAUDE_CONFIG_DIR_OPENROUTER ||
      path.join(parentEnv.HOME || "", ".claude_openrouter"),
    ANTHROPIC_BASE_URL: proxyUrl,
    ANTHROPIC_AUTH_TOKEN: apiKey,
    // Empty, not absent: an inherited real Anthropic key takes precedence over
    // ANTHROPIC_AUTH_TOKEN, and the call would quietly go to Anthropic.
    ANTHROPIC_API_KEY: "",
    // Every model alias resolves to the one model this run was launched with.
    // A nested run can start further runs, and each of those picks a model of
    // its own from this alias vocabulary — by name, from an agent type's
    // definition, or from a built-in default. Pointing all four at the named
    // model means those runs still happen, still on the model the caller chose
    // and paid for, and still speaking with this run's voice.
    ANTHROPIC_DEFAULT_OPUS_MODEL: model,
    ANTHROPIC_DEFAULT_SONNET_MODEL: model,
    ANTHROPIC_DEFAULT_HAIKU_MODEL: model,
    ANTHROPIC_DEFAULT_FABLE_MODEL: model,
    // The background chores — conversation titles and the like — ride the
    // cheap alias, which now points at a model that may be neither cheap nor
    // free. Nothing about this run needs them. Any non-empty value switches
    // them off, "0" included; the variable reads as a switch, not a boolean.
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1",
  };
}

/** Mirror the child's fate. A signalled child has no exit code, so report it
 *  the way a shell does — 128 + signal number. */
function resolveExitCode(code, signal) {
  if (code !== null && code !== undefined) return code;
  const signals = { SIGINT: 2, SIGKILL: 9, SIGTERM: 15, SIGHUP: 1, SIGQUIT: 3 };
  return 128 + (signals[signal] || 0);
}

// A group signal fails in two harmless ways. ESRCH means every process in the
// group is gone. EPERM is what macOS answers for a group whose remaining members
// have exited but are not yet reaped, and a member this launcher may not signal
// is beyond its reach either way. Both mean there is nothing left to stop.

function signalGroup(pid, signal) {
  try {
    process.kill(-pid, signal);
  } catch { /* the group is already gone */ }
}

function groupAlive(pid) {
  try {
    process.kill(-pid, 0);
    return true;
  } catch {
    return false;
  }
}

/** Watch the child until it exits on its own or the launcher ends it.
 *
 *  Every decision is taken on a tick, so the order of precedence is fixed
 *  whatever order the events arrived in: the child's own exit, then a signal
 *  to the launcher, then the timeout, then the idle timeout. Ending the child
 *  means SIGTERM to its whole process group, then SIGKILL to whatever is left
 *  once KILL_GRACE_MS has passed. The run counts as ended only when the child
 *  has exited and nothing remains in its group.
 *
 *  @returns {Promise<{code: number}|{reason: string}>} */
function supervise(child, { timeoutMs, idleMs, lastForward, now, every }) {
  return new Promise((resolve, reject) => {
    const startedAt = now();
    let exitCode = null;
    let signalled = false;
    let ending = null;

    const onSignal = () => { signalled = true; };
    process.on("SIGINT", onSignal);
    process.on("SIGTERM", onSignal);
    const stopTicking = every(tick);
    const settle = (fn, value) => {
      stopTicking();
      process.off("SIGINT", onSignal);
      process.off("SIGTERM", onSignal);
      fn(value);
    };

    child.on("exit", (code, signal) => { exitCode = resolveExitCode(code, signal); });
    child.on("error", (err) => {
      settle(reject, err.code === "ENOENT" ? new Error("`claude` was not found on PATH.") : err);
    });

    function expiry(t) {
      if (signalled) return "signal";
      if (timeoutMs && t >= startedAt + timeoutMs) return "timeout";
      if (idleMs && t >= lastForward() + idleMs) return "idle";
      return null;
    }

    function tick() {
      const t = now();
      if (ending) {
        if (exitCode !== null && !groupAlive(child.pid)) return settle(resolve, { reason: ending.reason });
        if (!ending.killed && t - ending.since >= KILL_GRACE_MS) {
          signalGroup(child.pid, "SIGKILL");
          ending.killed = true;
        }
        return;
      }
      if (exitCode !== null) return settle(resolve, { code: exitCode });
      const reason = expiry(t);
      if (reason) {
        ending = { reason, since: t, killed: false };
        signalGroup(child.pid, "SIGTERM");
      }
    }
  });
}

/** Run one launch to its end and return the launcher's exit code.
 *
 *  `deps` replaces the parts of the outside world a test needs to control:
 *  `now` reads the clock in milliseconds, `every(fn)` calls `fn` once per tick
 *  and returns a function that stops it, `env` is the environment the child
 *  is built from, and `startProxy` starts the proxy. */
async function main(launcherArgv, deps = {}) {
  const {
    now = () => performance.now(),
    every = (fn) => {
      const timer = setInterval(fn, POLL_MS);
      return () => clearInterval(timer);
    },
    env: parentEnv = process.env,
    startProxy = proxy.start,
  } = deps;

  // Before the proxy binds anything: a bad invocation should cost no listener.
  const clock = takeClockFlags(launcherArgv);
  if (clock.error) {
    process.stderr.write(`[run] ${clock.error}\n`);
    return EXIT_CONFIG_ERROR;
  }
  const argv = clock.argv;

  const argvError = validateArgv(argv);
  if (argvError) {
    process.stderr.write(`[run] ${argvError}\n`);
    return EXIT_CONFIG_ERROR;
  }

  const resolved = resolveModel(argv);
  if (resolved.error) {
    process.stderr.write(`[run] ${resolved.error}\n`);
    return EXIT_CONFIG_ERROR;
  }
  const model = resolved.model;

  if (proxy.isDeniedModel(model)) {
    process.stderr.write(
      `[run] ${model} is not reachable over this transport, by design and not by ` +
      "accident: Claude models run natively in the harness that launched this run, " +
      "and the large GPT tiers run through their own vendor transport. Dispatch " +
      "through the transport that serves it, or name a model from another vendor.\n"
    );
    return EXIT_CONFIG_ERROR;
  }

  let forwardedAt;
  const { port, close } = await startProxy({
    port: 0,
    pinnedModel: model,
    onForward: () => { forwardedAt = now(); },
  });
  const proxyUrl = `http://127.0.0.1:${port}`;

  let env;
  try {
    env = buildChildEnv(parentEnv, proxyUrl, model);
  } catch (err) {
    process.stderr.write(`[run] ${err.message}\n`);
    await close();
    return EXIT_CONFIG_ERROR;
  }

  process.stderr.write(`[run] proxy listening on ${proxyUrl}\n`);

  const child = spawn("claude", argv, {
    env,
    // stdout is passed straight through: it carries the JSON result and must
    // not be contaminated by proxy logging, which goes to stderr.
    stdio: "inherit",
    // Its own process group, so that ending the run reaches every process
    // the child started and not only the child itself.
    detached: true,
  });

  try {
    // The idle clock starts with the child, not with the proxy.
    forwardedAt = now();
    const outcome = await supervise(child, {
      timeoutMs: clock.timeoutMs,
      idleMs: clock.idleMs,
      lastForward: () => forwardedAt,
      now,
      every,
    });
    if (outcome.reason === undefined) return outcome.code;
    process.stderr.write(`[run] reason=${outcome.reason}\n`);
    return EXIT_ROUTE;
  } finally {
    await close();
  }
}

if (require.main === module) {
  main(process.argv.slice(2))
    .then((code) => { process.exitCode = code; })
    .catch((err) => {
      process.stderr.write(`[run] ${err.message}\n`);
      process.exitCode = EXIT_CONFIG_ERROR;
    });
}

module.exports = {
  main,
  validateArgv,
  resolveModel,
  buildChildEnv,
  resolveExitCode,
  EXIT_CONFIG_ERROR,
  EXIT_ROUTE,
};
