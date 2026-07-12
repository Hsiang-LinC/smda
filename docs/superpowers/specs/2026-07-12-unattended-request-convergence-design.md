---
status: draft-for-human-review
date: 2026-07-12
---

# Unattended Request Convergence Design

## Purpose

SMDA is an unattended automation runtime for backlog work. A user or system
admits a Request, or supplies an already accepted spec, and may then leave.
SMDA gathers repository context, produces and reviews a spec when needed,
selects a workflow, schedules agent work, enforces review and integration
gates, lands accepted work, and projects progress back to the Backlog.

Human or operator participation is exceptional. It occurs only through an
actionable Escalation when authority, product judgment, or operating repair is
required.

This design evolves the current approved-spec executor into a complete
request-to-completion convergence loop. It preserves the existing Workflow
Engine, Workflow Definitions, Runtime Ledger, Workflow Graph, Parent and Child
roles, and Execution, Backlog, and Context Adapter seams.

## Current Gap

The current Runtime can execute an approved spec through decomposition, Child
implementation and review, Parent QA, and landing. It does not yet implement
the complete intended product:

- candidate classification primarily parses issue metadata;
- Parent and Roadmap intake require an approved repo spec path;
- admitted workflow progression is rediscovered through Backlog scans;
- a daemon tick waits for its dispatched worker batch to finish;
- a changed spec becomes a checksum error rather than a versioned Amendment;
- retry exhaustion and unrelated blocking causes collapse into
  `HUMAN_REVIEW_REQUIRED` phases;
- normal recovery may require an operator to select a phase with `force-phase`;
- required Backlog Projection enqueue is not atomic with every transition;
- Parent transitions repeat immutable spec facts and do not reject stale phases.

The last two gaps are already accepted in ADR-0009 and ADR-0010.

## Original A-E Deepening Requirements

This design incorporates the five architecture deepening decisions that
preceded the unattended-loop design. The requirements below are normative and
make their traceability self-contained.

### A. Parent Role Facts Have One Static Residence

Workflow Definitions are the only static residence for Parent Phase, Work
Handler kind, Role Contract, and pure transitions. Runtime implementations own
only stateful hooks, atomic persistence, heterogeneous Effects, and dynamic
bounded-policy escalation.

The duplicate Parent role-stage registry and the five pass-through Parent role
tick callers must be deleted. Adding a Parent RoleAttempt requires a Role
Contract, Stage/transition entries, and only the genuinely stateful success or
failure hooks; it must not require another forwarding caller or parallel stage
registry.

This preserves ADR-0006 while completing its intended deletion.

### B. Workflow Graph Is The Complete Child Graph Truth

The Workflow Graph owns every durable decomposition fact:

- Child identity, title, and body;
- acceptance criteria;
- in-scope and out-of-scope declarations;
- touched surfaces;
- verification requirements;
- risk classification;
- typed dependency edges, reasons, and required artifacts.

Scheduling derives the smaller node/dependency view it needs from this graph.
That derived view is an implementation detail, not another source of truth.
Child runtime Phase, claim, retry, and Attempt History remain Runtime Ledger
facts rather than Workflow Graph fields.

Graph acceptance atomically stores and activates one version, creates Child
runtime records, and enqueues publication intents. Tests exercise graph
normalization, validation, persistence, scheduling derivation, context
generation, and publication through this one domain shape.

### C. Runtime Ledger Exposes Semantic Attempt History

The Runtime Ledger is the complete durable machine truth, not only a Phase
table. Attempt History is the ordered record of Attempt requests and Attempt
Result Artifacts, interpreted through semantic workflow queries.

Workflow control must not load all Attempt rows and independently filter raw
status strings, Phase strings, idempotency keys, request JSON, or result JSON.
It consumes shared meanings such as:

- the next Attempt number for one Stage generation;
- the latest matching result;
- the latest review findings;
- the latest accepted-quality candidate reference;
- QA feedback and cycle statistics;
- conflict and resolver history.

