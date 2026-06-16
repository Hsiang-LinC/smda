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

- [x] **Step 3: Commit**

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

Add `attempt_ledger` with `attempt_id`, `target_kind`, `target_id`, target `phase`,
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

### Task 23B: Product-Owned Child Role Contract Baseline

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/role_contracts.py`
- Create: `packages/sandcastle-runner/src/roleContracts.ts`
- Modify: `packages/scheduler/src/smda_scheduler/role_attempts.py`
- Modify: `packages/sandcastle-runner/src/runRoleAttempt.ts`
- Test: `packages/scheduler/tests/test_role_attempts.py`
- Test: `packages/scheduler/tests/test_runtime.py`
- Test: `packages/sandcastle-runner/tests/runRoleAttempt.test.ts`

- [x] **Step 1: Move child role names, schema ids, output tags, and prompt text behind a product registry**

Python scheduler dispatch now maps child phases through
`role_contracts.py` instead of hard-coded generic role strings.

- [x] **Step 2: Add TypeScript schema id lookup for Sandcastle `Output.object`**

The runner validates supported `schema_id` values through
`roleContracts.ts`. Unknown schema ids return `agent_protocol_failed`, not a
role verdict.

- [x] **Step 3: Preserve schema metadata in IPC and durable attempt results**

Runner results include `schema_id` and `schema_package_version`; Python maps
them into `AttemptOutcome` and persists them in attempt result JSON.

- [x] **Step 4: Keep setup skill out of role contract ownership**

The setup skill no longer carries prompt/template/schema/report bundles. It may
only configure prompt override references when the product supports
compatibility checks.

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

### Task 30: Git Parent Integration Adapter

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/git_integration.py`
- Test: `packages/scheduler/tests/test_git_integration.py`

- [x] **Step 1: Write failing git adapter tests**

Use temporary git repositories to test that the adapter detects an existing
candidate ref on the parent integration branch and cherry-picks a missing
candidate ref once.

- [x] **Step 2: Implement `ParentIntegration` adapter**

Add `GitParentIntegration`, using `git merge-base --is-ancestor` for recovery
inspection and `git switch` + `git cherry-pick` for candidate application.

- [x] **Step 3: Keep recovery policy separate**

Do not move ledger/idempotency decisions into the git adapter. The adapter only
answers branch truth and applies the candidate when the product recovery policy
asks it to.

- [x] **Step 4: Run green tests**

Run: `uv run pytest packages/scheduler/tests/test_git_integration.py -q` and
the full product gate.

Note: this provides the concrete git plumbing for
`recover_or_apply_child_accept`; it does not yet wire live parent closeout into
the daemon CLI.

### Task 31: Linear Environment Wiring

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/linear_backlog.py`
- Modify: `packages/scheduler/tests/test_linear_backlog.py`

- [x] **Step 1: Write failing factory tests**

Test that missing Linear environment variables raise a named config error, and
that supplied env values create an adapter using the API key, team id, and
state ids.

- [x] **Step 2: Implement environment factory**

Add `LinearConfigError` and `build_linear_backlog_adapter`, reading
`LINEAR_API_KEY`, `SMDA_LINEAR_TEAM_ID`, and `SMDA_LINEAR_STATE_<NAME>`.

- [x] **Step 3: Keep secrets out of repo config**

Do not add secrets to `smda.config.json`; live credentials remain local env or
local secret-manager concerns.

- [x] **Step 4: Run green tests**

Run: `uv run pytest packages/scheduler/tests/test_linear_backlog.py -q` and the
full product gate.

Note: this wires the default Linear adapter for live use without enabling live
daemon mode automatically.

### Task 32: Backlog Candidate Route Classification

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/candidate_routing.py`
- Modify: `packages/scheduler/src/smda_scheduler/workspace_tick.py`
- Test: `packages/scheduler/tests/test_candidate_routing.py`
- Test: `packages/scheduler/tests/test_workspace_tick.py`

- [x] **Step 1: Write failing route classification tests**

Test explicit `Execution: smda`, `Execution: smda-child`, obsolete
`Execution: orchestrator`, unsupported modes, explicit-only missing modes, and
implicit one-child normalization.

- [x] **Step 2: Implement minimal product classifier**

Add `CandidateRoutingDecision` and `CandidateRoute`. Keep parsing scoped to
tracker body fields and child handle context: parent issue, graph checksum, and
node id.

- [x] **Step 3: Wire route classification into workspace tick**

`run_workspace_tick` can now block invalid candidates with tracker-visible
pending effects, or pass a typed routing decision to an injected routed
dispatcher. The old single-argument dispatcher remains for tests and non-routed
composition.

- [x] **Step 4: Run green tests**

