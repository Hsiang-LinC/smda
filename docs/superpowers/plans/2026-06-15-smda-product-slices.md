# SMDA Product Slices Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the SMDA Scheduler product from the boot contract outward, preserving the three-tier boundary.

**Architecture:** Start with Tier 1 boot validation and fake Tier 2 adapters, then add workflow routing, scheduling, Sandcastle execution, backlog adapters, and setup-skill integration. Each slice must be independently testable and must not require a real tracker or agent runtime until the adapter slices.

**Tech Stack:** Python scheduler core, pytest, JSON/YAML config loading, fake adapters for core tests, later TypeScript Sandcastle runner behind JSON IPC.

---

## File Structure

- `pyproject.toml`: project metadata, runtime dependencies, pytest config.
- `packages/scheduler/src/smda_scheduler/`: Python runtime package.
- `packages/scheduler/src/smda_scheduler/config.py`: config loading, validation, workspace id derivation.
- `packages/scheduler/src/smda_scheduler/adapters.py`: adapter protocols, capability sets, registry, negotiation.
- `packages/scheduler/src/smda_scheduler/errors.py`: named boot/config/capability errors.
- `packages/scheduler/tests/`: pytest suite for boot contract and future core behavior.
- `docs/superpowers/plans/2026-06-15-smda-product-slices.md`: this plan.

---

### Task 1: Boot Contract Package Skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `packages/scheduler/src/smda_scheduler/__init__.py`
- Create: `packages/scheduler/src/smda_scheduler/errors.py`
- Test: `packages/scheduler/tests/test_config.py`

- [x] **Step 1: Write failing import/config test**

```python
from pathlib import Path

from smda_scheduler.config import load_config


def test_loads_minimal_json_config(tmp_path: Path):
    config_path = tmp_path / "smda.config.json"
    config_path.write_text(
        """
        {
          "config_schema_version": 1,
          "runtime": {"version_constraint": ">=0.1.0", "state_root": ".smda/state", "artifact_root": ".smda/artifacts"},
          "adapters": {
            "execution": {"id": "fake-execution", "version_constraint": ">=0.1.0", "provider": "noSandbox"},
            "backlog": {"id": "fake-backlog", "version_constraint": ">=0.1.0", "scope_id": "demo"},
            "context": {"id": "fake-context", "version_constraint": ">=0.1.0"}
          },
          "schemas": {"role_schema_package_version": ">=0.1.0"},
          "context": {"bootloader_path": "AGENTS.md", "spec_locations": ["docs"], "quality_gates": ["pytest"]},
          "policy": {"issue_entry": "explicit-only", "qa": {"max_same_feedback_fingerprint": 2, "max_total_remediation_children": 3, "max_parent_qa_cycles": 2}},
          "prompts": {"overrides_dir": null},
          "labels": {}
        }
        """,
        encoding="utf-8",
    )

    config = load_config(config_path, repo_root=tmp_path)

    assert config.runtime.state_root == ".smda/state"
    assert config.adapters.backlog.scope_id == "demo"
```

- [x] **Step 2: Run red test**

Run: `PYTHONPATH=packages/scheduler/src pytest packages/scheduler/tests/test_config.py -q`
Expected: FAIL because `smda_scheduler.config` does not exist.

- [x] **Step 3: Add minimal package skeleton and loader**

Implement dataclasses for the config shape, JSON loading, required field checks, and named errors.

- [x] **Step 4: Run green test**

Run: `PYTHONPATH=packages/scheduler/src pytest packages/scheduler/tests/test_config.py -q`
Expected: PASS.

---

### Task 2: Workspace Identity And Paths

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/config.py`
- Test: `packages/scheduler/tests/test_config.py`

- [x] **Step 1: Write failing tests for derived workspace id and paths**

Test that `workspace_id` is derived from canonical repo root, backlog adapter id, and backlog scope id, and that ledger/artifact paths are namespaced under configured roots.

- [x] **Step 2: Run red test**

Run: `PYTHONPATH=packages/scheduler/src pytest packages/scheduler/tests/test_config.py -q`
Expected: FAIL because workspace derivation does not exist.

- [x] **Step 3: Implement derivation**

Use `sha256(f"{canonical_repo_root}|{backlog_adapter_id}|{backlog_scope_id}")[:16]`.

- [x] **Step 4: Run green test**

Run: `PYTHONPATH=packages/scheduler/src pytest packages/scheduler/tests/test_config.py -q`
Expected: PASS.

---

### Task 3: Adapter Capability Negotiation

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/adapters.py`
- Test: `packages/scheduler/tests/test_adapters.py`

