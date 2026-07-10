const { test } = require("node:test");
const assert = require("node:assert/strict");

const wizard = require("../../scripts/install-wizard.js");

test("install is intercepted without invoking python", () => {
  const { launch } = require("../../bin/mco.js");
  const records = [];
  const originalMain = wizard.main;
  wizard.main = (...args) => {
    records.push(["install-wizard", ...args]);
    return Promise.resolve();
  };
  try {
    launch(["install", "--dry-run", "--json"]);
  } finally {
    wizard.main = originalMain;
  }
  assert.deepEqual(records[0][1], ["--dry-run", "--json"]);
});
