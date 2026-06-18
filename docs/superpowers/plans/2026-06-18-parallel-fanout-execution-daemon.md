# Parallel Fan-out Execution Daemon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the SMDA daemon tick scan multiple coarse tracker states and dispatch every eligible candidate concurrently (bounded by `max_parallel`), so a full `parent → children → land` pipeline drains autonomously.

**Architecture:** Keep the existing per-tick model and the `Claim`/lease + durable-tracker-effect safety substrate. The tick scans an ordered set of states, computes the eligible candidate set from a scan-time snapshot, then dispatches up to `max_parallel` of them through a `ThreadPoolExecutor` batch-join. Ledger writes are serialized by an internal lock (WAL mode); agent subprocesses run in parallel. Published children are set to `Todo` so they are scannable.

**Tech Stack:** Python 3.13, stdlib `concurrent.futures.ThreadPoolExecutor`, stdlib `threading`, SQLite (WAL), pytest. Package root: `packages/scheduler`. Run tests with `uv run --project packages/scheduler pytest`.

## Global Constraints

- All source under `packages/scheduler/src/smda_scheduler/`; tests under `packages/scheduler/tests/`.
- Run tests: `uv run --project packages/scheduler pytest <path> -v`.
- `max_parallel` default = **3** (CLI `--max-parallel`, threaded through to the tick).
- Scan-state ordering is **in-flight first**: controller passes `--state "In Progress" --state Todo`; the ordered list is preserved end-to-end so slot-filling drains WIP before new intake.
- One dispatch per distinct issue per tick. An issue is in exactly one coarse state, so the merged candidate set has distinct issues — never double-claimed.
- Backward compatibility: a single `--state` value must still work (its list has one element).
- Child dispatch state constant: `_CHILD_DISPATCH_STATE = "Todo"` (mirrors `_ROADMAP_MEMBER_DISPATCH_STATE`).
- Commit after every task. Conventional Commit messages. End commit messages with:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

### Task 1: Multi-state scanner

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/scanner.py`
- Test: `packages/scheduler/tests/test_scanner.py`

**Interfaces:**
- Consumes: `CandidateBacklog.list_issues(*, state, label, parent_id, limit, cursor) -> BacklogPage` (unchanged).
- Produces:
  - `scan_dispatch_candidates(backlog, *, state: str, label, parent_id, limit=50, cursor=None) -> BacklogPage` (kept, backward compatible).
  - `scan_dispatch_candidates_multi(backlog, *, states: Sequence[str], label, parent_id, limit=50, cursor=None) -> list[tuple[str, BacklogIssue]]` — returns `(source_state, issue)` pairs in `states` order, then page order within each state.

- [ ] **Step 1: Write the failing test**

Add to `packages/scheduler/tests/test_scanner.py`:

```python
from collections.abc import Sequence

from smda_scheduler.scanner import scan_dispatch_candidates_multi


class MultiStateBacklog:
    def __init__(self, pages: dict[str, BacklogPage]) -> None:
        self.pages = pages
        self.states_scanned: list[str] = []

    def list_issues(self, *, state, label, parent_id, limit, cursor) -> BacklogPage:
        self.states_scanned.append(state)
        return self.pages.get(state, BacklogPage(issues=()))


def _issue(issue_id: str, state: str) -> BacklogIssue:
    return BacklogIssue(id=issue_id, title=issue_id, state=state, labels=frozenset({"agent"}))


