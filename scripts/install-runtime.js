"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const PACKAGE_NAME = "@tt-a1i/mco";
const SKILLS_CLI_PACKAGE = "skills@1";
const SKILL_NAME = "mco-cli";
const DRY_RUN_MCO_PLACEHOLDER = "mco";

const manifest = require("../runtime/data/skill_calling_agents.json");
const KNOWN_SKILL_AGENTS = new Set(Object.keys(manifest.agents || {}));
const CALLING_AGENT_BINARIES = Object.entries(manifest.agents || {}).flatMap(
  ([agent, spec]) => (spec.binaries || []).map((binary) => ({ binary, agent })),
);

function defaultRunner(command, args, options = {}) {
  return spawnSync(command, args, {
    encoding: "utf8",
    shell: false,
    ...options,
  });
}

function normalizeSkillAgents(values) {
  const agents = [];
  const seen = new Set();
  for (const raw of values) {
    const value = String(raw).trim();
    if (!value) {
      continue;
    }
    if (value.startsWith("-") || /[\u0000-\u001f]/.test(value)) {
      throw new Error(`invalid skill agent: ${value}`);
    }
    if (!KNOWN_SKILL_AGENTS.has(value)) {
      throw new Error(`unknown skill agent: ${value}`);
    }
    if (!seen.has(value)) {
      agents.push(value);
      seen.add(value);
    }
  }
  if (agents.length === 0) {
    throw new Error("agent_selection_required");
  }
  return agents;
}

function buildNpmInstallArgv(version) {
  return ["install", "-g", `${PACKAGE_NAME}@${version}`];
}

function buildSkillsCliAddArgv(packageRoot, agents) {
  const normalized = normalizeSkillAgents(agents);
  const argv = [
    "npx",
    "-y",
    SKILLS_CLI_PACKAGE,
    "add",
    String(packageRoot),
    "--skill",
    SKILL_NAME,
    "--copy",
    "--global",
    "--yes",
  ];
  for (const agent of normalized) {
    argv.push("--agent", agent);
  }
  return argv;
}

function buildSkillSyncArgv(globalMcoScript, agents, { dryRun = false } = {}) {
  const argv = [globalMcoScript, "skills", "sync", "--json"];
  if (dryRun) {
    argv.push("--dry-run");
  }
  for (const agent of normalizeSkillAgents(agents)) {
    argv.push("--agent", agent);
  }
  return argv;
}

function buildDoctorArgv(globalMcoScript) {
  return [globalMcoScript, "doctor", "--skill-health", "--json"];
}

function globalMcoScriptPathFromRoot(globalRoot) {
  return path.join(globalRoot, "@tt-a1i", "mco", "bin", "mco.js");
}

function resolveGlobalMcoScript(runner = defaultRunner, options = {}) {
  const env = options.env || process.env;
  const platform = options.platform || process.platform;
  const existsSync = options.existsSync || fs.existsSync;
  const allowPlaceholder = options.allowPlaceholder === true;

  const rootResult = runner("npm", ["root", "-g"], { env });
  if (rootResult.status === 0) {
    const globalRoot = String(rootResult.stdout || "").trim();
    if (globalRoot) {
      const scriptPath = globalMcoScriptPathFromRoot(globalRoot);
      if (existsSync(scriptPath)) {
        return scriptPath;
      }
    }
  }

  if (platform === "win32") {
    const prefixResult = runner("npm", ["prefix", "-g"], { env });
    if (prefixResult.status === 0) {
      const prefix = String(prefixResult.stdout || "").trim();
      if (prefix) {
        const scriptPath = path.join(prefix, "node_modules", "@tt-a1i", "mco", "bin", "mco.js");
        if (existsSync(scriptPath)) {
          return scriptPath;
        }
      }
    }
  }

  const lookup = runner(platform === "win32" ? "where" : "which", ["mco"], { env });
  if (lookup.status === 0) {
    const candidate = String(lookup.stdout || "").trim().split(/\r?\n/)[0];
    if (candidate && existsSync(candidate)) {
      return candidate.endsWith(".js") ? candidate : candidate;
    }
  }

  if (allowPlaceholder) {
    return DRY_RUN_MCO_PLACEHOLDER;
  }
  return null;
}

