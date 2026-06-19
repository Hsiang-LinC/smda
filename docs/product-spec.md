# SMDA Scheduler Product Spec

Status: draft for review
Date: 2026-06-15

## Purpose

Build SMDA as a reusable scheduler product instead of hand-vendoring a custom
runtime into every consumer repo. The first consumer is `trading-advisor`, but
the product must stand on its own.

SMDA is a broad scheduler/workflow runtime:

```text
issue/backlog input
-> parent spec intake
-> reviewed child graph
-> dependency-gated child phase execution
-> parent integration and QA/remediation
-> final accept
```

This is an evolution of Symphony-style issue automation. Here "Symphony-style"
means the upstream idea of issue-driven agent scheduling; `codex-symphony` is
the local Python implementation used as an extraction source. SMDA extends that
baseline with parent/child graph orchestration, typed phase routing, and parent
closeout.

## Product Boundaries

### Tier 1 — Fixed Cores (Product-Owned)

Scheduling engine and workflow engine are compiled into the product, coupled and
not swappable. SMDA Scheduler owns:

- backlog polling and dispatch coordination;
- claim/lease, retry/backoff, concurrency, daemon lifecycle, and
  reconciliation;
- parent spec intake and approval gates;
- child graph creation, graph review routing, and graph mutation policy;
- child phase routing: implement, spec review, quality review, fixer loops;
- durable phase ledger for parent and child workflow phases;
- dependency-gated scheduling using graph edges and backlog blocking
  projections;
- context packet assembly for each role attempt;
- parent integration branch policy;
- parent verification, QA, feedback classification, remediation, and final
  accept;
- setup/onboarding contract for target repos.

### Tier 2 — Pluggable Adapters (Adapter-Owned)

Each adapter ships with a default and is swappable only by writing code against
its interface — a product contribution, never a setup-skill output.

Sandcastle execution adapter owns:

- agent process execution;
- sandbox/worktree/session lifecycle;
- branch strategy and commit collection for a role attempt;
- structured output extraction with `Output.object`;
- typed schema validation through Standard Schema;
- structured output recovery through `StructuredOutputError` session metadata;
- sandbox provider choice: `noSandbox`, Docker, Podman, Vercel, or custom
  providers;
- execution agent selection from Tier-3 config: provider, model, and optional
  effort.

Backlog adapters own:

- issue reads/writes;
- parent/child hierarchy projection;
- blocking relation projection;
- coarse state transitions and comments;
- tracker-specific labels/metadata.

Context adapters own:

- repository bootloader and harness discovery;
- quality gate discovery;
- roadmap/spec/ADR routing;
- repo-specific command and documentation references.

Scheduler mechanics are product core, not a swappable adapter. The product can
later expose narrower extension points for scheduling policy, but the initial
runtime owns scanning, claiming, retrying, reconciliation, and daemon operation.
Adapter agnosticism applies to execution, backlog, and context mechanisms.

## Architecture

Initial implementation should be hybrid:

```text
Python scheduler/runtime core
  uses
TypeScript Sandcastle execution adapter
```

Rationale:

- Existing `codex-symphony` provides a Python baseline scheduler: CLI, daemon,
  Linear adapter, scan/dispatch loop, review/accept primitives, janitor, and
  reconciliation.
- Existing `trading-advisor/symphony/smda_*` provides a Python SMDA prototype:
  graph, parent/child state, phase transitions, publication, acceptance, QA,
  and status surfaces.
- Sandcastle is TypeScript and already provides the execution primitives that
  should not be reimplemented in Python.

The Python core calls the TypeScript adapter through a stable JSON IPC
contract. The runner should be spawn-per-attempt for the first implementation:
the scheduler persists the attempt request before spawn, then records the
result or process failure after exit. A long-lived runner service can be added
later only behind the same IPC contract.

If the TypeScript process dies before returning a result, the scheduler records
`execution_failed` with the process exit code/signal and preserves any
Sandcastle worktree/log/session metadata available from stdout/stderr or the
configured artifact paths. The workflow transition is handled through adapter
failure policy, not through role verdict logic.

