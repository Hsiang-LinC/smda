<!-- codex-harness: generated 2026-06-17 -->
# Tracker: Local Ledger

Last verified: 2026-06-23

## Identity
- kind: local
- truth: `docs/work-ledger/` files in this repo
- id format: kebab-slug section headings (`## <slug>`)

## State Machine

| State | Meaning | Who may set |
|---|---|---|
| planned | scoped, not started | anyone |
| in-progress | being worked | the agent working it |
| blocked | needs human decision or external change | anyone |
| done | verified complete; entry moves to `completed.md` | the agent, with evidence — the human in the loop is the gate |
| abandoned | dropped; entry moves to `abandoned.md` with `resume-if:` | human, or agent with human approval |

States live in the `status:` field of `active.md` / `follow-ups.md` entries.
The author of a change never accepts (sets `done` on) its own item — a human
in the loop is the acceptance gate. A human may set any state.

## Labels
Triage vocabulary (applied by the design-workflow skills —
`engineering:grill-with-docs`, `engineering:to-prd`, `engineering:to-issues`,
`engineering:triage`):
- `needs-triage` — captured, not yet assessed
- `needs-info` — blocked on clarification before it can be scoped
- `ready-for-agent` — scoped and dispatch-eligible by an agent
- `ready-for-human` — needs a human decision or action
- `wontfix` — assessed and declined

Labels are written into an entry's `next:` or a `labels:` line as needed; the
`status:` field is the authoritative lifecycle state.

## Work Item Format
Every entry carries `status:`, `source:`, `next:`, `updated:` per
`docs/harness/index.md` § Conventions. Use optional `parent:` to group related
slices under the roadmap upgrade that owns their rollout order without creating
a second tracker. Entries intended for orchestrated dispatch additionally carry
`acceptance:` (observable outcomes), `verify:` (commands + expected outcomes),
and `blocked-by:` (slugs; use `none` when no blocker exists).

## Dispatch Eligibility
An item is dispatchable when its `active.md` entry has `status: planned`, a
concrete action in `next:`, `acceptance:` and `verify:` filled, and every
`blocked-by:` slug already present in `completed.md`. Re-evaluated every
dispatch pass — completing a blocker unblocks dependents implicitly.

## Read / Write
- read: open `docs/work-ledger/active.md`, find your entry
- write: edit entry fields directly; move entries between ledger files on
  state change
- entry formats: `docs/harness/index.md` § Conventions

## Completion Evidence
Moving an entry to `completed.md` requires: `done:` date, `summary:`,
`verified:` (command run + outcome), `follow-ups:` ref or none.

## Failure Handling
On worker or verification failure: set `status: blocked`, record the
failing command, its output, and the suspected cause in the entry, and put
the unblock condition in `next:`. Never leave an entry `in-progress` after
its worker exits. Re-dispatch: anyone may return it to `planned` with a
note on what changed since the failure.

## Archive Policy
`completed.md` and `abandoned.md` are written at completion time — they ARE
the archive; no backfill loop needed.

## Interactive Rule
Bright-line work with no matching entry: add one to `active.md`
(`status: planned` or `in-progress`) before the first edit. Entry creation
is cheap and reversible — do not ask permission for it.
