import assert from "node:assert/strict";
import { test } from "node:test";

import { runRoleAttempt } from "../src/runRoleAttempt.ts";

// Live Sandcastle execution smoke. Runs ONE real role attempt through the
// default Sandcastle dependencies (noSandbox provider + a real agent) and
// asserts a typed `succeeded` result.
//
// Skipped unless explicitly opted in, so the normal `npm run test:ts` gate
// never spawns an agent or needs credentials. Enable with:
//
//   SMDA_SMOKE_SANDCASTLE=1          # opt in
//   SMDA_SMOKE_CWD=/path/to/git/repo # branchable working tree for the attempt
//   SMDA_SMOKE_AGENT_PROVIDER=codex  # optional: codex (default) | claudeCode
//   SMDA_SMOKE_AGENT_MODEL=...       # optional: default codex model is gpt-5.5
//   <plus whatever credentials the chosen agent provider requires>
//
// Then:
//   SMDA_SMOKE_SANDCASTLE=1 SMDA_SMOKE_CWD=$(pwd) npm run test:ts

function skipReason(): string | false {
  if (process.env.SMDA_SMOKE_SANDCASTLE !== "1") {
    return "set SMDA_SMOKE_SANDCASTLE=1 to run the live Sandcastle smoke test";
  }
  if (!process.env.SMDA_SMOKE_CWD) {
    return "set SMDA_SMOKE_CWD to a branchable git working tree";
  }
  return false;
}

test(
  "live Sandcastle run produces a typed role result",
  { skip: skipReason() },
  async () => {
    const provider =
      process.env.SMDA_SMOKE_AGENT_PROVIDER === "claudeCode"
        ? "claudeCode"
        : "codex";
    const model =
      process.env.SMDA_SMOKE_AGENT_MODEL ??
      (provider === "codex" ? "gpt-5.5" : "claude-opus-4-8");

    const request = {
      attempt_id: `smoke-${Date.now()}`,
      role: "child_implementer",
      phase: "IMPLEMENTING",
      branch: `smda-smoke/${Date.now()}`,
      cwd: process.env.SMDA_SMOKE_CWD as string,
      context_packet: { smoke: true },
      prompt:
        "This is a connectivity smoke test. Create or update smda-smoke.txt " +
        "with the text 'smoke ok'. " +
        "Emit exactly this JSON inside the result tag: " +
        '<smda_child_implementer_result>{"verdict":"DONE",' +
        '"required_next_action":"submit_for_spec_review",' +
        '"report":"smoke ok"}</smda_child_implementer_result>',
      output_tag: "smda_child_implementer_result",
      schema_id: "smda.child-implementer-result.v1",
      sandbox_provider: "noSandbox",
      agent: { provider, model },
    };

    const result = await runRoleAttempt(request);

    assert.equal(
      result.status,
      "succeeded",
      `expected succeeded, got ${result.status}: ${
        "error_message" in result ? result.error_message : ""
      }`,
    );
    if (result.status === "succeeded") {
      assert.equal(result.attempt_id, request.attempt_id);
      assert.equal(result.schema_id, request.schema_id);
      assert.ok(
        "verdict" in result.result && result.result.verdict.length > 0,
        "expected a verdict in the typed result",
      );
      assert.ok(result.commits.length > 0, "expected a published commit");
    }
  },
);
