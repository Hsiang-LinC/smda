# Phase 3a — Parent Dependency Gate (Roadmap Ordering) Implementation Plan

> **REQUIRED SUB-SKILL:** `superpowers:executing-plans` + `tdd`. Red → green →
> refactor, one task at a time.

> **Agent handoff (read first — hand-rolled RepoContextPacket):**
> - **Branch:** work on `target-c`. Do NOT branch from `master`/`main`.
> - **Read first:** [CONTEXT.md](../../CONTEXT.md) (Roadmap, Member),
>   [ADR-0002](../../adr/0002-roadmap-as-in-engine-decomposed-parent-set.md),
>   [target-C spec](../specs/2026-06-16-target-c-modular-parallel-engine.md) §5.
> - **Mirror the child tier:** this is the parent-tier analogue of
>   `child_dependency_gate.py` + the child graph store. Read those first.
> - **Line numbers are indicative** — grep for symbols.
> - **Prereqs:** Phase 1 (engine). Independent of Phase 0/2.
> - **Discipline:** TDD red→green. Parity = don't change existing assertions.
>   `uv run pytest packages/scheduler/tests/`, `npm run test:ts`, `tsc` green.

**Goal:** Make parents block / auto-unblock each other along a roadmap. Given
parent→parent dependency edges in the ledger, a Parent does not dispatch until
every blocking upstream Parent is `FINAL_ACCEPTED`; once an upstream lands,
the downstream auto-unblocks on the next scan tick. This is the parent-tier mirror
of the child dependency gate. Implements the ordering half of
[ADR-0002](../../adr/0002-roadmap-as-in-engine-decomposed-parent-set.md).

**Scope split:** Phase 3a is the **gate + edge store + scan wiring** — the
mechanism. The edges are seeded directly via the ledger API here (tests; later the
decomposer). The **`roadmap_decomposer` role** that authors the parent set + edges
from a Roadmap Spec is **Phase 3b** (separate plan). The land-to-base / roadmap →
main / conflict probe is **Phase 4**.

**Architecture:** A new ledger roadmap-edge store (`from_parent → to_parent`,
`blocks_dispatch`), cycle-checked on write. A pure `parent_dependency_gate`
(mirror of `child_dependency_gate`) takes a parent's blockers + the set of
`FINAL_ACCEPTED` parents and returns eligibility. `run_workspace_tick` consults it
for PARENT-route candidates at the existing `is_parent_paused` skip seam
(`workspace_tick.py:80-85`): blocked → `skipped_count += 1; continue`. Auto-unblock
is implicit on re-scan; no event system.

**Tech Stack:** Python scheduler, SQLite `PhaseLedger`, pytest.

## Relationship To Other Plans

- Phase 3 (step a) of
  [target-c-implementation-path](2026-06-16-target-c-implementation-path.md).
- Spec §5; [ADR-0002](../../adr/0002-roadmap-as-in-engine-decomposed-parent-set.md).
- Phase 3b (`roadmap_decomposer`) writes the edges this gate reads.
- Phase 4 (land + conflict) consumes the same `FINAL_ACCEPTED` completion signal.

## Scope

In scope:
- Ledger roadmap-edge store: schema + `record_roadmap_edges` +
  `load_roadmap_blockers(parent_id)`; cycle-checked on write.
- `parent_dependency_gate.py`: pure gate + `ParentDependencyGateResult`.
- Wire the gate into `run_workspace_tick` for PARENT / IMPLICIT_PARENT routes.
- Tests for store, gate, scan-skip, and auto-unblock.

Out of scope:
- `roadmap_decomposer` role + Roadmap Spec routing (Phase 3b).
- Landing parents to a base branch / roadmap → main / conflict probe (Phase 4).
- Tracker projection of parent→parent edges (the decomposer does this in 3b via
  `link_blocking`; the gate reads the ledger, not the tracker — per ADR-0002).

## File Structure

- Modify `phase_ledger.py` (roadmap-edge table + record/load + cycle check).
- Create `parent_dependency_gate.py`.
- Modify `workspace_tick.py` (gate check in the candidate loop).
- Modify `runtime_factory.py` if the workspace tick needs the gate wired into the
  configured tick.
- Tests: `test_phase_ledger.py`, `test_parent_dependency_gate.py`,
  `test_workspace_tick.py`.

---

## Task 1: Ledger roadmap-edge store

**Files:** `phase_ledger.py`; `test_phase_ledger.py`.

- [x] **Step 1: Failing tests** — record edges, load blockers, reject a cycle.

```python
def test_record_and_load_roadmap_blockers(tmp_path):
    ledger = PhaseLedger(tmp_path / "l.sqlite")
    ledger.record_roadmap_edges([
        {"from_parent_id": "P1", "to_parent_id": "P2", "blocks_dispatch": True,
         "reason": "P2 builds on P1"},
    ])
    assert ledger.load_roadmap_blockers("P2") == ("P1",)
    assert ledger.load_roadmap_blockers("P1") == ()

def test_record_roadmap_edges_rejects_cycle(tmp_path):
    ledger = PhaseLedger(tmp_path / "l.sqlite")
    with pytest.raises(GraphError):
        ledger.record_roadmap_edges([
            {"from_parent_id": "P1", "to_parent_id": "P2", "blocks_dispatch": True, "reason": "x"},
            {"from_parent_id": "P2", "to_parent_id": "P1", "blocks_dispatch": True, "reason": "y"},
        ])
```

