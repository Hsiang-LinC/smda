# SMDA Context

Domain glossary for the SMDA spec-driven development scheduler. Terms here are
meaningful to people reasoning about the workflow, not implementation details.

## Glossary

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
A single approved spec issue (`Execution: smda`). The largest unit the engine
orchestrated before Roadmap support. Owns its own decomposition graph, scheduler
state, QA, and acceptance. One Parent = one node on a Roadmap.

### Roadmap Spec
The single approved issue that triggers roadmap decomposition (the roadmap-tier
analogue of a Parent's spec). Its direction is agreed in an interactive
human+agent discussion; the issue is then decomposed in-engine into the parent
set.

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

### Parent Integration Conflict Resolver
The in-engine role that resolves a Child accept conflict on a Parent's
integration branch. Its goal is narrow: make the `CHILDREN_PUBLISHED` child
acceptance pass for the conflicted Child without changing the Parent's approved
spec or bypassing acceptance bookkeeping. It is not a generic code reviewer or a
manual merge escape hatch.

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
The `Execution:` value on an issue (`smda`, `smda-child`, `smda-task`,
`smda-review`, `manual`) that selects which Workflow Definition runs. A Mode is a
registry key, not a branch of dispatch logic.

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

### Process Logs
The human-readable stdout/stderr evidence emitted while a role attempt runs.
Process Logs may explain or diagnose an attempt, but they are not workflow
control input.
_Avoid_: IPC stream, result stream
