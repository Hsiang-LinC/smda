# SMDA Component Inventory — files, tiers, and a pruning list

Status: draft for review (pre-implementation inventory)
Purpose: enumerate the intended components → modules → files of the finished
product, tag each by tier and the workflow step that uses it, and mark what to
**CUT / MERGE / DEFER / KEEP** before any code is written. This is the cut list
to apply before implementation, not a build order.

Tiers: T1 = fixed cores (scheduling + workflow). T2 = pluggable adapters. T3 =
config surface (setup skill). See `adapter-boundaries.md`.

---

## 1. Three artifacts

| Artifact | Form | Tier | Enters consumer repo? |
|---|---|---|---|
| SMDA Scheduler | versioned product (daemon + CLI) | T1 cores + T2 default adapters | No — one deployment |
| setup-smda-automation | SMDA plugin skill | T3 config surface | Yes, but writes config only |
| docs / spec | markdown contracts | cross-tier | Travels with the product |

---

## 2. SMDA Scheduler product

```
packages/scheduler/smda_scheduler/
  scheduling/    scanner.py claim.py retry.py reconciliation.py      # T1
  workflow/      graph.py transitions.py phase_ledger.py
                 context_packets.py parent_qa.py remediation.py      # T1
  adapters/
    backlog/     linear.py                                          # T2
                 # github.py/local.py deferred; fake backlog is tests only
    context/     codex_harness.py                                   # T2
    execution/   protocol.py sandcastle.py fake.py                  # T2
  cli/           control surfaces                                    # T1
  daemon/        long-running scan loop                              # T1
packages/sandcastle-runner/
  src/ runRoleAttempt.ts roleContracts.ts                           # T2 (TS)
packages/scheduler/src/smda_scheduler/role_contracts.py             # T1/T2 seam
  child role manifest: role↔phase↔schema_id↔output_tag↔prompt text
```

### scheduling/ (T1)

| file | purpose | workflow step |
|---|---|---|
| `scanner.py` | poll backlog, find eligible work; `tick` reuses this scanner | every dispatch pass |
| `route_dispatch.py` | route classified issues to child/task/parent/roadmap runtime handlers | configured dispatch |
| `claim.py` | claim/lease, concurrency slot, per-workspace lock | claim parent/child, serialized accept |
| `retry.py` | backoff + transient classification for `execution_failed` | adapter failure handling |
| `reconciliation.py` | post-crash tracker projection repair, pending-write resend | restart, tracker drift |

### workflow/ (T1 — irreducible core)

| file | purpose | workflow step |
|---|---|---|
| `graph.py` | smda-graph DAG, dependency typing, mutation application | decompose, dependency-gate |
| `transitions.py` | **TRANSITIONS table**: typed verdict → next phase | every routing decision |
| `phase_ledger.py` | parent/child phase truth, SQLite atomic write, AFK resume | every transition, crash recovery |
| `context_packets.py` | static + runtime packet assembly | CONTEXT_HYDRATING |
| `parent_qa.py` | integration verification, QA plan, bounded counters | parent closeout |
| `remediation.py` | QA bug → remediation child routing | QA loop |

### adapters/ (T2 — interface is product, new impl is a product contribution)

| file | purpose | note |
|---|---|---|
| `execution/protocol.py` | execution interface: `runAttempt`, `capabilities()` | interface = product |
| `execution/sandcastle.py` | default: IPC to TS runner, Output.object, worktree, session | every attempt |
| `execution/fake.py` | fake adapter for core tests | tests only |
| `backlog/linear.py` | Linear read/write, hierarchy/blocking projection | file, publish, accept |
| `backlog/github.py` | GitHub variant | see DEFER |
| `backlog/local_ledger.py` | local ledger tracker | implemented product adapter |
| `context/codex_harness.py` | bootloader/gate/doc-location discovery | packet assembly |

### role contracts and sandcastle-runner (T1/T2 seam + T2, TS)

| file | purpose |
|---|---|
| `runRoleAttempt.ts` | IPC request → createSandbox → run prompt → `Output.object` (extract+validate+retry-once) → typed result + evidence |
| `roleContracts.ts` | MVP schema id registry and `Output.object` schema lookup for supported role results |
| `role_contracts.py` | Python-side parent/child phase role registry used to assemble role, prompt text, output tag, and schema id for role attempts |

