# SMDA Architecture Rationale — Build vs. Adopt

Status: design rationale (agnostic; no runtime impl assumed)
Audience: any agent (Codex included) comparing this against the SMDA spec
Purpose: justify why the SMDA core should own only the *method*, delegate every
*mechanism* to adapters, and stop hand-coding logic that adapters already
provide. Hand-rolling that mechanism is wasted effort and a maintenance liability.

---

## 1. The one principle everything follows from

SMDA exists to **move control out of an in-context LLM orchestrator and into a
deterministic state machine**. That single goal forces two boundaries:

1. **Deterministic vs. prompted.** Anything that must run *without an LLM in the
   loop* (scheduling, routing, phase persistence) is **code**. Anything an LLM
   does *per attempt* (implement, review, fix) is a **prompt**. The control plane
   is therefore a program, never a skill.

2. **Core vs. adapters.** SMDA owns the deterministic control plane:
   scheduling, task graph, phase routing, phase ledger, parent integration/QA
   loop, and context packet assembly. It delegates the external mechanisms:
   sandboxing, structured-output extraction, tracker I/O, and harness discovery.
   Those sit behind adapter boundaries.

Everything below is a consequence of these two boundaries.

---

## 2. The three pieces

SMDA is **not "one skill."** It is three artifacts with three different forms.
Collapsing them into a single skill is the original design error — a skill is a
prompt read by an LLM, and it cannot *be* a daemon that runs unattended.

```
┌──────────────────────────────────────────────────────────────┐
│ (1) SETUP SKILL   — engineering plugin, per-repo installer     │
│     detect stack · write config · set .gitignore ·             │
│     validate · legacy hard-gate.                               │
│     Installs and wires. Contains NO engine.                    │
└───────────────────────────────┬──────────────────────────────┘
                                 │ onboards a repo onto ↓
┌──────────────────────────────────────────────────────────────┐
│ (2) SMDA RUNTIME  — product, versioned, agnostic METHOD core   │
│                                                                │
│   OWNS (irreducible product core):                             │
│     • scheduling: scan, claim, retry, concurrency, reconcile   │
│     • task graph: decompose, 2-stage review, bounded mutation  │
│     • routing / TRANSITIONS: verdict → next phase              │
│     • phase ledger (durable state — AFK resume truth)          │
│     • parent integration branch + QA loop (+ bounded counters) │
│     • context packets (static child + runtime)                 │
│                                                                │
│   REQUIRES, via adapter interfaces ↓↓↓                         │
└──────┬────────────────────────┬────────────────────┬──────────┘
       │                        │                    │
┌──────▼─────────┐   ┌──────────▼───────┐   ┌────────▼─────────┐
│ EXECUTION       │   │ BACKLOG           │   │ CONTEXT           │
│ adapter         │   │ adapter           │   │ adapter           │
│ default:        │   │ default: Linear   │   │ default: Codex    │
│ SandCastle      │   │                   │   │ harness           │
│                 │   │                   │   │                   │
│ • sandbox /     │   │ • parent/child    │   │ • repo map / gates│
│   attempt iso   │   │ • dependency edges│   │ • bootloader      │
│ • Output.object │   │ • coarse states   │   │ • ADR/spec paths  │
│   (extract +    │   │ • labels          │   │ • quality gates   │
│   validate +    │   │ • comments        │   │                   │
│   retry)        │   │                   │   │                   │
│ • session       │   │                   │   │                   │
│   capture/resume│   │                   │   │                   │
└─────────────────┘   └───────────────────┘   └──────────────────┘
```

(3) **SPEC / methodology** — the contract that both the runtime and the skill
reference (`methodology.md` plus the SMDA product docs). It defines the phases,
gates, and result shapes. It is documentation, not a running thing.

---

## 3. What gets deleted, and why hand-coding it was waste

Two kinds of deletion. Be precise about the difference — they are not the same
strength of claim.

- **→ Execution adapter (SandCastle):** *concrete free code.* The extraction /
  validation / retry / session machinery is an actual library feature. You stop
  writing it entirely; you keep only the *schema shape* (passed as the
  `Output.object` argument).
- **→ Scheduler product core:** claim / retry / concurrency / reconciliation are
  scheduler responsibilities compiled into the SMDA Scheduler product. The
  waste was duplicating those fields inside workflow run-state schemas.

| Hand-coded artifact | Delete → | Provided by | Why hand-coding it was waste |
|---|---|---|---|
| `*-result` extract-from-`<output>` code | Execution adapter | SandCastle `Output.object()` | Re-implements a solved library primitive (parse + schema-validate + retry-once). Pure duplication. |
| `*-result` type-validation code | Execution adapter | SandCastle `Output.object()` | Same. The schema *definition* is the only part worth keeping; the validator is free. |
| retry-on-invalid-output loop | Execution adapter | SandCastle `Output.object()` | A generic concern baked into every role by hand. |
| `role-attempt-envelope`, `phase-artifact-envelope` | Execution adapter | SandCastle session capture / resume + worktree | Session record + cross-phase artifact passing is library-owned. Keep only role↔schema id↔output tag linkage in the product role contract registry. |
| `child-run-state.attempts[]`, `.dependencies` | Scheduler product core | scheduler attempt ledger + dependency gate | Attempt history and dependency-block snapshots are scheduler state. Duplicating them inside workflow state causes drift. |
| `parent-run-state` claim/retry fields | Scheduler product core | scheduler claim/retry | Same — scheduler state leaking into the method ledger. |
| `tracker-reconciliation-report` | Scheduler product core + backlog adapter | scheduler reconciliation | Reconcile-after-partial-failure is scheduler/backlog observability, not workflow contract state. |
| review-failure → fix re-dispatch loop *engine* | Scheduler product core | scheduler continuation run | The *re-dispatch mechanism* is generic. The *decision* (next §5) is workflow routing. |

