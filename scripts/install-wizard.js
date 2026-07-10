"use strict";

const path = require("node:path");

const runtime = require("./install-runtime.js");

function agentSelectionError(message, extra = {}) {
  return {
    ok: false,
    action: "install",
    ...extra,
    error: {
      category: "configuration",
      subtype: "agent_selection_required",
      message: message || "Choose one or more calling agents for the mco-cli Skill.",
      retryable: false,
      exit_code: 2,
    },
  };
}

function buildRetryCommand(agents) {
  const parts = ["mco", "skills", "sync"];
  for (const agent of agents) {
    parts.push("--agent", agent);
  }
  return parts.join(" ");
}

function printResult(payload, json) {
  if (json) {
    console.log(JSON.stringify(payload, null, 2));
    return;
  }
  if (payload.ok) {
    console.log("MCO installation complete.");
    if (payload.cli) {
      console.log(`CLI: ${payload.cli.status} (${payload.cli.version || "unknown"})`);
    }
    if (payload.skills && payload.skills.status !== "skipped") {
      console.log(`Skill: ${payload.skills.status} -> ${payload.skills.agents.join(", ")}`);
    }
    if (payload.doctor && payload.doctor.overall_ok === false) {
      console.log("Doctor: completed with onboarding warnings (provider auth may be pending).");
    }
    console.log("");
    console.log("Dry-run example:");
    console.log("  npx @tt-a1i/mco@latest install --agent codex --dry-run --json");
    return;
  }
  const message = payload.error?.message || payload.message || "Installation failed.";
  console.error(message);
  if (payload.retry_command) {
    console.error(`Retry: ${payload.retry_command}`);
  }
}

function runDoctor(globalMcoScript, runner, env) {
  const doctorArgs = runtime.buildDoctorArgv(globalMcoScript).slice(1);
  const result = runtime.runMcoScript(globalMcoScript, doctorArgs, runner, { env });
  if (result.status !== 0) {
    return { status: "failed", overall_ok: false, exit_code: result.status || 1 };
  }
  try {
    const payload = JSON.parse(String(result.stdout || "{}"));
    return {
      status: "completed",
      overall_ok: Boolean(payload.overall_ok),
      payload,
    };
  } catch (_err) {
    return { status: "completed", overall_ok: false };
  }
}

async function maybePromptAgents(detectedAgents, deps) {
  if (detectedAgents.length === 0) {
    return [];
  }
  if (!deps.isTTY) {
    return detectedAgents;
  }
  if (!runtime.promptsAvailable()) {
    return null;
  }
  const clack = require("@clack/prompts");
  clack.intro("MCO installer");
  const selected = await clack.multiselect({
    message: "Install the mco-cli Skill into these calling agents?",
    options: detectedAgents.map((agent) => ({ value: agent, label: agent })),
    initialValues: detectedAgents,
    required: true,
  });
  if (clack.isCancel(selected)) {
    return [];
  }
  return selected;
}

function buildSkillPlan({ packageRoot, globalMcoScript, agents, dryRun }) {
  const syncArgv = runtime.buildSkillSyncArgv(globalMcoScript, agents, { dryRun: true });
  const launch = runtime.buildMcoLaunch(globalMcoScript, syncArgv.slice(1));
  return {
    status: dryRun ? "planned" : "pending",
    name: runtime.SKILL_NAME,
    agents,
    argv: [launch.displayPath, ...syncArgv.slice(1)],
    underlying_argv: runtime.buildSkillsCliAddArgv(packageRoot, agents),
  };
}

