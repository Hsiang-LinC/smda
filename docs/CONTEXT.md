# SMDA Context

Domain glossary for the SMDA spec-driven development scheduler. Terms here are
meaningful to people reasoning about the workflow, not implementation details.

## Glossary

### Request
The immutable snapshot of user or system intent admitted for unattended SMDA
execution. Admission authorizes work only within the Request's expressed scope.
Later semantic changes are Amendments; they do not rewrite the admitted Request.

### Admission
The point at which a Backlog item in the configured scope receives the configured
opt-in and becomes an SMDA Request. Admission establishes execution and automatic
landing authority within the Request scope, subject to repo policy and later
Control Events.

### Amendment
A versioned semantic change to an admitted Request. An Amendment is assessed
against the current Accepted Spec Artifact, Workflow Graph, and accepted work;
it may leave them unchanged, require new review, invalidate work, or escalate a
decision. Editing a Backlog projection does not silently replace workflow truth.

### Accepted Spec Artifact
The immutable specification governing a workflow, identified by Git path and
commit/blob reference with its checksum, Request version, authority provenance,
review evidence, and risk class. It may originate from a supplied spec or from
SMDA spec writing; downstream workflows treat both origins identically.

### Policy Acceptance
Automated acceptance of a reviewed spec when its scope remains within Request
authority and its risk class permits unattended execution. Policy Acceptance is
distinct from spec quality review and from a human decision required by policy.

### Control Event
An admitted external instruction that changes whether or under what intent a
workflow may proceed: Pause/Resume, Cancel, Amend, or Resolve Escalation. Control
Events do not directly set workflow phases.

### Escalation
An actionable durable pause when unattended work needs either a product decision
or an operating repair. It records evidence and allowed domain actions; a human
or operator resolves an Escalation by selecting an allowed action, never by
choosing an internal phase.

### Roadmap
A directional unit of work spanning multiple **Parents**, executed in dependency
order. SMDA models a Roadmap *emergently*: it is not a stored entity. A Roadmap
is the set of `Execution: smda` Parent issues plus the parent-to-parent blocking
edges between them. A Roadmap is "done" when every member Parent has reached
`FINAL_ACCEPTED`. Roadmap progression is the parent-tier analogue of the existing
child dependency gate: a Parent becomes dispatchable once all of its upstream
blocking Parents are accepted, and auto-unblock happens for free on the next scan
tick. Decided 2026-06-16 (emergent over first-class).

### Parent
A workflow scope governed by one Accepted Spec Artifact that needs decomposition,
Child integration, Parent QA, and final acceptance. It owns its Workflow Graph
and integration truth. One Parent may also be one node on a Roadmap.

### Roadmap Spec
The Accepted Spec Artifact whose scope requires decomposition into multiple
Parents and their dependency relationships.

### Roadmap Decomposer
The in-engine role that reads a Roadmap Spec and authors the whole parent set at
once — every member Parent issue plus every parent-to-parent dependency edge —
with global visibility of the set. Because one author sees the whole set,
cross-parent *dependency* is resolved at source (the parent-tier analogue of how
parent→child decomposition authors child dependencies). It does NOT resolve
cross-parent *conflict* (two parents editing the same file), which is a
file-level fact invisible from specs and handled by a separate integrate-time
gate. Decided 2026-06-16 (in-engine authoring over ad-hoc).

### Child
A scheduler-created issue (`Execution: smda-child`) produced by decomposing a
Parent's spec into a dependency graph of implementable nodes. Runs the SDD loop
(implement → spec review → quality review → accept).
Child execution context comes from the persisted graph/ledger; the tracker issue
body is the human-visible projection, not machine truth.

### Workflow Graph
The complete, durable graph authored by Parent decomposition: every Child's
identity, title, body, acceptance criteria, scope, touched surfaces,
verification, risk, and typed dependency edges. It is persisted in the Runtime
Ledger as workflow truth. Scheduling derives the node/dependency view it needs
from this graph inside the implementation; that view is not a second source of
truth. The Workflow Graph does not own a Child's runtime phase, claim, or
attempt history, which remain Runtime Ledger scheduler state.

### Runtime Ledger
The durable store of SMDA machine truth for a workspace. It owns Parent, Child,
and Roadmap workflow state; Request and Amendment versions; Accepted Spec
references; Workflow Graph persistence; Attempt Result Artifact history; claims,
retries, Control Events, and Escalations; Parent acceptance and landing
operations; and pending Backlog Projection effects. Phase progress is one part
of this ledger, not its whole interface. Backlog issues and Local Ledger Backlog
entries remain human-visible projections, not runtime truth after Admission.

