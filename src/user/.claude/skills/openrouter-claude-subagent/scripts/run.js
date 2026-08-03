#!/usr/bin/env node
// Launcher for an OpenRouter-backed `claude` subagent.
//
// Starts the SSE-repair proxy IN-PROCESS on a kernel-assigned port, spawns
// `claude` against it, forwards every CLI argument through, and exits with
// the child's status.
//
// The proxy runs in-process rather than as a spawned sibling on purpose: the
// listener dies with this process no matter how it dies. A spawn-plus-trap
// design only cleans up if the wrapper survives long enough to run the trap,
// and gets no say at all under SIGKILL — leaving an orphaned proxy squatting
// a port, which poisons every later run with nobody watching.
//
// Usage:
//   node run.js --model <id> --effort <level> --permission-mode dontAsk \
//               --allowedTools Read Grep -p "<prompt>"
//
// All four of those flags are required — see REQUIRED_FLAGS for why each one
// is refused rather than defaulted. Everything else is passed through verbatim.

const { spawn } = require("child_process");
const path = require("path");
const proxy = require("./proxy.js");

/** Launcher-level failure (bad config), distinct from any `claude` exit code. */
const EXIT_CONFIG_ERROR = 78;

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

/** Check argv for the required flags, accepting both `--flag v` and `--flag=v`.
 *  @returns {string|null} a message naming every missing flag, or null if none. */
function validateArgv(argv) {
  const present = new Set(
    argv.filter((arg) => arg.startsWith("--")).map((arg) => arg.split("=", 1)[0])
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
  const values = [];
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--model") {
      const next = argv[i + 1];
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

async function main(argv) {
  // Before the proxy binds anything: a bad invocation should cost no listener.
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

  const { port, close } = await proxy.start({ port: 0, pinnedModel: model });
  const proxyUrl = `http://127.0.0.1:${port}`;

  let env;
  try {
    env = buildChildEnv(process.env, proxyUrl, model);
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
  });

  // Forward interactive signals so the child shuts down before this process
  // does, rather than being orphaned against a proxy that is about to vanish.
  const forward = (sig) => child.kill(sig);
  process.on("SIGINT", forward);
  process.on("SIGTERM", forward);

  try {
    return await new Promise((resolve, reject) => {
      child.on("error", (err) => {
        reject(
          err.code === "ENOENT"
            ? new Error("`claude` was not found on PATH.")
            : err
        );
      });
      child.on("exit", (code, signal) => resolve(resolveExitCode(code, signal)));
    });
  } finally {
    process.off("SIGINT", forward);
    process.off("SIGTERM", forward);
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
};
