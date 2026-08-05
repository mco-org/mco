"use strict";

const fs = require("node:fs");
const path = require("node:path");

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

module.exports = { resolveExecutable };