A complete raw snapshot may remain available for read-only status and diagnosis,
but cannot drive transitions, retry, acceptance, QA, or conflict routing. The
same semantic Interface is the test surface for ordering, latest-result rules,
and evidence selection.

### D. Backlog Projection Uses A Transactional Outbox

Every required Backlog Projection effect commits in the same Runtime Ledger
transaction as the workflow change that produced it. Delivery occurs later
through the Backlog Adapter with stable idempotency and at-least-once retry.

The Backlog may lag but cannot become workflow truth or silently miss a
committed lifecycle change. Child and Roadmap publication additionally use
durable intents and Adapter receipts so externally allocated issue identifiers
do not reopen the transition/projection crash window.

Failure-injection tests must prove that a required projection cannot be absent
after its transition commits and that duplicate delivery does not duplicate the
semantic external effect. This requirement is recorded in ADR-0009.

### E. Parent And Roadmap Transitions Are Fenced

Initial intake is the only writer of immutable Accepted Spec facts. Later
Parent and Roadmap transitions preserve those facts and require the expected
current Phase; stale work fails instead of overwriting newer Runtime Ledger
truth.

A transition may atomically include its Attempt Result Artifact, Workflow Graph
change, operation fact, Escalation, and required Backlog Projections. The
unattended design extends the same fence with active ownership and expected
Request, Spec, and Workflow Graph versions.

The existing Child durable attempt path remains distinct; Parent and Child are
not forced through one shallow persistence Interface. Tests cover immutable
fact preservation, stale Phase/ownership/version rejection, and each required
atomic fact combination. This requirement is recorded in ADR-0010.

## Goals

1. Accept a raw Request or an already accepted spec through one external
   admission surface.
2. Run unattended until the work is completed, canceled, or parked in an
   actionable Escalation.
3. Make the Runtime Ledger and immutable Git references sufficient to explain
   current truth after daemon, worker, or Backlog failures.
4. Support multiple issues, Parents, Children, implementations, and reviews in
   parallel on one host.
5. Keep Backlog availability out of workflow progression and landing gates.
6. Prevent duplicate execution and stale worker completion under periodic
   daemon wakeups.
7. Reuse the existing Runtime and Adapter seams; add no broker or distributed
   event system without measured need.

## Non-goals

- remote worker fleets;
- a message broker;
- event sourcing;
- multi-coordinator high availability;
- arbitrary user-defined workflows;
- arbitrary phase mutation;
- a separate phase for each risk, wait, retry, or Escalation reason;
- replacing SQLite before a measured ceiling;
- reorganizing large files without a responsibility moving behind a deeper
  Module interface.

## Product Contract

### Admission Authority

An issue is admitted when it enters the configured Backlog scope and carries
the configured opt-in label or state. Admission authorizes SMDA to classify,
specify, implement, review, integrate, and land work within the Request's
expressed scope. It also authorizes required Backlog Projections.

An explicit manual opt-out prevents admission. Repo policy may additionally
require human authority for specified risk classes or before landing.

At admission, SMDA saves an immutable Request snapshot. Later semantic changes
do not silently replace that snapshot; they enter as versioned Amendments.

### Automatic Landing Authority

Admission authorizes landing to the configured target branch after all required
spec, Child, Parent QA, repository quality, conflict, and authority gates pass.
Landing is forbidden while a Pause, Cancel, pending Amendment, unresolved
Escalation, or stale Spec or Workflow Graph version exists.

Backlog Projection delivery is not a landing gate. A completed workflow may
remain visibly out of sync while the outbox retries or an Operator Escalation
is resolved.

## Request And Spec Flow

### Dual Intake, Single Accepted Spec

Two intake paths converge on one Accepted Spec Artifact:

1. **Supplied spec fast path:** validate its immutable Git reference, checksum,
   authority provenance, freshness, acceptance criteria, repository context,
   and policy requirements.
2. **Raw Request path:** gather context, author a spec, run independent spec
   review, fix bounded review findings, and accept by policy or Escalation
   resolution.

Downstream workflows do not branch on whether the spec was supplied or
generated.

### Spec Review And Authority

