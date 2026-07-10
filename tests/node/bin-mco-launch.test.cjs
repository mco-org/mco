const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

test("ordinary commands still invoke python3 with package mco script", () => {
  const { launch } = require("../../bin/mco.js");
  const records = [];
  const runner = (command, args, options) => {
    records.push({ command, args, options });
    return { status: 0, error: null };
  };
  launch(["--help"], { runner });
  assert.equal(records.length, 1);
  assert.equal(records[0].command, "python3");
  assert.equal(records[0].args[0], path.resolve(__dirname, "../..", "mco"));
  assert.equal(records[0].args[1], "--help");
});
