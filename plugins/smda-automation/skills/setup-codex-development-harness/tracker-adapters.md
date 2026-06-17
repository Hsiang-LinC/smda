# Tracker Adapters

Presets for `docs/harness/tracker.md`. Generation picks one preset, fills
`{...}` braces from detection, and writes it as `docs/harness/tracker.md`
with the standard generated header and `Last verified:` line. Generated
repos must not depend on this plugin file at runtime. Hint braces (e.g.
`{extend per repo}`) must also be resolved at generation — replace with
concrete values or delete the hint; a generated `tracker.md` contains no
braces of any kind.

Label names in presets are defaults. When the repo or its detected
workflow skills already use a different vocabulary (e.g. `ready-for-agent`
where a preset says `agent`), substitute consistently across **all**
sections at generation — one fact, one label; never leave two labels
meaning the same thing.

## The Contract

Every adapter fills the same ten sections, in this order. A missing or
brace-containing section fails validation. This file is simultaneously the
agent's tracker manual and any orchestrator's integration interface: an
orchestrator derives everything it needs — what to dispatch (§5), which
transitions it may perform (§2), how to read and write items (§6), what to
do on failure (§8) — from the generated `tracker.md` alone. The harness
never generates orchestrator config; conforming to `tracker.md` is the
whole integration.

1. **Identity** — kind, where truth lives, work-item ID format.
2. **State Machine** — states: name / meaning / which actor may set it.
   Authority boundaries are encoded here, including the **acceptance
   authority**: who may set the Done-equivalent state. Two profiles,
   chosen at generation: **human-gated** (default — a human accepts) and
   **agent-gated** (a reviewer agent distinct from the author accepts,
   with verification evidence; humans handle escalations only). Two
   invariants in both profiles: the agent that authored a change never
   accepts its own item, and a human may set any state — profiles grant
   agent authority, they never revoke human authority.
3. **Labels** — actor / work-type / gate classifications ("none" is
   valid). When design-workflow skills are detected, this section also
   carries the triage vocabulary those skills apply (defaults:
   `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`,
   `wontfix`) — mapped to the repo's existing labels and reconciled with
   the dispatch/actor labels per the substitution rule above.
4. **Work Item Format** — required content of a dispatch-eligible item:
   source ref (the approved spec/plan, or conversation), acceptance
   criteria, verification commands with expected outcomes, dependencies in
   the tracker's native encoding. This is the scaffold agents use when
   splitting an approved plan into items.
5. **Dispatch Eligibility** — one machine-checkable rule for what an
   orchestrator may dispatch. References § Work Item Format and the
   dependency encoding. Unblocking is implicit: eligibility is re-evaluated
   every dispatch pass; there is no unblock transition.
6. **Read / Write** — how an agent reads its work item and posts updates
   (MCP tool names, CLI commands, or file edits). Name the access path
   actually detected in the repo; if none, state "none detected — report
   to user".
7. **Completion Evidence** — required content: changed files, verification
   commands and outcomes, remaining risks, follow-up refs.
8. **Failure Handling** — one rule: on worker or verification failure,
   post the evidence (failing command, output, suspected cause) and set
   the failure state. No silent failures; no item left in the claimed
   state after its worker exits. Names who may return a failed item to
   the dispatchable state.
9. **Archive Policy** — how Done/Canceled items become `completed.md` /
   `abandoned.md` entries (per-item at completion, batch at refresh).
10. **Interactive Rule** — behavior when bright-line work has no matching
    item: create one (with what defaults) or ask the user.

Profile braces (`{human-gated: ... | agent-gated: ...}`) resolve at
generation to the chosen profile's text only — like every other brace,
none survive into the generated file.

## Preset: local

```markdown
<!-- codex-harness: generated {DATE} -->
# Tracker: Local Ledger

Last verified: {DATE}

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
| done | verified complete; entry moves to `completed.md` | {human-gated: the agent, with evidence — the human in the loop is the gate | agent-gated: a reviewer agent distinct from the author, with evidence} |
| abandoned | dropped; entry moves to `abandoned.md` with `resume-if:` | human, or agent with human approval |

States live in the `status:` field of `active.md` / `follow-ups.md` entries.
A human may set any state in either profile.

## Labels
{repo-specific labels, else "none"}

## Work Item Format
Every entry carries `status:`, `source:`, `next:`, `updated:` per
`docs/harness/index.md` § Conventions. Entries intended for orchestrated
dispatch additionally carry `acceptance:` (observable outcomes), `verify:`
(commands + expected outcomes), and `blocked-by:` (slugs; omit when none).

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
```

## Preset: github

```markdown
<!-- codex-harness: generated {DATE} -->
# Tracker: GitHub Issues

Last verified: {DATE}

## Identity
- kind: github
- truth: GitHub issues in `{owner/repo}`
- id format: `#<number>`

## State Machine