Run:
`uv run pytest packages/scheduler/tests/test_candidate_routing.py packages/scheduler/tests/test_workspace_tick.py -q`
and the full product gate.

Note: this slice does not implement parent graph decomposition/publication or
live child execution dispatch. It closes the scanner-to-routing gap so later
live daemon wiring can dispatch parent and child candidates without a prompt
reclassifying execution mode.

### Task 33: Routed Child Candidate Dispatch Composition

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py`
- Modify: `packages/scheduler/tests/test_runtime.py`
- Modify: `packages/scheduler/tests/test_workspace_tick.py`

- [x] **Step 1: Write failing runtime tests for routed child hydration**

Test that a `CandidateRoute.CHILD` decision plus a backlog child issue hydrates
`parent_issue_id`, `node_id`, title, body, and acceptance criteria into the
existing child phase machine.

- [x] **Step 2: Implement `run_child_candidate_tick`**

Compose a single child handle into `run_child_workflow_tick` using a one-node
graph and `ChildTaskContext`. Reject non-child routes before dispatch.

- [x] **Step 3: Add workspace tick integration coverage**

Prove a routed workspace tick can pass a child decision into
`run_child_candidate_tick` and produce a typed role attempt through the
execution adapter.

- [x] **Step 4: Run green tests**

Run:
`uv run pytest packages/scheduler/tests/test_runtime.py packages/scheduler/tests/test_workspace_tick.py -q`
and the full product gate.

Note: this slice intentionally does not read the full parent graph or publish
children. It connects already-dispatchable `smda-child` handles to the child
phase machine; dependency correctness remains upstream in graph/backlog
blocking.

### Task 34: Routed Parent Candidate Intake

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py`
- Modify: `packages/scheduler/src/smda_scheduler/phase_ledger.py`
- Modify: `packages/scheduler/tests/test_runtime.py`
- Modify: `packages/scheduler/tests/test_workspace_tick.py`
- Modify: `packages/scheduler/tests/test_phase_ledger.py`

- [x] **Step 1: Write failing parent intake tests**

Test that a routed `Execution: smda` parent blocks with no approved spec path,
routes draft specs to `Human Review`, and persists approved specs as
`SPEC_FINALIZED`.

- [x] **Step 2: Add durable parent run state**

Persist parent id, semantic phase, spec path, spec checksum, and approval
evidence in the SQLite phase ledger.

- [x] **Step 3: Implement `run_parent_candidate_intake`**

Parse the spec reference from the tracker body, validate the spec is under the
repo root, read simple front matter, compute a checksum, and return the next
coarse tracker state without starting graph decomposition.

- [x] **Step 4: Add workspace tick integration coverage**

Prove a routed parent candidate can flow through `run_workspace_tick` into
parent intake and persist `SPEC_FINALIZED`.

- [x] **Step 5: Run green tests**

Run:
`uv run pytest packages/scheduler/tests/test_runtime.py packages/scheduler/tests/test_workspace_tick.py packages/scheduler/tests/test_phase_ledger.py -q`
and the full product gate.

Note: this slice intentionally stops before graph decomposition and child
publication. It closes the parent scanner-to-spec-gate gap so the next slice can
dispatch product-owned graph decomposition/review attempts from durable parent
state.