Most unit tests should run against a fake execution adapter; a small smoke
suite should exercise the real Sandcastle adapter.

## Runtime Modules

Suggested package layout:

```text
packages/scheduler/
  smda_scheduler/
    scheduling/
      scanner.py
      claim.py
      retry.py
      reconciliation.py
    workflow/
      graph.py
      transitions.py
      phase_ledger.py
      context_packets.py
      parent_qa.py
      remediation.py
    adapters/
      backlog/
        linear.py
        # github.py, local.py deferred; fake backlog lives in tests only
      context/
        codex_harness.py
      execution/
        protocol.py
        sandcastle.py
        fake.py
    cli/
    daemon/

packages/sandcastle-runner/
  src/
    runRoleAttempt.ts
    roleContracts.ts
```

## Schema Source Of Truth

The product must not define role result schemas independently in Python and
TypeScript.

Initial source of truth: TypeScript Standard Schema definitions exposed from
`packages/sandcastle-runner/src/roleContracts.ts`.

Generated artifacts:

- Python dispatch metadata in
  `packages/scheduler/src/smda_scheduler/role_contracts.py` for the parent and
  child phases currently assembled by the scheduler;
- schema version metadata included in every `RoleAttemptRequest` and
  `RoleAttemptResult`.

Version rule:

- Python scheduler config declares the expected schema package version. Concrete
  role schema ids are resolved from the product-owned schema manifest, with repo
  overrides reserved for an explicit advanced mode.
- The TypeScript runner returns its schema package version and schema id with
  each result.
- Version mismatch is `agent_protocol_failed`, not a role failure. The
  scheduler blocks the affected parent/child scope and records a repairable
  configuration error.

Python may type results with generated models or typed dictionaries, but it
does not own independent validation schemas for Sandcastle role output. The MVP
uses a small duplicated role metadata registry on the Python side only for
dispatch assembly; role output validation remains TypeScript/Sandcastle-owned.

## State Ownership

The product must separate workflow truth from scheduler/execution bookkeeping.

| Concern | Source of truth | Notes |
|---|---|---|
| Parent phase | SMDA phase ledger | Contains the semantic parent phase, spec ref/checksum, graph ref/checksum, integration branch, QA cycle count, remediation count, final accept ref. |
| Child phase | SMDA phase ledger | Contains node id, semantic child phase, current candidate ref, accepted commit, latest transition, pause/human-review marker. |
| Dependency truth | SMDA graph edges | Child state may cache `blocked_by_node_ids` as a derived snapshot, but graph edges are canonical. Backlog blocking relations are adapter projection. |
| Attempts | Scheduler/execution attempt ledger | Attempt history, session ids, logs, worktree paths, structured output errors, commits, and retry metadata do not live inside child-run-state. Child state may keep `latest_attempt_id` or `latest_result_ref`. |
| Claim/lease/retry/backoff | Scheduling state | Parent/child run state must not own generic dispatch claim or retry fields. |
| Tracker effects/projection | SMDA scheduler ledger (`tracker_effect_ledger`) | Intended backlog writes are recorded durably, retried before scans, and marked sent/failed. Backlog state such as Linear is the human-visible projection target, not the workflow database. |
| Tracker reconciliation | Scheduling/backlog reconciliation | Reconciliation reports are scheduler/backlog observability and repair surfaces, not SMDA workflow contracts. |

This means current prototype fields such as `child-run-state.attempts[]`,
canonical `child-run-state.dependencies`, parent claim/retry fields, and
workflow-owned `tracker-reconciliation-report` should not be carried forward as
SMDA workflow-state design.

The product CLI `status` command must report local workflow state and tracker
projection health together. Operators should use the local ledger status as
runtime truth, then inspect the backlog manager to confirm projection delivery.

## Final Accept And Merge Policy

Product v1 final accept means durable parent tracker closeout after parent QA
passes. The daemon records final evidence and tracker effects; it must not
implicitly merge, squash, rebase, or push the consumer repository main branch.