### shared contracts

- MVP shared contract is code-owned: Python `role_contracts.py` assembles parent
  and child attempt metadata; TypeScript `roleContracts.ts` validates supported schema
  ids and supplies the `Output.object` schema. Do not create a second
  hand-maintained JSON schema bundle.
- Future role manifest generation can replace the duplicated metadata when
  there is a real multi-version schema package to protect.

---

## 3. setup skill (T3)

| file | purpose |
|---|---|
| `SKILL.md` | onboarding flow: detect → propose → write config → validate → report; legacy hard-gate |
| `methodology.md` | SMDA method reference (not runtime) |
| `adapters.md` | available adapters + capabilities, to aid selection |
| `fixtures/README.md` | clean-room validation fixtures |

Emits `smda.config.yaml` (+ optional prompt wording override references). Never
engine, adapter code, schema bundles, report envelopes, generic harness files,
or prompt files. It requires the Engineering Codex development harness or an
equivalent repo context contract to exist first.

---

## 4. docs

`architecture-rationale.md`, `product-spec.md`, `adapter-boundaries.md`,
`contracts.md`, `trading-advisor-extraction-inventory.md`, this file.

---

## 5. Pruning list — CUT / MERGE / DEFER / KEEP

### CUT (delete; dead weight now)

| target | reason |
|---|---|
| `tracker-reconciliation-report` schema | already assigned to scheduler/backlog; a dead duplicate as a workflow schema. `reconciliation.py` produces the report internally. |
| `phase-artifact-envelope`, `role-attempt-envelope` schemas | covered by Sandcastle session capture + attempt ledger; keeping them resurrects what was already deleted. |
| `tracker-projection` schema | pure backlog-adapter concept, not a core schema. |
| `reports/smda/*.md` as *versioned contract* | reports are prompt scaffolding, not artifacts to validate. Keep evidence text inside role prompts/results, not a versioned file set. |

### MERGE (over-split; collapse)

| current | merge into |
|---|---|
| `graph-spec-review-result` / `graph-execution-review-result` / `child-spec-review-result` / `child-quality-review-result` / `child-fixer-result` (near-identical verdict+findings+next_action) | one `review-result.schema.json` + `review_type`. Half the 23 schemas share this shape — the largest over-engineering. |
| `parent_qa.py` + `remediation.py` | one module for MVP; remediation is a QA branch, not its own module. |
| `contracts/{workflow-contract-manifest, role-contract-manifest}` | defer external JSON manifests until schema package generation exists. MVP uses product code registries to avoid a second drifting source. |
| `pause-record` schema | a field on run-state, not a standalone schema. |

### DEFER (YAGNI; keep interface, build later)

| target | reason |
|---|---|
| `backlog/github.py`, `backlog/local.py` | first consumer is trading-advisor = Linear; product-spec already says no all-tracker support on day one. Ship `linear.py`, leave the interface for the rest. |
| execution providers `vercel`, `custom` | keep in the enum, don't implement for MVP; noSandbox + worktree suffices. |
| methodology roadmap layer (multi-parent restructuring) | an extra abstraction layer; v1 single-parent flow does not need it. Keep the doc, don't build the code. |
| §4 four-dimension version matrix, fully cross-ranged | MVP needs only `runtime ↔ config_schema_version`. Full cross-product is idle until multiple adapter versions exist in the wild. Ship a two-dimension gate first. |

### KEEP (core; do not prune)

`graph.py`, `transitions.py`, `phase_ledger.py`, `context_packets.py`,
`scanner.py`, `claim.py`, `execution/protocol.py` + `sandcastle.py` + `fake.py`,
`linear.py`, `codex_harness.py`, the parent/child role contract registry,
`child-run-state` / `parent-run-state` / `smda-graph` / `dependency-edge` /
the config schema.

### Net effect

Applying CUT + MERGE takes the schema set from ~23 to ~14 and removes two dead
modules/manifests. The highest-ROI prune is the `review-result` collapse plus
the four dead tracker/envelope schemas — do that before touching module
structure.