### Task 35: Parent Graph Decomposer Role Request

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/workflow.py`
- Modify: `packages/scheduler/src/smda_scheduler/role_contracts.py`
- Modify: `packages/scheduler/src/smda_scheduler/role_attempts.py`
- Modify: `packages/scheduler/src/smda_scheduler/sandcastle_execution.py`
- Modify: `packages/sandcastle-runner/src/roleContracts.ts`
- Modify: `packages/scheduler/tests/test_role_attempts.py`
- Modify: `packages/sandcastle-runner/tests/runRoleAttempt.test.ts`

- [x] **Step 1: Write failing parent graph decomposer request tests**

Test that a product-owned parent graph decomposer request carries the approved
spec path, checksum, approval evidence, full spec text, bootloader, doc
locations, and quality gates.

- [x] **Step 2: Add the parent role contract**

Add `ParentPhase.GRAPH_DECOMPOSING`, the `graph_decomposer` role, schema id
`smda.graph-decomposer-result.v1`, output tag
`smda_graph_decomposer_result`, and a prompt that forbids child publication or
tracker mutation.

- [x] **Step 3: Add parent request assembly**

Add `ParentSpecContext` and `build_parent_graph_decomposer_request`, using the
same Sandcastle IPC request shape as child roles.

- [x] **Step 4: Register the schema id in the TS runner**

Allow `runRoleAttempt.ts` to resolve the graph decomposer schema id through the
product-owned `roleContracts.ts` registry.

- [x] **Step 5: Run focused green tests**

Run:
`uv run pytest packages/scheduler/tests/test_role_attempts.py -q`
and
`npm run test:ts -- --test-reporter=spec packages/sandcastle-runner/tests/runRoleAttempt.test.ts`.

Note: this slice intentionally stops before durable parent attempt dispatch,
graph review, graph persistence, child publication, and dependency projection.
The next slice should generalize or add the parent attempt ledger boundary
before running graph decomposer attempts from `SPEC_FINALIZED` parent state.

### Task 36: Durable Parent Graph Decomposition Dispatch

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/workflow.py`
- Modify: `packages/scheduler/src/smda_scheduler/phase_ledger.py`
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py`
- Modify: `packages/scheduler/tests/test_phase_ledger.py`
- Modify: `packages/scheduler/tests/test_runtime.py`

- [x] **Step 1: Write failing parent attempt ledger and runtime tests**

Test that role attempts can target a parent scope, and that a
`SPEC_FINALIZED` parent dispatches the graph decomposer with full approved spec
context.

- [x] **Step 2: Generalize attempt identity**

Keep the child scheduler API, but store attempts as
`target_kind + target_id + phase` so parent and child attempts use one durable
ledger without putting attempt history into parent/child run state.

- [x] **Step 3: Add parent graph decomposition tick**

Read the durable parent run, verify the spec checksum, build the graph
decomposer request, record the attempt request before execution, run the
execution adapter, and atomically record the result plus parent phase transition.

- [x] **Step 4: Transition successful decomposition to graph review**

Route `DONE + submit_for_graph_review` from `GRAPH_DECOMPOSING` to
`GRAPH_SPEC_REVIEWING`. Failed adapter/protocol/structured-output attempts are
recorded and block the parent with evidence.

- [x] **Step 5: Run focused green tests**

Run:
`uv run pytest packages/scheduler/tests/test_phase_ledger.py -q`
and
`uv run pytest packages/scheduler/tests/test_runtime.py::test_run_parent_graph_decomposition_tick_dispatches_from_spec_finalized -q`.

Note: this slice intentionally stops before parsing the graph-decomposer
result into an `smda-graph`, graph spec/execution review, child issue
publication, and backlog blocking projection.

### Task 37: Typed Graph Decomposer Output

**Files:**
- Modify: `packages/sandcastle-runner/src/roleContracts.ts`
- Modify: `packages/sandcastle-runner/src/runRoleAttempt.ts`
- Modify: `packages/sandcastle-runner/tests/runRoleAttempt.test.ts`
- Modify: `packages/scheduler/src/smda_scheduler/scheduling.py`
- Modify: `packages/scheduler/src/smda_scheduler/sandcastle_execution.py`
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py`
- Modify: `packages/scheduler/tests/test_sandcastle_execution.py`

- [x] **Step 1: Write failing typed graph output tests**

Test that the graph decomposer result schema carries child nodes with node id,
title, body, acceptance criteria, and dependencies, and that the Python
execution adapter preserves the full raw result.

- [x] **Step 2: Add the graph decomposer result schema**

Keep generic review/role results shared, but give
`smda.graph-decomposer-result.v1` a unique typed payload because it produces the
workflow graph artifact.

- [x] **Step 3: Preserve raw role output in scheduler outcomes**

Add `raw_result` to `AttemptOutcome` and map successful Sandcastle IPC results
without discarding graph payload fields.

- [x] **Step 4: Persist raw result fields in attempt result JSON**

Merge raw role result fields into scheduler/runtime attempt-result JSON so the
next graph persistence slice can read typed children from durable evidence.

- [x] **Step 5: Run focused green checks**

Run:
`npm run test:ts -- --test-reporter=spec packages/sandcastle-runner/tests/runRoleAttempt.test.ts`,
`npm run typecheck`, and
`uv run pytest packages/scheduler/tests/test_sandcastle_execution.py::test_sandcastle_execution_adapter_preserves_raw_graph_decomposer_result -q`.

Note: this slice intentionally stops before graph invariant validation, graph
review role dispatch, child issue publication, and dependency projection.

### Task 38: Durable SMDA Graph Persistence

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/phase_ledger.py`
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py`
- Modify: `packages/scheduler/tests/test_phase_ledger.py`
- Modify: `packages/scheduler/tests/test_runtime.py`

- [x] **Step 1: Write failing graph persistence tests**

Test that the phase ledger can store a parent graph with child node metadata,
acceptance criteria, dependencies, and a graph checksum, and that parent graph
decomposition persists the graph.

- [x] **Step 2: Add graph tables and ledger API**

Add `smda_graph` and `smda_graph_child` tables with
`record_graph`/`load_graph` helpers. Store dependency truth in the graph, not
inside child run state.

- [x] **Step 3: Parse and validate graph decomposer output**