function buildMcoLaunch(scriptPath, skillArgs) {
  if (scriptPath === DRY_RUN_MCO_PLACEHOLDER) {
    return {
      command: DRY_RUN_MCO_PLACEHOLDER,
      argv: skillArgs,
      displayPath: DRY_RUN_MCO_PLACEHOLDER,
    };
  }
  if (scriptPath.endsWith(".js")) {
    return {
      command: process.execPath,
      argv: [scriptPath, ...skillArgs],
      displayPath: scriptPath,
    };
  }
  return {
    command: scriptPath,
    argv: skillArgs,
    displayPath: scriptPath,
  };
}

function runMcoScript(scriptPath, skillArgs, runner = defaultRunner, options = {}) {
  const allowPlaceholder = options.allowPlaceholder === true;
  const launch = buildMcoLaunch(scriptPath, skillArgs);

  if (launch.command === DRY_RUN_MCO_PLACEHOLDER) {
    if (allowPlaceholder) {
      return { status: 0, stdout: "", stderr: "", error: null, launch };
    }
    return {
      status: 1,
      stdout: "",
      stderr: "Global mco entrypoint not found. Ensure npm global install succeeded and global bin is on PATH.",
      error: null,
      launch,
      failure: "global_mco_not_found",
    };
  }

  if (!scriptPath) {
    return {
      status: 1,
      stdout: "",
      stderr: "Global mco entrypoint not found after install.",
      error: null,
      launch,
      failure: "global_mco_not_found",
    };
  }

  const result = runner(launch.command, launch.argv, options);
  return { ...result, launch };
}

function detectCallingAgents(runner = defaultRunner, options = {}) {
  const env = options.env || process.env;
  const platform = options.platform || process.platform;
  const lookupCmd = platform === "win32" ? "where" : "which";
  const detected = [];
  const seen = new Set();
  for (const entry of CALLING_AGENT_BINARIES) {
    const result = runner(lookupCmd, [entry.binary], { env });
    if (result.status === 0 && String(result.stdout || "").trim() && !seen.has(entry.agent)) {
      detected.push(entry.agent);
      seen.add(entry.agent);
    }
  }
  return detected;
}

function parseInstallArgs(argv) {
  const options = {
    agents: [],
    yes: false,
    skipSkills: false,
    dryRun: false,
    json: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === "--agent") {
      const value = argv[index + 1];
      if (!value || value.startsWith("-")) {
        throw new Error("missing value for --agent");
      }
      options.agents.push(value);
      index += 1;
      continue;
    }
    if (token === "--yes") {
      options.yes = true;
      continue;
    }
    if (token === "--skip-skills") {
      options.skipSkills = true;
      continue;
    }
    if (token === "--dry-run") {
      options.dryRun = true;
      continue;
    }
    if (token === "--json") {
      options.json = true;
      continue;
    }
    throw new Error(`unknown install flag: ${token}`);
  }
  if (options.agents.length > 0) {
    options.agents = normalizeSkillAgents(options.agents);
  }
  return options;
}

function readPackageVersion(packageRoot) {
  const pkg = require(path.join(packageRoot, "package.json"));
  return String(pkg.version);
}

function promptsAvailable() {
  try {
    require.resolve("@clack/prompts");
    return true;
  } catch (_err) {
    return false;
  }
}

module.exports = {
  PACKAGE_NAME,
  SKILL_NAME,
  DRY_RUN_MCO_PLACEHOLDER,
  KNOWN_SKILL_AGENTS,
  buildDoctorArgv,
  buildMcoLaunch,
  buildNpmInstallArgv,
  buildSkillSyncArgv,
  buildSkillsCliAddArgv,
  defaultRunner,
  detectCallingAgents,
  globalMcoScriptPathFromRoot,
  normalizeSkillAgents,
  parseInstallArgs,
  promptsAvailable,
  readPackageVersion,
  resolveGlobalMcoScript,
  runMcoScript,
};