- [x] **Step 1: Write failing tests for required and optional capabilities**

Test that missing required capability raises `CapabilityError`, while missing optional capability records fallback names.

- [x] **Step 2: Run red test**

Run: `PYTHONPATH=packages/scheduler/src pytest packages/scheduler/tests/test_adapters.py -q`
Expected: FAIL because adapter negotiation does not exist.

- [x] **Step 3: Implement minimal protocols and negotiation**

Create `CapabilitySet`, `AdapterDescriptor`, `WorkflowRequirements`, `NegotiationResult`, and `negotiate_capabilities`.

- [x] **Step 4: Run green test**

Run: `PYTHONPATH=packages/scheduler/src pytest packages/scheduler/tests/test_adapters.py -q`
Expected: PASS.

---

### Task 4: Boot Gate

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/boot.py`
- Test: `packages/scheduler/tests/test_boot.py`

- [x] **Step 1: Write failing tests for successful boot and refused boot**

Test successful boot with fake adapters, refusal on missing required capability, and refusal on config schema mismatch.

- [x] **Step 2: Run red test**

Run: `PYTHONPATH=packages/scheduler/src pytest packages/scheduler/tests/test_boot.py -q`
Expected: FAIL because boot gate does not exist.

- [x] **Step 3: Implement boot gate**

Load config, derive workspace, resolve fake adapter descriptors, negotiate workflow requirements, and return a `BootResult`.

- [x] **Step 4: Run green test**

Run: `PYTHONPATH=packages/scheduler/src pytest packages/scheduler/tests/test_boot.py -q`
Expected: PASS.

---

### Task 5: Slice 1 Verification And Commit

**Files:**
- Modify: all files from Tasks 1-4.

- [x] **Step 1: Run all Slice 1 tests**

Run: `PYTHONPATH=packages/scheduler/src pytest packages/scheduler/tests -q`
Expected: all tests PASS.

- [x] **Step 2: Run docs/code sanity checks**

Run: `git diff --check`
Expected: no output, exit 0.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml packages/scheduler docs/superpowers/plans/2026-06-15-smda-product-slices.md
git commit -m "Implement SMDA boot contract slice"
```

---

## Later Slices

### Task 13: Setup Skill Integration

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/cli.py`
- Test: `packages/scheduler/tests/test_cli.py`
- External update: `/Users/danny/codex-local-marketplace/plugins/engineering/skills/setup-smda-automation/SKILL.md`

- [x] **Step 1: Write failing tests for product boot validation CLI**

Run: `uv run pytest packages/scheduler/tests/test_cli.py -q`
Expected: FAIL because `smda_scheduler.cli` does not exist.

- [x] **Step 2: Implement `validate-config` CLI**

Expose non-live validation only: load config, run boot gate, print workspace
summary or named config error.

- [x] **Step 3: Update setup skill to Tier-3 config/wiring only**

Remove instructions to vendor runtime engine/adapter code, copied schema
validators, workflow manifests, report parsers, and hand-parsed `<output>`
requirements.

- [x] **Step 4: Run green tests**

Run: `uv run pytest packages/scheduler/tests -q`
Expected: PASS.

### Task 12: Test Fake Backlog Fixture Contract

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/backlog.py`
- Test: `packages/scheduler/tests/test_backlog.py`

- [x] **Step 1: Write failing adapter contract tests**

Test issue fetch, comments, coarse state updates, child creation, hierarchy
projection, and blocking relation projection against a test-only fake adapter.

- [x] **Step 2: Run red test**

Run: `uv run pytest packages/scheduler/tests/test_backlog.py -q`
Expected: FAIL because `smda_scheduler.backlog` does not exist.

