import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join } from "node:path";
import test from "node:test";

import {
  graphDecomposerResultSchema,
  roleResultSchema,
  roleAttemptRequestSchema,
  runRoleAttempt,
  type RoleAttemptRequest,
} from "../src/runRoleAttempt.ts";
import { roleResultSchemaForId } from "../src/roleContracts.ts";

const baseRequest: RoleAttemptRequest = {
  attempt_id: "attempt-1",
  role: "child_implementer",
  phase: "IMPLEMENTING",
  branch: "smda/child-A",
  cwd: "/repo",
  context_packet: { child_id: "child-A", quality_gates: ["pytest"] },
  prompt: "Implement child A",
  output_tag: "smda_child_implementer_result",
  schema_id: "smda.child-implementer-result.v1",
  sandbox_provider: "noSandbox",
  agent: { provider: "codex", model: "gpt-5.5", effort: "high" },
};

const completeGraphChild = {
  node_id: "child-001",
  title: "Extract scheduler runtime",
  body: "Move scheduler code into the SMDA product.",
  in_scope: ["scheduler runtime"],
  out_of_scope: ["consumer repo cleanup"],
  touched_surfaces: {
    files: ["packages/scheduler/src/smda_scheduler/runtime.py"],
    modules: ["smda_scheduler.runtime"],
    contracts: ["smda.graph-decomposer-result.v1"],
    docs: ["docs/product-spec.md"],
    tests: ["packages/scheduler/tests/test_runtime.py"],
  },
  acceptance_criteria: ["scheduler tests pass"],
  verification: {
    required: ["uv run pytest packages/scheduler/tests/test_runtime.py -q"],
    smoke: ["uv run pytest packages/scheduler/tests -q"],
  },
  risk_level: "medium",
  dependencies: [],
};

test("validates role attempt requests", () => {
  const parsed = roleAttemptRequestSchema.parse(baseRequest);

  assert.equal(parsed.attempt_id, "attempt-1");
  assert.equal(parsed.agent.provider, "codex");
  assert.equal(parsed.agent.model, "gpt-5.5");
  assert.equal(parsed.agent.effort, "high");
});

test("rejects invalid review next actions", () => {
  assert.throws(() =>
    roleResultSchemaForId("smda.review-result.v1").parse({
      verdict: "PASS",
      required_next_action: "invented_action",
    }),
  );
});

test("requires complete graph decomposer child context", () => {
  assert.throws(() =>
    roleResultSchemaForId("smda.graph-decomposer-result.v1").parse({
      verdict: "DONE",
      required_next_action: "submit_for_graph_review",
      children: [
        {
          node_id: "child-001",
          title: "Extract scheduler runtime",
          body: "Move scheduler code into the SMDA product.",
          acceptance_criteria: ["scheduler tests pass"],
          dependencies: [],
        },
      ],
    }),
  );
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
  assert.equal(result.schema_id, "smda.child-implementer-result.v1");
  assert.equal(result.schema_package_version, "0.1.0");
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
  assert.equal(options.name, "attempt-1:child_implementer");
  assert.equal(options.output.fakeOutput.tag, "smda_child_implementer_result");
  assert.equal(options.output.fakeOutput.schema, roleResultSchema);
});

test("isolates git global config across parallel Sandcastle attempts", async () => {
  const repo = mkdtempSync(join(tmpdir(), "smda-runner-repo-"));
  const gitConfigPaths: string[] = [];
  const deps = {
    run: async (options: Record<string, unknown>) => {
      const env = (options.sandbox as { env?: Record<string, string> }).env;
      if (env?.GIT_CONFIG_GLOBAL) {
        gitConfigPaths.push(env.GIT_CONFIG_GLOBAL);
      }
      return {
        output: {
          verdict: "DONE",
          required_next_action: "submit_for_spec_review",
          report: "implemented",
        },
        commits: [{ sha: "abc123" }],
        branch: "smda/child-A",
      };
    },
    outputObject: (options: { tag: string; schema: unknown }) => ({
      fakeOutput: options,
    }),
    agentProvider: () => ({ fakeAgent: true }),
  };

  await Promise.all([
    runRoleAttempt(
      { ...baseRequest, attempt_id: "attempt/with:unsafe chars", cwd: repo },
      deps,
    ),
    runRoleAttempt({ ...baseRequest, attempt_id: "attempt-2", cwd: repo }, deps),
  ]);

  assert.equal(gitConfigPaths.length, 2);
  assert.notEqual(gitConfigPaths[0], gitConfigPaths[1]);
  assert.equal(
    dirname(gitConfigPaths[0]),
    join(repo, ".sandcastle", "gitconfigs"),
  );
  assert.equal(
    basename(gitConfigPaths[0]),
    "attempt_with_unsafe_chars.gitconfig",
  );
  assert.equal(basename(gitConfigPaths[1]), "attempt-2.gitconfig");
});