Spec review is always automated and independent of the writer.

- Low and normal risk: one independent reviewer may produce policy acceptance.
- High risk: require a second independent reviewer. Disagreement, ambiguity,
  authority expansion, or repo policy creates a Decision Escalation.
- Writer and reviewer must be distinct RoleAttempts.
- Model-reported confidence is not acceptance evidence.
- Deterministic completeness, traceability, path, checksum, and policy checks
  run before agent review.
- Repeated identical findings or exhausted fix cycles create a Decision
  Escalation.

Review validates spec quality. Authority determines whether SMDA may act on the
scope. These are separate facts.

### Git-backed Accepted Spec Artifact

The Accepted Spec Artifact identifies immutable content by Git path and
commit/blob reference. The Runtime Ledger stores the reference, checksum,
Request version, authority source, review evidence, risk class, and acceptance
kind.

- A supplied spec is pinned to an immutable Git reference at admission.
- A supplied spec that is not yet Git-tracked must first be materialized into
  an isolated spec commit; a mutable working-tree path alone is not accepted.
- A generated spec is committed through an isolated worktree and accepted into
  the Parent integration branch after review.
- Generated specs land with their implementation when repo policy persists
  specs in the repository.
- Attempt evidence may cache spec text for diagnosis and recovery, but does not
  create a second canonical spec.

### Amendments

An Amendment references the prior Request version and records a new immutable
Request snapshot. Impact analysis yields one of:

- no semantic change;
- spec update and review required;
- Workflow Graph update and review required;
- accepted work invalidated, requiring a Decision Escalation;
- scope removed, canceling unaccepted work.

An Amendment does not directly select a phase. The Workflow Definition applies
the legal action for the impact result.

## Workflow Selection

Request Intake selects an internal lifecycle:

- **Roadmap:** multiple Parents with dependency or landing relationships;
- **Parent:** decomposition, Child integration, Parent QA, and remediation;
- **single-task:** one low or normal risk scope without Parent decomposition or
  Parent QA.

Users do not need to know internal Child or task modes. Explicit execution
metadata remains an override and compatibility input, not the normal admission
requirement. Scheduler-created Child markers remain system-owned.

The single-task path creates a synthetic one-node Workflow Graph and reuses the
complete Child loop:

```text
implement
-> spec review
-> fix spec, if needed
-> quality review
-> fix quality, if needed
-> accepted
```

It may skip graph decomposition and Parent QA, but not Child spec or quality
review.

## Runtime Architecture

### One Runtime, Existing Deep Modules

The product remains one Automation Runtime with:

- Request Intake;
- a single Coordinator;
- one Workflow Engine interpreting Workflow Definitions;
- a Runtime Ledger;
- a bounded local worker pool;
- Execution, Backlog, and Context Adapters.

This design does not require a Module for every domain noun. Request,
Amendment, retry, Control Event, and Escalation records may remain behind the
Runtime Ledger interface until distinct variation justifies another seam.

### Truth Residence

| Fact | Canonical residence |
|---|---|
| admitted user intent | immutable Request snapshot |
| later requirement change | versioned Amendment |
| accepted spec content | immutable Git commit/blob |
| spec authority and review evidence | Runtime Ledger |
| Child decomposition | Workflow Graph in the Runtime Ledger |
| phase, claim, retry, Escalation | Runtime Ledger |
| candidate, integration, landed code | Git |
| human-visible lifecycle | Backlog Projection |
| process logs and sessions | Attempt evidence |

Backlog issues cease to be workflow progression truth after admission. They
remain the ingress for new Requests and Control Events and the target for
eventual projections.

### Coordinator Cycle

The configured timer wakes the Coordinator. A wakeup does not itself authorize
any Stage execution. Each cycle:

1. ingests new Requests and Control Events;
2. reconciles expired ownership and pending Effects;
3. harvests completed Attempts;
4. derives every nonterminal work item's disposition;
5. atomically claims runnable work;
6. submits work until bounded capacity is full;
7. returns without waiting for all in-flight workers.

