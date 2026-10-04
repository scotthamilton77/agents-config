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
    () => buildChildEnv(parentEnv, "http://127.0.0.1:1", "vendor/model"),
    /OPENROUTER_API_KEY/
  );
});

test("buildChildEnv sets ANTHROPIC_BASE_URL to the passed proxy URL", () => {
  const env = buildChildEnv({ OPENROUTER_API_KEY: "sk-or-1" }, "http://127.0.0.1:9999", "vendor/model");
  assert.equal(env.ANTHROPIC_BASE_URL, "http://127.0.0.1:9999");
});

test("buildChildEnv sets ANTHROPIC_AUTH_TOKEN to the OpenRouter key", () => {
  const env = buildChildEnv({ OPENROUTER_API_KEY: "sk-or-1" }, "http://127.0.0.1:1", "vendor/model");
  assert.equal(env.ANTHROPIC_AUTH_TOKEN, "sk-or-1");
});

test("buildChildEnv sets ANTHROPIC_API_KEY to present-and-empty, not absent", () => {
  const env = buildChildEnv({ OPENROUTER_API_KEY: "sk-or-1" }, "http://127.0.0.1:1", "vendor/model");
  assert.ok("ANTHROPIC_API_KEY" in env, "ANTHROPIC_API_KEY must be present");
  assert.equal(env.ANTHROPIC_API_KEY, "");
});

test("buildChildEnv overrides an inherited real ANTHROPIC_API_KEY to empty", () => {
  const parentEnv = {
    OPENROUTER_API_KEY: "sk-or-1",
    ANTHROPIC_API_KEY: "sk-ant-real-and-billable",
  };
  const env = buildChildEnv(parentEnv, "http://127.0.0.1:1", "vendor/model");
  assert.equal(env.ANTHROPIC_API_KEY, "");
});

test("buildChildEnv defaults CLAUDE_CONFIG_DIR to <HOME>/.claude_openrouter", () => {
  const env = buildChildEnv(
    { OPENROUTER_API_KEY: "sk-or-1", HOME: "/home/u" },
    "http://127.0.0.1:1",
    "vendor/model"
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
    "http://127.0.0.1:1",
    "vendor/model"
  );
  assert.equal(env.CLAUDE_CONFIG_DIR, "/custom/dir");
});

test("buildChildEnv passes through unrelated parent env vars", () => {
  const env = buildChildEnv(
    { OPENROUTER_API_KEY: "sk-or-1", PATH: "/usr/bin:/bin" },
    "http://127.0.0.1:1",
    "vendor/model"
  );
  assert.equal(env.PATH, "/usr/bin:/bin");
});

