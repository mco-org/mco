"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

function pathext(env) {
  return String(env.PATHEXT || ".COM;.EXE;.BAT;.CMD")
    .split(";")
    .filter(Boolean)
    .map((ext) => ext.toLowerCase());
}

function pathDirs(env) {
  const key = env.Path ? "Path" : "PATH";
  return String(env[key] || "")
    .split(path.delimiter)
    .filter(Boolean);
}

function resolveExecutable(command, env = process.env, existsSync = fs.existsSync) {
  if (process.platform !== "win32" || !command || path.extname(command)) {
    return command;
  }
  const extensions = pathext(env);
  for (const dir of pathDirs(env)) {
    for (const ext of extensions) {
      const candidate = path.join(dir, `${command}${ext}`);
      if (existsSync(candidate)) {
        return candidate;
      }
    }
  }
  return command;
}

function isCmdShim(command) {
  return process.platform === "win32" && /\.(cmd|bat)$/i.test(command);
}

// Escape a single arg for use inside a quoted cmd.exe command line. Only `%`
// needs escaping inside quotes (env-var expansion); `& | < > ^ !` etc. pass
// through literally. `^%` blocks expansion, matching cross-spawn behavior.
function escapeCmdArg(value) {
  return `"${String(value).replace(/"/g, '""').replace(/%/g, "^%")}"`;
}

// Build argv for running a .cmd/.bat shim through cmd.exe with shell:false.
// Returns e.g. ["/d", "/s", "/c", "\"\"C:\\Tools\\npm.cmd\" \"install\" -g\"\""].
function buildCmdShimArgv(shimPath, args, comSpec) {
  const inner = args.map(escapeCmdArg).join(" ");
  const line = `""${shimPath}"${inner ? ` ${inner}` : ""}"`;
  const shell = comSpec || process.env.ComSpec || "cmd.exe";
  return { comSpec: shell, argv: [shell, "/d", "/s", "/c", line] };
}

// Spawn a command, resolving bare names to shims on Windows. Node cannot spawn
// .cmd/.bat files directly (EINVAL), so they are routed through cmd.exe with
// shell:false kept and every arg quoted, preventing shell injection.
function spawnExecutable(command, args, options = {}) {
  const env = options.env || process.env;
  const resolved = resolveExecutable(command, env);
  if (isCmdShim(resolved)) {
    const { argv } = buildCmdShimArgv(resolved, args, env.ComSpec);
    return spawnSync(argv[0], argv.slice(1), {
      encoding: "utf8",
      shell: false,
      windowsVerbatimArguments: true,
      ...options,
    });
  }
  return spawnSync(resolved, args, {
    encoding: "utf8",
    shell: false,
    ...options,
  });
}

module.exports = { resolveExecutable, spawnExecutable, isCmdShim, buildCmdShimArgv, escapeCmdArg };
