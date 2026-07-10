const { test, mock } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const wizard = require("../../scripts/install-wizard.js");

const PACKAGE_ROOT = path.resolve(__dirname, "../..");

function makeRunner(records) {
  return (command, args, options = {}) => {
    records.push({ command, args, options });
    if (command === "npm" && args[0] === "install") {
      return { status: 0, stdout: "", stderr: "", error: null };
    }
    if (command === "npm" && args[0] === "prefix") {
      return { status: 0, stdout: "/tmp/npm-global\n", stderr: "", error: null };
    }
    if (command === process.execPath || command.endsWith("/mco") || command.endsWith("mco.js")) {
      return {
        status: 0,
        stdout: JSON.stringify({ ok: true, skill_health: { status: "ok" } }),
        stderr: "",
        error: null,
      };
    }
    return { status: 0, stdout: "", stderr: "", error: null };
  };
}

test("dry-run without agents returns agent_selection_required", async () => {
  const stdoutChunks = [];
  const exit = mock.method(process, "exit", (code) => {
    throw new Error(`process.exit:${code}`);
  });
  mock.method(console, "log", (...args) => {
    stdoutChunks.push(args.join(" "));
  });
  try {
    await wizard.main(["--dry-run", "--json"], {
      runner: () => ({ status: 0, stdout: "", stderr: "", error: null }),
      packageRoot: PACKAGE_ROOT,
      version: "0.10.8",
      isTTY: false,
      detectCallingAgents: () => [],
    });
  } catch (err) {
    if (!String(err.message).startsWith("process.exit:")) {
      throw err;
    }
  } finally {
    mock.restoreAll();
  }
  assert.equal(String(exit.mock.calls[0].arguments[0]), "2");
  const payload = JSON.parse(stdoutChunks.join("\n"));
  assert.equal(payload.ok, false);
  assert.equal(payload.error.subtype, "agent_selection_required");
  assert.equal(payload.dry_run, true);
  assert.match(payload.retry_command, /--agent/);
});

test("dry-run json returns planned commands without executing", async () => {
  const records = [];
  const runner = makeRunner(records);
  const stdoutChunks = [];
  const exit = mock.method(process, "exit", (code) => {
    throw new Error(`process.exit:${code}`);
  });
  mock.method(console, "log", (...args) => {
    stdoutChunks.push(args.join(" "));
  });
  try {
    await wizard.main(["--dry-run", "--json", "--agent", "codex"], {
      runner,
      packageRoot: PACKAGE_ROOT,
      version: "0.10.8",
      isTTY: false,
    });
  } catch (err) {
    if (!String(err.message).startsWith("process.exit:")) {
      throw err;
    }
  } finally {
    mock.restoreAll();
  }
  assert.equal(String(exit.mock.calls[0].arguments[0]), "0");
  const payload = JSON.parse(stdoutChunks.join("\n"));
  assert.equal(payload.ok, true);
  assert.equal(payload.dry_run, true);
  assert.deepEqual(payload.cli.argv, ["npm", "install", "-g", "@tt-a1i/mco@0.10.8"]);
  assert.match(payload.skills.underlying_argv.join(" "), /--copy/);
  assert.equal(records.length, 0);
});

test("yes with no detected agents returns agent_selection_required", async () => {
  const runner = (command) => {
    if (command === "which" || command === "where") {
      return { status: 1, stdout: "", stderr: "", error: null };
    }
    if (command === "npm") {
      return { status: 0, stdout: "", stderr: "", error: null };
    }
    return { status: 0, stdout: "", stderr: "", error: null };
  };
  const stdoutChunks = [];
  const exit = mock.method(process, "exit", (code) => {
    throw new Error(`process.exit:${code}`);
  });
  mock.method(console, "log", (...args) => {
    stdoutChunks.push(args.join(" "));
  });
  try {
    await wizard.main(["--yes", "--json"], {
      runner,
      packageRoot: PACKAGE_ROOT,
      version: "0.10.8",
      isTTY: false,
      detectCallingAgents: () => [],
    });
  } catch (err) {
    if (!String(err.message).startsWith("process.exit:")) {
      throw err;
    }
  } finally {
    mock.restoreAll();
  }
  assert.equal(String(exit.mock.calls[0].arguments[0]), "2");
  const payload = JSON.parse(stdoutChunks.join("\n"));
  assert.equal(payload.ok, false);
  assert.equal(payload.error.subtype, "agent_selection_required");
  assert.equal(payload.cli.status, "installed");
});

test("failed cli install and failed skill sync expose distinct stages", async () => {
  const stdoutChunks = [];
  let exit = mock.method(process, "exit", (code) => {
    throw new Error(`process.exit:${code}`);
  });
  mock.method(console, "log", (...args) => {
    stdoutChunks.push(args.join(" "));
  });
  const runner = (command, args) => {
    if (command === "npm" && args[0] === "install") {
      return { status: 1, stdout: "", stderr: "npm failed", error: null };
    }
    return { status: 0, stdout: "", stderr: "", error: null };
  };
  try {
    await wizard.main(["--agent", "codex", "--yes", "--json"], {
      runner,
      packageRoot: PACKAGE_ROOT,
      version: "0.10.8",
      isTTY: false,
    });
  } catch (err) {
    if (!String(err.message).startsWith("process.exit:")) {
      throw err;
    }
  }
  assert.equal(String(exit.mock.calls[0].arguments[0]), "1");
  const payload = JSON.parse(stdoutChunks.join("\n"));
  assert.equal(payload.stage, "cli_install");

  stdoutChunks.length = 0;
  mock.restoreAll();
  exit = mock.method(process, "exit", (code) => {
    throw new Error(`process.exit:${code}`);
  });
  mock.method(console, "log", (...args) => {
    stdoutChunks.push(args.join(" "));
  });
  const runner2 = (command, args) => {
    if (command === "npm") {
      return { status: 0, stdout: "/tmp/npm-global\n", stderr: "", error: null };
    }
    if (command === process.execPath) {
      return { status: 1, stdout: "", stderr: "skill sync failed", error: null };
    }
    return { status: 0, stdout: "", stderr: "", error: null };
  };
  try {
    await wizard.main(["--agent", "codex", "--yes", "--json"], {
      runner: runner2,
      packageRoot: PACKAGE_ROOT,
      version: "0.10.8",
      isTTY: false,
      globalMcoScript: "/tmp/npm-global/node_modules/@tt-a1i/mco/bin/mco.js",
    });
  } catch (err) {
    if (!String(err.message).startsWith("process.exit:")) {
      throw err;
    }
  } finally {
    mock.restoreAll();
  }
  assert.equal(String(exit.mock.calls[0].arguments[0]), "1");
  const payload2 = JSON.parse(stdoutChunks.join("\n"));
  assert.equal(payload2.stage, "skill_sync");
  assert.match(payload2.retry_command, /skills sync/);
});