- [x] **Step 3: Implement test fake adapter**

Keep `BacklogIssue`/`BacklogError` in product code as shared types. Keep the
fake adapter implementation in scheduler tests, not in product code.

- [x] **Step 4: Run green test**

Run: `uv run pytest packages/scheduler/tests/test_backlog.py -q`
Expected: PASS.

### Task 10: Sandcastle Role Attempt Runner

**Files:**
- Create: `package.json`
- Create: `tsconfig.json`
- Create: `packages/sandcastle-runner/src/runRoleAttempt.ts`
- Test: `packages/sandcastle-runner/tests/runRoleAttempt.test.ts`

- [x] **Step 1: Write failing tests for request validation, Sandcastle option mapping, and failure mapping**

Run: `npm run test:ts`
Expected: FAIL because `runRoleAttempt.ts` does not exist.

- [x] **Step 2: Implement runner with injected Sandcastle dependencies**

Use `Output.object` for structured output, branch strategy `{ type: "branch" }`,
and status mapping for `structured_output_failed` vs `execution_failed`.

- [x] **Step 3: Run green tests and typecheck**

Run: `npm run test:ts && npm run typecheck`
Expected: PASS.

### Task 11: JSON IPC CLI Wrapper

**Files:**
- Create: `packages/sandcastle-runner/src/cli.ts`
- Test: `packages/sandcastle-runner/tests/cli.test.ts`

- [x] **Step 1: Write failing tests for JSON stdout and protocol failure stderr**

Run: `npm run test:ts`
Expected: FAIL because `cli.ts` does not exist.

- [x] **Step 2: Implement `runCli` and stdin/stdout main**

Keep CLI as transport only: parse JSON, call runner, emit JSON.

- [x] **Step 3: Run green tests and typecheck**

Run: `npm run test:ts && npm run typecheck`
Expected: PASS.

### Task 8: Scheduling Run Loop With Fake Execution

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/scheduling.py`
- Test: `packages/scheduler/tests/test_scheduling.py`

- [x] **Step 1: Write failing tests for scan, claim, dispatch, and phase update**

Test that the scheduler asks workflow for eligible children, claims one child,
dispatches a fake role attempt, records the attempt, clears the claim, and
applies the workflow transition.

- [x] **Step 2: Run red test**

Run: `uv run pytest packages/scheduler/tests/test_scheduling.py -q`
Expected: FAIL because `smda_scheduler.scheduling` does not exist.

- [x] **Step 3: Implement minimal run loop**

Add scheduling state, fake attempt result handling, claim/lease fields, and
`run_once`.

- [x] **Step 4: Run green test**

Run: `uv run pytest packages/scheduler/tests/test_scheduling.py -q`
Expected: PASS.

### Task 9: Retry, Backoff, And Claim Reconciliation

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/scheduling.py`
- Modify: `packages/scheduler/src/smda_scheduler/workflow.py`
- Test: `packages/scheduler/tests/test_scheduling.py`

- [x] **Step 1: Write failing tests for execution failure, retry backoff, exhaustion, and expired claim repair**

Test transient failure backoff, max-attempt exhaustion to human review, and
reconciliation of expired claims.

- [x] **Step 2: Run red test**

Run: `uv run pytest packages/scheduler/tests/test_scheduling.py -q`
Expected: FAIL because retry/backoff/reconcile behavior does not exist.

- [x] **Step 3: Implement retry/backoff/reconcile**

Add scheduler-owned attempt limits, `next_not_before`, and
`reconcile_expired_claims`.

- [x] **Step 4: Run green test**

Run: `uv run pytest packages/scheduler/tests/test_scheduling.py -q`
Expected: PASS.