Normalize typed `raw_result.children`, reject duplicate child ids, and run the
existing workflow graph invariant checks before persistence.

- [x] **Step 4: Atomically persist graph with parent transition**

Record the attempt result, parent phase transition to `GRAPH_SPEC_REVIEWING`,
and graph artifact in one ledger transaction.

- [x] **Step 5: Run focused green tests**

Run:
`uv run pytest packages/scheduler/tests/test_phase_ledger.py::test_phase_ledger_persists_smda_graph -q`
and
`uv run pytest packages/scheduler/tests/test_runtime.py::test_run_parent_graph_decomposition_tick_dispatches_from_spec_finalized -q`.

Note: this slice intentionally stops before graph spec/execution review role
dispatch, child issue publication, dependency projection to the backlog
manager, and child scheduling from the persisted graph.

### Task 39: Graph Spec Review Dispatch

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/workflow.py`
- Modify: `packages/scheduler/src/smda_scheduler/role_contracts.py`
- Modify: `packages/scheduler/src/smda_scheduler/role_attempts.py`
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py`
- Modify: `packages/scheduler/tests/test_role_attempts.py`
- Modify: `packages/scheduler/tests/test_runtime.py`

- [x] **Step 1: Write failing graph spec review tests**

Test that the graph spec reviewer request carries approved spec context,
persisted graph checksum, and child graph nodes, and that a parent in
`GRAPH_SPEC_REVIEWING` dispatches the reviewer.

- [x] **Step 2: Add the graph spec reviewer role contract**

Add `graph_spec_reviewer` on `ParentPhase.GRAPH_SPEC_REVIEWING`, using the
shared `smda.review-result.v1` schema and output tag
`smda_graph_spec_review_result`.

- [x] **Step 3: Add graph review request assembly**

Add `ParentGraphContext` and `build_parent_graph_spec_review_request`, carrying
the persisted graph rather than asking the reviewer to rediscover it.

- [x] **Step 4: Add runtime dispatch and PASS transition**

Read parent run state and persisted graph, record a parent role attempt, run the
execution adapter, and transition `PASS + submit_for_graph_execution_review` to
`GRAPH_EXECUTION_REVIEWING`.

- [x] **Step 5: Run focused green tests**

Run:
`uv run pytest packages/scheduler/tests/test_role_attempts.py::test_build_parent_graph_spec_review_request_carries_graph_context -q`
and
`uv run pytest packages/scheduler/tests/test_runtime.py::test_run_parent_graph_spec_review_tick_dispatches_from_graph_spec_reviewing -q`.

Note: this slice intentionally stops before graph execution review dispatch,
review-failure loopback to graph mutation, child issue publication, and backlog
blocking projection.

### Task 40: Graph Execution Review Dispatch

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/workflow.py`
- Modify: `packages/scheduler/src/smda_scheduler/role_contracts.py`
- Modify: `packages/scheduler/src/smda_scheduler/role_attempts.py`
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py`
- Modify: `packages/scheduler/tests/test_role_attempts.py`
- Modify: `packages/scheduler/tests/test_runtime.py`

- [x] **Step 1: Write failing graph execution review tests**

Test that the graph execution reviewer request carries persisted graph context,
and that a parent in `GRAPH_EXECUTION_REVIEWING` dispatches the reviewer.

- [x] **Step 2: Add graph execution reviewer contract**

Add `graph_execution_reviewer` on `ParentPhase.GRAPH_EXECUTION_REVIEWING`, using
the shared `smda.review-result.v1` schema and output tag
`smda_graph_execution_review_result`.

- [x] **Step 3: Add execution review request assembly**

Reuse `ParentGraphContext` for execution review and require the reviewer to
check dependency order, merge risk, and safe parallelism before publication.

- [x] **Step 4: Add runtime dispatch and PASS transition**

Read parent run state and persisted graph, record a parent role attempt, run the
execution adapter, and transition `PASS + publish_child_issues` to
`CHILD_PUBLICATION_READY`.

- [x] **Step 5: Run focused green tests**

Run:
`uv run pytest packages/scheduler/tests/test_role_attempts.py::test_build_parent_graph_execution_review_request_carries_graph_context -q`
and
`uv run pytest packages/scheduler/tests/test_runtime.py::test_run_parent_graph_execution_review_tick_dispatches_from_graph_execution_reviewing -q`.

Note: this slice intentionally stops before child issue publication, Linear
hierarchy/blocking projection, review-failure loopback, and child scheduling
from the published graph.

### Task 41: Child Issue Publication Projection

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/workflow.py`
- Modify: `packages/scheduler/src/smda_scheduler/phase_ledger.py`
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py`
- Modify: `packages/scheduler/tests/test_phase_ledger.py`
- Modify: `packages/scheduler/tests/test_runtime.py`

