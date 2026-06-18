---
status: approved
created_at: 2026-06-18
owner: agent
approved_at: 2026-06-18
approved_by: human
approval_evidence: conversation design review approval 2026-06-18 ("可以直接改成完整版的fan-out框架" + "三點都照你建議的")
---

# Parallel Fan-out Execution Daemon

## Problem

The SMDA Scheduler daemon cannot drive a full `parent → children → land`
pipeline, for two compounding reasons:

1. **Single-state scan.** `smda-scheduler daemon --state Todo` scans exactly one
   coarse tracker state (`LinearBacklogAdapter.list_issues` filters
   `state.name.eq`). Work moves through `In Progress` (every active parent/child
   phase) and `Agent Review` (child `QUALITY_REVIEW_PASSED`, parked) across many
   ticks, one phase per tick. A `Todo`-only scan can only do new intake; it never
   re-finds in-flight parents (intake flips them to `In Progress`) or lets a
   parent land its passed children.

2. **Children published into a non-scannable state.** `run_parent_child_publication_tick`
   creates children via `create_child`, which sets no `stateId`, so they land in
   the Linear team default state (`Backlog`, position 0) — neither `Todo` nor
   `In Progress`. Roadmap members are explicitly set to `Todo`
   (`_ROADMAP_MEMBER_DISPATCH_STATE`), but regular parent children are not.

3. **Sequential, blocking dispatch.** `run_workspace_tick` dispatches exactly one
   candidate per tick, and `SandcastleExecutionAdapter.run_role_attempt` is a
   blocking `subprocess.run`. Throughput is one phase advance per tick for the
   whole repo. The engine's data model (`Claim` + `lease_expires_at` +
   `reconcile_expired_claims`, durable idempotent tracker effects) was designed
   for concurrent workers, but the daemon loop never exploits it.

Observed failure (trading-advisor, 2026-06-18): the ledger is empty, every tick
logs `idle`, and `DANNY-70` — an `Execution: smda` parent — sits in `Agent Review`
(manually mislabelled) while the daemon scans an empty `Todo`.

## Goal

A fan-out execution daemon: each tick scans the active coarse states, computes
every eligible candidate, and dispatches them **concurrently** (bounded by
`max_parallel`), reusing the existing claim/lease + durable-effect safety
substrate. Children are published into a scannable state. The full pipeline drains
autonomously.

Out of scope (deliberate non-goals, may be added later): intra-tick dependency
cascade, multi-process / distributed workers, an asyncio rewrite, a continuous
worker pool, priority/fairness scheduling.

## Current Baseline

- `daemon.py` — `run_daemon(tick, max_ticks, interval, sleep)` loops `tick()`
  then sleeps; any tick exception → `DaemonResult(status="failed")`.
- `scanner.py` — `scan_dispatch_candidates(backlog, state, label, parent_id, ...)`
  delegates to `list_issues` for one state.
- `workspace_tick.py` — `run_workspace_tick` runs `retry_pending_tracker_effects`
  once, scans one state, then iterates candidates and dispatches **the first**
  routable/eligible one (classify → pause check → dependency gate →
  `dispatch_routed_candidate`), returning a single `TickResult`.
- `runtime_factory.py` — builds `dispatch_routed_candidate` (routes CHILD / TASK /
  PARENT / ROADMAP to the matching tick) and the workspace tick lambda with
  `scan_state: str`.
- `runtime.py` — dispatch ends in `run_once_durable` → `run_once`, which advances
  exactly one phase and calls `execution.run_role_attempt`. Child publication
  (`run_parent_child_publication_tick`) calls `backlog.create_child` with no state.
- `sandcastle_execution.py` — `run_role_attempt` → `subprocess.run` (blocking).
- `phase_ledger.py` — SQLite-backed; single-threaded access today.
- `cli.py` — `--state` (single), `--label`, `--max-ticks`, `--owner`.
- Concurrency substrate already present: `Claim`/`lease_expires_at` on child run
  state, `reconcile_expired_claims`, durable `tracker_effect_ledger` retried at
  tick start, graph-checksum validation on child dispatch.

## Design

### A. Multi-state scan (`scanner.py`)

`scan_dispatch_candidates` takes an **ordered `states: Sequence[str]`** instead of
a single `state`. It calls `list_issues` per state and returns the merged
candidate set, each candidate tagged with its source state. Order is preserved so
downstream slot-filling can honour "in-flight first". `list_issues` itself is
unchanged (still one state per call); the scanner loops.

### B. Eligible-set computation (`workspace_tick.py`)

Per tick, after `retry_pending_tracker_effects` (run once, state-independent):

1. Scan all configured states → merged candidates.
2. For each candidate compute eligibility from a **scan-time snapshot**:
   classify (route + context completeness), pause check, dependency gate
   (`parent_dependency_gate` / `child_dependency_gate`). Ineligible candidates are
   silently skipped (dependency) or block-recorded (bad routing), exactly as today.
3. Order eligible candidates **in-flight first** (`In Progress` source state before
   `Todo`), then take the first `max_parallel` as the dispatch batch. The remainder
   waits for a later tick; dispatched candidates become claim-leased and drop out of
   the next scan, so there is no starvation.

Dependency resolution is progressive across ticks: a child unblocked by a sibling
that lands in the same tick is picked up on the **next** scan (existing
"auto-unblocks on a later scan" semantics). No intra-tick cascade.

