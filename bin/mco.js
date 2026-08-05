#!/usr/bin/env node

const { resolve } = require("node:path");

const { spawnExecutable } = require("../scripts/exec-util.js");

function defaultRunner(command, args, options) {
  return spawnExecutable(command, args, options);
}

function launch(args, deps = {}) {
  if (args[0] === "install") {
    void require("../scripts/install-wizard.js")
      .main(args.slice(1), deps)
      .catch((err) => {
        console.error(String(err.message || err));
        process.exit(1);
      });
    return;
  }

  const scriptPath = resolve(__dirname, "..", "mco");
  const runner = deps.runner || defaultRunner;
  const result = runner("python3", [scriptPath, ...args], {
    stdio: "inherit",
    shell: false,
  });

  if (result.error) {
    console.error(`Failed to run python3: ${result.error.message}`);
    process.exit(1);
  }

  process.exit(result.status === null ? 1 : result.status);
}

if (require.main === module) {
  launch(process.argv.slice(2));
}

module.exports = { launch };