### Task 14: Persistent Child Phase Ledger

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/phase_ledger.py`
- Modify: `packages/scheduler/src/smda_scheduler/scheduling.py`
- Test: `packages/scheduler/tests/test_phase_ledger.py`

- [x] **Step 1: Write failing tests for durable child state and pre-dispatch claim persistence**

Test that child phase, attempt count, claim, and backoff metadata persist across
new ledger instances, and that `run_once_durable` writes the claim before the
executor starts.

- [x] **Step 2: Run red test**

Run: `uv run pytest packages/scheduler/tests/test_phase_ledger.py -q`
Expected: FAIL because `smda_scheduler.phase_ledger` does not exist.

- [x] **Step 3: Implement minimal SQLite phase ledger**

Add `PhaseLedger` with `load_scheduler_state` / `save_scheduler_state`, plus a
durable scheduling wrapper that persists claimed and terminal states through a
state sink.

- [x] **Step 4: Run green test**

Run: `uv run pytest packages/scheduler/tests/test_phase_ledger.py -q`
Expected: PASS.

Note: this slice intentionally covers child phase/claim truth only. Full
attempt request/result records and idempotency keys remain part of the execution
adapter / attempt-ledger slice.

### Task 15: Linear Backlog Adapter

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/linear_backlog.py`
- Test: `packages/scheduler/tests/test_linear_backlog.py`

- [x] **Step 1: Check current Linear GraphQL docs**

Use Linear developer docs for `issueCreate`, `issueUpdate`, `commentCreate`,
`issueRelationCreate`, GraphQL endpoint, and personal API key auth.

- [x] **Step 2: Write failing adapter contract tests**

Test descriptor capabilities, issue fetch mapping, coarse state updates,
comments, child creation with parent, hierarchy projection, blocking relation
projection, GraphQL error mapping, and HTTP transport request shape.

- [x] **Step 3: Implement transport-injected Linear adapter**

Add a GraphQL transport protocol, stdlib HTTP transport, and
`LinearBacklogAdapter` methods for the MVP backlog contract. Keep credential
wiring outside the adapter so daemon/setup can own secret resolution.

- [x] **Step 4: Run green test**

Run: `uv run pytest packages/scheduler/tests/test_linear_backlog.py -q`
Expected: PASS.

Note: this slice does not perform a live Linear smoke test. Live credentials,
workspace/team/state-id resolution, and daemon wiring are later setup/control
surface work.

### Task 16: Python-To-Sandcastle Execution Adapter

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/sandcastle_execution.py`
- Modify: `packages/scheduler/src/smda_scheduler/scheduling.py`
- Test: `packages/scheduler/tests/test_sandcastle_execution.py`

- [x] **Step 1: Inspect TS runner IPC contract**

Read `packages/sandcastle-runner/src/runRoleAttempt.ts` and `cli.ts` to use the
actual JSON request/result shape already tested on the TypeScript side.

- [x] **Step 2: Write failing Python adapter tests**

Test successful result mapping, structured-output failure mapping, protocol
failure mapping, and the exact JSON request sent to the subprocess runner.

- [x] **Step 3: Implement subprocess JSON IPC adapter**

Add `RoleAttemptRequest`, `ProcessResult`, and `SandcastleExecutionAdapter`.
Map TS runner statuses into scheduler `AttemptOutcome` without letting Python
know Sandcastle internals.

- [x] **Step 4: Run green test**

Run: `uv run pytest packages/scheduler/tests/test_sandcastle_execution.py -q`
Expected: PASS.

Note: this slice does not assemble prompts/context packets or decide role
routing. It only provides the execution adapter used once workflow routing has
selected a role attempt.

### Task 17: Daemon Control Loop Surface

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/daemon.py`
- Modify: `packages/scheduler/src/smda_scheduler/cli.py`
- Test: `packages/scheduler/tests/test_daemon.py`
- Test: `packages/scheduler/tests/test_cli.py`

- [x] **Step 1: Write failing daemon loop and CLI control tests**

Test max-tick stopping, tick failure reporting, injected CLI tick execution, and
explicit failure when the CLI daemon command is not wired to a live tick
function.

- [x] **Step 2: Implement pure daemon loop**

Add `TickResult`, `DaemonResult`, and `run_daemon` with injected `tick` and
`sleep` functions.

- [x] **Step 3: Add CLI daemon command**

Expose `smda-scheduler daemon --max-ticks --interval-seconds` as a control
surface. Keep live scanning unwired unless a tick function is supplied by the
runtime composition layer.