async function main(argv, deps = {}) {
  const packageRoot = deps.packageRoot || path.resolve(__dirname, "..");
  const version = deps.version || runtime.readPackageVersion(packageRoot);
  const runner = deps.runner || runtime.defaultRunner;
  const env = deps.env || process.env;
  const isTTY = deps.isTTY ?? Boolean(process.stdin.isTTY && process.stdout.isTTY);
  const detectCallingAgents = deps.detectCallingAgents
    || (() => runtime.detectCallingAgents(runner, { env }));

  let options;
  try {
    options = runtime.parseInstallArgs(argv);
  } catch (err) {
    const payload = {
      ok: false,
      action: "install",
      error: {
        category: "input",
        subtype: "parse_error",
        message: String(err.message || err),
        retryable: false,
        exit_code: 2,
      },
    };
    printResult(payload, argv.includes("--json"));
    process.exit(2);
    return;
  }

  let agents = [...options.agents];
  if (agents.length === 0 && !options.skipSkills) {
    const detected = detectCallingAgents();
    if (options.yes) {
      agents = detected;
    } else if (isTTY && !options.dryRun) {
      if (!runtime.promptsAvailable()) {
        const payload = agentSelectionError(
          "Interactive agent selection requires @clack/prompts. Pass --agent or use --yes with detected agents.",
          {
            cli: { status: "planned", version },
            skills: { status: "skipped", reason: "prompts_unavailable" },
            retry_command: "npx @tt-a1i/mco@latest install --agent codex --yes",
          },
        );
        printResult(payload, options.json);
        process.exit(2);
        return;
      }
      const prompted = await maybePromptAgents(detected, { isTTY });
      if (prompted === null) {
        agents = [];
      } else {
        agents = prompted;
      }
    }
  }

  const npmArgv = ["npm", ...runtime.buildNpmInstallArgv(version)];

  if (options.dryRun) {
    const globalMcoScript = deps.globalMcoScript || runtime.DRY_RUN_MCO_PLACEHOLDER;
    if (!options.skipSkills && agents.length === 0) {
      const payload = agentSelectionError(
        "Choose one or more calling agents for the mco-cli Skill.",
        {
          dry_run: true,
          cli: {
            status: "planned",
            version,
            argv: npmArgv,
          },
          skills: { status: "skipped", reason: "agent_selection_required" },
          retry_command: "npx @tt-a1i/mco@latest install --agent codex --yes",
        },
      );
      printResult(payload, options.json);
      process.exit(2);
      return;
    }
    const payload = {
      ok: true,
      action: "install",
      dry_run: true,
      cli: {
        status: "planned",
        version,
        argv: npmArgv,
      },
      skills: options.skipSkills
        ? { status: "skipped", reason: "skip_skills" }
        : buildSkillPlan({ packageRoot, globalMcoScript, agents, dryRun: true }),
      doctor: {
        status: "planned",
        argv: [globalMcoScript, ...runtime.buildDoctorArgv(globalMcoScript).slice(1)],
      },
    };
    printResult(payload, options.json);
    process.exit(0);
    return;
  }

  if (!options.skipSkills && agents.length === 0) {
    const payload = agentSelectionError(
      "Choose one or more calling agents for the mco-cli Skill.",
      {
        cli: {
          status: "not_started",
          version,
        },
        skills: { status: "skipped", reason: "agent_selection_required" },
        retry_command: "mco skills sync --agent <agent>",
      },
    );
    printResult(payload, options.json);
    process.exit(2);
    return;
  }

  const cliResult = runner("npm", runtime.buildNpmInstallArgv(version), { env });
  if (cliResult.status !== 0) {
    const payload = {
      ok: false,
      action: "install",
      stage: "cli_install",
      cli: { status: "failed", version },
      error: {
        category: "runtime",
        subtype: "cli_install_failed",
        message: String(cliResult.stderr || "Global npm install failed."),
        retryable: true,
        exit_code: 1,
      },
    };
    printResult(payload, options.json);
    process.exit(1);
    return;
  }

  const globalMcoScript = deps.globalMcoScript || runtime.resolveGlobalMcoScript(runner, { env });
  if (!globalMcoScript) {
    const payload = {
      ok: false,
      action: "install",
      stage: "global_mco_resolve",
      cli: { status: "installed", version },
      error: {
        category: "runtime",
        subtype: "global_mco_not_found",
        message: "Installed MCO globally but could not locate bin/mco.js under npm root -g.",
        retryable: true,
        exit_code: 1,
      },
      retry_command: buildRetryCommand(agents),
    };
    printResult(payload, options.json);
    process.exit(1);
    return;
  }

  let skillsPayload = { status: "skipped", reason: "skip_skills" };
  if (!options.skipSkills && agents.length > 0) {
    const syncArgs = runtime.buildSkillSyncArgv(globalMcoScript, agents).slice(1);
    const syncResult = runtime.runMcoScript(globalMcoScript, syncArgs, runner, { env });
    skillsPayload = {
      status: syncResult.status === 0 ? "installed" : "failed",
      name: "mco-cli",
      agents,
      argv: [syncResult.launch.displayPath, ...syncArgs],
      exit_code: syncResult.status,
    };
    if (syncResult.status !== 0) {
      const payload = {
        ok: false,
        action: "install",
        stage: "skill_sync",
        cli: { status: "installed", version },
        skills: skillsPayload,
        retry_command: buildRetryCommand(agents),
        error: {
          category: "runtime",
          subtype: syncResult.failure === "global_mco_not_found" ? "global_mco_not_found" : "skill_sync_failed",
          message: String(syncResult.stderr || "Skill sync failed."),
          retryable: true,
          exit_code: 1,
        },
      };
      printResult(payload, options.json);
      process.exit(1);
      return;
    }
  }

  const doctor = runDoctor(globalMcoScript, runner, env);
  const payload = {
    ok: true,
    action: "install",
    cli: { status: "installed", version },
    skills: skillsPayload,
    doctor,
  };
  printResult(payload, options.json);
  process.exit(0);
}

module.exports = { main, buildRetryCommand };

if (require.main === module) {
  main(process.argv.slice(2)).catch((err) => {
    console.error(String(err.message || err));
    process.exit(1);
  });
}
