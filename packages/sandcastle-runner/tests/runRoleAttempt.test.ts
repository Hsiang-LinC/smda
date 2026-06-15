import assert from "node:assert/strict";
import test from "node:test";

import {
  roleResultSchema,
  roleAttemptRequestSchema,
  runRoleAttempt,
  type RoleAttemptRequest,
} from "../src/runRoleAttempt.ts";

const baseRequest: RoleAttemptRequest = {
  attempt_id: "attempt-1",
  role: "implementer",
  phase: "IMPLEMENTING",
  branch: "smda/child-A",
  cwd: "/repo",
  context_packet: { child_id: "child-A", quality_gates: ["pytest"] },
  prompt: "Implement child A",
  output_tag: "result",
  schema_id: "smda.role-result.v1",
  sandbox_provider: "noSandbox",
  agent: { provider: "codex", model: "gpt-5" },
};

test("validates role attempt requests", () => {
  const parsed = roleAttemptRequestSchema.parse(baseRequest);

  assert.equal(parsed.attempt_id, "attempt-1");
  assert.equal(parsed.agent.provider, "codex");
});

test("maps a successful Sandcastle run into a role attempt result", async () => {
  const seenOptions: unknown[] = [];

  const result = await runRoleAttempt(baseRequest, {
    run: async (options) => {
      seenOptions.push(options);
      return {
        output: {
          verdict: "DONE",
          required_next_action: "submit_for_spec_review",
          report: "implemented",
        },
        commits: [{ sha: "abc123" }],
        branch: "smda/child-A",
        logFilePath: ".sandcastle/logs/attempt-1.log",
      };
    },
    outputObject: (options) => ({ fakeOutput: options }),
    sandboxProvider: () => ({ fakeSandbox: true }),
    agentProvider: () => ({ fakeAgent: true }),
  });

  assert.equal(result.status, "succeeded");
  assert.deepEqual(result.result, {
    verdict: "DONE",
    required_next_action: "submit_for_spec_review",
    report: "implemented",
  });
  assert.deepEqual(result.commits, [{ sha: "abc123" }]);
  assert.equal(result.branch, "smda/child-A");
  assert.equal(result.log_file_path, ".sandcastle/logs/attempt-1.log");
  const options = seenOptions[0] as {
    agent: unknown;
    sandbox: unknown;
    cwd: string;
    branchStrategy: unknown;
    prompt: string;
    maxIterations: number;
    name: string;
    output: { fakeOutput: { tag: string; schema: unknown } };
  };
  assert.deepEqual(options.agent, { fakeAgent: true });
  assert.deepEqual(options.sandbox, { fakeSandbox: true });
  assert.equal(options.cwd, "/repo");
  assert.deepEqual(options.branchStrategy, {
    type: "branch",
    branch: "smda/child-A",
  });
  assert.equal(options.prompt, "Implement child A");
  assert.equal(options.maxIterations, 1);
  assert.equal(options.name, "attempt-1:implementer");
  assert.equal(options.output.fakeOutput.tag, "result");
  assert.equal(options.output.fakeOutput.schema, roleResultSchema);
});

test("maps structured output errors separately from execution failures", async () => {
  const structured = await runRoleAttempt(baseRequest, {
    run: async () => {
      const error = new Error("bad output");
      error.name = "StructuredOutputError";
      Object.assign(error, {
        rawMatched: "{bad json",
        branch: "smda/child-A",
        preservedWorktreePath: "/tmp/worktree",
        sessionId: "session-1",
        sessionFilePath: "/tmp/session.jsonl",
      });
      throw error;
    },
    outputObject: (options) => ({ fakeOutput: options }),
    sandboxProvider: () => ({ fakeSandbox: true }),
    agentProvider: () => ({ fakeAgent: true }),
  });

  assert.equal(structured.status, "structured_output_failed");
  assert.equal(structured.branch, "smda/child-A");
  assert.equal(structured.preserved_worktree_path, "/tmp/worktree");
  assert.equal(structured.session_id, "session-1");

  const execution = await runRoleAttempt(baseRequest, {
    run: async () => {
      throw new Error("docker unavailable");
    },
    outputObject: (options) => ({ fakeOutput: options }),
    sandboxProvider: () => ({ fakeSandbox: true }),
    agentProvider: () => ({ fakeAgent: true }),
  });

  assert.equal(execution.status, "execution_failed");
  assert.match(execution.error_message ?? "", /docker unavailable/);
});
