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

- **Slice 5 — Backlog adapter:** first real Linear or local adapter and adapter contract fixtures.
- **Slice 6 — Setup skill integration:** setup writes config only, validates boot gate, links runtime.

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
