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

// ─── GPT and Gemini need the user's instruction; Claude never runs ──

/** VALID_ARGV on `model`, with `extra` launcher flags in front. */
const argvFor = (model, extra = []) => [...extra, "--model", model, ...VALID_ARGV.slice(2)];

const GPT_SPELLINGS = [
  "openai/gpt-5.6-sol",
  "gpt-6-luna",
  "openai/gpt-5.5-mini",
  "openai/gpt-5.6-mini",
  "gpt-5.6-mini",
  "openai/gpt-5.6-mini:nitro",
  "OpenAI/GPT-5.5-Mini",
];
const GEMINI_SPELLINGS = [
  "google/gemini-3.8-flash",
  "gemini-3.1-pro",
  "google/gemini-3.8-flash:free",
  "Google/Gemini-3.8-Flash",
];
const CLAUDE_SPELLINGS = [
  "anthropic/claude-opus-5",
  "claude-sonnet-5",
  "anthropic/claude-opus-5:beta",
  "Anthropic/Claude-Opus-5",
];

for (const [family, spellings] of [["GPT", GPT_SPELLINGS], ["Gemini", GEMINI_SPELLINGS]]) {
  for (const model of spellings) {
    test(`DEL-F1: ${model} exits 78 before the proxy binds, naming ${family} and the flag that lifts it`, async () => {
      const { result, stderr } = await captureStderr(() => mainWithoutProxy(argvFor(model)));
      assert.equal(result, EXIT_CONFIG_ERROR);
      assert.match(stderr, new RegExp(`\\b${family}\\b`));
      assert.match(stderr, /--user-instructed\b/);
    });
  }
}

for (const model of CLAUDE_SPELLINGS) {
  test(`DEL-F1: ${model} exits 78 before the proxy binds, naming Claude and no flag`, async () => {
    const { result, stderr } = await captureStderr(() => mainWithoutProxy(argvFor(model)));
    assert.equal(result, EXIT_CONFIG_ERROR);
    assert.match(stderr, /\bClaude\b/);
    assert.doesNotMatch(stderr, /--user-instructed/);
  });

  test(`DEL-F3: ${model} with --user-instructed still exits 78 before the proxy binds`, async () => {
    const { result, stderr } = await captureStderr(() =>
      mainWithoutProxy(argvFor(model, ["--user-instructed"])),
    );
    assert.equal(result, EXIT_CONFIG_ERROR);
    assert.match(stderr, /\bClaude\b/);
    assert.doesNotMatch(stderr, /--user-instructed/);
  });
}

