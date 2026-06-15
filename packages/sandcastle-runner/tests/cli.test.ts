import assert from "node:assert/strict";
import test from "node:test";

import { runCli } from "../src/cli.ts";

test("runCli emits JSON result on stdout", async () => {
  const result = await runCli(
    JSON.stringify({ attempt_id: "attempt-1" }),
    async (request) => ({
      status: "succeeded",
      attempt_id: String((request as { attempt_id: string }).attempt_id),
      schema_id: "smda.child-implementer-result.v1",
      schema_package_version: "0.1.0",
      result: { verdict: "DONE", required_next_action: "accept_candidate" },
      commits: [],
      branch: "smda/child-A",
    }),
  );

  assert.equal(result.exitCode, 0);
  assert.equal(result.stderr, "");
  assert.deepEqual(JSON.parse(result.stdout), {
    status: "succeeded",
    attempt_id: "attempt-1",
    schema_id: "smda.child-implementer-result.v1",
    schema_package_version: "0.1.0",
    result: { verdict: "DONE", required_next_action: "accept_candidate" },
    commits: [],
    branch: "smda/child-A",
  });
});

test("runCli reports protocol failure for invalid JSON", async () => {
  const result = await runCli("{not json", async () => {
    throw new Error("should not run");
  });

  assert.equal(result.exitCode, 1);
  assert.equal(result.stdout, "");
  assert.deepEqual(JSON.parse(result.stderr), {
    status: "agent_protocol_failed",
    error_message: "Invalid JSON IPC request",
  });
});