- [x] **Step 4: Run green tests**

Run: `uv run pytest packages/scheduler/tests/test_daemon.py packages/scheduler/tests/test_cli.py -q`
Expected: PASS.

Note: this slice intentionally does not scan Linear or assemble context
packets. It only provides the daemon lifecycle/control surface that later
runtime wiring will call.

### Task 18: Setup Skill Product Boundary Refresh

**Files:**
- External modify:
  `/Users/danny/codex-local-marketplace/plugins/engineering/skills/setup-smda-automation/SKILL.md`
- External modify:
  `/Users/danny/codex-local-marketplace/plugins/engineering/skills/setup-smda-automation/adapters.md`
- External modify:
  `/Users/danny/codex-local-marketplace/plugins/engineering/skills/setup-smda-automation/methodology.md`

- [x] **Step 1: Inspect current setup skill instructions**

Confirm whether the skill still treats prompts, schemas, reports, manifests,
or legacy Symphony runtime files as target-repo artifacts.

- [x] **Step 2: Refresh Tier-3 boundary wording**

Make the skill say that SMDA Scheduler owns runtime contracts and setup owns
config, harness/bootloader routing, tracker notes, local secrets, ignored state
paths, and optional prompt wording/context overrides.

- [x] **Step 3: Remove misleading adapter defaults**

Make Linear the MVP backlog default. GitHub/local-file/custom trackers require
product adapters and must not be generated by setup.

- [x] **Step 4: Update validation language**

Use product boot/config validation and product role-schema compatibility.
Do not validate copied schema files, report parsers, or setup-installed
workflow manifests.

Note: the skill directory is currently untracked in the local engineering
plugin repo, which also has unrelated dirty files. This slice updates the files
in place but does not commit that external repo.

### Task 19: Product Adapter Registry

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/boot.py`
- Modify: `packages/scheduler/src/smda_scheduler/adapters.py`
- Modify: `packages/scheduler/tests/helpers.py`
- Test: `packages/scheduler/tests/test_boot.py`
- Test: `packages/scheduler/tests/test_cli.py`

- [x] **Step 1: Write failing tests for real adapter ids**

Test that a config using `sandcastle`, `linear`, and `codex-harness` boots and
validates without injecting a test registry, while fake adapter ids still fail
unless tests inject a fake registry.

- [x] **Step 2: Implement product registry descriptors**

Add product descriptors for Sandcastle execution, Linear backlog, and Codex
harness context capabilities.

- [x] **Step 3: Keep fake adapters out of product registry**

Use the product registry only when no explicit registry is supplied. Tests can
still inject fake descriptors; consumer setup cannot accidentally boot fake ids.

- [x] **Step 4: Run green tests**

Run: `uv run pytest packages/scheduler/tests/test_boot.py packages/scheduler/tests/test_cli.py -q`
Expected: PASS.

Note: this slice validates adapter availability/capabilities. It does not wire
Linear credentials, context packet discovery, or live daemon scanning.

### Task 20: Attempt Request/Result Ledger

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/phase_ledger.py`
- Modify: `packages/scheduler/src/smda_scheduler/scheduling.py`
- Test: `packages/scheduler/tests/test_phase_ledger.py`

- [x] **Step 1: Write failing attempt-ledger tests**

Test request/result persistence, idempotency-key reuse, result+child-state
atomic update, and `run_once_durable` recording the attempt request before the
executor starts.

- [x] **Step 2: Implement SQLite attempt table**

Add `attempt_ledger` with `attempt_id`, `child_id`, target `phase`,
`idempotency_key`, status, request JSON, result JSON, and error message.

- [x] **Step 3: Wire durable scheduling**

Have `run_once_durable` record a deterministic attempt request before dispatch
and persist attempt result plus final child state through one ledger method.

- [x] **Step 4: Run green tests**

Run: `uv run pytest packages/scheduler/tests/test_phase_ledger.py -q`
Expected: PASS.

Note: this slice covers attempt request/result and idempotency evidence.
Tracker-effect retry state and crash recovery during parent accept remain
future durability slices.