| State | Meaning | Who may set |
|---|---|---|
| open | backlog or active; refine with labels | anyone |
| open + label `in-progress` | claimed | the claiming agent or orchestrator |
| open + label `in-review` | work done; acceptance review pending | the working agent, with evidence |
| open + label `needs-human` | escalated; human decision required | {agent-gated only: reviewer agent or human — omit this row in human-gated} |
| open + label `blocked` | waiting on human or external change | anyone |
| closed (completed) | accepted done | {human-gated: human, after review | agent-gated: a reviewer agent distinct from the author, with verification evidence} |
| closed (not planned) | abandoned | human |

The author of a change never closes its own issue as completed.
{human-gated: human review closes. | agent-gated: an independent reviewer
agent closes from `in-review`; `needs-human` is reserved for escalations
the reviewer cannot resolve.} A human may set any state in either profile.

## Labels
- actor: `agent`, `human` {extend per repo}
- work-type: {repo-specific, else omit}
- gate: `needs-plan`, `needs-review` {extend per repo}
- lifecycle: `in-progress`, `in-review`, `blocked`{agent-gated: , `needs-human`}
- triage: {the five triage roles when design-workflow skills detected,
  mapped per the substitution rule | omit}

## Work Item Format
A dispatch-eligible issue's body contains:
- source: link to the approved spec/plan, or conversation ref
- acceptance criteria: observable outcomes a reviewer can check
- verification: commands to run and expected outcomes
- dependencies: one `Blocked by #<n>` line per blocker (none when independent)

## Dispatch Eligibility
open, labeled `agent`, no lifecycle label (`in-progress` / `in-review` /
`blocked`), every `Blocked by #<n>` reference closed, body satisfies
§ Work Item Format. Re-evaluated every dispatch pass — closing a blocker
unblocks dependents implicitly.

## Read / Write
- read: {detected: `gh issue view <n>` | GitHub MCP tool names | none detected — report to user}
- write: {detected: `gh issue comment <n>` / `gh issue edit <n> --add-label` | MCP equivalents}{agent-gated: ; reviewer agents may close completed issues and apply `needs-human`}

## Completion Evidence
Completion comment must include: changed files; verification commands and
outcomes; remaining risks; follow-up issue refs.

## Failure Handling
On worker or verification failure: post a comment with the failing command,
its output, and the suspected cause; add `blocked`, remove `in-progress`.
Never leave `in-progress` after the worker exits. Re-dispatch: a human or
triage agent removes `blocked` with a note on what changed since the failure.

## Archive Policy
closed-completed → `completed.md` entry; closed-not-planned →
`abandoned.md` entry (`resume-if:` from the closing comment). Per item at
completion or batch at refresh.

## Interactive Rule
Bright-line work with no matching issue: create one with an actor label and
body per § Work Item Format, or ask the user when scope is unclear.
```

## Preset: linear

```markdown
<!-- codex-harness: generated {DATE} -->
# Tracker: Linear

Last verified: {DATE}

## Identity
- kind: linear
- truth: Linear project `{project}`
- id format: `{TEAM}-<number>`

## State Machine

| State | Meaning | Who may set |
|---|---|---|
| Backlog | captured, not ready | human |
| Todo | scoped, dispatch-eligible when labeled | human; an agent issueizing an approved plan |
| In Progress | claimed | orchestrator or agent |
| In Review | work done; acceptance review pending | the working agent, with evidence |
| Human Review | escalated; human decision required | {agent-gated only: reviewer agent or human — omit this row in human-gated} |
| Done | accepted | {human-gated: human only | agent-gated: a reviewer agent distinct from the author, with verification evidence} |
| Blocked | waiting on decision/dependency/credential | anyone |
| Canceled | will not be actioned | human |

The author of a change never accepts it. {human-gated: human review is the
acceptance gate. | agent-gated: an independent reviewer agent accepts from
`In Review`; `Human Review` is reserved for items the reviewer escalates.}
A human may set any state in either profile.

## Labels
- actor: `agent`, `human`, `pairing`
- work-type: {repo-specific}
- gate: `needs-plan`, `needs-review` {extend per repo}
- triage: {the five triage roles when design-workflow skills detected,
  mapped per the substitution rule | omit}

## Work Item Format
A dispatch-eligible issue's body contains:
- source: link to the approved spec/plan, or conversation ref
- acceptance criteria: observable outcomes a reviewer can check
- verification: commands to run and expected outcomes
Dependencies are Linear blocking relations ("blocked by"), not body text.

## Dispatch Eligibility
state `Todo`, labeled `agent`, every blocking relation in a terminal state
(`Done` / `Canceled`), body satisfies § Work Item Format. Re-evaluated every
dispatch pass — a blocker reaching `Done` unblocks dependents implicitly.

## Read / Write
- read: {detected Linear MCP tool names | none detected — report to user}
- write: comment + state update via the same path; working agents may set:
  `In Review` (success), `Blocked` (failure){agent-gated: ; reviewer agents
  may set `Done` (accept) and `Human Review` (escalate)}

