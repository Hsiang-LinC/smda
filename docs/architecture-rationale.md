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

2. **Method vs. mechanism.** SMDA owns the *method*: the task graph, the phase
   routing, the phase ledger, the parent integration/QA loop, the context
   packets. It must **not** own the *mechanism*: sandboxing, structured-output
   extraction, claim/retry/concurrency scheduling. Those are adapter
   responsibilities. They are well-solved by existing runtimes and must sit
   behind adapter boundaries — never hand-coded inside the method core.

Everything below is a consequence of these two boundaries.

---

## 2. The three pieces

SMDA is **not "one skill."** It is three artifacts with three different forms.
Collapsing them into a single skill is the original design error — a skill is a
prompt read by an LLM, and it cannot *be* a daemon that runs unattended.

```
┌──────────────────────────────────────────────────────────────┐
│ (1) SETUP SKILL   — engineering plugin, per-repo installer     │
│     detect stack · write config · emit role prompts ·          │
│     set .gitignore · validate · legacy hard-gate.              │
│     Installs and wires. Contains NO engine.                    │
└───────────────────────────────┬──────────────────────────────┘
                                 │ onboards a repo onto ↓
┌──────────────────────────────────────────────────────────────┐
│ (2) SMDA RUNTIME  — product, versioned, agnostic METHOD core   │
│                                                                │
│   OWNS (irreducible — no adapter provides this):               │
│     • task graph: decompose, 2-stage review, bounded mutation  │
│     • routing / TRANSITIONS: verdict → next phase              │
│     • phase ledger (durable state — AFK resume truth)          │
│     • parent integration branch + QA loop (+ bounded counters) │
│     • context packets (static child + runtime)                 │
│                                                                │
│   REQUIRES, via adapter interfaces ↓↓↓ (does not implement)    │
└──────┬────────────────────────┬────────────────────┬──────────┘
       │                        │                    │
┌──────▼─────────┐   ┌──────────▼───────┐   ┌────────▼─────────┐
│ EXECUTION       │   │ SCHEDULER         │   │ BACKLOG + CONTEXT │
│ adapter         │   │ adapter           │   │ adapters          │
│ default:        │   │ default:          │   │ default: Linear/  │
│ SandCastle      │   │ Symphony (SPEC)   │   │ GitHub + harness  │
│                 │   │                   │   │                   │
│ • sandbox /     │   │ • claim/dispatch  │   │ • parent/child    │
│   attempt iso   │   │ • retry/backoff   │   │ • dependency edges│
│ • Output.object │   │ • concurrency     │   │ • coarse states   │
│   (extract +    │   │ • reconciliation  │   │ • labels          │
│   validate +    │   │ • workspace per   │   │ • repo map / gates│
│   retry)        │   │   attempt         │   │                   │
│ • session       │   │                   │   │                   │
│   capture/resume│   │                   │   │                   │
└─────────────────┘   └───────────────────┘   └──────────────────┘
```

(3) **SPEC / methodology** — the contract that both the runtime and the skill
reference (`methodology.md`, `schemas/`, `contracts/`). It defines the phases,
gates, and result shapes. It is documentation, not a running thing.

---

## 3. What gets deleted, and why hand-coding it was waste

Two kinds of deletion. Be precise about the difference — they are not the same
strength of claim.

- **→ Execution adapter (SandCastle):** *concrete free code.* The extraction /
  validation / retry / session machinery is an actual library feature. You stop
  writing it entirely; you keep only the *schema shape* (passed as the
  `Output.object` argument).
- **→ Scheduler adapter (Symphony SPEC):** *an architectural boundary.* Claim /
  retry / concurrency / reconciliation is a scheduler responsibility. Whether you
  adopt an existing implementation or write your own, it must live **behind the
  adapter, not inside the method core.** The waste is entangling it with SMDA
  logic, not the existence of the code itself.

