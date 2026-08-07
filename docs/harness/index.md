<!-- codex-harness: generated 2026-06-17 -->
# Development Harness Index

Last verified: 2026-08-07

Single residence of routing facts for this repo. Bootloaders point here;
never copy these tables elsewhere. Tracker identity lives only in
`docs/harness/tracker.md`.

## Start Sequence

1. Read `docs/harness/tracker.md`; read your work item per its Read/Write
   section.
2. Read `docs/harness/roadmap.md` § Current Node — know where this work
   sits in the long-horizon sequence.
3. Identify your task type in the routing table.
4. Read the listed context; use the listed workflow.
5. Before closing: post completion evidence and the state update per
   `tracker.md`; update durable repo docs when facts changed.

## Task Routing

| Task type | Read first | Workflow | Completion update |
|---|---|---|---|
| New feature | `docs/CONTEXT.md` (glossary), the relevant `docs/adr/`, the package you touch (`packages/sandcastle-runner` TS / `packages/scheduler` Python) | `superpowers:brainstorming` → `superpowers:writing-plans` → `superpowers:executing-plans` | tracker update per `tracker.md`; durable docs if facts changed |
| Plan intake (approved spec/plan → work items) | the approved spec/plan in `docs/superpowers/specs/` and `docs/superpowers/plans/` | `engineering:to-issues` (else split per `tracker.md` § Work Item Format) | work items created in `active.md`, dependencies encoded (`blocked-by:`), each linking the source plan |
| Bug / regression | `docs/known-gaps.md`, the failing test, the package source | `superpowers:systematic-debugging` (or `engineering:diagnose`) | regression test added; tracker update per `tracker.md` |
| Unfamiliar area | `docs/architecture-rationale.md`, `docs/component-inventory.md`, `docs/contracts.md`, then the package source | targeted reading (dispatch the Explore agent for broad sweeps) | index/map update if stable knowledge gained |
| Architecture decision | `docs/CONTEXT.md` + the relevant `docs/adr/` entries | `engineering:grill-with-docs` then write an ADR in `docs/adr/` | the ADR; glossary term added to `CONTEXT.md`; tracker update per `tracker.md` |
| Completion check | § Conventions quality gates | `superpowers:verification-before-completion` | completion evidence per `tracker.md` |

## Work Production

How new work enters this product repo's development tracker. User-in-the-loop
by design — orchestrated agents consume the output of this pipeline; they never
run it. This is a development-harness rule, not the SMDA product runtime's
unattended execution policy:

1. Position: read `roadmap.md` — which node is current, is it specced?
2. Design: `engineering:grill-with-docs` (or `superpowers:brainstorming`)
   — resolved terms land in `docs/CONTEXT.md`, hard decisions in `docs/adr/`.
3. PRD: `engineering:to-prd`.
4. Issueize: `engineering:to-issues` — dependencies encoded; items
   become dispatch-eligible per `tracker.md` § Dispatch Eligibility.
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
  - status: planned | in-progress | blocked
  - parent: <roadmap-upgrade-slug> (optional; groups slices without creating a second tracker)
  - source: <spec / plan / conversation ref>
  - blocked-by: <slugs, or none> (dispatch-intended entries)
  - acceptance: <observable outcomes> (dispatch-intended entries)
  - verify: <commands + expected outcomes> (dispatch-intended entries)
  - next: <single concrete next action>
  - updated: YYYY-MM-DD
  ```

  `completed.md`:
  ```markdown
  ## <kebab-slug>
  - done: YYYY-MM-DD
  - summary: <what changed>
  - verified: <command run / evidence; "backfilled from git history">
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
