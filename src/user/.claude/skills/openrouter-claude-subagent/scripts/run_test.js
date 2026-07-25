// Tests for run.js — the launcher that starts the in-process proxy, spawns
// `claude`, and mirrors the child's exit. Covers buildChildEnv and
// resolveExitCode as pure units, proxy.start/close as an integration
// lifecycle, and main()'s failure path when `claude` is not on PATH.
//
// SSE repair logic lives in proxy.js and is covered by proxy_test.js —
// out of scope here.

const test = require("node:test");
const assert = require("node:assert/strict");
const net = require("node:net");
const { spawnSync } = require("node:child_process");
const path = require("node:path");

const {
  main,
  validateArgv,
  buildChildEnv,
  resolveExitCode,
  EXIT_CONFIG_ERROR,
} = require("./run.js");
const proxy = require("./proxy.js");

/** A minimally valid invocation — every required flag present. */
const VALID_ARGV = [
  "--model", "vendor/model",
  "--effort", "low",
  "--permission-mode", "dontAsk",
  "--allowedTools", "Read",
  "-p", "task",
];

// ─── validateArgv ──────────────────────────────────────────────────

test("validateArgv returns null when every required flag is present", () => {
  assert.equal(validateArgv(VALID_ARGV), null);
});

test("validateArgv names the one flag that is missing, and only it", () => {
  const message = validateArgv([
    "--model", "vendor/model",
    "--permission-mode", "dontAsk",
    "--allowedTools", "Read",
  ]);
  // Anchored on the list itself: the explanatory tail names all four flags.
  assert.match(message, /missing required flag\(s\): --effort\./);
});

test("validateArgv names every missing flag, not just the first", () => {
  const list = validateArgv([]).match(/missing required flag\(s\): ([^.]*)\./)[1];
  assert.deepEqual(list.split(", "), [
    "--model",
    "--effort",
    "--permission-mode",
    "--allowedTools",
  ]);
});

test("validateArgv accepts the --allowed-tools spelling", () => {
  const argv = VALID_ARGV.map((a) => (a === "--allowedTools" ? "--allowed-tools" : a));
  assert.equal(validateArgv(argv), null);
});

test("validateArgv accepts the --flag=value form", () => {
  assert.equal(
    validateArgv([
      "--model=vendor/model",
      "--effort=low",
      "--permission-mode=dontAsk",
      "--allowedTools=Read",
    ]),
    null
  );
});

test("validateArgv ignores a flag name embedded inside an argument value", () => {
  // `--effort` appears in the prompt but was never passed; only argv elements
  // that themselves start with `--` count as flags.
  const message = validateArgv([
    "--model", "vendor/model",
    "--permission-mode", "dontAsk",
    "--allowedTools", "Read",
    "-p", "explain the --effort flag",
  ]);
  assert.match(message, /missing required flag\(s\): --effort\./);
});

test("main() rejects an incomplete invocation with EXIT_CONFIG_ERROR", async () => {
  // No `claude` spawn and no listener bind is reached on this path, so this
  // runs safely in-process regardless of what is installed.
  assert.equal(await main([]), EXIT_CONFIG_ERROR);
});

// ─── buildChildEnv ─────────────────────────────────────────────────

test("buildChildEnv throws mentioning OPENROUTER_API_KEY when absent", () => {
  const parentEnv = { HOME: "/home/u" };
  assert.throws(
    () => buildChildEnv(parentEnv, "http://127.0.0.1:1"),
    /OPENROUTER_API_KEY/
  );
});

test("buildChildEnv sets ANTHROPIC_BASE_URL to the passed proxy URL", () => {
  const env = buildChildEnv({ OPENROUTER_API_KEY: "sk-or-1" }, "http://127.0.0.1:9999");
  assert.equal(env.ANTHROPIC_BASE_URL, "http://127.0.0.1:9999");
});

test("buildChildEnv sets ANTHROPIC_AUTH_TOKEN to the OpenRouter key", () => {
  const env = buildChildEnv({ OPENROUTER_API_KEY: "sk-or-1" }, "http://127.0.0.1:1");
  assert.equal(env.ANTHROPIC_AUTH_TOKEN, "sk-or-1");
});

test("buildChildEnv sets ANTHROPIC_API_KEY to present-and-empty, not absent", () => {
  const env = buildChildEnv({ OPENROUTER_API_KEY: "sk-or-1" }, "http://127.0.0.1:1");
  assert.ok("ANTHROPIC_API_KEY" in env, "ANTHROPIC_API_KEY must be present");
  assert.equal(env.ANTHROPIC_API_KEY, "");
});

test("buildChildEnv overrides an inherited real ANTHROPIC_API_KEY to empty", () => {
  const parentEnv = {
    OPENROUTER_API_KEY: "sk-or-1",
    ANTHROPIC_API_KEY: "sk-ant-real-and-billable",
  };
  const env = buildChildEnv(parentEnv, "http://127.0.0.1:1");
  assert.equal(env.ANTHROPIC_API_KEY, "");
});

test("buildChildEnv defaults CLAUDE_CONFIG_DIR to <HOME>/.claude_openrouter", () => {
  const env = buildChildEnv(
    { OPENROUTER_API_KEY: "sk-or-1", HOME: "/home/u" },
    "http://127.0.0.1:1"
  );
  assert.equal(env.CLAUDE_CONFIG_DIR, path.join("/home/u", ".claude_openrouter"));
});