### The key correction this report exists to make

The single largest source of "I had to build so much" was re-implementing the
**structured-output pipeline** (define schema → run agent → extract → validate →
retry) once per role, and re-implementing **scheduler bookkeeping** (claim,
attempt, retry, reconcile) inside workflow state. Structured output belongs to
the execution adapter; scheduler bookkeeping belongs to the SMDA Scheduler
product core. Deleting duplicates is not loss of capability — it is removal of
drift.

---

## 4. What is NOT replaced — and was never the adapter's job

A review-failure → fix → re-review **decision** exists in **neither** adapter:

- The scheduler can *re-dispatch* an attempt, but only SMDA workflow routing
  knows that `verdict: FAIL` in `SPEC_REVIEWING` means "run the fixer."
- The execution adapter hands back a *typed result object* but explicitly
  *delegates workflow to caller code*. It does not route.

So the routing table is the irreducible core of SMDA:

```
agent text
   │  Execution adapter: Output.object(child-spec-review-result)   ← adopt
   ▼
typed result { verdict, required_next_action, findings }
   │  SMDA routing: TRANSITIONS[(phase, required_next_action)]      ← YOURS
   ▼
next dispatch: (phase=FIXING_SPEC, role=child_fixer)
   │  Scheduler core: continuation run re-dispatches the child       ← product
   ▼
(loop)
```

The boundary is the **typed result object**: upstream of it is the execution
adapter, downstream is SMDA routing, the re-dispatch is the scheduler. Three
parts make one loop. The middle is the only part no tool ships — and it is small
(a transition table), which is exactly why hand-building the other two parts was
the waste.

---

## 5. What SMDA-core irreducibly owns (do not delete these)

A guard list so the pruning above does not over-reach into things no adapter
covers:

1. **Task graph** — `smda-graph`, `graph-mutation-proposal`, dependency *typing*
   (`dependency-edge` type/reason/required-artifacts). Schedulers dispatch flat
   issues; execution adapters run flat tasks. The DAG is yours.
2. **Routing / TRANSITIONS** — verdict → next phase. The §4 table.
3. **Phase ledger** — the `child-run-state.phase` and `parent-run-state` phase
   enums. Load-bearing for AFK resume: the scheduler resumes *dispatch*, but
   mid-child *phase* resume reads this. Durability here is a hard requirement.
4. **Parent integration + QA loop** — integration branch, QA policy, bounded
   counters, remediation-child routing, feedback classification routing.
5. **Context packets** — `child-issue-packet`, `role-context-packet`. Context is
   a first-class artifact, not conversation history; no adapter assembles it.

Everything in §5 is the actual product. Everything in §3 was plumbing.

---

## 6. The form decision

| Concern | Form | Why |
|---|---|---|
| scheduler · routing · graph · phase ledger · QA | **Runtime product** (versioned package/service) | Deterministic, runs unattended without an LLM. A skill (an LLM prompt) cannot be a daemon. |
| detect stack · write config · validate · hard-gate | **Setup skill** (this plugin) | Per-repo install/wire step. Thin. Points target repos at the plugin-bundled runtime; contains no target-repo engine or role contract output. |
| phases · gates · result shapes | **Spec / methodology docs** | Contract referenced by both. |

This mirrors how the reference stacks are shaped: a contract document, a runtime
implementation, and a separate install/scaffold path. The runtime stays
adapter-aware but not scheduler-swappable: scheduling and workflow are product
core; execution, backlog, and context mechanisms remain adapter boundaries.

---

## 7. Deployment topology

The runtime is one long-running thing shipped by the SMDA plugin; repos are
onboarded onto it. Do **not** ship a full engine copy into every target repo.

```
        ┌───────────────────────────────────┐
        │  SMDA RUNTIME  (one deployment)    │
        │  backlog adapter watches tracker   │
        │  routing + graph + QA in core      │
        └───────┬────────────────┬───────────┘
        watches │                │ dispatches workers
         tracker│                │ (execution adapter: 1 sandbox / attempt)
        ┌───────▼───┐   ┌────────▼──┐   ┌──────────┐
        │ repo A     │   │ repo B    │   │ repo C   │
        │ WORKFLOW.md│   │ WORKFLOW  │   │ WORKFLOW │  ← each onboarded once
        │ + config   │   │ + config  │   │ + config │     by the setup skill
        │ + labels   │   │ + labels  │   │ + labels │
        └────────────┘   └───────────┘   └──────────┘
```

One runtime, many repos. The skill's per-repo job is to make a repo
*dispatchable* (config + harness routing + tracker labels/states), not to
install an engine or role contract bundle.

---

## 8. Checklist for comparing against the SMDA spec

- [ ] Every `*-result` schema kept as a shape, but its extract/validate/retry
      code removed (delegated to the execution adapter).
- [ ] No claim / attempt / retry / reconcile fields duplicated inside workflow
      run state; scheduler bookkeeping lives in the product scheduler core.
- [ ] Routing (`TRANSITIONS`) present as method-owned code — not a schema, not a
      prompt, not adapter-supplied.
- [ ] Graph, phase ledger, parent-QA, context packets retained as core.
- [ ] Runtime is a versioned product; the skill only installs/wires it.
- [ ] Execution, backlog, and context adapters declared as swappable product
      interfaces; scheduler/workflow core is not treated as a setup-time
      adapter.
```

If any of these fails, the spec is still paying to hand-build a mechanism an
adapter already owns — which is the waste this document exists to eliminate.