- [x] **Step 1: Write failing publication tests**

Test that a parent in `CHILD_PUBLICATION_READY` publishes durable graph children
as backlog child issues, records node-to-issue projections, embeds SMDA child
routing context in the issue body, and projects graph dependency edges as
blocking relations.

- [x] **Step 2: Add child issue projection ledger**

Add a durable `child_issue_projection` table so retries can skip already
published graph nodes instead of creating duplicate child handles.

- [x] **Step 3: Add publication runtime**

Create missing child issues from `smda_graph_child`, persist projections, link
blocking relations from dependency edges, and move the parent phase to
`CHILDREN_PUBLISHED`.

- [x] **Step 4: Keep workers read-only**

Child issue bodies include `Execution: smda-child`, parent issue id, graph
checksum, node id, source spec, and acceptance criteria. Workers still do not
mutate backlog state.

- [x] **Step 5: Run focused green tests**

Run:
`uv run pytest packages/scheduler/tests/test_phase_ledger.py::test_phase_ledger_persists_child_issue_projections -q`
and
`uv run pytest packages/scheduler/tests/test_runtime.py::test_run_parent_child_publication_tick_creates_children_and_blockers -q`.

Note: this slice intentionally stops before Linear label projection. The current
Linear adapter does not implement labels, so published children carry routing
context in the body and hierarchy/blocking relations, but may still need a
label-capable adapter surface before scanner-based child dispatch is fully
automatic in repositories whose tracker contract requires an `agent` label.

### Task 42: Linear Label Projection For Published Children

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/linear_backlog.py`
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py`
- Modify: `packages/scheduler/tests/test_linear_backlog.py`
- Modify: `packages/scheduler/tests/test_runtime.py`
- Modify: `docs/contracts.md`

- [x] **Step 1: Write failing label projection tests**

Test that Linear child creation can include configured label ids, rejects
unconfigured labels, and that child publication passes the configured child
label set into the backlog adapter.

- [x] **Step 2: Add Linear label id mapping**

Add optional `label_ids` to `LinearBacklogAdapter`, map requested label names to
`labelIds` in `IssueCreateInput`, and read env values like
`SMDA_LINEAR_LABEL_AGENT`.

- [x] **Step 3: Make label capability truthful**

Only declare the `labels` capability when the Linear adapter has configured
label ids.

- [x] **Step 4: Thread child labels through publication**

Add `child_labels` to `run_parent_child_publication_tick` so setup/config can
publish `agent`-labeled children without letting workers mutate tracker state.

- [x] **Step 5: Run focused green tests**

Run:
`uv run pytest packages/scheduler/tests/test_linear_backlog.py::test_linear_backlog_creates_child_issue_with_configured_labels packages/scheduler/tests/test_linear_backlog.py::test_linear_backlog_rejects_unconfigured_child_label -q`,
`uv run pytest packages/scheduler/tests/test_linear_backlog.py::test_linear_backlog_descriptor_declares_labels_when_configured packages/scheduler/tests/test_linear_backlog.py::test_linear_backlog_descriptor_declares_mvp_capabilities -q`,
and
`uv run pytest packages/scheduler/tests/test_runtime.py::test_run_parent_child_publication_tick_creates_children_and_blockers -q`.

Note: this slice stops before wiring config labels into the daemon command path;
the runtime surface now accepts labels and the Linear adapter can project them
when the caller supplies config-derived label names.

### Task 43: Parent Phase Dispatcher

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py`
- Modify: `packages/scheduler/tests/test_runtime.py`

- [x] **Step 1: Write failing dispatcher test**

Test that repeated parent workflow ticks advance a parent from `SPEC_FINALIZED`
through graph decomposition, graph spec review, graph execution review, child
publication, and `CHILDREN_PUBLISHED`.

- [x] **Step 2: Add parent workflow dispatcher**

Add `run_parent_workflow_tick` to route by durable parent phase instead of
requiring callers to manually pick each phase-specific runtime function.

- [x] **Step 3: Preserve one-step tick semantics**

Each call advances at most one parent phase. Daemon/workspace loops can call the
dispatcher repeatedly; a single tick does not spin through the entire parent
workflow in-process.

- [x] **Step 4: Thread runtime dependencies**

Pass repo context, execution adapter, backlog adapter, sandbox provider, agent
selection, owner, and config-derived child labels through the dispatcher.

- [x] **Step 5: Run focused green test**

Run:
`uv run pytest packages/scheduler/tests/test_runtime.py::test_run_parent_workflow_tick_advances_parent_state_machine_happy_path -q`.

Note: this slice stops before constructing the live daemon tick from config,
environment, and real adapter instances. It provides the product-owned parent
state-machine surface that daemon wiring should call.

### Task 44: Complete Child SDD Phase Transitions

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/workflow.py`
- Modify: `packages/scheduler/src/smda_scheduler/role_contracts.py`
- Modify: `packages/scheduler/tests/test_workflow.py`
- Modify: `packages/scheduler/tests/test_role_attempts.py`

