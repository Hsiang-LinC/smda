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

This is an evolution of Symphony-style issue automation. The baseline Symphony
model schedules `Todo` issues into worker/reviewer/accept loops. SMDA extends
that model with parent/child graph orchestration, typed phase routing, and
parent closeout.

## Product Boundaries

### Product-Owned

SMDA Scheduler owns:

- backlog polling and dispatch coordination;
- parent spec intake and approval gates;
- child graph creation, graph review routing, and graph mutation policy;
- child phase routing: implement, spec review, quality review, fixer loops;
- durable phase ledger for parent and child runs;
- dependency-gated scheduling using graph edges and backlog blocking
  projections;
- context packet assembly for each role attempt;
- parent integration branch policy;
- parent verification, QA, feedback classification, remediation, and final
  accept;
- setup/onboarding contract for target repos.

### Adapter-Owned

Sandcastle execution adapter owns:

- agent process execution;
- sandbox/worktree/session lifecycle;
- branch strategy and commit collection for a role attempt;
- structured output extraction with `Output.object`;
- typed schema validation through Standard Schema;
- structured output recovery through `StructuredOutputError` session metadata;
- provider choice: `noSandbox`, Docker, Podman, Vercel, or custom providers.

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
contract. Most unit tests should run against a fake execution adapter; a small
smoke suite should exercise the real Sandcastle adapter.

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
        github.py
        local.py
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
    schemas/
    prompts/
```

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

The setup skill is not the runtime. It should:

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
- Do not require container sandboxing for MVP; support `noSandbox` first while
  keeping Docker/Podman provider config in the contract.
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
