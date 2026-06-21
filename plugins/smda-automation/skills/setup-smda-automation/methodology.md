# SMDA Methodology

State-Machine-Driven Automation externalizes the control contract that an
LLM orchestrator normally keeps in its live session. It keeps LLMs as
stateless specialists and makes the manager deterministic.

## Agnostic Contract

SMDA does not require a specific harness, backlog manager, or orchestrator.
Any stack can host it if it provides these capabilities:

- durable project context: bootloader, architecture map, roadmap/spec/ADR
  locations, tracker contract, quality gates, contracts;
- backlog graph: roadmap-to-parent references when used, parent/child grouping,
  dependency edges, coarse states, comments/evidence;
- deterministic runtime state: task graph, phase ledger, attempts,
  artifacts, retry counters, failure fingerprints;
- isolated agent execution: fresh workspace per attempt;
- accept gate: apply candidate, run verification, record evidence, advance
  state;
- human pause/resume: Human Review or equivalent decision gate.

Default adapters are Codex development harness, Linear, and the SMDA Scheduler
product runtime. The method is not defined by those tools, but setup may only
wire adapters that exist in the product.

## Vocabulary

- **AFK**: planning/intake assessment that enough context exists for automation
  to start.
- **HITL**: planning/intake assessment that a human decision, scope, context, or
  approval is needed before or during automation.
- **`Execution:`**: scheduler routing marker on a tracker item body. It selects
  a workflow definition when SMDA is allowed to claim the item.
- **Agent Review**: execution gate where an automated candidate is ready for
  non-human review or acceptance handling.
- **Human Review**: execution gate where runtime needs a human decision,
  approval, missing context, or escalation handling.
- **Roadmap**: optional planning artifact for multi-parent restructuring. It
  records direction, shared constraints, spec-parent candidates, and parent
  dependencies, but it is not executable work.
- **Parent issue**: backlog-visible feature/spec item. Owns the approved spec,
  task graph, parent integration branch, parent QA, and final accept.
- **Child issue**: backlog-visible task node, usually one graph node.
- **Task node**: SMDA graph node backed by a child issue.
- **Phase**: deterministic execution step inside a task node.
- **Attempt**: one stateless agent invocation for one phase.
- **Artifact**: persisted input/output shared across phases.

| Term | Layer | Meaning |
|---|---|---|
| AFK | planning/intake | Context is sufficient for automation to start. |
| HITL | planning/intake | Human decision, scope, context, or approval is needed before or during automation. |
| `Execution:` | scheduler routing | Machine-readable route selecting an SMDA workflow definition. |
| `Agent Review` | execution gate | Automated candidate is ready for non-human review or acceptance handling. |
| `Human Review` | execution gate | Runtime needs human decision, approval, missing context, or escalation handling. |
| `Execution: manual` | routing opt-out | Scheduler must not claim the issue. |

## Roadmap Layer

Use a roadmap only when one feature/restructure is too broad for a single
parent spec. A roadmap is a thin layer above SMDA parents:

```text
roadmap / direction
-> multiple spec parent issues
-> each parent runs normal SMDA decomposition and child execution
```

The roadmap may define dependencies among parent issues, using the same backlog
dependency mechanism as child issues where possible. It may also hold shared
architecture constraints, non-goals, migration phases, and open decisions.

Roadmaps do not run implement/review loops, own integration branches, publish
child issues directly, or become the execution source of truth. Execution starts
only after a parent issue reaches `SPEC_FINALIZED`.

## Parent Flow

```text
Todo rough-intake parent
-> draft spec
-> Human Review
-> approved spec front matter + checksum
-> SPEC_FINALIZED
```

or:

```text
parent starts with approved spec
-> SPEC_FINALIZED
```

Then both tracks converge:

```text
SPEC_FINALIZED
-> decomposition
-> graph spec compliance review
-> graph execution-quality review
-> publish child issues
-> run children
-> parent verification
-> QA_READY / Human Review when policy requires
-> accept parent integration branch to main
```

## Control Surfaces

An SMDA runtime should expose deterministic control surfaces without adding a
second workflow:

- `status <parent>`: summarize parent/child phase, closure, dependencies, pause
  gates, and tracker-projection health from durable state;
- `validate <parent>`: validate persisted parent-run state and graph
  references, including contract manifests, graph checksums, materialized child
  mappings, closed-child commit evidence, and attempt artifact refs;
- `tick <parent>`: run one normal orchestrator/scanner pass, anchored to a
  parent identifier for operator visibility;
- `pause/resume <parent|parent#child>`: write or clear durable pause gates;
- `approve-spec <parent>`: write approved spec metadata and refresh the parent
  run checksum;
- `publish-children <parent> --dry-run`: produce a tracker publication plan
  without live writes;
- `approve-qa <parent>` or parent-accept equivalent: final approved accept;
- `add-qa-feedback <parent> --file <path>`: record feedback for classifier-led
  remediation.

The `tick` command must call the same scanner used by daemon mode. Do not build
parallel state-transition rules into the CLI.

Status truth is intentionally local-first. The SMDA ledger is the workflow
truth for parent phase, child phase, claims, attempts, pause gates, and pending
tracker effects. Linear or another backlog manager is the human-visible tracker
projection. A short mismatch between the ledger and Linear is normal while the
daemon drains `tracker_effect_ledger`; it becomes an operational problem when
`smda-scheduler status` shows pending effects with `last_error`/
`pending_with_errors`, the daemon is not running, or the same pending effect
survives repeated ticks.

## Issue Entry Policy

SMDA-only repos must not keep an independent generic worker path for autonomous
implementation. Setup must choose and document one issue-entry policy:

- explicit-only: dispatchable autonomous work must be `Execution: smda`;
- implicit one-child: eligible unmodeled work is normalized into a parent with
  one child task;
- blocked: unmodeled work is rejected until a parent spec/context packet exists.

Whichever policy is selected, child execution still uses `Execution:
smda-child` handles and the normal child phase machine.

Approved specs must be durable artifacts, normally under
`docs/superpowers/specs/`, with front matter equivalent to:

```yaml
status: approved
approval_evidence: <tracker comment, conversation ref, or review packet>
```

Draft specs may live in repo docs, but `status: draft` cannot drive
decomposition.

## Graph Decomposition

The decomposer produces a task graph, not executable work by itself. The graph
must pass two reviews before publication:

1. **Graph spec compliance**: covers every parent requirement, adds no extra
   scope, and traces child acceptance criteria to the spec.
2. **Graph execution quality**: validates dependency types, touched surfaces,
   parallel safety, task size, verification, and missing context.

Graph review failures loop through a fresh graph fixer. The fixer may change
only findings-scoped nodes/edges. Broader rewrites produce a replan proposal
or Human Review.

The default role prompt set is product-owned. This skill does not install role
prompts into target repos. Target repos may reference optional wording/context
override paths only when the product supports override compatibility checks:

- `parent-spec-shaper.md` for rough intake to draft spec;
- `graph-decomposer.md` for child graph proposals;
- `graph-spec-reviewer.md` and `graph-execution-reviewer.md` for graph gates;
- `child-implementer.md`, `child-spec-reviewer.md`,
  `child-quality-reviewer.md`, and `child-fixer.md` for the child phase loop;
- `parent-qa.md` and `qa-feedback-classifier.md` for parent closeout and QA
  feedback routing.

Runtime state transitions consume structured result objects produced through
the product execution adapter. With the Sandcastle adapter, structured output is
owned by `Output.object`; setup must not require hand-parsed `<output>` blocks
or copied schema validators in target repos. Freeform reports, tracker comments,
and Markdown summaries are evidence, not transition truth.

The complete role/schema/transition contract belongs to the SMDA Scheduler
product. Setup validates product/config compatibility and optional prompt
override compatibility; it does not install schema files, report envelopes,
workflow manifests, tracker projection schemas, attempt envelopes, or phase
artifact envelopes into consumer repos.

Use Sandcastle structured output when a role prompt mixes work and reporting:

```text
run role prompt with product-owned Output.object schema
-> product runner extracts one structured result object
-> retry structured output recovery once when validation fails
-> fail as agent_protocol_failure when it still does not validate
```

