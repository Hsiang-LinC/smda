import assert from "node:assert/strict";
import { readFile, rm, mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Readable } from "node:stream";
import test from "node:test";

import { readStream, runCli } from "../src/cli.ts";

test("runCli writes JSON result to the result file", async () => {
  const tempDir = await mkdtemp(join(tmpdir(), "smda-cli-"));
  const resultFilePath = join(tempDir, "result.json");

  const result = await runCli(
    JSON.stringify({ attempt_id: "attempt-1" }),
    {
      resultFilePath,
      runner: async (request) => ({
        status: "succeeded",
        attempt_id: String((request as { attempt_id: string }).attempt_id),
        schema_id: "smda.child-implementer-result.v1",
        schema_package_version: "0.1.0",
        result: { verdict: "DONE", required_next_action: "accept_candidate" },
        commits: [],
        branch: "smda/child-A",
      }),
    },
  );

  try {
    assert.equal(result.exitCode, 0);
    assert.equal(result.stdout, "");
    assert.equal(result.stderr, "");
    assert.deepEqual(JSON.parse(await readFile(resultFilePath, "utf-8")), {
      status: "succeeded",
      attempt_id: "attempt-1",
      schema_id: "smda.child-implementer-result.v1",
      schema_package_version: "0.1.0",
      result: { verdict: "DONE", required_next_action: "accept_candidate" },
      commits: [],
      branch: "smda/child-A",
    });
  } finally {
    await rm(tempDir, { recursive: true, force: true });
  }
});

test("runCli writes protocol failure artifact for invalid JSON", async () => {
  const tempDir = await mkdtemp(join(tmpdir(), "smda-cli-"));
  const resultFilePath = join(tempDir, "result.json");

  const result = await runCli("{not json", {
    resultFilePath,
    runner: async () => {
      throw new Error("should not run");
    },
  });

  try {
    assert.equal(result.exitCode, 1);
    assert.equal(result.stdout, "");
    assert.equal(result.stderr, "");
    assert.deepEqual(JSON.parse(await readFile(resultFilePath, "utf-8")), {
      status: "agent_protocol_failed",
      error_message: "Invalid JSON IPC request",
    });
  } finally {
    await rm(tempDir, { recursive: true, force: true });
  }
});

test("runCli rejects missing result file path", async () => {
  const result = await runCli(JSON.stringify({ attempt_id: "attempt-1" }), {
    runner: async () => {
      throw new Error("should not run");
    },
  });

  assert.equal(result.exitCode, 1);
  assert.equal(result.stdout, "");
  assert.equal(result.stderr, "Missing required --result-file");
});

test("readStream collects chunked stdin input", async () => {
  const input = await readStream(Readable.from(["{\"a\"", ":1", "}\n"]));

  assert.equal(input, "{\"a\":1}\n");
});