The worker pool is long-lived. Multiple implementations and reviews may run in
parallel across issues, Parents, Children, phases, and workspaces. Only
operations sharing Git truth are serialized: accepting into one Parent
integration branch and landing into one target branch.

Continuation and review work takes precedence over unlimited admission of new
work. The initial selection policy is continuation-first and oldest-runnable;
no general priority framework is introduced.

### Runnable Contract

A Stage is runnable only when all required facts hold:

- workflow and Control state permit execution;
- the current Phase has a Stage and Work Handler;
- dependencies and aggregate gates are satisfied;
- no unresolved Escalation exists;
- no active claim or in-flight Attempt exists for this Stage generation;
- retry time has arrived;
- required prior Effects and operations are complete;
- expected Request, Spec, Workflow Graph, and Phase versions are current.

Otherwise the work must derive exactly one explanatory disposition:

```text
CLAIMED
WAITING_DEPENDENCY
WAITING_RETRY
WAITING_EFFECT
PAUSED
ESCALATED
TERMINAL
```

When multiple underlying facts apply, the displayed disposition uses this
precedence: terminal, escalated, paused, claimed, waiting for retry, waiting for
an Effect, waiting for a dependency, then runnable.

These dispositions are derived from durable facts instead of stored as another
state machine. `idle` is valid only when every nonterminal work item has an
explainable non-runnable disposition.

### Trigger Contracts By Work Handler

- **RoleAttempt:** trigger after an atomic claim; do not trigger while claimed,
  running, waiting for retry, paused, or escalated.
- **Effect:** trigger from a pending or retry-due durable operation intent; do
  not trigger after a receipt or completion is recorded.
- **Aggregate:** re-evaluate its pure gate on each cycle; commit its transition
  only once when the gate becomes satisfied.

Workflow Definitions own Phase, Stage, Role Contract, pure transitions, and
these handler semantics. Runtime implementations retain stateful hooks and
heterogeneous Effects. Duplicate Parent role registries and pass-through role
callers provide no additional behavior and should be removed during migration.

## Claims, Attempts, And Fencing

Each Attempt identifies its target, Phase, Request/Spec/Graph generation,
ownership token, and idempotency key. Claim acquisition and active ownership
recording are atomic.

Attempt completion may change workflow truth only when:

- the ownership token is still active;
- the expected Phase still matches;
- expected Request, Spec, and Workflow Graph versions still match;
- the completion has not already committed.

A late stale worker may add diagnostic evidence but cannot transition Phase,
accept a candidate, or enqueue lifecycle projections. After a crash, lease
reconciliation can create a new ownership token without granting authority to
the old worker.

The Coordinator renews leases for locally known in-flight Attempts on each
cycle. Reconciliation may expire ownership only after renewal stops and the
lease deadline passes. This prevents a long-running healthy worker from being
duplicated merely because another timer wakeup occurred.

## Retry And Workflow Transitions

Retry mechanics are separate from workflow Phase.

- Agent process, timeout, and recoverable protocol failures retry the same
  Stage with bounded backoff.
- Structured output recovery inside one execution session belongs to the
  Execution Adapter.
- A valid reviewer `FAIL` is a successful RoleAttempt result and follows the
  Workflow Definition to a fixer Phase; it is not an execution retry.
- Backlog Projection delivery retries independently of workflow Phase and may
  continue after workflow completion.
- Expected-phase or ownership mismatch rejects stale work and does not consume
  a workflow retry.

Execution retry budgets are scoped to one Stage generation. Review/fixer cycle
budgets remain separate workflow policy and do not consume execution retries.

Retry exhaustion leaves the workflow Phase unchanged and creates an actionable
Escalation. Generic `HUMAN_REVIEW_REQUIRED` phases are removed; escalation is a
control and liveness fact, not work progress.

## Control And Escalation

### Control Events

The normal external command set is intentionally small:

- `PAUSE` / `RESUME`;
- `CANCEL`;
- `AMEND`;
- `RESOLVE_ESCALATION`.