- [x] **Step 1: Write failing child transition tests**

Test missing child SDD transitions: spec review `PASS` routes to
`QUALITY_REVIEWING`, and fixer `DONE` routes back to `SPEC_REVIEWING`.

- [x] **Step 2: Add transition table entries**

Add `SPEC_REVIEWING + PASS + submit_for_quality_review ->
QUALITY_REVIEWING` and `FIXING_SPEC + DONE + submit_for_spec_review ->
SPEC_REVIEWING`.

- [x] **Step 3: Add prompt route vocabulary**

Make child spec reviewer, fixer, and quality reviewer prompts name the exact
`verdict` / `required_next_action` pairs the scheduler can route.

- [x] **Step 4: Run focused green tests**

Run:
`uv run pytest packages/scheduler/tests/test_workflow.py::test_child_transition_table_routes_role_results -q`
and
`uv run pytest packages/scheduler/tests/test_role_attempts.py::test_build_child_role_attempt_request_maps_review_and_fix_roles -q`.

Note: this slice stops before parent integration of accepted child candidates;
it only makes the child SDD loop internally routable.

### Task 45: Parent Child Acceptance Dispatcher

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py`
- Modify: `packages/scheduler/src/smda_scheduler/workflow.py`
- Test: `packages/scheduler/tests/test_runtime.py`

- [x] **Step 1: Write failing acceptance tests**

Test that a parent in `CHILDREN_PUBLISHED` accepts child candidates whose child
run state reached `QUALITY_REVIEW_PASSED`, records idempotent parent accept
operations, and advances to `PARENT_QA_READY` only after every persisted graph
child has been accepted.

- [x] **Step 2: Add parent QA-ready phase**

Add `PARENT_QA_READY` as the explicit parent phase after child integration and
before parent-level QA execution.

- [x] **Step 3: Compose child acceptance tick**

Add `run_parent_child_acceptance_tick` to load the persisted graph, read durable
child run state, recover/apply parent accept operations through
`recover_or_apply_child_accept`, and preserve one-step tick semantics.

- [x] **Step 4: Route dispatcher from children-published phase**

Teach `run_parent_workflow_tick` to route `CHILDREN_PUBLISHED` through child
acceptance when an integration adapter and integration branch are configured;
otherwise block with a clear configuration error.

- [x] **Step 5: Run focused green tests**

Run:
`uv run pytest packages/scheduler/tests/test_runtime.py::test_run_parent_child_acceptance_tick_integrates_quality_passed_children -q`
and
`uv run pytest packages/scheduler/tests/test_runtime.py::test_run_parent_workflow_tick_routes_children_published_to_acceptance -q`.

Note: this slice stops before parent QA execution, remediation child creation,
and final parent close. It only makes accepted child candidates durable and
recoverable at the parent integration boundary.

### Task 46: Parent QA Review Dispatch

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/workflow.py`
- Modify: `packages/scheduler/src/smda_scheduler/role_contracts.py`
- Modify: `packages/scheduler/src/smda_scheduler/role_attempts.py`
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py`
- Modify: `packages/sandcastle-runner/src/roleContracts.ts`
- Test: `packages/scheduler/tests/test_role_attempts.py`
- Test: `packages/scheduler/tests/test_runtime.py`

- [x] **Step 1: Write failing parent QA request test**

Test that the parent QA reviewer request carries approved spec context,
persisted graph context, repo context, and explicit route vocabulary:
`PASS/accept_parent` and `FAIL/plan_remediation`.

- [x] **Step 2: Add parent QA role contract**

Add `parent_qa_reviewer` using the shared `smda.review-result.v1` schema instead
of creating another near-identical review schema.

- [x] **Step 3: Add parent QA runtime tick**

Dispatch parent QA from `PARENT_QA_READY`, persist the attempt, and route
`PASS/accept_parent` to `FINAL_ACCEPT_READY`.

- [x] **Step 4: Add QA failure route**

Route `FAIL/plan_remediation` to `REMEDIATION_PLANNING` instead of treating a
review failure as a protocol error.

- [x] **Step 5: Run focused green tests**

Run:
`uv run pytest packages/scheduler/tests/test_role_attempts.py::test_build_parent_qa_review_request_carries_final_integration_context -q`
and
`uv run pytest packages/scheduler/tests/test_runtime.py::test_run_parent_qa_review_tick_dispatches_from_parent_qa_ready packages/scheduler/tests/test_runtime.py::test_run_parent_qa_review_tick_routes_fail_to_remediation_planning -q`.

### Task 47: Parent Remediation Feedback Loop

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py`
- Test: `packages/scheduler/tests/test_runtime.py`

