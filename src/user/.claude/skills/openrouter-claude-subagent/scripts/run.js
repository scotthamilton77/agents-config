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

const { spawn } = require("child_process");
const path = require("path");
const proxy = require("./proxy.js");

/** Launcher-level failure (bad config), distinct from any `claude` exit code. */
const EXIT_CONFIG_ERROR = 78;

/** Build the child environment. The launcher owns every variable that decides
 *  WHERE the traffic goes, so a caller cannot half-configure the redirect and
 *  silently bill the wrong account. */
function buildChildEnv(parentEnv, proxyUrl) {
  const apiKey = parentEnv.OPENROUTER_API_KEY;
  if (!apiKey) {
    throw new Error(
      "OPENROUTER_API_KEY is not set. This launcher does not create or store " +
      "credentials — export the key, or ask where to find it."
    );
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
  const { port, close } = await proxy.start({ port: 0 });
  const proxyUrl = `http://127.0.0.1:${port}`;

  let env;
  try {
    env = buildChildEnv(process.env, proxyUrl);
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

module.exports = { main, buildChildEnv, resolveExitCode, EXIT_CONFIG_ERROR };