def test_scan_multi_preserves_state_order_and_tags_source():
    backlog = MultiStateBacklog(
        {
            "In Progress": BacklogPage(issues=(_issue("DANNY-2", "In Progress"),)),
            "Todo": BacklogPage(issues=(_issue("DANNY-1", "Todo"),)),
        }
    )

    result = scan_dispatch_candidates_multi(
        backlog,
        states=["In Progress", "Todo"],
        label="agent",
        parent_id=None,
    )

    assert backlog.states_scanned == ["In Progress", "Todo"]
    assert result == [("In Progress", backlog.pages["In Progress"].issues[0]),
                      ("Todo", backlog.pages["Todo"].issues[0])]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project packages/scheduler pytest tests/test_scanner.py::test_scan_multi_preserves_state_order_and_tags_source -v`
Expected: FAIL with `ImportError: cannot import name 'scan_dispatch_candidates_multi'`.

- [ ] **Step 3: Write minimal implementation**

Append to `packages/scheduler/src/smda_scheduler/scanner.py` (add `from collections.abc import Sequence` and `from smda_scheduler.backlog import BacklogIssue` to imports):

```python
def scan_dispatch_candidates_multi(
    backlog: CandidateBacklog,
    *,
    states: Sequence[str],
    label: str,
    parent_id: str | None,
    limit: int = 50,
    cursor: str | None = None,
) -> list[tuple[str, BacklogIssue]]:
    candidates: list[tuple[str, BacklogIssue]] = []
    for state in states:
        page = backlog.list_issues(
            state=state,
            label=label,
            parent_id=parent_id,
            limit=limit,
            cursor=cursor,
        )
        candidates.extend((state, issue) for issue in page.issues)
    return candidates
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --project packages/scheduler pytest tests/test_scanner.py -v`
Expected: PASS (both old and new scanner tests).

- [ ] **Step 5: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/scanner.py packages/scheduler/tests/test_scanner.py
git commit -m "feat(scanner): add ordered multi-state candidate scan

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: PhaseLedger thread-safety (WAL + internal lock)

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/phase_ledger.py`
- Test: `packages/scheduler/tests/test_phase_ledger.py`

**Interfaces:**
- Produces: `PhaseLedger` is safe to call concurrently from multiple threads. No signature changes — an internal `threading.RLock` guards every public mutator/reader, and the DB is opened in WAL mode at construction.

**Note (design refinement):** the spec described an injected write-lock; an internal `RLock` on `PhaseLedger` is cleaner and transparent to callers. `PhaseLedger` already opens a fresh `sqlite3.connect(...)` with `BEGIN IMMEDIATE` per call, so the lock only needs to serialize whole-method calls, held for microseconds — never across an agent subprocess.

- [ ] **Step 1: Write the failing test**

Add to `packages/scheduler/tests/test_phase_ledger.py`:

```python
import threading

from smda_scheduler.phase_ledger import PhaseLedger


def test_concurrent_tracker_effect_writes_do_not_lock(tmp_path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    errors: list[Exception] = []

    def writer(n: int) -> None:
        try:
            ledger.record_tracker_effect(
                effect_id=f"effect-{n}",
                idempotency_key=f"key-{n}",
                effect_type="comment",
                target_id=f"DANNY-{n}",
                payload={"body": f"body {n}"},
            )
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(ledger.load_pending_tracker_effects()) == 20


def test_wal_mode_enabled(tmp_path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")
    import sqlite3

    with sqlite3.connect(ledger.path) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
```

