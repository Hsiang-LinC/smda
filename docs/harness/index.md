<!-- codex-harness: generated 2026-06-17 -->
# Development Harness Index

Last verified: 2026-08-07

Single residence of routing facts for this repo. Bootloaders point here;
never copy these tables elsewhere. Tracker identity lives only in
`docs/harness/tracker.md`.

## Start Sequence

1. Read `docs/harness/tracker.md`; read your work item's `phase`, `source`,
   `next`, and recorded evidence per its Read/Write section. Resume from that
   phase; do not restart design or advance on conversation memory alone.
2. Read `docs/harness/roadmap.md` § Current Node — know where this work
   sits in the long-horizon sequence.
3. Identify your task type in the routing table.
4. Read the listed context; use the listed workflow.
5. Before closing: post completion evidence and the state update per
   `tracker.md`; update durable repo docs when facts changed.

## Task Routing

| Task type | Read first | Workflow | Completion update |
|---|---|---|---|
| New feature | `docs/CONTEXT.md` (glossary), the relevant `docs/adr/`, the package you touch (`packages/sandcastle-runner` TS / `packages/scheduler` Python) | Use `superpowers:brainstorming`; unresolved behavior follows Work Production design/PRD. A bounded item with an approved source revision and an eligible tracker entry proceeds to Interactive implementation; an approved multi-slice source follows Plan intake. | tracker update per `tracker.md`; durable docs if facts changed |
| Plan intake (approved spec/plan → work items) | the approved spec/plan in `docs/superpowers/specs/` and `docs/superpowers/plans/` | `engineering:to-issues` (else split per `tracker.md` § Work Item Format) | work items created in `active.md`, dependencies encoded (`blocked-by:`), each linking the source plan |
| Bug / regression | `docs/known-gaps.md`, the failing test, the package source | `superpowers:systematic-debugging` (or `engineering:diagnose`) | regression test added; tracker update per `tracker.md` |
| Interactive implementation | the approved source, work-item acceptance and verification, touched package | Use `engineering:tdd` for behavior-changing code, scripts, or config; for nonbehavioral changes use the item's acceptance and applicable quality gates. Use `superpowers:writing-plans` → `superpowers:executing-plans` when the task needs a multi-step plan. | criterion-level evidence and candidate revision per `tracker.md` |
| Unfamiliar area | `docs/architecture-rationale.md`, `docs/component-inventory.md`, `docs/contracts.md`, then the package source | targeted reading (dispatch the Explore agent for broad sweeps) | index/map update if stable knowledge gained |
| Architecture decision | `docs/CONTEXT.md` + the relevant `docs/adr/` entries | `engineering:grill-with-docs` then write an ADR in `docs/adr/` | the ADR; glossary term added to `CONTEXT.md`; tracker update per `tracker.md` |
| Completion check | `docs/harness/quality-gates.md`, `tracker.md` § State Machine | `superpowers:verification-before-completion` → for interactive-owned work, run Codex built-in `codex review` on the frozen candidate when available. Record an explicit decision by a distinct reviewer on that exact candidate; if built-in review does not provide one, use `superpowers:requesting-code-review` to dispatch an independent reviewer. Resolve findings and re-review changed candidates. Runtime-owned work returns its role artifact for SMDA review dispatch. | verification and independent acceptance evidence per `tracker.md` |

## Work Production

How new work enters this product repo's development tracker. User-in-the-loop
by design — orchestrated agents consume the output of this pipeline; they never
run it. This is a development-harness rule, not the SMDA product runtime's
unattended execution policy:

1. Position: read `roadmap.md` — which node is current, is it specced?
2. Design when behavior is unresolved: `engineering:grill-with-docs` (or
   `superpowers:brainstorming`) — resolved terms land in `docs/CONTEXT.md`,
   hard decisions in `docs/adr/`.
3. PRD: use `engineering:to-prd` when product behavior needs a durable approved
   spec; a single bounded item with approved scope may use a scoped plan.
4. Issueize: use `engineering:to-issues` when the approved source needs multiple
   independently reviewable slices; encode dependencies and apply
   `tracker.md` § Dispatch Eligibility. A single bounded item stays one item.
5. Node close: when the current node's items are all terminal, propose the
   roadmap advance to the user (see `roadmap.md` header rule).

## Artifact Adapters

