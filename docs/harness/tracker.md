<!-- codex-harness: generated 2026-06-17 -->
# Tracker: Local Ledger

Last verified: 2026-08-07

## Identity
- kind: local
- truth: `docs/work-ledger/` files in this repo
- id format: kebab-slug section headings (`## <slug>`)

## State Machine

| State | Meaning | Who may set |
|---|---|---|
| planned | scoped, not started | anyone |
| in-progress | being worked | the agent working it |
| in-review | implementation and verification evidence posted; independent technical or human product acceptance pending | the agent working it |
| blocked | needs human decision or external change | anyone |
| done | verified complete; entry moves to `completed.md` | an independent reviewer agent accepts technical items with revision-bound evidence; a human accepts user-facing product slices; the execution owner may transcribe either decision |
| abandoned | dropped; entry moves to `abandoned.md` with `resume-if:` | human, or agent with human approval |

States live in the `status:` field of `active.md` / `follow-ups.md` entries.
Agent-gated acceptance is the default for this repo. The author never accepts
its own change. A human may set any state; unresolved scope or behavior,
changed authority, high-risk or protected changes, unavailable independent
review, and repeated review/fix failure escalate to a human with evidence and
a precise question. Human silence is not acceptance.

For a user-facing product slice, an independent agent records technical
approval on the entry, which stays `in-review` until the
user explicitly accepts a usable candidate against concrete functional and
experience scenarios. Record candidate identity, scenarios, feedback, actor,
decision, and date. Rejected feedback returns the affected work to
`in-progress`; a changed candidate receives fresh technical review. This
product gate does not apply to unrelated technical items.

For interactive work, the execution owner posts the candidate commit SHA,
criterion-level results and verification commands/outcomes, then sets
`in-review` and assigns an independent reviewer agent the source, criteria,
exact commit and evidence. If review must use a patch, freeze its base SHA,
complete included file list (including untracked files), and artifact hash.
Recheck the same candidate identity before acceptance. The reviewer does not
edit the candidate.
On actionable rejection, record findings, return to `in-progress`, fix, and
review the new revision. On pass, record reviewer identity, decision, reviewed
revision, evidence and date. Move a technical item to `completed.md` after that
review; keep a user-facing product slice `in-review` until its human product
decision is recorded. If delegation is
unavailable, retain `in-review` with a concrete next action. A runtime-assigned
worker only returns its role artifact; the runtime owns reviewer dispatch and
lifecycle writes for its item. Ownership changes require an explicit handoff.

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
Every entry carries `status:`, `phase:`, `owner:`, `source:`, `next:`, `updated:` per
`docs/harness/index.md` § Conventions. Use optional `parent:` to group related
slices under the roadmap upgrade that owns their rollout order without creating
a second tracker. Ready items may use `owner: unassigned`; claimed interactive
items use `owner: interactive` and a shared phase. Runtime-owned items use
`owner: runtime:<assignment-ref>` and `phase: runtime:<ledger-ref>`; the runtime
ledger remains authoritative for phase and next action even if the tracker
projection lags. All executable entries carry `acceptance:` (observable
outcomes), `verify:` (commands + expected outcomes), and `blocked-by:`
(slugs; use `none` when no blocker exists). New executable work also identifies
its scope and non-goals in the item or linked approved source.

## Dispatch Eligibility
An item is ready when its `active.md` entry has `status: planned`, the
§ Work Item Format fields are complete, `next:` is executable, the linked
source revision is current and approved for the requested scope, and no
implementation-blocking question or triage, review, or human-action gate
remains. Scope and non-goals must be identified. Roadmap-sequenced work must
name the current node in `parent:`; independent maintenance may omit it. Every
`blocked-by:` slug must have accepted completion in
`completed.md`, or a recorded waiver or supersession explaining how that
obligation is satisfied. Re-evaluate before starting; completing a blocker
unblocks dependents implicitly. Interactive agents apply the same readiness
check before implementation; clarification may start earlier. This is the
development tracker policy, not a claim that an SMDA runtime is dispatching
this repository's work.

## Read / Write
- read: open `docs/work-ledger/active.md`, find your entry
- write: edit entry fields directly; move entries between ledger files on
  state change
- entry formats: `docs/harness/index.md` § Conventions

## Completion Evidence
Moving an entry to `completed.md` requires: `done:` date, `summary:`,
`verified:` (command run + outcome), `accepted:` (independent reviewer or
human, decision, reviewed revision, evidence reference and date), and
`follow-ups:` ref or none.

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
