# Core Templates

Everything the **core** topology generates: bootloader block, pointer line,
`docs/harness/index.md`, `docs/harness/tracker.md` (from a
[tracker-adapters.md](tracker-adapters.md) preset), `docs/harness/roadmap.md`,
the work-ledger files, and — when design-workflow skills are detected — the
`docs/agents/` files. `{...}` braces = fill at generation time. Entry formats
come from [ledger-conventions.md](ledger-conventions.md).

Ledger files by mode: **local** generates all four; **remote trackers**
generate only the two archives (`completed.md`, `abandoned.md`).

## Bootloader block (single residence, ~15 lines max)

```markdown
<!-- codex-harness:begin -->
## Development Harness

Before any development task, read `docs/harness/index.md` and follow its routing.

Hard rules:
1. Work state lives in the tracker — read `docs/harness/tracker.md` before
   starting work.
2. Bright line: any work that changes code, contracts, or docs is
   tracker-worthy — before the first edit, confirm a work item covers it or
   create one per `tracker.md` (interactive sessions included). Pure
   reading, discussion, or Q&A is not tracker-worthy.
3. Definition of done includes the tracker update defined in `tracker.md`
   and updating durable repo docs when facts changed. A change without its
   tracker update is incomplete work.
4. Routing tables live only in `docs/harness/index.md`. Do not duplicate them here.
<!-- codex-harness:end -->
```

## Pointer line (every other detected bootloader)

```markdown
<!-- codex-harness:begin -->
Development harness: see `AGENTS.md` § Development Harness. Tracker contract
in `docs/harness/tracker.md`.
<!-- codex-harness:end -->
```

(Replace `AGENTS.md` with the actual residence file if the user chose another.)

## `docs/harness/tracker.md`

Generated from the chosen preset in [tracker-adapters.md](tracker-adapters.md)
— the **only** file in the generated repo that names the concrete tracker.
All ten contract sections filled; no braces left.

## `docs/harness/index.md`

```markdown
<!-- codex-harness: generated {DATE} -->
# Development Harness Index

Last verified: {DATE}

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
| New feature | {repo-specific docs/dirs} | {detected design+planning skills, else "design before code"} | tracker update per `tracker.md`; durable docs if facts changed |
| Plan intake (approved spec/plan → work items) | the approved spec/plan | {detected issueization skill, else split per `tracker.md` § Work Item Format} | work items created, dependencies encoded, each linking the source plan |
| Bug / regression | {repo-specific docs/tests} | {detected debugging skill, else "reproduce before fixing"} | regression test; tracker update per `tracker.md` |
| Unfamiliar area | {architecture docs if extended, else key source dirs} | {detected exploration skill, else targeted reading} | index/map update if stable knowledge gained |
| Architecture decision | {CONTEXT.md / docs/adr/ if present} | {detected decision skill, else "write an ADR"} | the decision doc; tracker update per `tracker.md` |
| Completion check | Conventions § quality gates | {detected verification skill, else "run full test suite"} | completion evidence per `tracker.md` |

Rows are a starting set — keep only the ones meaningful for this repo, add
repo-specific ones found during exploration.

## Work Production

How new work enters the tracker. User-in-the-loop by design — orchestrated
agents consume the output of this pipeline; they never run it:

1. Position: read `roadmap.md` — which node is current, is it specced?
2. Design: {detected grilling/design skill, else "stress-test the plan with
   the user"} — resolved terms land in the glossary, hard decisions in ADRs.
3. PRD: {detected PRD skill, else "write a PRD; user approves"}.
4. Issueize: {detected issueization skill, else split per `tracker.md`
   § Work Item Format} — dependencies encoded; items become
   dispatch-eligible per `tracker.md` § Dispatch Eligibility.
5. Node close: when the current node's items are all terminal, propose the
   roadmap advance to the user (see `roadmap.md` header rule).

## Coexisting Systems

| System | Class | Truth |
|---|---|---|
| {detected system} | orthogonal-composed \| overlap-resolved \| conflict-user-decided | {where its truth lives} |
| {detected orchestrator, if any} | orthogonal-composed | its own config; state/label names must match `tracker.md` |

## Conventions

- Tracker: `docs/harness/tracker.md` — the only file that names the tracker.
- Roadmap: `docs/harness/roadmap.md` — long-horizon direction; node
  transitions are user decisions (agents propose with evidence, never
  advance alone).
- Workflow-skill config: {`docs/agents/` files — tracker/label facts there
  are pointers into `tracker.md`, never copies | omit when not generated}
- Archives: `completed.md` / `abandoned.md` exist in every mode; entries
  written per `tracker.md` § Archive Policy.
- Entry formats: {paste the applicable formats from ledger-conventions as fenced blocks:
  archives always; live entries in local mode only}
- Markers: `codex-harness` comments delimit generated regions. Edit outside
  them freely; refresh never touches user-authored content.
- Quality gates: {repo test/lint commands} must pass before completion
  evidence is posted.
```