Main-branch merge, squash, and PR creation are explicit operator actions outside
the daemon in v1. A future `accept-parent --strategy ...` command may provide
that surface, but it must be a separate CLI action with dirty-tree checks,
verification command execution, and explicit operator invocation. It must not
run as a side effect of backlog scanning.

## Sandcastle Integration

The execution adapter request should include:

- `attempt_id`;
- `role`;
- `phase`;
- `branch`;
- `prompt` or `prompt_file`;
- `context_packet`;
- `output_tag`;
- Standard Schema reference or generated TypeScript schema module;
- sandbox provider config;
- hooks/copy settings;
- logging/correlation metadata.

The execution adapter result should include:

- `status`: `succeeded`, `structured_output_failed`, `execution_failed`,
  `canceled`;
- typed `result` when successful;
- `commits`;
- `branch`;
- `worktree_path` or preserved worktree path;
- `session_id` and `session_file_path` when available;
- `log_path`;
- structured error metadata.

SMDA must not parse role output text itself in normal execution. It receives
typed results from Sandcastle and applies workflow transitions.

## Adapter Failure Policy

Role verdicts and adapter failures are different events.

| Event | Owner | Default handling |
|---|---|---|
| `structured_output_failed` after same-session recovery is exhausted | execution adapter reports, scheduler records, workflow receives protocol failure | Mark attempt as protocol failed; retry according to role protocol retry limit; on exhaustion move child/parent to `HUMAN_REVIEW_REQUIRED` or `FAILED` per phase policy. |
| `execution_failed` from sandbox crash, agent process error, TS runner crash, or timeout | scheduler/execution | Retry with backoff when failure is classified transient; otherwise preserve artifacts and move scope to `BLOCKED` or `HUMAN_REVIEW_REQUIRED`. |
| schema version mismatch | scheduler/config | Block scope with configuration error; do not route as role verdict. |
| role result verdict/action | SMDA workflow engine | Apply transition table for the current phase. |

The implementation plan must make these rows explicit in a transition/policy
table before live execution is enabled.

## Durability And Crash Recovery

The durable ledger is a product requirement, not a best-effort log.

Initial store: SQLite under the runtime state directory, with file-based
artifacts for large prompt/log/session payloads. SQLite is chosen for atomic
phase, dispatch, and attempt metadata updates across daemon restarts.

Atomicity requirements:

- Before dispatching an attempt, persist the attempt request, target phase, and
  idempotency key.
- After adapter completion, persist the attempt result and phase transition in
  one transaction.
- Tracker writes are idempotent effects recorded in the ledger before being
  sent; pending writes are retried by scheduling reconciliation.
- Parent integration branch accept is serialized under a parent-level lock.

Crash during `ACCEPTING_TO_PARENT_BRANCH` is owned by SMDA Scheduler. Recovery
must inspect the parent integration branch, accepted child commit refs,
candidate patch refs, and ledger idempotency key, then either record the accept
as completed or resume/apply it exactly once. Backlog reconciliation only
repairs tracker projection; it does not decide branch truth.

## Isolation Policy

MVP isolation is git-worktree-per-attempt, not container-per-attempt.

`noSandbox` is acceptable for local MVP only when Sandcastle still creates an
attempt worktree/branch. Parallel children must never run against the same host
working tree. Container providers such as Docker or Podman are a second
isolation axis for untrusted code, dependency isolation, and stronger AFK
parallelism; they should be configurable from day one but not mandatory for
first local smoke tests.

## Multi-Repo State And Credential Isolation

One daemon serves many onboarded repos, so per-repo state must be namespaced by
a stable `workspace_id`. Without this, a daemonized runtime double-claims work
or leaks credentials across repos.

- **Derivation:** by default, `workspace_id` is derived by the runtime from
  `canonical_repo_root + backlog_adapter_id + backlog_scope_id`, where the
  scope id is the tracker project/workspace id or an adapter-declared local
  scope. Repo config does not define it except through an advanced override.
- **State:** `<state_root>/<workspace_id>/ledger.sqlite`; large payloads under
  `<artifact_root>/<workspace_id>/`. No shared ledger or artifact directory
  across workspaces.
- **Locks:** claim/lease locks are namespaced per workspace, with one lock per
  parent for serialized accept (see Durability And Crash Recovery).