| Artifact type | Residence | Notes |
|---|---|---|
| Roadmap / upgrade map | `docs/harness/roadmap.md` | One direction residence. Keep milestone and upgrade ordering here; do not create initiative directories. |
| Active work slices | `docs/work-ledger/active.md` | Tracker truth for currently actionable slices. Use `parent:` to group slices under a roadmap upgrade without duplicating status in the roadmap. |
| Follow-up debt | `docs/work-ledger/follow-ups.md` | Parking lot only. Promote into `active.md` when a slice becomes actionable. |
| Specs and plans | `docs/superpowers/specs/`, `docs/superpowers/plans/` | Source artifacts for designed work; active tracker entries link back here instead of copying full plans. |
| ADRs | `docs/adr/` | Hard-to-reverse architecture decisions only. |

## Domain Docs

| Domain fact | Residence |
|---|---|
| Vocabulary and core concepts | `docs/CONTEXT.md` |
| Product contracts and schemas | `docs/contracts.md` |
| Adapter and consumer/product boundaries | `docs/adapter-boundaries.md` |
| Architecture rationale and component map | `docs/architecture-rationale.md`, `docs/component-inventory.md` |
| Known product gaps | `docs/known-gaps.md` |

## Quality Gates

Quality-gate commands, cheap harness checks, and completion expectations live in
`docs/harness/quality-gates.md`.

## Coexisting Systems

| System | Class | Truth |
|---|---|---|
| Design-workflow skills (`superpowers:*`, `engineering:*`) | orthogonal-composed | the skill library; this harness supplies tracker/domain/quality-gate facts directly |
| `docs/superpowers/plans/` + `docs/superpowers/specs/` (target-C phase history) | orthogonal-composed | historical record; completed milestones mirror into `completed.md` |
| `plugins/smda-automation/` (`setup-smda-automation`) | orthogonal-composed | the SMDA skill consumes this harness and writes only SMDA-specific Tier-3 config/routing pointers |

Note: `sandcastle` / `linear` / `codex-harness` referenced in `docs/` are the
**SMDA product's own adapters** (the thing being built), not this repo's dev
tracker. This repo's tracker is the local ledger named in `tracker.md`.

## Conventions

- Tracker: `docs/harness/tracker.md` — the only file that names the tracker.
- Roadmap: `docs/harness/roadmap.md` — long-horizon direction; node
  transitions are user decisions (agents propose with evidence, never
  advance alone).
- Workflow-skill config: if present, `docs/agents/` files are compatibility
  pointers into `tracker.md`, never copies. New generic harness setup belongs
  to the Engineering harness skill, not the SMDA plugin.
- Archives: `completed.md` / `abandoned.md` exist in every mode; entries
  written per `tracker.md` § Archive Policy.
- Entry formats (section entries, never tables):

  Live entries — `active.md` / `follow-ups.md`:
  ```markdown
  ## <kebab-slug>
  - status: planned | in-progress | in-review | blocked
  - phase: clarify | specify | slice | implement | accept (interactive); runtime:<ledger-ref> (runtime-owned)
  - owner: unassigned | interactive | runtime:<assignment-ref>
  - parent: <roadmap-upgrade-slug> (optional; groups slices without creating a second tracker)
  - source: <spec / plan / conversation ref>
  - blocked-by: <slugs, or none> (executable entries)
  - acceptance: <observable outcomes> (executable entries)
  - verify: <commands + expected outcomes> (executable entries)
  - next: <single concrete next action, or runtime ledger reference when runtime-owned>
  - updated: YYYY-MM-DD
  ```

  Runtime-owned entries point to the runtime ledger for authoritative phase
  and next action; the local entry does not run a second lifecycle.

  `completed.md`:
  ```markdown
  ## <kebab-slug>
  - done: YYYY-MM-DD
  - summary: <what changed>
  - verified: <command run / evidence; "backfilled from git history">
  - accepted: <independent reviewer or human, decision, candidate revision, evidence and date; for new entries>
  - follow-ups: <ref into follow-ups.md, or none>
  ```
  `abandoned.md`:
  ```markdown
  ## <kebab-slug>
  - abandoned: YYYY-MM-DD
  - why: <reason>
  - resume-if: <condition that would make it viable again>
  ```
- Markers: `codex-harness` comments delimit generated regions. Edit outside
  them freely; refresh never touches user-authored content.
- Quality gates: see `docs/harness/quality-gates.md`.