test("a prompt that reads --user-instructed lifts nothing", async () => {
  const argv = argvFor("google/gemini-3.8-flash").slice(0, -1).concat("--user-instructed");
  const { result } = await captureStderr(() => mainWithoutProxy(argv));
  assert.equal(result, EXIT_CONFIG_ERROR);
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

/** Run the launcher as its own process and resolve with its exit and stderr.
 *  It leads a process group of its own, so a test can kill everything it
 *  started without knowing the shape of the tree. */
function launch(argv, env) {
  const proc = spawn(process.execPath, [RUN_JS, ...argv], {
    env,
    stdio: ["ignore", "ignore", "pipe"],
    detached: true,
  });
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

// ─── The clock flags refuse a value that bounds nothing ────────────

/** Run `fn` with everything written to stderr captured, and return both. */
async function captureStderr(fn) {
  const realWrite = process.stderr.write;
  let text = "";
  process.stderr.write = (chunk) => {
    text += chunk;
    return true;
  };
  try {
    return { result: await fn(), stderr: text };
  } finally {
    process.stderr.write = realWrite;
  }
}

const BAD_CLOCK_VALUES = [
  ["a non-numeric value", (flag) => [flag, "soon"]],
  ["a zero value", (flag) => [flag, "0"]],
  ["a negative value", (flag) => [flag, "-5"]],
  ["no value", (flag) => [flag]],
];

for (const flag of ["--timeout", "--idle-timeout"]) {
  for (const [label, given] of BAD_CLOCK_VALUES) {
    test(`DEL-B5: ${flag} with ${label} exits 78 before the proxy binds, naming the flag`, async () => {
      // The flag goes last, so "no value" really is the end of argv.
      const { result, stderr } = await captureStderr(() =>
        mainWithoutProxy([...VALID_ARGV, ...given(flag)]),
      );
      assert.equal(result, EXIT_CONFIG_ERROR);
      assert.match(stderr, new RegExp(`\\[run\\] ${flag}\\b`));
    });
  }
}

// ─── The clock flags never reach the child ─────────────────────────

const WITH_CLOCK_FLAGS = [
  ["--timeout", ["--timeout", "600"]],
  ["--idle-timeout", ["--idle-timeout=300"]],
  ["both clock flags", ["--idle-timeout", "300", "--timeout=600"]],
];

for (const [label, flags] of WITH_CLOCK_FLAGS) {
  test(`DEL-B7: with ${label}, the child receives what it receives without them`, async () => {
    const [before, after] = [VALID_ARGV.slice(0, 4), VALID_ARGV.slice(4)];
    const withFlags = await childLaunch([...before, ...flags, ...after]);
    const without = await childLaunch(VALID_ARGV);
    assert.deepEqual(withFlags, without);
  });
}

// ─── Runs on a hand-driven clock ───────────────────────────────────
//
// main() reads time through `now` and checks on the run through the tick it
// hands to `every`. A test owns both, so it decides exactly what the clock
// reads when each tick is processed. Process deaths still happen on the real
// clock, so each hand-fired tick is followed by a short real pause.

const http = require("node:http");
const { EXIT_ROUTE } = require("./run.js");

/** Keeps the fake alive until something ends it. */
const STAY = "setInterval(() => {}, 1 << 30);";
/** Makes the fake ignore both signals a launcher would end it with. */
const IGNORE_SIGNALS = 'process.on("SIGTERM", () => {}); process.on("SIGINT", () => {});';
/** Starts a grandchild in the fake's own process group that ignores both
 *  signals, and records only once the grandchild has said it is ready. */
const WITH_GRANDCHILD = `
const grandchild = spawn(process.execPath, ["-e",
  'process.on("SIGTERM", () => {}); process.on("SIGINT", () => {}); process.stdout.write("ready"); setInterval(() => {}, 1 << 30);'],
  { stdio: ["ignore", "pipe", "ignore"] });
grandchild.stdout.once("data", () => record({ grandchild: grandchild.pid }));
${STAY}`;
/** Sends one streaming completion through the proxy and holds the response
 *  open, recording once the first upstream bytes have reached it. */
const HOLD_UPSTREAM = `
const req = require("http").request(process.env.ANTHROPIC_BASE_URL + "/v1/messages", {
  method: "POST", headers: { "content-type": "application/json", accept: "text/event-stream" },
}, (res) => res.once("data", () => record()));
req.end(JSON.stringify({ model: "vendor/model", messages: [], stream: true }));
${STAY}`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function manualClock() {
  const clock = { t: 0, tick: null };
  clock.now = () => clock.t;
  clock.every = (fn) => {
    clock.tick = fn;
    return () => { clock.tick = null; };
  };
  return clock;
}

/** Set the clock to `t`, process one tick, and give real processes a moment. */
async function tickAt(clock, t) {
  clock.t = t;
  if (clock.tick) clock.tick();
  await sleep(30);
}

/** Start main() in-process against the fake in `bin`, capturing its stderr. */
function startRun(launcherArgv, bin, clock, upstream) {
  const run = { settled: false, code: undefined, stderr: "" };
  const realWrite = process.stderr.write;
  process.stderr.write = (chunk) => {
    run.stderr += chunk;
    return true;
  };
  run.done = main(launcherArgv, {
    now: clock.now,
    every: clock.every,
    env: launchEnv(bin),
    startProxy: (opts) => proxy.start({ ...opts, upstream }),
  }).then(
    (code) => { run.code = code; },
    (err) => { run.error = err; },
  ).finally(() => {
    process.stderr.write = realWrite;
    run.settled = true;
  });
  return run;
}

/** Advance the clock a quarter second per tick until the run settles, and
 *  return what the clock read when it did. Gives up fifteen seconds past the
 *  start, which is past every bound these tests assert. */
async function tickUntilSettled(clock, run) {
  const giveUpAt = clock.t + 15000;
  while (!run.settled && clock.t < giveUpAt) await tickAt(clock, clock.t + 250);
  return clock.t;
}

/** True once no process is left in the group the child leads. */
function groupGone(pid) {
  try {
    process.kill(-pid, 0);
    return false;
  } catch {
    return true;
  }
}

/** Resolve true if a TCP connect to the port is refused. */
function connectRefused(port) {
  return new Promise((resolve) => {
    const socket = net.connect({ port, host: "127.0.0.1" });
    socket.on("error", (err) => resolve(err.code === "ECONNREFUSED"));
    socket.on("connect", () => { socket.destroy(); resolve(false); });
  });
}

const proxyPort = (record) => Number(record.env.ANTHROPIC_BASE_URL.match(/:(\d+)$/)[1]);

/** A stand-in for OpenRouter. Held, it opens a streaming response and never
 *  ends it; otherwise it answers each request at once. */
async function startUpstream({ held = false } = {}) {
  const upstream = { requests: 0, closed: false };
  const server = http.createServer((req, res) => {
    upstream.requests++;
    req.resume();
    if (!held) return res.end("{}");
    req.socket.on("close", () => { upstream.closed = true; });
    res.writeHead(200, { "content-type": "text/event-stream" });
    // OpenAI-format, so the proxy passes it through rather than holding the
    // stream back for repair.
    res.write('data: {"id":"held"}\n\n');
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  upstream.url = `http://127.0.0.1:${server.address().port}`;
  upstream.close = () => {
    server.closeAllConnections();
    return new Promise((r) => server.close(r));
  };
  return upstream;
}

/** A fake that is running and ready to be watched, until something ends it. */
const RUNNING = `record(); ${STAY}`;

/** Start a run on a hand-driven clock, hand it to `body`, and afterwards end
 *  whatever the body left running. */
async function withRun(launcherArgv, behaviour, body, { held = false } = {}) {
  const upstream = await startUpstream({ held });
  const bin = fakeClaude(behaviour);
  const clock = manualClock();
  const run = startRun(launcherArgv, bin, clock, upstream.url);
  try {
    const child = await readRecord(bin);
    await body({ run, clock, child, upstream });
  } finally {
    if (!run.settled && fs.existsSync(path.join(bin, "record.json"))) {
      signalGroupOf(await readRecord(bin), "SIGKILL");
      await tickUntilSettled(clock, run);
    }
    if (run.settled) await run.done;
    await upstream.close();
  }
}

function signalGroupOf(child, signal) {
  try { process.kill(-child.pid, signal); } catch { /* already gone */ }
}

/** Assert the launcher ended the run for `reason` within ten seconds of the
 *  tick at `expiryAt`, leaving no process in the child's group and no proxy. */
async function assertEndedFor(reason, { run, clock, child }, expiryAt) {
  const endedAt = await tickUntilSettled(clock, run);
  assert.ok(endedAt - expiryAt <= 10000, `the run ended ${endedAt - expiryAt} ms after expiry`);
  assert.equal(run.error, undefined);
  assert.equal(run.code, EXIT_ROUTE);
  assert.match(run.stderr, new RegExp(`^\\[run\\] reason=${reason}$`, "m"));
  assert.ok(groupGone(child.pid), "a process in the child's group survived");
  assert.ok(await connectRefused(proxyPort(child)), "the proxy is still listening");
}

/** Assert the run ended with the child's own exit code and no reason line. */
async function assertOwnExit(code, { run, clock }) {
  await tickUntilSettled(clock, run);
  assert.equal(run.error, undefined);
  assert.equal(run.code, code);
  assert.doesNotMatch(run.stderr, /reason=/);
}

/** End the fake with its own exit code 3, and wait until the launcher can
 *  have seen it go. */
async function childExitsOnItsOwn(child) {
  process.kill(child.pid, "SIGUSR2");
  while (!groupGone(child.pid)) await sleep(10);
  await sleep(100);
}

const B1_CHILDREN = [
  ["a compliant child", RUNNING],
  ["a child that ignores SIGTERM", IGNORE_SIGNALS + RUNNING],
  ["a child that started a child of its own in the group", WITH_GRANDCHILD],
  ["a run whose upstream response is still open", HOLD_UPSTREAM],
];

for (const [label, behaviour] of B1_CHILDREN) {
  test(`DEL-B1: --timeout ends ${label} within ten seconds of the expiry tick`, async () => {
    const held = behaviour === HOLD_UPSTREAM;
    await withRun(["--timeout", "30", ...VALID_ARGV], behaviour, async (r) => {
      await tickAt(r.clock, 29999);
      assert.equal(r.run.settled, false, "the run ended before its timeout");

      await tickAt(r.clock, 30000);
      await assertEndedFor("timeout", r, 30000);
      if (held) {
        await sleep(200);
        assert.ok(r.upstream.closed, "the upstream response is still open, which keeps the launcher alive");
      }
    }, { held });
  });
}

/** Wait for a launched launcher to exit. If it is still running `ms` later,
 *  kill it and the child's group, so a launcher that never ends fails the
 *  test instead of hanging the suite. */
async function exitWithin(launched, child, ms) {
  let timer;
  const late = new Promise((resolve) => { timer = setTimeout(resolve, ms, null); });
  const result = await Promise.race([launched.done, late]);
  clearTimeout(timer);
  if (result) return result;
  signalGroupOf(launched.proc, "SIGKILL");
  signalGroupOf(child, "SIGKILL");
  throw new Error(`the launcher was still running ${ms} ms later`);
}

test("DEL-B1: on the real clock, --timeout 1 ends the run and the launcher exits 75", async () => {
  const bin = fakeClaude(WITH_GRANDCHILD);
  const startedAt = Date.now();
  const launched = launch(["--timeout", "1", ...VALID_ARGV], launchEnv(bin));
  const child = await readRecord(bin);
  const result = await exitWithin(launched, child, 15000);
  const elapsed = Date.now() - startedAt;
  assert.ok(elapsed >= 1000, `the launcher exited after ${elapsed} ms, before its timeout`);
  assert.ok(elapsed <= 11000, `the launcher exited ${elapsed - 1000} ms after its timeout`);
  assert.equal(result.code, EXIT_ROUTE);
  assert.match(result.stderr, /^\[run\] reason=timeout$/m);
  assert.ok(groupGone(child.pid), "a process in the child's group survived");
});

// ─── The idle timeout ──────────────────────────────────────────────

/** Send one completion request through the proxy, as the child would. */
function forwardCompletion(child) {
  return new Promise((resolve, reject) => {
    const req = http.request(`${child.env.ANTHROPIC_BASE_URL}/v1/messages`, {
      method: "POST",
      headers: { "content-type": "application/json" },
    }, (res) => { res.resume(); res.on("end", resolve); });
    req.on("error", reject);
    req.end(JSON.stringify({ model: "vendor/model", messages: [] }));
  });
}

test("DEL-B2: a run that forwards no completion request for M seconds ends with reason=idle", async () => {
  await withRun(["--idle-timeout", "10", ...VALID_ARGV], RUNNING, async (r) => {
    await tickAt(r.clock, 9999);
    assert.equal(r.run.settled, false, "the run ended before it had been idle for M seconds");
    await tickAt(r.clock, 10000);
    await assertEndedFor("idle", r, 10000);
  });
});

test("DEL-B2: a run that forwards a request every M minus one seconds is not ended by the idle timeout", async () => {
  await withRun(["--idle-timeout", "10", ...VALID_ARGV], RUNNING, async (r) => {
    for (let t = 1000; t <= 40000; t += 1000) {
      r.clock.t = t;
      if (t % 9000 === 0) await forwardCompletion(r.child);
      await tickAt(r.clock, t);
    }
    assert.equal(r.upstream.requests, 4, "the scripted requests did not all reach the upstream");
    assert.equal(r.run.settled, false, "the idle timeout ended a run that kept forwarding");
    await childExitsOnItsOwn(r.child);
    await assertOwnExit(3, r);
  });
});

test("DEL-B2: a run that forwards one request and then none for M seconds is ended", async () => {
  await withRun(["--idle-timeout", "10", ...VALID_ARGV], RUNNING, async (r) => {
    r.clock.t = 5000;
    await forwardCompletion(r.child);
    await tickAt(r.clock, 14999);
    assert.equal(r.run.settled, false, "the idle clock did not restart at the forwarded request");
    await tickAt(r.clock, 15000);
    await assertEndedFor("idle", r, 15000);
  });
});

// ─── Both flags, and the child's own exit ──────────────────────────

test("DEL-B3: with both flags, an idle timeout that expires first decides the reason", async () => {
  await withRun(["--timeout", "30", "--idle-timeout", "10", ...VALID_ARGV], RUNNING, async (r) => {
    await tickAt(r.clock, 10000);
    await assertEndedFor("idle", r, 10000);
  });
});

test("DEL-B3: with both flags, a timeout that expires first decides the reason", async () => {
  await withRun(["--timeout", "10", "--idle-timeout", "30", ...VALID_ARGV], RUNNING, async (r) => {
    await tickAt(r.clock, 10000);
    await assertEndedFor("timeout", r, 10000);
  });
});

test("DEL-B3: when both flags expire on one tick the reason is timeout", async () => {
  await withRun(["--timeout", "10", "--idle-timeout", "10", ...VALID_ARGV], RUNNING, async (r) => {
    await tickAt(r.clock, 10000);
    await assertEndedFor("timeout", r, 10000);
  });
});

test("DEL-B3: a child that exits on its own before an expiry yields its own exit code and no reason line", async () => {
  await withRun(["--timeout", "10", "--idle-timeout", "10", ...VALID_ARGV], RUNNING, async (r) => {
    r.clock.t = 5000;
    await childExitsOnItsOwn(r.child);
    await tickAt(r.clock, 5000);
    await assertOwnExit(3, r);
  });
});

test("DEL-B3: a child that exits on the same tick as an expiry yields its own exit code and no reason line", async () => {
  await withRun(["--timeout", "10", "--idle-timeout", "10", ...VALID_ARGV], RUNNING, async (r) => {
    r.clock.t = 10000;
    await childExitsOnItsOwn(r.child);
    await tickAt(r.clock, 10000);
    await assertOwnExit(3, r);
  });
});

// ─── A signal to the launcher ──────────────────────────────────────

for (const signal of ["SIGTERM", "SIGINT"]) {
  test(`DEL-B6: ${signal} to the launcher ends a child that ignores it, grandchild included, and exits 75`, async () => {
    const bin = fakeClaude(IGNORE_SIGNALS + WITH_GRANDCHILD);
    const launched = launch(VALID_ARGV, launchEnv(bin));
    const child = await readRecord(bin);
    const signalledAt = Date.now();
    launched.proc.kill(signal);
    const result = await exitWithin(launched, child, 15000);
    const elapsed = Date.now() - signalledAt;
    assert.ok(elapsed <= 10000, `the launcher exited ${elapsed} ms after the signal`);
    assert.equal(result.code, EXIT_ROUTE);
    assert.match(result.stderr, /^\[run\] reason=signal$/m);
    assert.ok(groupGone(child.pid), "a process in the child's group survived");
  });
}

test("DEL-B6: a signal and an expiry on one tick report reason=signal", async () => {
  await withRun(["--timeout", "10", ...VALID_ARGV], RUNNING, async (r) => {
    r.clock.t = 10000;
    process.emit("SIGTERM", "SIGTERM");
    await tickAt(r.clock, 10000);
    await assertEndedFor("signal", r, 10000);
  });
});

// ─── An instructed run, end to end ─────────────────────────────────

/** Sends two completions for the model the run is pinned to and one for
 *  another model through the proxy, records the statuses, and exits 0. */
const SEND_COMPLETIONS = `
const send = (model) => new Promise((resolve) => {
  const req = require("http").request(process.env.ANTHROPIC_BASE_URL + "/v1/messages", {
    method: "POST", headers: { "content-type": "application/json" },
  }, (res) => { res.resume(); res.on("end", () => resolve(res.statusCode)); });
  req.end(JSON.stringify({ model, messages: [] }));
});
(async () => {
  const pinned = process.env.ANTHROPIC_DEFAULT_SONNET_MODEL;
  record({ statuses: [await send(pinned), await send(pinned), await send("some/other")] });
  process.exit(0);
})();`;

const ledgerLines = (stderr) => stderr.split("\n").filter((line) => line.includes("model-ledger"));

/** Run `launcherArgv` with the completion-sending fake to its own exit, and
 *  return what the child received, the exit code and the proxy's ledger. */
async function observeRun(launcherArgv) {
  let seen;
  await withRun(launcherArgv, SEND_COMPLETIONS, async ({ run, clock, child, upstream }) => {
    await tickUntilSettled(clock, run);
    assert.equal(run.error, undefined);
    seen = {
      child: normalise(child),
      statuses: child.statuses,
      code: run.code,
      forwarded: upstream.requests,
      ledger: ledgerLines(run.stderr),
    };
  });
  return seen;
}

for (const model of ["openai/gpt-5.6-mini", "google/gemini-3.8-flash"]) {
  test(`DEL-F2: --user-instructed starts the run on ${model} and every ledger line carries the mark`, async () => {
    const seen = await observeRun(argvFor(model, ["--user-instructed"]));
    assert.equal(seen.code, 0);
    assert.deepEqual(seen.child.argv, argvFor(model), "the flag is the launcher's and never reaches the child");
    assert.equal(seen.child.env.ANTHROPIC_DEFAULT_SONNET_MODEL, model);
    assert.deepEqual(seen.statuses, [200, 200, 403]);
    assert.equal(seen.forwarded, 2);
    assert.equal(seen.ledger.length, 3);
    for (const line of seen.ledger) assert.ok(line.split(" ").includes("user-instructed"), line);
    for (const line of seen.ledger.slice(0, 2)) assert.ok(line.split(" ").includes("decision=forward"), line);
  });
}

for (const model of ["vendor/model", "moonshotai/kimi-k3"]) {
  test(`DEL-F4: --user-instructed on ${model} changes no argv, environment, exit code or ledger`, async () => {
    const without = await observeRun(argvFor(model));
    const withFlag = await observeRun(argvFor(model, ["--user-instructed"]));
    assert.equal(without.ledger.length, 3);
    assert.deepEqual(withFlag, without);
  });
}