## `docs/harness/roadmap.md`

The layer above the tracker: milestone sequence and current position.
Backlog items live in the tracker; direction lives here. Written at node
boundaries only — exactly when the user is in the loop — so write-cost
stays human-supervised.

```markdown
<!-- codex-harness: generated {DATE} -->
# Roadmap

Last verified: {DATE}

Long-horizon direction. Work items live in the tracker
(`docs/harness/tracker.md`); this file holds the milestone sequence and the
current position. Node transitions are user decisions made in interactive
sessions: an agent may propose advancing — with evidence that the current
node's items are all terminal — but never advances a node alone.

## Current Node

{milestone-id} — {one-line goal}

## Milestones

### {milestone-id}: {name}
- status: done | current | next | later
- goal: {one line}
- spec: {PRD / spec / ADR refs, or "not yet specced"}
- items: {how this node's work items are found in the tracker — label,
  milestone, or project ref — or "not yet issueized"}

{one section per milestone, in sequence order; greenfield repos get a
single current milestone capturing the project's first goal}

## Direction Notes

{cross-node intent, constraints, deliberately-not-doing — or nothing}
```

## `docs/agents/` files (only when design-workflow skills are detected)

Generated when Environment detection finds the design-workflow chain
(grilling / PRD / issueization / triage skills) in the environment — those
skills read these paths. Tracker and label facts stay in `tracker.md`;
two of the three files are pure pointers.

### `docs/agents/issue-tracker.md`

```markdown
<!-- codex-harness: generated {DATE} -->
# Issue Tracker

Managed by the development harness. Tracker identity, states, work-item
format, and read/write paths live in `docs/harness/tracker.md` — read that
file and follow it.
```

### `docs/agents/triage-labels.md`

```markdown
<!-- codex-harness: generated {DATE} -->
# Triage Labels

Managed by the development harness. The triage vocabulary lives in
`docs/harness/tracker.md` § Labels — read it there; do not duplicate it here.
```

### `docs/agents/domain.md`

```markdown
<!-- codex-harness: generated {DATE} -->
# Domain Docs

Layout: {single-context | multi-context}.

- Glossary: {`CONTEXT.md` at the repo root | `CONTEXT-MAP.md` at the root
  pointing to per-context `CONTEXT.md` files}
- ADRs: {`docs/adr/` | per-context `docs/adr/` plus system-wide `docs/adr/`}

Consumer rules:
- Read the glossary before naming things; use its terms in code, issues,
  and docs.
- Check ADRs in the area you touch before proposing architectural change.
- Resolved terms go into the glossary as they crystallise. Decisions that
  are hard to reverse, surprising without context, and a real trade-off
  get an ADR.
```

## `docs/work-ledger/active.md` (local mode only)

```markdown
<!-- codex-harness: generated {DATE} -->
# Active Work

Entry format: see `docs/harness/index.md` § Conventions.

{entries discovered during exploration, or nothing — an empty section list is valid}
```

## `docs/work-ledger/follow-ups.md` (local mode only)

```markdown
<!-- codex-harness: generated {DATE} -->
# Follow-ups

Known debt and opportunities. Entry format: see `docs/harness/index.md` § Conventions.

{entries found during exploration, or nothing}
```

## `docs/work-ledger/completed.md` (all modes)

```markdown
<!-- codex-harness: generated {DATE} -->
# Completed Work

Archive — newest first. Entry format: see `docs/harness/index.md` § Conventions.

{backfilled milestone entries from git history — and from the tracker's Done
 items in remote modes — newest first}

## project-started
- done: {date of first commit; today only if the repo has no commits}
- summary: project started
- verified: {backfilled from git history | greenfield init}
- follow-ups: none
```

## `docs/work-ledger/abandoned.md` (all modes)

```markdown
<!-- codex-harness: generated {DATE} -->
# Abandoned Work

Archive — paths tried and dropped, each with a resume condition. Entry
format: see `docs/harness/index.md` § Conventions.

{entries found during exploration — and from the tracker's Canceled items in
 remote modes — or nothing}
```
