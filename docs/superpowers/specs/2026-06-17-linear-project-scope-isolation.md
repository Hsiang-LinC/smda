---
status: approved
created_at: 2026-06-17
owner: agent
approved_at: 2026-06-17
approved_by: human
approval_evidence: conversation review approval 2026-06-17 ("review好了，進plan")
---

# Linear Project Scope Isolation

## Problem

`BacklogAdapterConfig.scope_id` (the Linear project, e.g.
`trading-advisor-41f010901151`) is parsed from `smda.config.json` but never
applied to the live tracker query. `LinearBacklogAdapter.list_issues` filters
only by `team + state + label` (+ optional parent), and
`build_linear_backlog_adapter` reads only `SMDA_LINEAR_TEAM_ID` from the
environment.

Consequence: two repos that share one Linear team and the `agent` label both
scan the same `Todo + agent` issue set. Repo A's daemon will dispatch repo B's
issue inside repo A's workspace. The declared project scope provides no
isolation, so multiple SMDA-managed repos on the same Linear workspace today
require a separate Linear *team* each. See follow-up `linear-scope-id-ignored`.

## Current Baseline

- `config.py` parses `adapters.backlog.scope_id` into
  `BacklogAdapterConfig.scope_id`; nothing reads it for the query.
- `linear_backlog.py`:
  - `build_linear_backlog_adapter(env)` reads `SMDA_LINEAR_TEAM_ID`,
    `SMDA_LINEAR_STATE_*`, `SMDA_LINEAR_LABEL_*`.
  - `LinearBacklogAdapter.list_issues` filter:
    `{ state:{name:{eq}}, labels:{name:{eq}}, parent? }`, scoped to `teamId`.
  - `create_issue` (child publication) sets `teamId` + label ids; it does **not**
    set a project.
- `cli._build_live_daemon_tick` loads the config and builds the adapter from
  `os.environ`; it has the config in hand at build time.

## Design

Scope every backlog query and every published child to a single Linear project,
driven by a project id supplied like the team id.

### Two halves (both required)

1. **Scan filter.** Add `project: { id: { eq: <project_id> } }` to the
   `list_issues` filter when a project id is configured. This narrows the team
   scan to one project.
2. **Child creation.** Stamp `projectId` on issues created by `create_issue`
   (child/remediation publication). Without this, published children fall
   outside the project and the new scan filter would never return them —
   breaking dispatch. Both halves must land together.

### Where the project id comes from

Prefer an environment value `SMDA_LINEAR_PROJECT_ID` (the project UUID),
consistent with `SMDA_LINEAR_TEAM_ID` living in the environment, while
`config.adapters.backlog.scope_id` stays the human-readable project reference.

- `build_linear_backlog_adapter` reads `SMDA_LINEAR_PROJECT_ID` and threads it
  into `LinearBacklogAdapter(project_id=...)`.
- The adapter applies it to the list filter and to `create_issue` input.
- Optional validation: `validate-config` / `validate-context` can warn when
  `scope_id` is set in config but `SMDA_LINEAR_PROJECT_ID` is absent (declared
  isolation not actually enforced).

### Backward compatibility

`project_id` is optional. Unset → current team-wide behavior (no project
filter, no project stamp). Document team-wide mode as unsafe when multiple
SMDA-managed repos share one team; the recommended multi-repo setup sets
`SMDA_LINEAR_PROJECT_ID` per repo so they can share a team.

## Decisions

- Project id is sourced from the environment (`SMDA_LINEAR_PROJECT_ID`, UUID),
  not from the config slug, to avoid a slug→id resolution step and to match the
  existing env-driven id pattern.
- Filtering by project id (not slug) — Linear's issue filter takes the project
  id; the config `scope_id` slug remains documentation/validation only.
- Child creation must set `projectId`; scan filtering alone is insufficient and
  would regress child dispatch.

## Acceptance Criteria

- With `SMDA_LINEAR_PROJECT_ID` set, `list_issues` returns only issues in that
  project (within the team), for the given state + label.
- Issues created via `create_issue` carry the configured project, so a
  subsequent scan with the project filter returns them.
- Two repos sharing a team but configured with different project ids do not see
  each other's `Todo + agent` issues — no cross-repo dispatch.
- With `SMDA_LINEAR_PROJECT_ID` unset, behavior is unchanged from today
  (team-wide), and validation surfaces a warning when `scope_id` is configured
  without the env id.

## Verification

- `uv run --project . smda-scheduler` unit tests for `linear_backlog`:
  - `list_issues` includes the project filter when a project id is set, and
    omits it when not.
  - `create_issue` includes `projectId` when set.
  - a fake-transport test proving project A's adapter never returns project B's
    issues from the same team.
- Extend the live Linear smoke (`gap-2-live-linear-smoke`) to assert
  project-scoped listing against a real project.
- `pytest` green for `packages/scheduler/tests/test_linear_backlog.py`.

## Out Of Scope

- A project filter expressed via Linear *slugId* (we filter by project id).
- Auto-creating Linear projects during setup (live tracker mutation; remains a
  separate approved step).
- Changing the default isolation recommendation retroactively for existing
  single-repo setups.

## Follow-ups

- Update `setup-smda-automation` (`daemon-operations.md` § 1 and `adapters.md`)
  to add `SMDA_LINEAR_PROJECT_ID` to the env contract and document
  project-per-repo as the multi-repo isolation default once this lands.
- Resolves follow-up `linear-scope-id-ignored`.