Pause stops new Attempts, acceptance, and landing. In-flight work may finish
and preserve evidence but cannot be accepted while paused. Cancel stops
unaccepted work and reaches terminal `CANCELED`; it does not automatically
revert already landed code. Authority revocation is a Cancel reason, not a
separate command.

Only Control Events that the Backlog Adapter has observed and durably admitted
can affect the workflow. A Backlog outage does not implicitly revoke existing
authority or pause admitted work.

`force-phase` remains an audited break-glass repair tool and is not a normal
resolution path.

### Escalation

Escalations have two audiences:

- **Decision:** requirement ambiguity, scope expansion, risk authority,
  reviewer disagreement, or non-converging product findings;
- **Operator:** credentials, Adapter failure, repo/worktree failure, projection
  failure, or Runtime invariant violation.

An Escalation records its reason, evidence, required action, and allowed domain
actions. A human or operator selects an allowed action; they do not select a
Phase. The Workflow Definition and policy determine whether the action retries
the same Stage, creates an Amendment, verifies an external fix, accepts a risk,
or cancels the work.

## Workflow Graph Activation And Publication

After graph reviews pass, one atomic Runtime Ledger change:

- stores and activates the accepted Workflow Graph version;
- creates Child runtime records;
- enqueues stable Child publication intents;
- moves the Parent into Child execution and aggregation.

Eligible Children may run immediately. They do not wait for external Child
issues to exist. External issue IDs are projection receipts, not Child
identities. Projection ordering ensures create precedes later state, comment,
dependency, or Escalation effects.

Child publication uses a durable saga: save intent, deliver with stable
idempotency, save the Adapter receipt, and retry unresolved intents. Publication
delay never becomes a workflow progression gate.

## Atomic Workflow Commit And Projection

A workflow result and every required durable fact commit together. Depending on
the Stage, this may include:

- expected-phase transition;
- Attempt Result Artifact;
- Workflow Graph mutation;
- retry or Escalation facts;
- Git accept or landing operation facts;
- Backlog Projection effects.

The Backlog Adapter delivers projections later with at-least-once semantics and
stable idempotency. A Backlog may lag but cannot silently miss a committed
transition. This extends ADR-0009 and ADR-0010 across publication and all
Parent/Roadmap transition paths.

Workflow completion and Projection delivery are separate facts. Final landing
does not wait for Projection delivery. Delivery beyond configured policy creates
an Operator Escalation while reconciliation continues.

## Parent And Child Completion

Child candidates pass independent spec and quality reviews before acceptance.
Accepted Child refs are integrated deterministically into the Parent integration
branch. Acceptance for one Parent is serialized; different Parents may proceed
in parallel.

After all required Children are accepted, Parent QA checks the integrated branch
against the Accepted Spec Artifact and repository gates. QA failure creates
bounded remediation Children that reuse the same Child workflow. Exhausted or
repeated identical findings create a Decision Escalation.

Final landing requires current authority, current Spec and Workflow Graph
versions, accepted required Children, Parent QA, repository gates, no active
control block, and a safe base/conflict probe. Conflicts use the existing bounded
resolver path before Escalation.

## Liveness And Failure Contract

Every nonterminal item must be runnable, claimed, waiting on an explicit
dependency/retry/effect, paused, or escalated. Unexpected exceptions are saved
as durable System Incidents; they cannot disappear into a transient tick result
or cause a false `idle` report.

Failure ownership is explicit:

| Failure | Default owner and behavior |
|---|---|
| same-session structured output recovery | Execution Adapter |
| transient execution failure | Scheduler retries same Stage |
| non-retryable or exhausted execution failure | Operator Escalation |
| valid reviewer failure | Workflow transition to fixer |
| repeated identical findings | Decision Escalation |
| stale completion | fenced rejection and truth reload |
| worker death | lease reconciliation and new claim |
| daemon crash | workspace lock release and durable reconciliation |
| Backlog outage | workflow continues; projection retries |
| Git conflict | bounded resolver, then Escalation |
| Runtime invariant violation | System Incident and Operator Escalation |

## Verification