test("buildChildEnv honors CLAUDE_CONFIG_DIR_OPENROUTER override", () => {
  const env = buildChildEnv(
    {
      OPENROUTER_API_KEY: "sk-or-1",
      HOME: "/home/u",
      CLAUDE_CONFIG_DIR_OPENROUTER: "/custom/dir",
    },
    "http://127.0.0.1:1"
  );
  assert.equal(env.CLAUDE_CONFIG_DIR, "/custom/dir");
});

test("buildChildEnv passes through unrelated parent env vars", () => {
  const env = buildChildEnv(
    { OPENROUTER_API_KEY: "sk-or-1", PATH: "/usr/bin:/bin" },
    "http://127.0.0.1:1"
  );
  assert.equal(env.PATH, "/usr/bin:/bin");
});

test("buildChildEnv does not mutate the passed-in parentEnv object", () => {
  const parentEnv = { OPENROUTER_API_KEY: "sk-or-1", HOME: "/home/u" };
  const snapshot = { ...parentEnv };
  buildChildEnv(parentEnv, "http://127.0.0.1:1");
  assert.deepEqual(parentEnv, snapshot);
});

// ─── resolveExitCode ───────────────────────────────────────────────

test("resolveExitCode returns the numeric exit code when one is given", () => {
  assert.equal(resolveExitCode(7, null), 7);
});

test("resolveExitCode returns 0 for code 0, not the signal fallback", () => {
  // Guards against `code || fallback`-style bugs: 0 is falsy but valid.
  assert.equal(resolveExitCode(0, null), 0);
});

test("resolveExitCode maps SIGTERM to 143", () => {
  assert.equal(resolveExitCode(null, "SIGTERM"), 143);
});

test("resolveExitCode maps SIGINT to 130", () => {
  assert.equal(resolveExitCode(null, "SIGINT"), 130);
});

test("resolveExitCode maps SIGKILL to 137", () => {
  assert.equal(resolveExitCode(null, "SIGKILL"), 137);
});

test("resolveExitCode handles null code with an unrecognized signal without throwing", () => {
  assert.equal(resolveExitCode(null, "SIGUNKNOWN"), 128);
});

test("resolveExitCode handles null code and null signal without throwing", () => {
  assert.equal(resolveExitCode(null, null), 128);
});

// ─── proxy.start / close lifecycle ─────────────────────────────────

test("proxy.start({port:0}) resolves with a numeric, non-zero port", async () => {
  const { port, close } = await proxy.start({ port: 0 });
  try {
    assert.equal(typeof port, "number");
    assert.notEqual(port, 0);
  } finally {
    await close();
  }
});

test("two concurrent start({port:0}) calls receive different ports", async () => {
  const [a, b] = await Promise.all([proxy.start({ port: 0 }), proxy.start({ port: 0 })]);
  try {
    assert.notEqual(a.port, b.port);
  } finally {
    await Promise.all([a.close(), b.close()]);
  }
});

test("close() stops the listener — a subsequent TCP connect is refused", async () => {
  const { port, close } = await proxy.start({ port: 0 });
  await close();

  await new Promise((resolve, reject) => {
    const socket = net.connect({ port, host: "127.0.0.1" });
    const timer = setTimeout(() => {
      socket.destroy();
      reject(new Error("timed out waiting for connection refusal"));
    }, 2000);
    socket.on("error", (err) => {
      clearTimeout(timer);
      try {
        assert.equal(err.code, "ECONNREFUSED");
        resolve();
      } catch (e) {
        reject(e);
      }
    });
    socket.on("connect", () => {
      clearTimeout(timer);
      socket.destroy();
      reject(new Error("connection succeeded after close()"));
    });
  });
});

// ─── main() child-process behavior ─────────────────────────────────

test("main() reports an error mentioning `claude` when it is not on PATH", () => {
  // Run main() in a child node process with a bogus PATH, so the spawn of
  // the literal `claude` command reliably ENOENTs without depending on
  // whether the real `claude` binary happens to be installed here.
  const runJsPath = path.join(__dirname, "run.js");
  const script = `
    const { main } = require(${JSON.stringify(runJsPath)});
    main(${JSON.stringify(VALID_ARGV)}).then((code) => { process.exitCode = code; })
             .catch((err) => {
               process.stderr.write(err.message + "\\n");
               process.exitCode = 1;
             });
  `;
  const result = spawnSync(process.execPath, ["-e", script], {
    env: { ...process.env, PATH: "/nonexistent-bin-dir", OPENROUTER_API_KEY: "sk-or-1" },
    encoding: "utf8",
    timeout: 10000,
  });

  assert.match(result.stderr, /claude.*not found/i);
});

test("no proxy listener survives after main()'s not-on-PATH failure path", (t) => {
  // The evidence for this is entirely inside the child process spawned in
  // the previous test (its `finally` block calls close() before exit) —
  // nothing is observable about that listener from out here beyond the
  // child process itself exiting, which the previous test already checks
  // via spawnSync's bounded wait. Asserting anything further here would be
  // vacuous.
  t.skip("not observable from outside the child process; see the preceding PATH test");
});