test("publishes dirty branch worktree changes as a candidate commit", async () => {
  const repo = mkdtempSync(join(tmpdir(), "smda-runner-repo-"));
  const worktreesDir = join(repo, ".sandcastle", "worktrees");
  const candidateWorktree = join(worktreesDir, "smda-child-A");
  git(repo, ["init"]);
  git(repo, ["config", "user.name", "Test User"]);
  git(repo, ["config", "user.email", "test@example.invalid"]);
  writeFileSync(join(repo, "README.md"), "base\n");
  git(repo, ["add", "README.md"]);
  git(repo, ["commit", "-m", "base"]);
  git(repo, ["worktree", "add", "-b", "smda/child-A", candidateWorktree]);
  mkdirSync(join(candidateWorktree, "shim"), { recursive: true });

  const result = await runRoleAttempt(
    {
      ...baseRequest,
      cwd: repo,
      branch: "smda/child-A",
    },
    {
      run: async () => {
        writeFileSync(
          join(candidateWorktree, "shim", "workflows.py"),
          "def create_workflow():\n    return 'ok'\n",
        );
        return {
          output: {
            verdict: "DONE",
            required_next_action: "submit_for_spec_review",
            report: "implemented",
          },
          commits: [],
          branch: "smda/child-A",
        };
      },
      outputObject: (options) => ({ fakeOutput: options }),
      sandboxProvider: () => ({ fakeSandbox: true }),
      agentProvider: () => ({ fakeAgent: true }),
    },
  );

  assert.equal(result.status, "succeeded");
  assert.equal(result.commits.length, 1);
  const [commit] = result.commits;
  assert.match(commit.sha, /^[0-9a-f]{40}$/);
  assert.equal(
    readFileSync(join(candidateWorktree, "shim", "workflows.py"), "utf8"),
    "def create_workflow():\n    return 'ok'\n",
  );
  assert.equal(git(candidateWorktree, ["status", "--short"]), "");
  assert.match(
    git(repo, ["show", "--stat", "--oneline", commit.sha]),
    /shim\/workflows.py/,
  );
});

test("reports unknown role schema ids as protocol failures", async () => {
  const result = await runRoleAttempt(
    {
      ...baseRequest,
      schema_id: "smda.unknown-result.v1",
    },
    {
      run: async () => {
        throw new Error("should not run");
      },
      outputObject: (options) => ({ fakeOutput: options }),
      sandboxProvider: () => ({ fakeSandbox: true }),
      agentProvider: () => ({ fakeAgent: true }),
    },
  );

  assert.equal(result.status, "agent_protocol_failed");
  assert.equal(result.attempt_id, "attempt-1");
  assert.equal(result.schema_id, "smda.unknown-result.v1");
  assert.equal(result.schema_package_version, "0.1.0");
  assert.match(result.error_message, /Unknown SMDA role schema id/);
});

function git(cwd: string, args: string[]): string {
  return execFileSync("git", args, {
    cwd,
    encoding: "utf8",
    env: {
      ...process.env,
      GIT_AUTHOR_NAME: "Test User",
      GIT_AUTHOR_EMAIL: "test@example.invalid",
      GIT_COMMITTER_NAME: "Test User",
      GIT_COMMITTER_EMAIL: "test@example.invalid",
    },
  }).trim();
}

test("accepts the parent graph decomposer result schema", async () => {
  const seenOptions: unknown[] = [];

  const result = await runRoleAttempt(
    {
      ...baseRequest,
      attempt_id: "parent-graph-1",
      role: "graph_decomposer",
      phase: "GRAPH_DECOMPOSING",
      branch: "smda/danny-66/graph-decomposing",
      context_packet: {
        parent_issue_id: "DANNY-66",
        spec_path: "docs/superpowers/specs/smda.md",
      },
      prompt: "Decompose the approved parent spec",
      output_tag: "smda_graph_decomposer_result",
      schema_id: "smda.graph-decomposer-result.v1",
    },
    {
      run: async (options) => {
        seenOptions.push(options);
        return {
          output: {
            verdict: "DONE",
            required_next_action: "submit_for_graph_review",
            children: [completeGraphChild],
          },
          commits: [],
          branch: "smda/danny-66/graph-decomposing",
        };
      },
      outputObject: (options) => ({ fakeOutput: options }),
      sandboxProvider: () => ({ fakeSandbox: true }),
      agentProvider: () => ({ fakeAgent: true }),
    },
  );

  assert.equal(result.status, "succeeded");
  assert.equal(result.schema_id, "smda.graph-decomposer-result.v1");
  if (result.status === "succeeded") {
    assert.equal("children" in result.result, true);
    if (!("children" in result.result)) {
      throw new Error("graph decomposer result missing children");
    }
    assert.deepEqual(result.result.children, [completeGraphChild]);
  }
  const options = seenOptions[0] as {
    output: { fakeOutput: { tag: string; schema: unknown } };
  };
  assert.equal(options.output.fakeOutput.tag, "smda_graph_decomposer_result");
  assert.equal(options.output.fakeOutput.schema, graphDecomposerResultSchema);
});

test("accepts the roadmap decomposer result schema and requires parents", () => {
  const schema = roleResultSchemaForId("smda.roadmap-decomposer-result.v1");

  const parsed = schema.parse({
    verdict: "DONE",
    required_next_action: "publish_roadmap_parents",
    parents: [
      {
        node_id: "parent-001",
        title: "Introduce roadmap member store",
        body: "Add durable storage for roadmap member parent specs.",
        risk_level: "medium",
        dependencies: [],
      },
    ],
    roadmap_edges: [
      {
        from: "parent-001",
        to: "parent-002",
        type: "code_dependency",
        blocks_dispatch: true,
        reason: "parent-002 reads the member store.",
      },
    ],
  });

  assert.equal("parents" in parsed, true);
  assert.throws(() =>
    schema.parse({
      verdict: "DONE",
      required_next_action: "publish_roadmap_parents",
      parents: [],
    }),
  );
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
  assert.equal(structured.schema_id, "smda.child-implementer-result.v1");
  assert.equal(structured.schema_package_version, "0.1.0");
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
  assert.equal(execution.schema_id, "smda.child-implementer-result.v1");
  assert.equal(execution.schema_package_version, "0.1.0");
  assert.match(execution.error_message ?? "", /docker unavailable/);
});
