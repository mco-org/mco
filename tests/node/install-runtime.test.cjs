const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const runtime = require("../../scripts/install-runtime.js");

test("buildNpmInstallArgv pins exact package version", () => {
  assert.deepEqual(runtime.buildNpmInstallArgv("0.10.9"), [
    "install",
    "-g",
    "@tt-a1i/mco@0.10.9",
  ]);
});

test("resolveGlobalMcoScript uses npm root -g on Unix", () => {
  const runner = (command, args) => {
    if (command === "npm" && args[0] === "root") {
      return { status: 0, stdout: "/opt/homebrew/lib/node_modules\n", stderr: "", error: null };
    }
    return { status: 1, stdout: "", stderr: "", error: null };
  };
  const expected = "/opt/homebrew/lib/node_modules/@tt-a1i/mco/bin/mco.js";
  const scriptPath = runtime.resolveGlobalMcoScript(runner, {
    existsSync: (candidate) => candidate === expected,
  });
  assert.equal(scriptPath, expected);
});

test("resolveGlobalMcoScript returns null when entry is missing", () => {
  const runner = (command, args) => {
    if (command === "npm" && args[0] === "root") {
      return { status: 0, stdout: "/opt/homebrew/lib/node_modules\n", stderr: "", error: null };
    }
    return { status: 1, stdout: "", stderr: "", error: null };
  };
  assert.equal(runtime.resolveGlobalMcoScript(runner, { existsSync: () => false }), null);
});

test("resolveGlobalMcoScript uses Windows npm prefix fallback", () => {
  const prefix = "C:\\Users\\dev\\AppData\\Roaming\\npm";
  const expected = path.win32.join(prefix, "node_modules", "@tt-a1i", "mco", "bin", "mco.js");
  const runner = (command, args) => {
    if (command === "npm" && args[0] === "root") {
      return { status: 1, stdout: "", stderr: "", error: null };
    }
    if (command === "npm" && args[0] === "prefix") {
      return { status: 0, stdout: `${prefix}\r\n`, stderr: "", error: null };
    }
    return { status: 1, stdout: "", stderr: "", error: null };
  };
  assert.equal(runtime.resolveGlobalMcoScript(runner, {
    platform: "win32",
    existsSync: (candidate) => candidate === expected,
  }), expected);
});

test("skills CLI dependency is pinned to the tested version", () => {
  assert.equal(runtime.SKILLS_CLI_PACKAGE, "skills@1.5.15");
  assert.equal(runtime.buildSkillsCliAddArgv("/pkg/mco", ["codex"])[2], "skills@1.5.15");
});

test("resolveGlobalMcoScript allows dry-run placeholder", () => {
  const runner = () => ({ status: 1, stdout: "", stderr: "", error: null });
  assert.equal(
    runtime.resolveGlobalMcoScript(runner, { allowPlaceholder: true, existsSync: () => false }),
    runtime.DRY_RUN_MCO_PLACEHOLDER,
  );
});

test("detectCallingAgents maps installed binaries to skill agent ids", () => {
  const runner = (command, args) => {
    if (command === "which" && args[0] === "claude") {
      return { status: 0, stdout: "/usr/local/bin/claude\n", stderr: "", error: null };
    }
    if (command === "which" && args[0] === "agent") {
      return { status: 0, stdout: "/usr/local/bin/agent\n", stderr: "", error: null };
    }
    if (command === "which" && args[0] === "pi") {
      return { status: 0, stdout: "/usr/local/bin/pi\n", stderr: "", error: null };
    }
    return { status: 1, stdout: "", stderr: "", error: null };
  };
  assert.deepEqual(runtime.detectCallingAgents(runner), ["claude-code", "cursor", "pi"]);
});

test("normalizeSkillAgents accepts supported MCO calling agents", () => {
  assert.deepEqual(
    runtime.normalizeSkillAgents(["pi", "hermes-agent", "github-copilot", "qwen-code"]),
    ["pi", "hermes-agent", "github-copilot", "qwen-code"],
  );
});

test("normalizeSkillAgents rejects unknown ids", () => {
  assert.throws(
    () => runtime.normalizeSkillAgents(["gemini"]),
    /unknown skill agent: gemini/,
  );
});

test("runMcoScript uses node for .js entrypoints", () => {
  const records = [];
  const runner = (command, args) => {
    records.push({ command, args });
    return { status: 0, stdout: "{}", stderr: "", error: null };
  };
  runtime.runMcoScript("/tmp/npm-global/node_modules/@tt-a1i/mco/bin/mco.js", ["skills", "status"], runner);
  assert.equal(records[0].command, process.execPath);
  assert.equal(records[0].args[0], "/tmp/npm-global/node_modules/@tt-a1i/mco/bin/mco.js");
});

test("runMcoScript fails when placeholder used without allowPlaceholder", () => {
  const result = runtime.runMcoScript(runtime.DRY_RUN_MCO_PLACEHOLDER, ["skills", "sync"], () => ({
    status: 0,
    stdout: "",
    stderr: "",
    error: null,
  }));
  assert.equal(result.status, 1);
  assert.equal(result.failure, "global_mco_not_found");
});