The product role contract is the source of truth for:

- prompt, report, schema id, output tag, and result-schema linkage;
- allowed `required_next_action` values for each role;
- success/failure transition targets;
- required static and runtime context packet fields;
- expected artifacts;
- reviewer independence policy;
- backlog/tracker side effects in adapter-neutral terms.

## Child Phase Machine

Each child task runs an SDD-shaped internal machine:

```text
READY
-> context hydration
-> implement attempt
-> spec review
-> fix spec loop when needed
-> quality review
-> fix quality loop when needed
-> accept into parent integration branch
-> CLOSED / Done
```

Reviewer attempts must be independent from the implement/fix attempt they
review. Spec reviewer and quality reviewer are separate attempts; different
sessions are preferred but not always a hard requirement.

Natural-language report sections are evidence only. Phase transitions require
structured results validated by the product execution adapter. A role attempt
should record product prompt/schema version metadata and any configured prompt
override reference.

## Context Packets

Context is a first-class artifact, not conversation history.

Static child packet:

- parent spec path/checksum and relevant sections;
- task goal, in-scope, out-of-scope;
- dependencies and dependency types;
- touched surfaces;
- acceptance criteria;
- required verification;
- reviewer checklist.

Runtime packet:

- parent integration branch and current head;
- dependency outputs and accepted commits;
- current candidate patch/diff when reviewing/fixing;
- attempt counters and failure fingerprints;
- graph mutations already applied;
- known risks and prior attempt summaries.

Missing mandatory context means do not dispatch. Return a context hydration
failure or Human Review instead of asking a worker to become a mini
orchestrator.

## Dependencies And Parallelism

Dependency edges carry type, reason, dispatch blocking policy, and required
artifacts:

- `code_dependency`: usually blocks dispatch until upstream is Done.
- `contract_dependency`: may run in parallel only when a frozen contract
  artifact/checksum exists.
- `test_dependency`: usually verified at parent integration time.
- `sequencing_only`: ordering evidence without code blocking.

Independent children may implement/review in parallel. Accept into the parent
integration branch is serialized. A child is Done only after its candidate is
accepted into the current parent branch and required child verification passes.

## Failure And Mutation

Workers and reviewers may propose graph mutations, but they never mutate the
graph directly. The deterministic manager applies only approved, bounded
mutations:

- split pending child;
- add prerequisite child;
- narrow scope;
- adjust dependencies among not-yet-started children;
- cancel a pending child only when superseded.

High-risk changes, public contract changes, parent spec changes, repeated
failure fingerprints, and broad replans go to Human Review.

Failures carry a `freeze_scope`: child, downstream, overlap group, or parent.
Maximize automation by freezing the smallest safe scope.

## Parent Integration And QA

Each parent owns an integration branch. Child candidates are accepted into that
branch. Parent completion runs full verification and creates a QA plan or
Human Review packet according to risk policy.

Default final accept strategy: squash the parent integration branch into main,
recording child commits and artifacts in the parent completion evidence.

QA feedback that is a bug against the approved spec becomes a remediation child
inside the same parent run. New requirements or changed direction go to Human
Review/spec amendment. QA loops need bounded limits by fingerprint, total
remediation children, and parent QA cycles.

Default QA loop policy:

```yaml
max_same_feedback_fingerprint: 2
max_total_remediation_children: 5
max_parent_qa_cycles: 3
on_limit_exhausted: HUMAN_REVIEW_REQUIRED
```

These values belong in product policy/config, not in individual issue
descriptions or setup-generated runtime files. Hitting a limit must stop further
automatic QA/remediation and route the parent to Human Review with evidence.

## Artifact Residence

- Repo docs: durable specs, ADRs, contracts, architecture, final reusable QA.
- Runtime state: task graph, packets, attempts, candidates, review findings,
  mutation proposals, dependency summaries.
- Tracker: project visibility, parent/child grouping, dependencies, summaries,
  human decisions.

Intermediate runtime artifacts are audit/recovery logs, not long-term docs.
Promote reusable knowledge into repo docs before parent Done.