### Task 21: Codex Harness Context Packet Discovery

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/context_packets.py`
- Test: `packages/scheduler/tests/test_context_packets.py`

- [x] **Step 1: Write failing context adapter tests**

Test repo packet discovery from `SmdaConfig`, adapter capabilities, missing
required bootloader handling, and repo-root path escape rejection.

- [x] **Step 2: Implement context packet dataclasses and adapter**

Add `RepoContextPacket`, `ContextDiscoveryError`, and
`CodexHarnessContextAdapter`.

- [x] **Step 3: Keep scope to discovery**

Resolve bootloader/spec/ADR locations and quality gates. Do not assemble
role-specific prompts, read the full spec graph, or scan Linear in this slice.

- [x] **Step 4: Run green tests**

Run: `uv run pytest packages/scheduler/tests/test_context_packets.py -q`
Expected: PASS.

Note: this slice makes issue-worker context discoverable from repo config. Live
daemon scanner wiring and role-specific context packet assembly remain later
slices.

### Task 22: Context Validation CLI

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/cli.py`
- Test: `packages/scheduler/tests/test_cli.py`
- External modify:
  `/Users/danny/codex-local-marketplace/plugins/engineering/skills/setup-smda-automation/SKILL.md`
- Consumer modify:
  `/Users/danny/Desktop/GitHub/trading-advisor/docs/harness/quality-gates.md`

- [x] **Step 1: Write failing CLI tests**

Test successful context summary output and `context_invalid` failure when the
configured repo context is missing.

- [x] **Step 2: Implement `validate-context`**

Load config and run `CodexHarnessContextAdapter.build_repo_packet`, returning
bootloader/spec/ADR/quality-gate summary JSON.

- [x] **Step 3: Update setup/consumer validation commands**

Add `validate-context` to the setup skill and trading-advisor quality gates so
consumer repos can prove worker context sources exist.

- [x] **Step 4: Run green tests**

Run: `uv run pytest packages/scheduler/tests/test_cli.py -q`
Expected: PASS.

Note: this still does not assemble role-specific packets or dispatch workers.
It is a non-live setup/boot gate.

### Task 23: Child Role Attempt Request Assembly

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/role_attempts.py`
- Modify: `packages/scheduler/src/smda_scheduler/sandcastle_execution.py`
- Modify: `packages/sandcastle-runner/src/runRoleAttempt.ts`
- Test: `packages/scheduler/tests/test_role_attempts.py`
- Test: `packages/scheduler/tests/test_sandcastle_execution.py`
- Test: `packages/sandcastle-runner/tests/runRoleAttempt.test.ts`

- [x] **Step 1: Write failing request assembly tests**

Test that child phase maps to product-owned role names, branch names,
structured context packets, prompt text, output tag, and schema id.

- [x] **Step 2: Implement role request builder**

Add `ChildTaskContext`, `AgentSelection`, phase-to-role routing, branch naming,
and prompt/context packet assembly for child role attempts.

- [x] **Step 3: Carry `context_packet` through Sandcastle IPC**

Add `context_packet` to the Python request payload and TypeScript runner
request schema so execution receives structured context evidence, not only
freeform prompt text.

- [x] **Step 4: Run green tests**

Run:
`uv run pytest packages/scheduler/tests/test_role_attempts.py packages/scheduler/tests/test_sandcastle_execution.py -q`
and `npm run test:ts && npm run typecheck`.

Note: this still does not scan Linear or start live daemons. It closes the
product-owned handoff between workflow phase selection and execution adapter
dispatch.

### Task 24: Attempt Dispatch Context

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/scheduling.py`
- Modify: `packages/scheduler/tests/test_scheduling.py`
- Modify: `packages/scheduler/tests/test_phase_ledger.py`

- [x] **Step 1: Write failing executor-shape tests**

Test that schedulers pass `AttemptDispatch` to executors with child id, phase,
attempt id, attempt number, and owner.

- [x] **Step 2: Implement dispatch context**

Add `AttemptDispatch` and make both in-memory and durable scheduling use one
deterministic attempt id/idempotency calculation.

- [x] **Step 3: Preserve ledger guarantees**

Keep claim persistence before dispatch and result+state persistence after
dispatch, while passing the resolved attempt id to the executor.