### C. Concurrent dispatch (batch-join, `ThreadPoolExecutor`)

The batch is dispatched through `ThreadPoolExecutor(max_workers=max_parallel)`;
each worker runs one `dispatch_routed_candidate` end-to-end (which blocks on the
agent `subprocess.run`). The tick **joins** the whole batch before returning
(batch-join model — no long-lived pool). Tick duration ≈ the slowest dispatch in
the batch, not the sum.

Threads (not asyncio) are sufficient because the dispatched work is
subprocess-bound and releases the GIL while waiting.

### D. Ledger thread-safety (write-lock)

Concurrent SQLite writers raise `database is locked`. The expensive work (agent
subprocess) runs **outside** any lock; the cheap ledger bookkeeping
(claim, phase transition, effect record) is serialized by a single
`threading.Lock` held only around ledger mutations. `phase_ledger` opens the
database in WAL mode. The write-lock is created in `runtime_factory` and injected
into the dispatch path.

Claim safety: the scan yields a candidate set of **distinct** issues (an issue is
in exactly one coarse state), each dispatched by exactly one worker. The atomic,
lock-guarded claim before the subprocess means no two workers ever claim the same
child. `reconcile_expired_claims` continues to release leases from crashed runs.

### E. Per-task failure isolation

Each worker wraps its dispatch in try/except. A `GraphError` or any other
exception is contained: the worker records a per-issue block effect (reusing
`_record_block_effects`) and returns a failed per-task result; it does **not**
propagate. One task failing never fails the tick. Only an infrastructure error
(e.g. `scan`/`list_issues` itself) fails the tick. `run_daemon`'s blanket
"any exception → failed" is narrowed accordingly.

The tick returns an aggregate `TickResult`: counts of `dispatched`, `blocked`,
`failed`, plus the reconciliation summary.

### F. Child publication dispatch-state (`runtime.py`)

After `create_child`, each new child is set to the dispatch state via
`backlog.set_coarse_state(created.id, _CHILD_DISPATCH_STATE)` where
`_CHILD_DISPATCH_STATE = "Todo"` — mirroring `_ROADMAP_MEMBER_DISPATCH_STATE`.
This makes published children immediately scannable. The set is idempotent.

### G. Landing stays serial

Children implement/review in parallel on their own candidate branches. Merging a
passed child into the parent integration branch is the **parent** dispatch's job
(`run_parent_child_acceptance_tick` reads `QUALITY_REVIEW_PASSED` from the ledger
and lands deterministically). Because each parent has a single dispatch task,
landing is naturally serial even when many children finish in one tick — matching
the `serial-merge` intent. Child dispatches do not touch the parent branch.

### H. Configuration & wiring

- `cli.py` — `--state` becomes repeatable (`action="append"`; a single value stays
  backward compatible); add `--max-parallel N` (default **3**).
- `runtime_factory.py` — `scan_state: str` → `scan_states: Sequence[str]`; thread
  `max_parallel` and the ledger write-lock through to the tick and dispatch path.
- `daemon.py` — tick signature returns the aggregate `TickResult`; loop otherwise
  unchanged.
- Controller `smda-daemon-loop.sh` (target repo) — invoke
  `--state "In Progress" --state Todo --max-parallel N`.

## Data Flow (one tick)

```
retry_pending_tracker_effects()                 # once, outbox drain
candidates = scan([In Progress, Todo], label)   # merged, source-tagged
eligible   = filter(classify + pause + dependency gate)   # snapshot
batch      = order(eligible, in_progress_first)[:max_parallel]
results    = ThreadPool(max_parallel).map(dispatch, batch) # concurrent, join
return aggregate(results)                        # dispatched/blocked/failed
```

## Error Handling

| Failure | Behaviour |
|---|---|
| One dispatch raises (GraphError/other) | Contained: per-issue block effect, worker returns failed; tick continues |
| `list_issues` / scan fails | Tick fails (`run_daemon` records `failed`) |
| SQLite `database is locked` | Prevented by write-lock + WAL; ledger writes serialized |
| Worker crashes mid-attempt | Claim lease expires → `reconcile_expired_claims` releases next tick |
| Batch larger than `max_parallel` | Remainder dispatched on later ticks (no starvation; claimed ones drop off scan) |

## Testing

- **scanner** — multi-state merge preserves order and source tagging.
- **workspace_tick (parallel)** — N eligible all dispatched; `max_parallel` cap
  respected; in-flight-first slot filling; per-task failure contained; aggregate
  counts correct; empty → idle.
- **ledger thread-safety** — concurrent claims under the write-lock produce no
  double-claim and no corruption (stress test with a fake clock/executor).
- **dependency gate snapshot** — blocked child skipped this tick, dispatched the
  next once the upstream lands.
- **child publication** — each created child is set to `Todo`
  (injected backlog transport asserts `set_coarse_state`).
- **cli** — `--state` repeatable parses to a list; single value backward
  compatible; `--max-parallel` default applied.

## Rollout

The change is internal to the daemon tick; the operator surface
(`validate-config`, `status`, `pause`/`resume`, `reconcile-claims`) is unchanged.
After merge, the trading-advisor controller is updated to scan
`{In Progress, Todo}` with a `max_parallel` cap, and `DANNY-70` is given an
approved spec and moved to `Todo` to be intaken (tracked separately).