| Hand-coded artifact | Delete → | Provided by | Why hand-coding it was waste |
|---|---|---|---|
| `*-result` extract-from-`<output>` code | Execution adapter | SandCastle `Output.object()` | Re-implements a solved library primitive (parse + schema-validate + retry-once). Pure duplication. |
| `*-result` type-validation code | Execution adapter | SandCastle `Output.object()` | Same. The schema *definition* is the only part worth keeping; the validator is free. |
| retry-on-invalid-output loop | Execution adapter | SandCastle `Output.object()` | A generic concern baked into every role by hand. |
| `role-attempt-envelope`, `phase-artifact-envelope` | Execution adapter | SandCastle session capture / resume + worktree | Session record + cross-phase artifact passing is library-owned. Keep only prompt↔schema↔report linkage (folds into the manifest). |
| `child-run-state.attempts[]`, `.dependencies` | Scheduler adapter | scheduler claim/attempt + dependency gate | The attempt record and dependency-block gate are scheduler state. Duplicated inside the method ledger. |
| `parent-run-state` claim/retry fields | Scheduler adapter | scheduler claim/retry | Same — scheduler state leaking into the method ledger. |
| `tracker-reconciliation-report` | Scheduler adapter | scheduler reconciliation | Reconcile-after-partial-failure is the scheduler's defining job. Re-deriving it in the method is rework. |
| review-failure → fix re-dispatch loop *engine* | Scheduler adapter | scheduler continuation run | The *re-dispatch mechanism* is free (continuation run). Only the *decision* (next §5) is yours. |

### The key correction this report exists to make

The single largest source of "I had to build so much" was re-implementing the
**structured-output pipeline** (define schema → run agent → extract → validate →
retry) once per role, and re-implementing **scheduler bookkeeping** (claim,
attempt, retry, reconcile) inside the method. Both are adapter responsibilities.
Neither belongs in SMDA. Deleting them is not loss of capability — it is removal
of duplication.

---

## 4. What is NOT replaced — and was never the adapter's job

A review-failure → fix → re-review **decision** exists in **neither** adapter:

- The scheduler will *re-dispatch* an issue (continuation run) but does not know
  that `verdict: FAIL` means "run the fixer." Scheduler SPECs explicitly leave
  review loops out of first-class orchestrator concerns.
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
next dispatch: (phase=FIXING_SPEC, prompt=child-fixer.md)
   │  Scheduler adapter: continuation run re-dispatches the issue   ← adopt
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
| detect stack · write config · emit role prompts · validate · hard-gate | **Setup skill** (this plugin) | Per-repo install/wire step. Thin. Installs and points at the runtime; contains no engine. |
| phases · gates · result shapes | **Spec / methodology docs** | Contract referenced by both. |

This mirrors how the reference stacks are shaped: a contract document, a runtime
implementation, and a separate install/scaffold path. The runtime stays
adapter-agnostic — the execution and scheduler adapters above are *defaults*, not
hard dependencies; any implementation satisfying the capability list is valid.

---

## 7. Deployment topology

The runtime is one long-running thing; repos are onboarded onto it. Do **not**
ship a full engine copy into every repo.

```
        ┌───────────────────────────────────┐
        │  SMDA RUNTIME  (one deployment)    │
        │  scheduler adapter watches tracker │
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
*dispatchable* (WORKFLOW.md role prompts + config + tracker labels), not to
install an engine.

---

## 8. Checklist for comparing against the SMDA spec

- [ ] Every `*-result` schema kept as a shape, but its extract/validate/retry
      code removed (delegated to the execution adapter).
- [ ] No claim / attempt / retry / reconcile logic implemented inside the method
      core; all behind the scheduler adapter.
- [ ] Routing (`TRANSITIONS`) present as method-owned code — not a schema, not a
      prompt, not adapter-supplied.
- [ ] Graph, phase ledger, parent-QA, context packets retained as core.
- [ ] Runtime is a versioned product; the skill only installs/wires it.
- [ ] Execution and scheduler adapters declared as swappable defaults, not hard
      dependencies (agnostic preserved).
```

If any of these fails, the spec is still paying to hand-build a mechanism an
adapter already owns — which is the waste this document exists to eliminate.