- [x] **Step 4: Run green tests**

Run:
`uv run pytest packages/scheduler/tests/test_scheduling.py packages/scheduler/tests/test_phase_ledger.py -q`
and the full product gate.

Note: this makes execution adapter dispatch possible without duplicating
attempt id logic outside the scheduler.

### Task 25: Runtime Child Tick Composition

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/runtime.py`
- Test: `packages/scheduler/tests/test_runtime.py`

- [x] **Step 1: Write failing composition tests**

Test that a child workflow tick loads durable state, receives scheduler dispatch
context, builds a typed `RoleAttemptRequest`, calls the execution adapter, and
persists the resulting child phase/attempt state.

- [x] **Step 2: Implement runtime composition layer**

Add `RoleExecutionAdapter` protocol and `run_child_workflow_tick`, connecting
workflow graph, child task context, repo context packet, phase ledger, role
request builder, and execution adapter.

- [x] **Step 3: Keep live backlog scanning out of scope**

This slice accepts graph/task inputs directly. Linear polling, parent graph
publication, and daemon live scanning remain separate slices.

- [x] **Step 4: Run green tests**

Run: `uv run pytest packages/scheduler/tests/test_runtime.py -q` and the full
product gate.

Note: this is the first product-owned path that proves SMDA can select a child
phase and dispatch a typed Sandcastle-compatible role attempt without setup
skill code.

### Task 26: Backlog Candidate Scanner

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/scanner.py`
- Modify: `packages/scheduler/src/smda_scheduler/backlog.py`
- Modify: `packages/scheduler/src/smda_scheduler/linear_backlog.py`
- Test: `packages/scheduler/tests/test_scanner.py`
- Test: `packages/scheduler/tests/test_linear_backlog.py`

- [x] **Step 1: Check Linear filtering docs**

Use Context7 Linear developer docs to confirm issue filters, relationship
filters, team issue connections, and Relay pagination.

- [x] **Step 2: Write scanner and Linear adapter tests**

Test adapter-neutral candidate scanning and Linear `list_issues` mapping for
state, label, parent, limit, cursor, labels, and page info.

- [x] **Step 3: Implement narrow scanner**

Add `BacklogPage`, `CandidateBacklog`, `scan_dispatch_candidates`, and
`LinearBacklogAdapter.list_issues`.

- [x] **Step 4: Run green tests**

Run:
`uv run pytest packages/scheduler/tests/test_scanner.py packages/scheduler/tests/test_linear_backlog.py -q`
and the full product gate.

Note: scanner discovers backlog candidates only. It does not decide workflow
phase, publish child graphs, mutate tracker state, or wire live credentials.

### Task 27: Tracker Effect Retry Ledger

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/phase_ledger.py`
- Create: `packages/scheduler/src/smda_scheduler/reconciliation.py`
- Modify: `packages/scheduler/tests/test_phase_ledger.py`
- Test: `packages/scheduler/tests/test_reconciliation.py`

- [x] **Step 1: Write failing ledger tests**

Test idempotent tracker-effect recording, pending-effect reload across ledger
instances, sent marking, and failed-effect error retention.

- [x] **Step 2: Implement tracker-effect ledger table**

Add `tracker_effect_ledger` with effect id, idempotency key, effect type,
target id, payload JSON, status, and last error.

- [x] **Step 3: Write failing reconciliation tests**

Test pending comment/state effects are sent through a tracker adapter and then
marked sent, while send failures remain pending for the next pass.

- [x] **Step 4: Implement retry primitive**

Add `retry_pending_tracker_effects` with a narrow `TrackerEffectSender`
protocol. Keep tracker API semantics inside the backlog adapter.

- [x] **Step 5: Run green tests**

Run:
`uv run pytest packages/scheduler/tests/test_phase_ledger.py packages/scheduler/tests/test_reconciliation.py -q`
and the full product gate.

Note: this does not create new tracker effects from workflow transitions yet.
It provides the durable outbox/retry primitive required before live daemon
operation.

### Task 28: Parent Accept Recovery Primitive

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/parent_acceptance.py`
- Modify: `packages/scheduler/src/smda_scheduler/phase_ledger.py`
- Test: `packages/scheduler/tests/test_parent_acceptance.py`