### AFK Convergence Suite

With fake Adapters, repeatedly run Coordinator cycles until each scenario
reaches exactly one of:

```text
COMPLETED
ESCALATED with actionable allowed actions
CANCELED
```

Required scenarios:

1. raw Request to generated spec, single-task execution, and automatic landing;
2. supplied spec to Parent graph, parallel Children, Parent QA, and landing;
3. spec review failure, fixer, and successful re-review;
4. Child spec and quality fixer loops;
5. Parent QA remediation;
6. transient execution retry;
7. retry exhaustion, Operator resolution, and same-Stage resume;
8. requirement ambiguity, Decision resolution, Amendment, and re-review;
9. Pause during in-flight work and later Resume;
10. Cancel during execution without candidate acceptance;
11. Backlog outage with later projection convergence;
12. crash before and after claim, spawn, result, transition, external effect,
    and receipt;
13. duplicate poll and duplicate effect delivery;
14. stale worker completion after replacement;
15. delayed Child publication with continued Child execution;
16. Parent integration and final landing conflict paths;
17. multiple issues and mixed phases under bounded parallel capacity.

### Required Invariants

- at most one active ownership per Stage generation;
- stale ownership cannot transition workflow truth;
- transition and required Projection enqueue are atomic;
- an Accepted Spec immutable Git reference is reproducible;
- an Amendment cannot silently replace an active Spec;
- every `idle` result has explainable dispositions for all nonterminal work;
- Backlog state cannot drive admitted workflow progression;
- Escalation resolution cannot arbitrarily mutate Phase;
- writer/implementer cannot review or accept its own Artifact;
- automatic landing requires current authority and all configured gates.

### Concurrency

Use controlled fake workers whose completions arrive out of order. Verify that
the Coordinator harvests fast work and fills released capacity without waiting
for the slowest Attempt; continuations and reviews do not starve; different
Parents run in parallel; Parent integration and target landing retain narrow
serialization; configured concurrency is never exceeded.

### Live Validation

After deterministic tests pass, retain only focused live smoke coverage:

- one real Sandcastle RoleAttempt;
- one real Backlog create/comment/state sequence;
- one small raw-Request convergence flow;
- one daemon restart and reconciliation flow.

## Upgrade Boundary

Single-host parallelism does not require a distributed scheduler. Move beyond
this design only after evidence of at least one of:

- workers must execute across machines or specialized environments;
- runnable work waits while compute capacity is idle because the Coordinator is
  a measured bottleneck;
- SQLite claim/commit contention violates the scheduling objective;
- coordinator failover without lease-delay interruption is required;
- event replay, independent consumers, or temporal audit becomes a product
  requirement.

Remote workers, if eventually needed, are the next incremental step and do not
by themselves require event sourcing.

## Existing Decision Alignment

- ADR-0001: retains one Workflow Engine and multiple Definitions.
- ADR-0002: retains in-engine Roadmap decomposition and durable Parent
  dependency truth; supersedes the requirement that Roadmap direction must
  always be agreed outside the daemon because raw Roadmap Requests may now pass
  through automated spec intake and policy acceptance.
- ADR-0003: retains automatic Parent and Roadmap landing with serialized Git
  truth and bounded conflict repair; replaces its generic Human Review phase
  target with a typed Escalation.
- ADR-0004 and ADR-0005: retains product-owned Role Contracts and typed result
  validation.
- ADR-0006: retains kind-driven Parent dispatch, stateful bounded policies, and
  removal of duplicate role plumbing; exhausted policy creates an Escalation
  without replacing the current workflow Phase.
- ADR-0007 and ADR-0008: retains durable evidence and dedicated conflict
  resolution.
- ADR-0009: expands transactional Backlog Projection across all transitions and
  publication.
- ADR-0010: expands expected-phase Parent Transition into fenced atomic workflow
  commits.

Historical specs that require explicit execution metadata, a human approval for
every spec, Backlog-driven admitted progression, task-mode omission of Child
spec review, or generic Human Review phases are superseded by this design when
the corresponding migration lands.