- **Credentials/tokens:** adapter tokens are scoped per adapter-instance per
  workspace, resolved from that workspace's `smda.config.local.*` or a
  workspace-scoped secret reference. A workspace never reads another's secrets.
- **Concurrency slots:** counted per workspace and globally; the global cap
  bounds total host load across all repos.

## Workflow Semantics

SMDA phase transitions are method-owned. Examples:

```text
child IMPLEMENTING + implementer DONE
-> IMPLEMENT_DONE

child SPEC_REVIEWING + spec reviewer FAIL/fix_spec
-> FIXING_SPEC

child QUALITY_REVIEWING + quality reviewer PASS/accept_candidate
-> QUALITY_REVIEW_PASSED

parent QA_READY + QA FAIL/create_remediation_children
-> REMEDIATION_PLANNING
```

Sandcastle may retry bad structured output in the same session, but it does not
decide workflow transitions. Backlog adapters may re-dispatch or reconcile
work, but they do not decide SMDA phase routing.

Graph-aware dependency gating is workflow-informed scheduling. The scheduling
engine owns the dispatch loop, but it must query the workflow engine for
graph-derived eligibility. The only adapter-neutral dependency projection is
the backlog blocking relation; if the backlog lacks that capability, SMDA gates
purely on the internal graph.

For live child issue dispatch, backlog blocking relations are projection only.
The scheduler gates dispatch from SMDA-owned state: persisted graph edges,
child scheduler phases, latest quality-pass candidate refs, and completed
parent accept operations. A dependency-waiting child is skipped rather than
manually blocked so it can become eligible automatically after upstream accept
recovery completes.

## Planner Template Policy

Sandcastle's `parallel-planner` and `parallel-planner-with-review` templates are
reference examples, not the SMDA source of truth.

Use their ideas:

- typed planner output;
- deterministic branch naming;
- `createSandbox` for multiple sequential role attempts on the same branch;
- `Promise.allSettled` for parallel child pipelines;
- per-run commit/log/session evidence.

Do not use their workflow directly as SMDA core, because SMDA requires parent
spec compliance, graph spec review, graph execution review, child phase
routing, parent integration, and QA/remediation gates.

## Setup Skill Role

The setup skill is the Tier-3 config surface. It is not the runtime and never
emits engine or adapter code. It should:

- detect target repo context and backlog adapter;
- validate required files and quality gates;
- install or reference SMDA Scheduler;
- write config;
- place prompt/template/config artifacts when configured;
- validate adapter availability;
- warn on legacy worker/orchestrator paths;
- avoid starting daemons or publishing live issues without explicit approval.

Long term, setup should prefer linking to the product runtime over vendoring
runtime code. Vendoring templates/config is acceptable; vendoring engine code
should be a fallback for development only.

## First Consumer: Trading Advisor

`trading-advisor` is the first consumer and extraction source. It should not
remain the canonical SMDA runtime implementation.

After product packaging exists, trading-advisor should receive:

- runtime config;
- prompt/template references or vendored templates;
- harness/tracker/quality gate integration;
- any repo-specific adapters;
- migration cleanup removing hand-rolled runtime code that belongs in the
  product.

## Non-Goals For Initial Product

- Do not support every backlog manager on day one.
- Do not rewrite Sandcastle execution primitives.
- Do not make Sandcastle planner templates the SMDA workflow.
- Do not require container sandboxing for MVP; support `noSandbox` first only
  with git-worktree-per-attempt isolation, while keeping Docker/Podman provider
  config in the contract.
- Do not keep long-term copies of product runtime code in consumer repos.

## Success Criteria

- A target repo can be onboarded through the setup skill without hand-writing
  SMDA runtime code.
- The scheduler can discover eligible work, decide the next SMDA phase, and
  dispatch a typed role attempt through Sandcastle.
- Structured output parsing/validation is handled by Sandcastle, not by SMDA
  core.
- The phase ledger records enough state to resume after daemon or process
  interruption.
- Trading-advisor can later replace its hand-rolled `symphony/smda_*` runtime
  with this product.
