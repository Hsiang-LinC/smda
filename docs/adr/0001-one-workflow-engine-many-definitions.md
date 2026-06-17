---
status: accepted
---

# One workflow engine, many definitions

SMDA's child workflow is already data-driven (a transition table + role-by-phase
map + dependency gate), but the parent workflow is a hard-coded if-ladder and
each execution mode (`smda`, `smda-child`, `smda-task`, …) is dispatched by a
bespoke `run_X_candidate_tick` in a route if-ladder. To make the system modular,
deep, and pluggable — where end-to-end is just one pipeline among many — we will
run ONE workflow engine that interprets **Workflow Definitions** (data: phases,
transition table, role map, terminal set, dependency gate). Parent, child, task,
review, and the parent/roadmap tier each become a registered Definition; adding a
workflow is a registry entry, not an if-branch.

A Stage's work is one of a closed set of three **Work Handlers** —
`RoleAttempt` (run one agent role), `Effect` (deterministic tracker/git ops), and
`Aggregate` (run a sub-workflow over child nodes until a terminal condition).
The `Aggregate` handler is the same code for "a Parent waits for its Children"
and "a Roadmap waits for its member Parents", which is the proof the unification
is natural rather than forced.

## Considered options

- **Two table-driven tiers (no full unify):** give the parent its own transition
  table but keep per-route bespoke ticks behind a dispatch map. Rejected: kills
  the parent if-ladder but leaves mode behaviour as shallow option flags and two
  separate engines.
- **Opaque work `Callable` per stage:** rejected — bespoke orchestration would
  hide inside lambdas, moving shallow proliferation rather than removing it; no
  shared `Aggregate`.
- **Everything-is-a-role-attempt:** rejected — forces deterministic effect and
  wait stages to masquerade as LLM roles.

## Consequences

- The in-flight plan `docs/superpowers/plans/2026-06-16-execution-modes-and-workflow-options-plan.md`
  is **redirected**: its typed `ExecutionMode` / `ModeTag` / `WorkflowOptions`
  survive as definition-selection inputs, but its `require_spec_review` boolean
  threading and net-new `run_task_candidate_tick` branch are replaced by a
  task Workflow Definition.
- Roadmap support (see [CONTEXT.md](../CONTEXT.md) "Roadmap") rides the same
  engine at the parent tier via an `Aggregate` stage — no separate roadmap FSM.