- [x] **Step 2: Implement** a `smda_roadmap_edge` table
  (`from_parent_id`, `to_parent_id`, `blocks_dispatch`, `reason`) in
  `_ensure_schema`; `record_roadmap_edges` (validate + insert in one txn);
  `load_roadmap_blockers(parent_id)` returns the sorted tuple of `from_parent_id`
  where `to_parent_id == parent_id and blocks_dispatch`. Reuse a topological cycle
  check (raise `GraphError` on a cycle) — adapt `workflow._reject_cycles`.

- [x] **Step 3: Run, green. Commit.**

---

## Task 2: `parent_dependency_gate`

**Files:** `parent_dependency_gate.py`; `test_parent_dependency_gate.py`.

Mirror `child_dependency_gate`: pure function, explicit inputs, frozen result.

- [x] **Step 1: Failing tests**

```python
def test_parent_eligible_when_no_blockers():
    r = parent_dependency_gate(parent_id="P1", blockers=(), final_accepted_parent_ids=frozenset())
    assert r.eligible

def test_parent_blocked_until_upstream_final_accepted():
    blocked = parent_dependency_gate(
        parent_id="P2", blockers=("P1",), final_accepted_parent_ids=frozenset())
    assert not blocked.eligible and blocked.blocked_by == ("P1",)
    unblocked = parent_dependency_gate(
        parent_id="P2", blockers=("P1",), final_accepted_parent_ids=frozenset({"P1"}))
    assert unblocked.eligible
```

- [x] **Step 2: Implement**

```python
@dataclass(frozen=True)
class ParentDependencyGateResult:
    eligible: bool
    blocked_by: tuple[str, ...] = ()
    reason: str = ""

def parent_dependency_gate(*, parent_id, blockers, final_accepted_parent_ids):
    waiting = tuple(b for b in blockers if b not in final_accepted_parent_ids)
    if not waiting:
        return ParentDependencyGateResult(eligible=True)
    return ParentDependencyGateResult(
        eligible=False, blocked_by=waiting,
        reason=f"Waiting for upstream parents to be FINAL_ACCEPTED: {', '.join(waiting)}",
    )
```

- [x] **Step 3: Run, green. Commit.**

---

## Task 3: Wire the gate into the workspace scan

**Files:** `workspace_tick.py`; `test_workspace_tick.py`.

- [x] **Step 1: Failing tests** — a PARENT candidate whose upstream is not
  `FINAL_ACCEPTED` is **skipped** (not dispatched, not blocked-commented); once the
  upstream parent_run reaches `FINAL_ACCEPTED`, the same candidate dispatches
  (auto-unblock).

- [x] **Step 2: Implement** — in `run_workspace_tick`, compute the
  `final_accepted_parent_ids` once per tick from
  `ledger.load_parent_runs()` (phase == `FINAL_ACCEPTED`). In the candidate loop,
  after the `is_parent_paused` skip and only for
  `decision.route in {CandidateRoute.PARENT, CandidateRoute.IMPLICIT_PARENT}`:

```python
    blockers = ledger.load_roadmap_blockers(candidate.id)
    gate = parent_dependency_gate(
        parent_id=candidate.id,
        blockers=blockers,
        final_accepted_parent_ids=final_accepted,
    )
    if not gate.eligible:
        skipped_count += 1
        continue
```

Keep it a silent skip (the tracker already shows the block relation via the
decomposer's `link_blocking` projection in 3b). Do NOT emit a Blocked tracker
effect — that would fight auto-unblock.

- [x] **Step 3: Parity gate** — full `test_workspace_tick` + `test_runtime_factory`
  green; only additive tests.

- [x] **Step 4: Commit.**

---

## Task 4: Full gate

- [x] `uv run pytest packages/scheduler/tests/ -q` ; `npm run test:ts` ;
  `npx tsc --noEmit`. All green.
- [x] Confirm: with no roadmap edges recorded, parent dispatch behaviour is
  unchanged (the gate is a no-op when `blockers == ()`).
- [x] Commit.

## Acceptance Criteria

1. The ledger stores parent→parent edges, returns a parent's blockers, and rejects
   a cycle.
2. `parent_dependency_gate` blocks a parent until every blocker is
   `FINAL_ACCEPTED`; eligible otherwise.
3. The workspace scan skips a blocked PARENT candidate and dispatches it once its
   upstreams are accepted (auto-unblock on re-scan, no event system).
4. With no edges, parent dispatch is unchanged (existing tests untouched).
5. Full suite + TS + tsc green.

## Done Definition

- Parents block / auto-unblock along recorded edges; the mechanism mirrors the
  child dependency gate and reads SMDA-owned ledger state (not the tracker).
- Ready for **Phase 3b** (`roadmap_decomposer` authors the edges + parent set) and
  **Phase 4** (landing to base + conflict), both of which build on this gate +
  the `FINAL_ACCEPTED` completion signal.

## Out Of Scope — Next Plans

- **Phase 3b:** `roadmap_decomposer` role — Roadmap Spec → parent issues +
  `record_roadmap_edges` + `link_blocking` projection; `Execution: smda-roadmap`
  routing; a `roadmap-decomposer-result` Zod schema (extends the Phase-0 artifact);
  the role declares `to-prd`/`to-issues` methodology (Phase 2).
- **Phase 4:** parent FINAL_ACCEPT lands to a parametric base; roadmap-completion
  Aggregate lands roadmap → main; `merge-tree` conflict probe + bounded auto-rebase.