- [x] **Step 1: Write failing remediation publication test**

Test that `REMEDIATION_PLANNING` creates a remediation child from the latest
parent QA failure report.

- [x] **Step 2: Append remediation node to graph**

Add `remediation-###` to the persisted graph with dependencies on all existing
graph children so the remediation child runs only after the integrated baseline.

- [x] **Step 3: Publish remediation child issue**

Create the child issue with normal `Execution: smda-child` metadata, record the
node-to-issue projection, project blocking relations, and return the parent to
`CHILDREN_PUBLISHED`.

- [x] **Step 4: Run focused green test**

Run:
`uv run pytest packages/scheduler/tests/test_runtime.py::test_run_parent_remediation_planning_tick_creates_remediation_child -q`.

Note: this slice reuses the normal child SDD loop and parent acceptance boundary.
It does not yet wire config-driven QA bounds into the remediation runtime tick.

### Task 48: Final Parent Accept Effects

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/workflow.py`
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py`
- Test: `packages/scheduler/tests/test_runtime.py`

- [x] **Step 1: Write failing final accept test**

Test that `FINAL_ACCEPT_READY` records durable tracker effects instead of
directly mutating the backlog.

- [x] **Step 2: Record idempotent closeout effects**

Record a final comment effect containing the parent QA pass report and a
`set_state` effect moving the parent to `Done`.

- [x] **Step 3: Advance parent phase**

Move the parent to `FINAL_ACCEPTED` after durable effects are recorded; workspace
reconciliation owns sending those effects to the backlog adapter.

- [x] **Step 4: Run focused green test**

Run:
`uv run pytest packages/scheduler/tests/test_runtime.py::test_run_parent_final_accept_tick_records_tracker_effects -q`.

### Task 49: Configured Workspace Tick Factory And CLI Daemon Wiring

**Files:**
- Create: `packages/scheduler/src/smda_scheduler/runtime_factory.py`
- Modify: `packages/scheduler/src/smda_scheduler/cli.py`
- Test: `packages/scheduler/tests/test_runtime_factory.py`
- Test: `packages/scheduler/tests/test_cli.py`

- [x] **Step 1: Write failing configured tick factory test**

Test that a config-built workspace tick derives the ledger path, discovers
Codex harness context, scans backlog candidates, classifies routing, and runs
parent intake without caller-side manual composition.

- [x] **Step 2: Add runtime factory**

Add `build_configured_workspace_tick` as the product-owned composition layer for
config, ledger, context packet, workspace scanning, routed child dispatch,
parent intake, and parent workflow dispatch.

- [x] **Step 3: Preserve workflow ownership**

Keep routing and phase semantics in `candidate_routing.py` and `runtime.py`; the
factory only composes dependencies and config-derived values such as execution
provider and child labels.

- [x] **Step 4: Wire daemon CLI config path**

Allow `smda-scheduler daemon <config> --repo-root <repo>` to build a live tick
from Linear + Sandcastle defaults, while preserving test injection for unit
coverage.

- [x] **Step 5: Run focused and full scheduler tests**

Run:
`uv run pytest packages/scheduler/tests/test_runtime_factory.py::test_build_configured_workspace_tick_routes_parent_intake_from_config -q`,
`uv run pytest packages/scheduler/tests/test_cli.py::test_daemon_cli_builds_tick_from_config_when_not_injected -q`,
and
`uv run pytest packages/scheduler/tests -q`.

Note: this slice does not add new config schema fields for scan state/label,
agent model, or integration branch. The CLI accepts scan state/label/owner flags
and the factory keeps adapter instances injectable so future packaging can
decide credential and process-launch policy without changing workflow code.

### Task 50: Config-Driven QA Remediation Bounds

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/workflow.py`
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py`
- Modify: `packages/scheduler/src/smda_scheduler/runtime_factory.py`
- Modify: `packages/scheduler/tests/helpers.py`
- Test: `packages/scheduler/tests/test_runtime.py`
- Test: `packages/scheduler/tests/test_runtime_factory.py`

- [x] **Step 1: Write failing remediation bounds test**

Test that `REMEDIATION_PLANNING` moves the parent to
`HUMAN_REVIEW_REQUIRED` when the persisted graph already contains the maximum
allowed remediation children.

- [x] **Step 2: Enforce graph-derived remediation count**

Use remediation graph nodes as the source of truth for total remediation count;
do not add duplicate parent-run counters for this MVP bound.

- [x] **Step 3: Thread bounds through parent dispatcher**