- [x] **Step 1: Write failing recovery tests**

Test that an already-integrated child candidate is recorded completed without
reapplying, and that a missing candidate is applied once even when the same
idempotency key is retried with a duplicate operation id.

- [x] **Step 2: Implement parent accept ledger table**

Add `parent_accept_ledger` with operation id, idempotency key, parent id, child
id, candidate ref, integration branch, status, and last error.

- [x] **Step 3: Implement recovery policy**

Add `ChildAcceptOperation`, `ParentIntegration`, and
`recover_or_apply_child_accept`. Recovery checks the integration branch probe
before applying, and marks completed or pending accordingly.

- [x] **Step 4: Run green tests**

Run:
`uv run pytest packages/scheduler/tests/test_parent_acceptance.py packages/scheduler/tests/test_phase_ledger.py -q`
and the full product gate.

Note: this slice intentionally does not implement concrete git branch
inspection/apply plumbing. It defines the idempotent recovery policy that the
git integration adapter must satisfy.

### Task 29: Workspace Tick Composition

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/workspace_tick.py`
- Test: `packages/scheduler/tests/test_workspace_tick.py`

- [x] **Step 1: Write failing workspace tick tests**

Test that a workspace tick retries pending tracker effects before dispatching a
candidate, and reports idle when no candidate is available.

- [x] **Step 2: Implement injectable tick composition**

Add `run_workspace_tick`, combining tracker-effect reconciliation, backlog
candidate scanning, and injected candidate dispatch into the daemon
`TickResult` shape.

- [x] **Step 3: Preserve live-side-effect boundary**

Keep Linear credentials, candidate-to-parent/child parsing, and Sandcastle
execution composition injected. The tick owns product order of operations, not
environment wiring.

- [x] **Step 4: Run green tests**

Run: `uv run pytest packages/scheduler/tests/test_workspace_tick.py -q` and the
full product gate.

Note: this is the product-owned daemon tick pipeline for tests and future live
wiring. It does not enable CLI daemon live mode by itself.

### Task 6: Workflow Graph And Child Phase Semantics

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/workflow.py`
- Test: `packages/scheduler/tests/test_workflow.py`

- [x] **Step 1: Write failing tests for graph eligibility and transition table**

Test dependency-gated child eligibility, unknown dependency rejection, cycle
rejection, and child role-result transitions.

- [x] **Step 2: Run red test**

Run: `uv run pytest packages/scheduler/tests/test_workflow.py -q`
Expected: FAIL because `smda_scheduler.workflow` does not exist.

- [x] **Step 3: Implement minimal workflow engine**

Add graph dataclasses, invariant validation, eligibility query, and a table
driven `transition_child_phase` function.

- [x] **Step 4: Run green test**

Run: `uv run pytest packages/scheduler/tests/test_workflow.py -q`
Expected: PASS.

### Task 7: QA Remediation Bounds

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/workflow.py`
- Test: `packages/scheduler/tests/test_workflow.py`

- [x] **Step 1: Write failing tests for QA feedback bounds**

Test same-feedback fingerprint limit and total remediation child limit.

- [x] **Step 2: Run red test**

Run: `uv run pytest packages/scheduler/tests/test_workflow.py -q`
Expected: FAIL because QA bound handling does not exist.

- [x] **Step 3: Implement minimal QA state**

Add `QaBounds`, `QaState`, and `record_qa_failure`.

- [x] **Step 4: Run green test**

Run: `uv run pytest packages/scheduler/tests/test_workflow.py -q`
Expected: PASS.

## Self-Review

- Spec coverage: Slice 1 covers config contract, workspace derivation, adapter capability negotiation, and boot gate. It intentionally does not cover workflow phases, daemon scheduling, Sandcastle IPC, or real backlog APIs.
- Placeholder scan: Later slices are named but intentionally not expanded into full task code until Slice 1 is complete and package conventions are established.
- Type consistency: Capability names use the snake_case contract from `docs/contracts.md`.