## Completion Evidence
Completion comment must include: changed files; verification commands and
outcomes; remaining risks; follow-up issue refs.

## Failure Handling
On worker or verification failure: post a comment with the failing command,
its output, and the suspected cause, then set `Blocked`. Never leave an
issue `In Progress` after its worker exits. Re-dispatch: a human or triage
agent returns it to `Todo` with a note on what changed since the failure.

## Archive Policy
`Done` → `completed.md` entry; `Canceled` → `abandoned.md` entry with
`resume-if:`. Batch backfill at refresh.

## Interactive Rule
Bright-line work with no matching issue: create one (`Todo`, actor label,
body per § Work Item Format), or ask the user when scope is unclear.
```

## Preset: jira

```markdown
<!-- codex-harness: generated {DATE} -->
# Tracker: JIRA

Last verified: {DATE}

## Identity
- kind: jira
- truth: JIRA project `{KEY}` at `{instance URL}`
- id format: `{KEY}-<number>`

## State Machine

JIRA workflows are instance-specific — fill from the actual board:

| State | Meaning | Who may set |
|---|---|---|
| {To Do} | scoped, dispatch-eligible when labeled | human; an agent issueizing an approved plan |
| {In Progress} | claimed | orchestrator or agent |
| {In Review} | work done; acceptance review pending | the working agent, with evidence |
| {Human Review} | escalated; human decision required | {agent-gated only: reviewer agent or human — omit this row in human-gated} |
| {Done} | accepted | {human-gated: human only | agent-gated: a reviewer agent distinct from the author, with verification evidence} |
| {Blocked} | waiting | anyone |

The author of a change never accepts it. {human-gated: human review is the
acceptance gate. | agent-gated: an independent reviewer agent accepts; the
escalation state is reserved for items the reviewer cannot resolve.}
A human may set any state in either profile.

## Labels
- actor: `agent`, `human` {map to labels or components per instance}
- work-type / gate: {repo-specific}
- triage: {the five triage roles when design-workflow skills detected,
  mapped per the substitution rule | omit}

## Work Item Format
A dispatch-eligible issue's description contains:
- source: link to the approved spec/plan, or conversation ref
- acceptance criteria: observable outcomes a reviewer can check
- verification: commands to run and expected outcomes
Dependencies are JIRA blocking links ("is blocked by"), not description text.

## Dispatch Eligibility
state {To Do}, labeled `agent`, every blocking link resolved, description
satisfies § Work Item Format. Re-evaluated every dispatch pass — resolving
a blocker unblocks dependents implicitly.

## Read / Write
- read: {detected: JIRA MCP tools | `jira issue view` CLI | none detected — report to user}
- write: comment + transition via the same path; working agents may
  transition to: {In Review}, {Blocked}{agent-gated: ; reviewer agents may
  transition to {Done} and {Human Review}}

## Completion Evidence
Completion comment must include: changed files; verification commands and
outcomes; remaining risks; follow-up issue refs.

## Failure Handling
On worker or verification failure: post a comment with the failing command,
its output, and the suspected cause, then transition to {Blocked}. Never
leave an issue {In Progress} after its worker exits. Re-dispatch: a human
or triage agent returns it to {To Do} with a note on what changed.

## Archive Policy
{Done} → `completed.md` entry; abandoned resolutions → `abandoned.md` with
`resume-if:`. Batch backfill at refresh.

## Interactive Rule
Bright-line work with no matching issue: create one ({To Do}, actor label,
description per § Work Item Format), or ask the user when scope is unclear.
```

## Custom skeleton

For trackers without a preset. Same ten sections; every line is a brace to
fill with the user. The validation gate (all sections filled, no braces left)
applies unchanged.

```markdown
<!-- codex-harness: generated {DATE} -->
# Tracker: {name}

Last verified: {DATE}

## Identity
- kind: custom
- truth: {where}
- id format: {format}

## State Machine
{states table: name / meaning / who may set. Encode the acceptance
authority per the chosen profile — human-gated or agent-gated — plus both
invariants: the author never accepts its own item; a human may set any
state.}

## Labels
{classifications, or "none"}

## Work Item Format
{required body fields — default: source ref; acceptance criteria;
verification commands + expected outcomes; dependencies in the tracker's
native encoding}

## Dispatch Eligibility
{one machine-checkable rule referencing § Work Item Format and the
dependency encoding}

## Read / Write
{detected access path; "none detected — report to user" is valid}

## Completion Evidence
{required content — default: changed files; verification commands and
outcomes; remaining risks; follow-up refs}

## Failure Handling
{one rule — default: post failing command + output + suspected cause, set
the failure state, never leave the claimed state after worker exit; name
who may re-dispatch}

## Archive Policy
{terminal states → completed.md / abandoned.md mapping}

## Interactive Rule
{create-or-ask behavior for bright-line work without a matching item}
```