Add `qa_bounds` to `run_parent_workflow_tick` and pass it into remediation
planning.

- [x] **Step 4: Thread config policy through runtime factory**

Convert `config.policy.qa` into `QaBounds` inside
`build_configured_workspace_tick` so daemon/config execution uses the same bound
as direct runtime calls.

- [x] **Step 5: Run focused and full scheduler tests**

Run:
`uv run pytest packages/scheduler/tests/test_runtime.py::test_run_parent_remediation_planning_tick_human_reviews_when_bounds_exhausted -q`,
`uv run pytest packages/scheduler/tests/test_runtime.py::test_run_parent_workflow_tick_threads_qa_bounds_to_remediation -q`,
`uv run pytest packages/scheduler/tests/test_runtime_factory.py::test_configured_workspace_tick_threads_qa_policy_to_parent_workflow -q`,
and
`uv run pytest packages/scheduler/tests -q`.

Note: this slice enforces the total remediation-child bound. Same-feedback
fingerprint and parent-QA-cycle bounds remain represented in config and
workflow helpers, but still need durable runtime enforcement before claiming
the full QA policy matrix is complete.

### Task 51: Complete QA Policy Bound Enforcement

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py`
- Test: `packages/scheduler/tests/test_runtime.py`

- [x] **Step 1: Write failing repeated-feedback bound test**

Test that repeated parent QA failures with the same normalized report
fingerprint move the parent to `HUMAN_REVIEW_REQUIRED` once the configured
same-feedback bound is exhausted.

- [x] **Step 2: Write failing parent-QA-cycle bound test**

Test that too many parent QA review attempts move the parent to
`HUMAN_REVIEW_REQUIRED` before another remediation child is created.

- [x] **Step 3: Enforce bounds from durable attempt history**

Derive fingerprint and cycle counts from the parent QA attempt ledger so the
decision survives daemon restarts without adding parent-run counters.

- [x] **Step 4: Run focused and full scheduler tests**

Run:
`uv run pytest packages/scheduler/tests/test_runtime.py::test_run_parent_remediation_planning_tick_human_reviews_repeated_feedback packages/scheduler/tests/test_runtime.py::test_run_parent_remediation_planning_tick_human_reviews_qa_cycle_limit -q`
and
`uv run pytest packages/scheduler/tests -q`.

Note: the full QA policy matrix is now enforced at remediation planning time:
total remediation children from graph truth, repeated feedback from parent QA
report fingerprints, and parent QA cycles from the attempt ledger.

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

### Task 8: Trading-Advisor Prototype Semantic Backfill

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/candidate_routing.py`
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py`
- Test: `packages/scheduler/tests/test_candidate_routing.py`
- Test: `packages/scheduler/tests/test_runtime.py`

- [x] **Step 1: Write failing tests for preserved context and approval semantics**

Port the first high-value trading-advisor prototype semantics into product
tests:

- `Execution: smda-child` handles require acceptance criteria, not only parent
  issue, graph checksum, and node id.
- approved parent specs require complete approval front matter:
  `status: approved`, `approval_evidence`, `approved_at`, and `approved_by`.
- graph decomposer children require non-empty acceptance criteria before the
  graph can advance to review/publication.

- [x] **Step 2: Run red tests**

Run:
`uv run pytest packages/scheduler/tests/test_candidate_routing.py::test_blocks_smda_child_handle_without_acceptance_criteria -q`
and
`uv run pytest packages/scheduler/tests/test_runtime.py::test_run_parent_candidate_intake_requires_complete_approval_frontmatter packages/scheduler/tests/test_runtime.py::test_run_parent_graph_decomposition_requires_child_acceptance_criteria -q`.

Expected: FAIL because the product accepted incomplete child context, incomplete
approval metadata, and empty child acceptance criteria.

- [x] **Step 3: Implement minimal contract checks**

Add the missing candidate-routing, parent-intake, and graph-child validation.
Update existing happy-path fixtures to satisfy the stricter contract.

- [x] **Step 4: Run focused and full scheduler tests**

Run the focused tests, then:
`uv run pytest packages/scheduler/tests -q`.

Note: the full scheduler suite produced one transient
`test_git_parent_integration_applies_candidate_to_integration_branch` failure
that passed when rerun in isolation and passed on the subsequent full-suite
run. It is tracked as an observed flaky test, not as a regression from this
slice.

## Self-Review

- Spec coverage: Slice 1 covers config contract, workspace derivation, adapter capability negotiation, and boot gate. It intentionally does not cover workflow phases, daemon scheduling, Sandcastle IPC, or real backlog APIs.
- Placeholder scan: Later slices are named but intentionally not expanded into full task code until Slice 1 is complete and package conventions are established.
- Type consistency: Capability names use the snake_case contract from `docs/contracts.md`.