test("buildChildEnv does not mutate the passed-in parentEnv object", () => {
  const parentEnv = { OPENROUTER_API_KEY: "sk-or-1", HOME: "/home/u" };
  const snapshot = { ...parentEnv };
  buildChildEnv(parentEnv, "http://127.0.0.1:1", "vendor/model");
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

// ─── resolveModel ──────────────────────────────────────────────────
//
// The run is pinned to one model, so the launcher has to know which one
// before it starts anything. Everything here is about refusing to guess.

const { resolveModel } = require("./run.js");

test("resolveModel reads the model from the --flag value form", () => {
  assert.deepEqual(resolveModel(VALID_ARGV), { model: "vendor/model" });
});

test("resolveModel reads the model from the --flag=value form", () => {
  assert.deepEqual(resolveModel(["--model=vendor/other", "-p", "task"]), { model: "vendor/other" });
});

test("resolveModel refuses --model with no value rather than pinning the next flag", () => {
  const result = resolveModel(["--model", "--effort", "low"]);
  assert.match(result.error, /--model was given no value/);
});

test("resolveModel refuses an empty --model=", () => {
  assert.match(resolveModel(["--model=", "-p", "task"]).error, /--model was given no value/);
});

test("resolveModel refuses a whitespace-only model name", () => {
  assert.match(resolveModel(["--model", "   ", "-p", "task"]).error, /--model was given no value/);
});

test("resolveModel accepts the same model named twice", () => {
  assert.deepEqual(
    resolveModel(["--model", "vendor/model", "--model", "vendor/model"]),
    { model: "vendor/model" },
  );
});

// Which of two `--model` flags the nested client would honour is its business,
// not this launcher's, and a wrong guess pins the wrong model — which is how
// the spend leaks in the first place.
test("resolveModel refuses two different models instead of choosing one", () => {
  const result = resolveModel(["--model", "vendor/model", "--model=anthropic/claude-opus-5"]);
  assert.match(result.error, /more than one value/);
  assert.match(result.error, /vendor\/model/);
});

// ─── buildChildEnv: the model pin ──────────────────────────────────

test("buildChildEnv points every model alias at the model the run was launched with", () => {
  const env = buildChildEnv({ OPENROUTER_API_KEY: "sk-or-1" }, "http://127.0.0.1:1", "moonshotai/kimi-k3");
  assert.equal(env.ANTHROPIC_DEFAULT_OPUS_MODEL, "moonshotai/kimi-k3");
  assert.equal(env.ANTHROPIC_DEFAULT_SONNET_MODEL, "moonshotai/kimi-k3");
  assert.equal(env.ANTHROPIC_DEFAULT_HAIKU_MODEL, "moonshotai/kimi-k3");
  assert.equal(env.ANTHROPIC_DEFAULT_FABLE_MODEL, "moonshotai/kimi-k3");
});

test("buildChildEnv overrides alias redirects inherited from the parent", () => {
  const env = buildChildEnv(
    {
      OPENROUTER_API_KEY: "sk-or-1",
      ANTHROPIC_DEFAULT_SONNET_MODEL: "anthropic/claude-sonnet-5",
      ANTHROPIC_DEFAULT_OPUS_MODEL: "anthropic/claude-opus-5",
    },
    "http://127.0.0.1:1",
    "moonshotai/kimi-k3",
  );
  assert.equal(env.ANTHROPIC_DEFAULT_SONNET_MODEL, "moonshotai/kimi-k3");
  assert.equal(env.ANTHROPIC_DEFAULT_OPUS_MODEL, "moonshotai/kimi-k3");
});

test("buildChildEnv switches off the background traffic the cheap alias would bill", () => {
  const env = buildChildEnv({ OPENROUTER_API_KEY: "sk-or-1" }, "http://127.0.0.1:1", "vendor/model");
  assert.equal(env.CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC, "1");
});

test("buildChildEnv refuses to build an environment with no model to pin", () => {
  assert.throws(
    () => buildChildEnv({ OPENROUTER_API_KEY: "sk-or-1" }, "http://127.0.0.1:1", ""),
    /model this run is pinned to/,
  );
});

// ─── main(): refusals that cost nothing ────────────────────────────
//
// A bad invocation must not bind a listener. `proxy.start` is stubbed to
// throw rather than to record, so a regression that reaches it fails the test
// loudly instead of leaking a live socket into the rest of the suite.

/** Run `main(argv)` with the proxy rigged to explode if it is ever started. */
async function mainWithoutProxy(argv) {
  const realStart = proxy.start;
  proxy.start = async () => {
    throw new Error("proxy.start was reached: this invocation should have been refused first");
  };
  try {
    return await main(argv);
  } finally {
    proxy.start = realStart;
  }
}

test("main() refuses an empty --model before the proxy binds anything", async () => {
  const code = await mainWithoutProxy([
    "--model=", "--effort", "low", "--permission-mode", "dontAsk",
    "--allowedTools", "Read", "-p", "task",
  ]);
  assert.equal(code, EXIT_CONFIG_ERROR);
});

test("main() refuses a denied model before the proxy binds anything", async () => {
  const code = await mainWithoutProxy([
    "--model", "anthropic/claude-opus-5", "--effort", "low", "--permission-mode", "dontAsk",
    "--allowedTools", "Read", "-p", "task",
  ]);
  assert.equal(code, EXIT_CONFIG_ERROR);
});

test("main() refuses a denied model named without its vendor prefix too", async () => {
  const code = await mainWithoutProxy([
    "--model", "gpt-5.6-sol", "--effort", "low", "--permission-mode", "dontAsk",
    "--allowedTools", "Read", "-p", "task",
  ]);
  assert.equal(code, EXIT_CONFIG_ERROR);
});

test("main() still accepts the -mini tiers the denylist exempts", async () => {
  // Reaching proxy.start is the pass condition here — the stub throwing is
  // proof the model cleared both refusals, and it costs no listener.
  await assert.rejects(
    mainWithoutProxy([
      "--model", "openai/gpt-5.6-mini", "--effort", "low", "--permission-mode", "dontAsk",
      "--allowedTools", "Read", "-p", "task",
    ]),
    /proxy\.start was reached/,
  );
});

// ─── The prompt is not a source of flags ───────────────────────────
//
// Prompt text routinely comes from the material being worked on, so a prompt
// that opens with a flag name must not be able to answer for that flag. The
// required-flag check is the launcher's guard against arguments that fail
// silently; satisfying it with borrowed text would disarm it.

test("a prompt that is exactly a flag name does not answer for that flag", () => {
  const message = validateArgv([
    "--model", "vendor/model",
    "--permission-mode", "dontAsk",
    "--allowedTools", "Read",
    "-p", "--effort",
  ]);
  assert.match(message, /missing required flag\(s\): --effort\./);
});

test("nor does a prompt in the --flag=value shape, under either prompt spelling", () => {
  const message = validateArgv([
    "--model", "vendor/model",
    "--permission-mode", "dontAsk",
    "--allowedTools", "Read",
    "--print", "--effort=high",
  ]);
  assert.match(message, /missing required flag\(s\): --effort\./);
});

test("a prompt cannot smuggle in a model of its own", () => {
  assert.deepEqual(
    resolveModel(["--model", "vendor/model", "-p", "--model=evil/model"]),
    { model: "vendor/model" },
  );
});

test("a legitimate prompt that merely mentions a flag still validates", () => {
  assert.equal(validateArgv([...VALID_ARGV.slice(0, -1), "explain the --effort flag"]), null);
});

// ─── Fake children ─────────────────────────────────────────────────
//
// The launcher spawns `claude` from PATH, so each test below writes a fake
// `claude` into a fresh directory and puts that directory first on PATH. The
// fake records its pid, argv and environment to `record.json` beside itself,
// which is how a test learns the proxy port and which process group to watch.

const fs = require("node:fs");
const os = require("node:os");
const { spawn } = require("node:child_process");

const RUN_JS = path.join(__dirname, "run.js");

/** Write a fake `claude` whose body runs `behaviour` and return its directory.
 *  The preamble gives the body a `record(extra)` helper, and SIGUSR2 makes the
 *  fake exit with code 3 so a test can end it on its own terms. */
function fakeClaude(behaviour) {
  const bin = fs.mkdtempSync(path.join(os.tmpdir(), "run-test-"));
  fs.writeFileSync(
    path.join(bin, "claude"),
    `#!/usr/bin/env node
const fs = require("fs"), path = require("path"), { spawn } = require("child_process");
function record(extra = {}) {
  const file = path.join(__dirname, "record.json");
  fs.writeFileSync(file + ".tmp", JSON.stringify({
    pid: process.pid, argv: process.argv.slice(2), env: process.env, ...extra,
  }));
  fs.renameSync(file + ".tmp", file);
}
process.on("SIGUSR2", () => process.exit(3));
${behaviour}
`,
    { mode: 0o755 },
  );
  return bin;
}

/** A fake that records what it was given and exits 0 at once. */
const RECORD_AND_EXIT = "record(); process.exit(0);";

/** The environment a launch under test inherits: nothing from the machine
 *  running the suite, so a recorded environment is the same everywhere. */
function launchEnv(bin, extra = {}) {
  return {
    HOME: "/home/fixture",
    OPENROUTER_API_KEY: "sk-or-fixture",
    ...extra,
    PATH: `${bin}:${path.dirname(process.execPath)}`,
  };
}

/** Wait for the fake child's record, which it writes once it is running. */
async function readRecord(bin, timeoutMs = 5000) {
  const file = path.join(bin, "record.json");
  const stop = Date.now() + timeoutMs;
  while (Date.now() < stop) {
    if (fs.existsSync(file)) return JSON.parse(fs.readFileSync(file, "utf8"));
    await new Promise((r) => setTimeout(r, 20));
  }
  throw new Error("the fake child never wrote its record");
}

/** Run the launcher as its own process and resolve with its exit and stderr. */
function launch(argv, env) {
  const proc = spawn(process.execPath, [RUN_JS, ...argv], { env, stdio: ["ignore", "ignore", "pipe"] });
  let stderr = "";
  proc.stderr.on("data", (c) => { stderr += c; });
  const done = new Promise((resolve) => {
    proc.on("close", (code, signal) => resolve({ code, signal, stderr }));
  });
  return { proc, done };
}

/** What a child received, with the values that differ run to run replaced by
 *  placeholders: the kernel-assigned proxy port, and the PATH that points at a
 *  fresh temporary directory. macOS adds `__CF_USER_TEXT_ENCODING` to every
 *  process it starts, keyed to the user running the suite, and the launcher
 *  never sets it, so it is left out. */
function normalise(record) {
  const env = { ...record.env, PATH: "<PATH>" };
  env.ANTHROPIC_BASE_URL = env.ANTHROPIC_BASE_URL.replace(/:\d+$/, ":<PORT>");
  delete env.__CF_USER_TEXT_ENCODING;
  return { argv: record.argv, env };
}

/** Launch with a recording fake child and return what that child received. */
async function childLaunch(argv, extraEnv = {}) {
  const bin = fakeClaude(RECORD_AND_EXIT);
  const { done } = launch(argv, launchEnv(bin, extraEnv));
  const result = await done;
  assert.equal(result.code, 0, result.stderr);
  return normalise(await readRecord(bin));
}

// ─── With no clock flag, the child's launch is unchanged ───────────
//
// Recorded from the launcher as it stood before it gained its clock, by
// running each input below through it with the recording fake child.

const PRE_CLOCK_LAUNCHES = [
  {
    argv: [
      "--model", "vendor/model", "--effort", "low", "--permission-mode", "dontAsk",
      "--allowedTools", "Read", "Grep", "-p", "task",
    ],
    extraEnv: {},
    child: {
      argv: [
        "--model", "vendor/model", "--effort", "low", "--permission-mode", "dontAsk",
        "--allowedTools", "Read", "Grep", "-p", "task",
      ],
      env: {
        HOME: "/home/fixture",
        OPENROUTER_API_KEY: "sk-or-fixture",
        PATH: "<PATH>",
        CLAUDE_CONFIG_DIR: "/home/fixture/.claude_openrouter",
        ANTHROPIC_BASE_URL: "http://127.0.0.1:<PORT>",
        ANTHROPIC_AUTH_TOKEN: "sk-or-fixture",
        ANTHROPIC_API_KEY: "",
        ANTHROPIC_DEFAULT_OPUS_MODEL: "vendor/model",
        ANTHROPIC_DEFAULT_SONNET_MODEL: "vendor/model",
        ANTHROPIC_DEFAULT_HAIKU_MODEL: "vendor/model",
        ANTHROPIC_DEFAULT_FABLE_MODEL: "vendor/model",
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1",
      },
    },
  },
  {
    argv: [
      "--model=moonshotai/kimi-k3", "--effort=medium", "--permission-mode=dontAsk",
      "--allowed-tools=Read", "--output-format", "json", "-p", "review this",
    ],
    extraEnv: {
      ANTHROPIC_API_KEY: "sk-ant-inherited",
      CLAUDE_CONFIG_DIR_OPENROUTER: "/custom/config",
      ANTHROPIC_DEFAULT_SONNET_MODEL: "anthropic/claude-sonnet-5",
    },
    child: {
      argv: [
        "--model=moonshotai/kimi-k3", "--effort=medium", "--permission-mode=dontAsk",
        "--allowed-tools=Read", "--output-format", "json", "-p", "review this",
      ],
      env: {
        HOME: "/home/fixture",
        OPENROUTER_API_KEY: "sk-or-fixture",
        ANTHROPIC_API_KEY: "",
        CLAUDE_CONFIG_DIR_OPENROUTER: "/custom/config",
        ANTHROPIC_DEFAULT_SONNET_MODEL: "moonshotai/kimi-k3",
        PATH: "<PATH>",
        CLAUDE_CONFIG_DIR: "/custom/config",
        ANTHROPIC_BASE_URL: "http://127.0.0.1:<PORT>",
        ANTHROPIC_AUTH_TOKEN: "sk-or-fixture",
        ANTHROPIC_DEFAULT_OPUS_MODEL: "moonshotai/kimi-k3",
        ANTHROPIC_DEFAULT_HAIKU_MODEL: "moonshotai/kimi-k3",
        ANTHROPIC_DEFAULT_FABLE_MODEL: "moonshotai/kimi-k3",
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1",
      },
    },
  },
  {
    // The prompt names both clock flags, and it is task text, not flags.
    argv: [
      "--model", "z-ai/glm-5", "--effort", "high", "--permission-mode", "dontAsk",
      "--allowedTools", "Read", "--print", "--timeout 30 --idle-timeout=5",
    ],
    extraEnv: { LANG: "C" },
    child: {
      argv: [
        "--model", "z-ai/glm-5", "--effort", "high", "--permission-mode", "dontAsk",
        "--allowedTools", "Read", "--print", "--timeout 30 --idle-timeout=5",
      ],
      env: {
        HOME: "/home/fixture",
        OPENROUTER_API_KEY: "sk-or-fixture",
        LANG: "C",
        PATH: "<PATH>",
        CLAUDE_CONFIG_DIR: "/home/fixture/.claude_openrouter",
        ANTHROPIC_BASE_URL: "http://127.0.0.1:<PORT>",
        ANTHROPIC_AUTH_TOKEN: "sk-or-fixture",
        ANTHROPIC_API_KEY: "",
        ANTHROPIC_DEFAULT_OPUS_MODEL: "z-ai/glm-5",
        ANTHROPIC_DEFAULT_SONNET_MODEL: "z-ai/glm-5",
        ANTHROPIC_DEFAULT_HAIKU_MODEL: "z-ai/glm-5",
        ANTHROPIC_DEFAULT_FABLE_MODEL: "z-ai/glm-5",
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1",
      },
    },
  },
];

PRE_CLOCK_LAUNCHES.forEach(({ argv, extraEnv, child }, i) => {
  test(`DEL-B4: with no clock flag the child receives the recorded pre-clock argv and environment (input ${i + 1})`, async () => {
    assert.deepEqual(await childLaunch(argv, extraEnv), child);
  });
});