(If `load_pending_tracker_effects` is not the exact reader name, use the existing reader for pending effects from `reconciliation.py` — confirm with `grep -n "def load_.*tracker_effect" phase_ledger.py` and adjust the assertion.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project packages/scheduler pytest tests/test_phase_ledger.py::test_wal_mode_enabled -v`
Expected: FAIL — journal mode is `delete` (default), not `wal`.

- [ ] **Step 3: Write minimal implementation**

In `phase_ledger.py`, add `import threading` at the top. In `PhaseLedger.__init__`, after `self.path` is set and the schema is ensured, enable WAL once and create the lock:

```python
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        # ... existing schema bootstrap ...
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
```

Wrap each **public** method body in `with self._lock:`. For example:

```python
    def record_tracker_effect(self, *, effect_id, idempotency_key, effect_type, target_id, payload):
        with self._lock:
            # ... existing body unchanged ...
```

Apply the same `with self._lock:` wrap to every public method that opens a connection (all `record_*`, `load_*`, `save_*`, `mark_*`, `is_parent_paused`, `set_parent_paused`, etc.). Internal helpers prefixed `_save_*`/`_load_*` that already run inside a locked public method must **not** re-acquire (the `RLock` is reentrant, so it is safe either way, but only wrap public entry points).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project packages/scheduler pytest tests/test_phase_ledger.py -v`
Expected: PASS (existing ledger tests + the two new ones).

- [ ] **Step 5: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/phase_ledger.py packages/scheduler/tests/test_phase_ledger.py
git commit -m "feat(ledger): make PhaseLedger thread-safe with WAL + internal lock

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Publish children into a scannable state

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/runtime.py` (function `run_parent_child_publication_tick`, ~line 1290-1353; constants block near `_ROADMAP_MEMBER_DISPATCH_STATE` ~line 486)
- Test: `packages/scheduler/tests/test_runtime_factory.py` (or the child-publication test file — confirm with `grep -rln "run_parent_child_publication_tick" tests/`)

**Interfaces:**
- Consumes: `BacklogPublicationAdapter.create_child(...) -> BacklogIssue`, `WorkspaceBacklog.set_coarse_state(issue_id, state)`.
- Produces: after publication, every created child issue is set to `_CHILD_DISPATCH_STATE = "Todo"`.

- [ ] **Step 1: Write the failing test**

Locate the existing publication test (`grep -rln "run_parent_child_publication_tick" packages/scheduler/tests/`). Add a test that the publication backlog receives a `set_coarse_state(child_id, "Todo")` for each created child. Mirror the existing publication test's fixture setup (graph + parent_run at `CHILD_PUBLICATION_READY`). Skeleton:

```python
def test_child_publication_sets_children_to_todo(tmp_path):
    # ... existing arrangement that drives run_parent_child_publication_tick ...
    # backlog is the recording publication adapter used by the existing test
    run_parent_child_publication_tick(issue=issue, ledger=ledger, backlog=backlog, ...)

    created_ids = [created.id for created in backlog.created_children]
    assert created_ids, "expected children to be created"
    for child_id in created_ids:
        assert (child_id, "Todo") in backlog.states
```

If the existing recording publication adapter does not capture `set_coarse_state`, extend it with a `self.states: list[tuple[str, str]]` list and a `set_coarse_state` method (mirror `RecordingBacklog` in `test_workspace_tick.py`).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project packages/scheduler pytest tests/<publication test file> -k child_publication_sets_children_to_todo -v`
Expected: FAIL — children are created but never set to `Todo`.

- [ ] **Step 3: Write minimal implementation**

In `runtime.py`, near `_ROADMAP_MEMBER_DISPATCH_STATE = "Todo"` add:

```python
_CHILD_DISPATCH_STATE = "Todo"
```

In `run_parent_child_publication_tick`, in the loop that calls `backlog.create_child(...)` and records the projection (~line 1311-1328), after `projections[node_id] = created.id` add:

```python
            backlog.set_coarse_state(created.id, _CHILD_DISPATCH_STATE)
```

(Place it inside the `if node_id in projections: continue` guard's else-path, i.e. only for newly created children, so re-runs stay idempotent — already guaranteed because the projection guard skips existing children.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --project packages/scheduler pytest tests/<publication test file> -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/runtime.py packages/scheduler/tests/<publication test file>
git commit -m "feat(runtime): publish children into Todo so the daemon can scan them

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Fan-out dispatch in the workspace tick

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/daemon.py` (extend `TickResult`)
- Modify: `packages/scheduler/src/smda_scheduler/workspace_tick.py`
- Test: `packages/scheduler/tests/test_workspace_tick.py`

**Interfaces:**
- Consumes: `scan_dispatch_candidates_multi` (Task 1); `classify_candidate`, `parent_dependency_gate`, `_record_block_effects` (existing in `workspace_tick.py`).
- Produces:
  - `TickResult(status: str, detail: str | None = None, dispatched: int = 0, blocked: int = 0, failed: int = 0, skipped: int = 0)`.
  - `run_workspace_tick(*, ledger, backlog, states: Sequence[str], label, parent_id, dispatch_candidate, issue_entry_policy=None, dispatch_routed_candidate=None, max_parallel: int = 3, limit=50, cursor=None) -> TickResult` — note `state: str` is replaced by `states: Sequence[str]`.

- [ ] **Step 1: Extend `TickResult` (write failing test)**

Add to `packages/scheduler/tests/test_daemon.py`:

```python
from smda_scheduler.daemon import TickResult


def test_tickresult_has_aggregate_counts():
    result = TickResult(status="dispatched", dispatched=2, blocked=1, failed=0, skipped=3)
    assert (result.dispatched, result.blocked, result.failed, result.skipped) == (2, 1, 0, 3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project packages/scheduler pytest tests/test_daemon.py::test_tickresult_has_aggregate_counts -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'dispatched'`.

- [ ] **Step 3: Extend `TickResult`**

In `daemon.py`:

```python
@dataclass(frozen=True)
class TickResult:
    status: str
    detail: str | None = None
    dispatched: int = 0
    blocked: int = 0
    failed: int = 0
    skipped: int = 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --project packages/scheduler pytest tests/test_daemon.py -v`
Expected: PASS.

- [ ] **Step 5: Write the failing fan-out test**

Add to `packages/scheduler/tests/test_workspace_tick.py`. This test uses two distinct candidates in two states and asserts both are dispatched in one tick, that ledger writes from concurrent dispatch do not error, and that the aggregate counts are correct. Use a `MultiStateBacklog` recording adapter (mirror Task 1, plus `comment`/`set_coarse_state` no-ops) and a routed-dispatch callback that records concurrency:

```python
import threading
from smda_scheduler.candidate_routing import CandidateRoute, CandidateRoutingDecision


def test_workspace_tick_dispatches_eligible_candidates_concurrently(tmp_path):
    ledger = PhaseLedger(tmp_path / "ledger.sqlite")

    class MultiBacklog:
        def __init__(self, pages):
            self.pages = pages
        def list_issues(self, *, state, label, parent_id, limit, cursor):
            return self.pages.get(state, BacklogPage(issues=()))
        def comment(self, issue_id, body): ...
        def set_coarse_state(self, issue_id, state): ...

    in_prog = BacklogIssue(id="DANNY-2", title="t2", state="In Progress",
                           labels=frozenset({"agent"}), body="Execution: smda-child")
    todo = BacklogIssue(id="DANNY-1", title="t1", state="Todo",
                        labels=frozenset({"agent"}), body="Execution: smda-child")
    backlog = MultiBacklog({
        "In Progress": BacklogPage(issues=(in_prog,)),
        "Todo": BacklogPage(issues=(todo,)),
    })

    seen: list[str] = []
    in_flight = []
    max_seen = [0]
    lock = threading.Lock()

    def routed(issue, decision):
        with lock:
            in_flight.append(issue.id)
            max_seen[0] = max(max_seen[0], len(in_flight))
            seen.append(issue.id)
        import time as _t; _t.sleep(0.02)
        with lock:
            in_flight.remove(issue.id)
        return TickResult(status="dispatched", detail=issue.id)

    def classify(issue, **_):
        return CandidateRoutingDecision(route=CandidateRoute.CHILD, reason="x",
                                        parent_issue_id="DANNY-0", node_id=issue.id)

    import smda_scheduler.workspace_tick as wt
    monkey = wt.classify_candidate
    wt.classify_candidate = classify
    try:
        result = run_workspace_tick(
            ledger=ledger, backlog=backlog,
            states=["In Progress", "Todo"], label="agent", parent_id=None,
            dispatch_candidate=lambda i: TickResult(status="blocked"),
            issue_entry_policy="explicit",
            dispatch_routed_candidate=routed,
            max_parallel=3,
        )
    finally:
        wt.classify_candidate = monkey

    assert set(seen) == {"DANNY-1", "DANNY-2"}
    assert result.dispatched == 2
    assert max_seen[0] == 2  # both ran concurrently
```

(If `CandidateRoute.CHILD` routing requires a non-`None` `parent_issue_id` graph in the ledger to dispatch, prefer routing through a fake `dispatch_routed_candidate` that ignores the decision contents — the test asserts the tick's *orchestration*, not real child execution. Keep `classify` returning a route that bypasses the parent/dependency gate, e.g. `CandidateRoute.CHILD`, which skips `parent_dependency_gate`.)

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run --project packages/scheduler pytest tests/test_workspace_tick.py::test_workspace_tick_dispatches_eligible_candidates_concurrently -v`
Expected: FAIL — `run_workspace_tick` rejects `states=`/`max_parallel=` (current signature takes `state: str`, dispatches one).

- [ ] **Step 7: Rewrite `run_workspace_tick` for fan-out**

Replace the body of `run_workspace_tick` in `workspace_tick.py`. Add imports:

```python
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

from smda_scheduler.scanner import scan_dispatch_candidates_multi
```

New function:

```python
def run_workspace_tick(
    *,
    ledger: PhaseLedger,
    backlog: WorkspaceBacklog,
    states: Sequence[str],
    label: str,
    parent_id: str | None,
    dispatch_candidate: DispatchCandidate,
    issue_entry_policy: str | None = None,
    dispatch_routed_candidate: DispatchRoutedCandidate | None = None,
    max_parallel: int = 3,
    limit: int = 50,
    cursor: str | None = None,
) -> TickResult:
    reconciliation = retry_pending_tracker_effects(ledger, backlog)
    detail_suffix = (
        f"reconciled={len(reconciliation.sent_effect_ids)}; "
        f"failed={len(reconciliation.failed_effect_ids)}"
    )

    candidates = scan_dispatch_candidates_multi(
        backlog, states=states, label=label, parent_id=parent_id,
        limit=limit, cursor=cursor,
    )
    if not candidates:
        return TickResult(status="idle", detail=detail_suffix)

    final_accepted = _final_accepted_parent_ids(ledger)
    skipped = 0
    blocked = 0
    # Each plan is (issue, thunk) where thunk() -> TickResult. Built from a
    # scan-time snapshot, in states order (in-flight first).
    plans: list[tuple[BacklogIssue, Callable[[], TickResult]]] = []

    for _source_state, candidate in candidates:
        if issue_entry_policy is None:
            plans.append((candidate, lambda c=candidate: dispatch_candidate(c)))
            continue

        decision = classify_candidate(candidate, issue_entry_policy=issue_entry_policy)
        if decision.route == CandidateRoute.BLOCK:
            _record_block_effects(ledger, issue=candidate, reason=decision.reason)
            blocked += 1
            continue

        paused_parent_id = _paused_parent_id(candidate, decision)
        if paused_parent_id is not None and ledger.is_parent_paused(paused_parent_id):
            skipped += 1
            continue

        if decision.route in {CandidateRoute.PARENT, CandidateRoute.IMPLICIT_PARENT}:
            gate = parent_dependency_gate(
                parent_id=candidate.id,
                blockers=ledger.load_roadmap_blockers(candidate.id),
                final_accepted_parent_ids=final_accepted,
            )
            if not gate.eligible:
                skipped += 1
                continue

        if dispatch_routed_candidate is None:
            plans.append((candidate, lambda c=candidate: dispatch_candidate(c)))
        else:
            plans.append(
                (candidate, lambda c=candidate, d=decision: dispatch_routed_candidate(c, d))
            )

    batch = plans[:max_parallel]

    def run_one(entry: tuple[BacklogIssue, Callable[[], TickResult]]) -> TickResult:
        issue, thunk = entry
        try:
            return thunk()
        except GraphError as error:
            _record_block_effects(ledger, issue=issue, reason=f"SMDA workflow error: {error}")
            return TickResult(status="failed", detail=f"{issue.id}: {error}")
        except Exception as error:  # contain any dispatch failure to its issue
            return TickResult(status="failed", detail=f"{issue.id}: {error}")

    results: list[TickResult] = []
    if batch:
        with ThreadPoolExecutor(max_workers=max_parallel) as pool:
            results = list(pool.map(run_one, batch))

    dispatched = sum(1 for r in results if r.status == "dispatched")
    failed = sum(1 for r in results if r.status == "failed")
    skipped += sum(1 for r in results if r.status == "skipped")
    blocked += sum(1 for r in results if r.status == "blocked")

    status = "dispatched" if dispatched else ("blocked" if blocked else "idle")
    detail = (
        f"dispatched={dispatched}; blocked={blocked}; failed={failed}; "
        f"skipped={skipped}; pending={max(0, len(plans) - len(batch))}; {detail_suffix}"
    )
    return TickResult(
        status=status, detail=detail,
        dispatched=dispatched, blocked=blocked, failed=failed, skipped=skipped,
    )
```

Add `from collections.abc import Callable` if not already imported (it is, via existing `from collections.abc import Callable`). Keep the existing `_final_accepted_parent_ids`, `_paused_parent_id`, `_record_block_effects` helpers unchanged.

- [ ] **Step 8: Keep all callers green (bridge runtime_factory + fix tests)**

The signature change (`state: str` → `states: Sequence[str]`) breaks the one production caller and the existing tests. Keep the suite green within this task:

1. **Bridge `runtime_factory.py`** so it still compiles (full generalization happens in Task 5). In the returned lambda, change `state=scan_state` to `states=[scan_state], max_parallel=3` — `scan_state` stays a `str` param here for now:

```python
    return lambda: run_workspace_tick(
        ledger=ledger,
        backlog=backlog,
        states=[scan_state],
        label=scan_label,
        parent_id=parent_id,
        dispatch_candidate=lambda issue: TickResult(
            status="blocked",
            detail=f"SMDA routing was not configured for {issue.id}",
        ),
        issue_entry_policy=config.policy.issue_entry,
        dispatch_routed_candidate=dispatch_routed_candidate,
        max_parallel=3,
        limit=limit,
        cursor=cursor,
    )
```

2. **Fix existing `test_workspace_tick.py` tests:** replace every `state="..."` call arg with `states=["..."]`.

Run: `uv run --project packages/scheduler pytest tests/test_workspace_tick.py tests/test_runtime_factory.py -v`
Expected: PASS — existing tests updated to `states=[...]`, the bridge keeps `runtime_factory` working, and the new concurrency test passes.

- [ ] **Step 9: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/daemon.py packages/scheduler/src/smda_scheduler/workspace_tick.py packages/scheduler/tests/test_daemon.py packages/scheduler/tests/test_workspace_tick.py
git commit -m "feat(workspace-tick): fan-out concurrent dispatch over a state set

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Wire scan-states + max_parallel through runtime_factory

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/runtime_factory.py`
- Test: `packages/scheduler/tests/test_runtime_factory.py`

**Interfaces:**
- Consumes: new `run_workspace_tick(..., states=..., max_parallel=...)` (Task 4).
- Produces: `build_configured_workspace_tick(*, ..., scan_states: Sequence[str], max_parallel: int = 3, ...)` — replaces `scan_state: str`. The returned tick lambda calls `run_workspace_tick(states=scan_states, max_parallel=max_parallel, ...)`.

- [ ] **Step 1: Write the failing test**

In `tests/test_runtime_factory.py`, find the existing builder test and add/adapt one asserting the built tick scans the provided ordered states. Use the existing fakes (`FakeBacklogAdapter`). Skeleton:

```python
def test_build_configured_workspace_tick_scans_state_set(tmp_path):
    # arrange config + fakes as the existing builder test does
    tick = build_configured_workspace_tick(
        config_path=config_path, repo_root=repo_root,
        backlog=backlog, execution=execution,
        scan_states=["In Progress", "Todo"], scan_label="agent",
        owner="smda-daemon", max_parallel=3,
    )
    tick()
    assert backlog.listed_states[:2] == ["In Progress", "Todo"]
```

(`listed_states` = however the existing `FakeBacklogAdapter` records `list_issues` state args; inspect `tests/fakes.py` and assert against the real attribute.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project packages/scheduler pytest tests/test_runtime_factory.py -k scans_state_set -v`
Expected: FAIL — `build_configured_workspace_tick` has no `scan_states`/`max_parallel`.

- [ ] **Step 3: Update `build_configured_workspace_tick`**

In `runtime_factory.py`: change the signature parameter `scan_state: str` → `scan_states: Sequence[str]`, add `max_parallel: int = 3` (add `from collections.abc import Sequence` if missing). In the returned lambda, change:

```python
    return lambda: run_workspace_tick(
        ledger=ledger,
        backlog=backlog,
        states=scan_states,
        label=scan_label,
        parent_id=parent_id,
        dispatch_candidate=lambda issue: TickResult(
            status="blocked",
            detail=f"SMDA routing was not configured for {issue.id}",
        ),
        issue_entry_policy=config.policy.issue_entry,
        dispatch_routed_candidate=dispatch_routed_candidate,
        max_parallel=max_parallel,
        limit=limit,
        cursor=cursor,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --project packages/scheduler pytest tests/test_runtime_factory.py -v`
Expected: PASS (update any existing builder test that passed `scan_state=` to `scan_states=[...]`).

- [ ] **Step 5: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/runtime_factory.py packages/scheduler/tests/test_runtime_factory.py
git commit -m "feat(runtime-factory): thread scan-state set and max_parallel to the tick

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: CLI — repeatable `--state` and `--max-parallel`

**Files:**
- Modify: `packages/scheduler/src/smda_scheduler/cli.py`
- Test: `packages/scheduler/tests/test_cli.py`

**Interfaces:**
- Consumes: `build_configured_workspace_tick(scan_states=..., max_parallel=...)` (Task 5).
- Produces: `daemon` subcommand accepts repeated `--state` (collected into a list, default `["Todo"]`) and `--max-parallel` (int, default 3). `_run_daemon_command` / `_build_live_daemon_tick` pass `scan_states` and `max_parallel`.

- [ ] **Step 1: Write the failing test**

In `tests/test_cli.py`, add a test using the `daemon_tick_builder` injection seam (the CLI already supports a custom builder) that captures the kwargs:

```python
def test_daemon_cli_collects_repeated_state_and_max_parallel(tmp_path):
    captured = {}

    def fake_builder(*, config_path, repo_root, scan_states, scan_label, owner, max_parallel):
        captured["scan_states"] = scan_states
        captured["max_parallel"] = max_parallel
        return lambda: TickResult(status="idle")

    cfg = tmp_path / "smda.config.json"
    cfg.write_text("{}")
    result = run_cli(
        ["daemon", str(cfg), "--repo-root", str(tmp_path),
         "--state", "In Progress", "--state", "Todo",
         "--max-parallel", "5", "--max-ticks", "1"],
        daemon_tick_builder=fake_builder,
    )

    assert captured["scan_states"] == ["In Progress", "Todo"]
    assert captured["max_parallel"] == 5
    assert result.exit_code == 0
```

(Import `TickResult` from `smda_scheduler.daemon` in the test. The `DaemonTickBuilder` signature changes to keyword `scan_states`/`max_parallel`; the fake matches it.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --project packages/scheduler pytest tests/test_cli.py -k repeated_state -v`
Expected: FAIL — `--state` currently stores a single string; builder takes `scan_state`, no `max_parallel`.

- [ ] **Step 3: Update the parser and daemon wiring**

In `_build_parser`, change the daemon args:

```python
    daemon.add_argument("--state", action="append", dest="state", default=None)
    daemon.add_argument("--label", default="agent")
    daemon.add_argument("--owner", default="smda-daemon")
    daemon.add_argument("--max-ticks", type=int, default=1)
    daemon.add_argument("--interval-seconds", type=float, default=30.0)
    daemon.add_argument("--max-parallel", type=int, default=3)
```

In `run_cli`'s `daemon` branch, normalize the default and pass new args:

```python
    if args.command == "daemon":
        return _run_daemon_command(
            config_path=args.config_path,
            repo_root=args.repo_root,
            scan_states=args.state or ["Todo"],
            scan_label=args.label,
            owner=args.owner,
            max_ticks=args.max_ticks,
            interval_seconds=args.interval_seconds,
            max_parallel=args.max_parallel,
            daemon_tick=daemon_tick,
            daemon_tick_builder=daemon_tick_builder,
        )
```

Change `_run_daemon_command` signature: replace `scan_state: str` with `scan_states: Sequence[str]`, add `max_parallel: int`. Update its builder call:

```python
                daemon_tick = builder(
                    config_path=config_path,
                    repo_root=repo_root,
                    scan_states=scan_states,
                    scan_label=scan_label,
                    owner=owner,
                    max_parallel=max_parallel,
                )
```

Change `_build_live_daemon_tick` signature: replace `scan_state: str` with `scan_states: Sequence[str]`, add `max_parallel: int`. Update its `build_configured_workspace_tick(...)` call to pass `scan_states=scan_states, max_parallel=max_parallel` (replacing `scan_state=scan_state`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --project packages/scheduler pytest tests/test_cli.py -v`
Expected: PASS (update any existing daemon CLI test referencing `scan_state` to `scan_states`).

- [ ] **Step 5: Commit**

```bash
git add packages/scheduler/src/smda_scheduler/cli.py packages/scheduler/tests/test_cli.py
git commit -m "feat(cli): repeatable --state and --max-parallel for the daemon

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Update the daemon controller template

**Files:**
- Modify: `plugins/smda-automation/skills/setup-smda-automation/daemon-operations.md` (the controller template block — the `uv run ... smda-scheduler daemon ...` invocation, and the §2 invocation-model description)

**Interfaces:**
- Consumes: the new CLI (Task 6).
- Produces: the documented controller invokes `--state "In Progress" --state Todo --max-parallel <N>`; §2 text describes per-tick fan-out over a state set.

- [ ] **Step 1: Update the controller invocation in the template**

In `daemon-operations.md`, in the controller template `run_loop`, change the daemon invocation:

```bash
    uv run --project "$SMDA_PROJECT" smda-scheduler daemon "$REPO_ROOT/smda.config.json" \
      --repo-root "$REPO_ROOT" --state "In Progress" --state Todo \
      --label agent --owner smda-daemon --max-parallel "${MAX_PARALLEL:-3}" --max-ticks 1 &
```

Add `MAX_PARALLEL` to the documented controller env near `STOP_GRACE` with a one-line comment.

- [ ] **Step 2: Update §2 "Daemon invocation model" prose**

Replace the single-state description so it states: a tick scans the ordered state set (`In Progress` then `Todo`, in-flight first), computes the eligible candidate set, and dispatches up to `--max-parallel` candidates concurrently (ThreadPool batch-join), still one bounded tick per `--max-ticks`. Note children are published into `Todo` and that `Agent Review` children need no scan (the parent lands them from the ledger).

- [ ] **Step 3: Verify the doc reads consistently**

Run: `grep -n "\-\-state\|max-parallel\|In Progress" plugins/smda-automation/skills/setup-smda-automation/daemon-operations.md`
Expected: the controller line and §2 both show the multi-state + `--max-parallel` invocation; no remaining `--state Todo \` single-state-only invocation in the controller template.

- [ ] **Step 4: Commit**

```bash
git add plugins/smda-automation/skills/setup-smda-automation/daemon-operations.md
git commit -m "docs(setup-smda): controller scans state set with --max-parallel fan-out

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] **Run the full scheduler test suite**

Run: `uv run --project packages/scheduler pytest -q`
Expected: all pass.

- [ ] **Confirm backward compatibility of a single `--state`**

Run: `uv run --project packages/scheduler pytest tests/test_cli.py -v`
Expected: a single `--state Todo` still resolves to `scan_states=["Todo"]`.