### Parent Transition
An atomic Runtime Ledger change that moves a Parent or Roadmap from its expected
current phase to its next phase while preserving the Accepted Spec Artifact facts
established at intake. It may commit associated Attempt Result Artifacts,
Workflow Graph changes, and required Backlog Projection effects together; Child
phase progression follows its separate durable workflow path.

### Backlog Projection
The adapter-neutral, durable record of workflow lifecycle changes that must be
reflected in a Backlog. Required effects are atomically enqueued with the
Runtime Ledger transition that produced them, then delivered to a Backlog
Adapter asynchronously with stable idempotency; the Backlog may lag but cannot
silently miss a committed transition.

### Local Ledger Backlog
A target repo's own file-backed work ledger used as an SMDA backlog source and
projection target. It remains the repo harness truth for work items, states, and
review gates. SMDA maps only adapter-neutral routing fields, comments/evidence,
and parent/child references through it; SMDA workflow phases stay in the product
runtime ledger.

### Parent Integration Conflict Resolver
The in-engine role that resolves a Child accept conflict on a Parent's
integration branch. Its goal is narrow: make the next deterministic Child
acceptance operation succeed for the conflicted Child without changing the
Parent's Accepted Spec Artifact or bypassing acceptance bookkeeping. It is not
a generic code reviewer or a manual merge escape hatch.

### Member (of a Roadmap)
A Parent that participates in a Roadmap. Membership is expressed by the
parent-to-parent blocking edges, not a stored list.

### Workflow Definition
A data description of one workflow: its phases, the transition table
(phase × verdict × action → phase), the role-by-phase map, the terminal phases,
and the dependency gate. SMDA runs ONE workflow engine that interprets these
definitions. `smda` (parent e2e), `smda-child` (SDD loop), `smda-task`,
`smda-review`, and the parent/roadmap tier are each a Definition, not a bespoke
code path. Adding a workflow = adding a Definition to the registry, not adding an
if-branch. Decided 2026-06-16 (one engine, many definitions).

### Stage
One step of a Workflow Definition: a gate (may I run?), a unit of work, and a
transition (verdict → next phase). The work is pluggable — see Work Handler.

### Work Handler
The pluggable "what this stage actually does" behind a Stage. The same engine
runs a stage whether the work is a single agent role attempt, a deterministic
effect, or waiting on a sub-workflow to finish (the last one is how a Parent
waits for its Children and how a Roadmap waits for its Parents — same code).

### Route / Mode
The persisted lifecycle choice that selects which Workflow Definition runs. An
`Execution:` value may explicitly override or provide compatibility input, but
normal Request Intake selects the Route; scheduler-created Child modes remain
system-owned. A Mode is a registry key, not a branch of dispatch logic. A Route
represents runtime lifecycle shape, not work-content category: short tasks,
debugging, test-writing, and proof-of-concept work should fit an existing Route
unless their ledger truth source, deterministic effects, or acceptance semantics
differ.

### Methodology Skill
The versioned, reusable description of *how* a role does its job well (e.g. `tdd`
for implementing, `to-issues` for decomposing, `diagnose` for fixing). The same
skill library humans invoke interactively. A Role Contract declares which
Methodology Skill(s) govern it, and the runner injects that content into the role
attempt so behaviour does not depend on the model's per-turn improvisation.
Decided 2026-06-16 (declared + injected over inlined or self-selected).

### Role Contract
The per-role specification: its persona, its task/prompt template, the output
schema it must satisfy, and the Methodology Skill(s) it binds. The unit a
`RoleAttempt` stage runs.

### Attempt Result Artifact
The machine-readable result produced by an execution adapter for one role
attempt. It is the scheduler's workflow-control input and carries the attempt
status, typed role output when present, and failure metadata when absent.
_Avoid_: Sandcastle IPC, process output

### Attempt History
The ordered record of role-attempt requests and Attempt Result Artifacts in the
Runtime Ledger. Workflow decisions consume semantic evidence derived from this
history — such as the latest matching result, review findings, candidate refs,
or conflict history — and never filter raw ledger rows themselves. A complete
read-only snapshot may support operator status and diagnosis, but it must not
drive workflow control.

### Process Logs
The human-readable stdout/stderr evidence emitted while a role attempt runs.
Process Logs may explain or diagnose an attempt, but they are not workflow
control input.
_Avoid_: IPC stream, result stream
