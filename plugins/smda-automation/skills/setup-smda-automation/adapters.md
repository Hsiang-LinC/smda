# SMDA Adapters

SMDA is method-first. These adapters describe the default deployment shape.

## Codex Development Harness Adapter

Use `engineering:setup-codex-development-harness` or an equivalent context
substrate before SMDA. The SMDA setup skill consumes this contract; it does not
generate the generic harness. The harness should provide:

- `AGENTS.md` or equivalent bootloader;
- `docs/harness/index.md` routing;
- `docs/harness/tracker.md` state/label/dispatch contract;
- `docs/harness/quality-gates.md`;
- source-of-truth docs for architecture, contracts, roadmap, ADRs, and specs;
- a documented roadmap policy for large changes: where roadmaps live, how they
  reference spec parent issues, and how parent dependencies are represented.

SMDA must not duplicate tracker facts in generated docs. It reads the harness
contract and writes only SMDA-specific routing/config pointers.

When SMDA is installed, fresh agent sessions must be able to discover it from
durable repo context:

- bootloader (`AGENTS.md`, `CLAUDE.md`, or equivalent) points to harness routing;
- harness routing points to the SMDA operating model and runtime commands;
- tracker docs describe only coarse SMDA execution modes and ownership;
- roadmap docs or tracker views point to spec parent issues and parent-level
  dependencies without duplicating execution state;
- handoff docs point to tracker issue context, runtime state, branch/artifacts,
  and verification evidence instead of relying on conversation history.

If the harness is absent, the setup skill should recommend installing it or
ask the user to identify equivalent files. Do not silently create a full
project harness from the SMDA skill.

Harness updates made by SMDA setup should add only SMDA-specific routing and
operator pointers. The generic harness remains the source of truth for task
routing, tracker shape, domain-doc paths, and quality gates.

## Shared policy and runtime enforcement

The basic harness must remain usable without SMDA: it owns the project’s
selected skill routes, design/spec handoffs, work-item readiness, evidence and
acceptance policy. SMDA maps that policy to supported runtime controls; it
retains dynamic eligibility, claims/leases, retries/recovery, typed dependency
checks, graph mutation review and serialized acceptance. Do not replace these
with a generic “tracker item closed” predicate or claim prose is enforcement.

SMDA executes the same harness phase contract; it does not introduce a second
development pipeline. During setup, map shared phases to existing runtime
roles, methodology skills, input/output artifacts and gate owners. Multiple
runtime states may implement one harness phase. Use the product's existing
role contracts; do not generate a second role registry or workflow engine.
Check methodology compatibility, not only whether a skill file exists.

An assigned worker executes its current role and returns its artifact. The
runtime owns phase advancement, lifecycle writes and publication; the worker
must not use interactive index routing to restart design, select another phase
or write a parallel tracker lifecycle. Shared requirements and acceptance gates
still apply. Unresolved decisions are reported through runtime escalation.
Switching an item between interactive and SMDA ownership requires a handoff of
source revision, state and evidence, and stopping the previous owner first.

For each SMDA-owned item, route graph production only through the runtime’s
approved-spec decomposition, graph review and publication. A `to-issues` skill
injected into a decomposer supplies methodology and returns the role artifact;
it must not also publish child issues. Do not prescribe external graph import
unless the installed product supports a reviewed import path.

Acceptance policy must distinguish spec approval, child integration, parent
acceptance and release. AFK intake is not authority to merge. Confirm that the
installed runtime can enforce the requested human/agent boundaries; unsupported
policy is a setup blocker for autonomous dispatch, not permission to weaken it.
Do not change the runtime’s product-owned role/schema contracts in repo docs.

Check `context.skills_dir` when using the Codex harness context adapter:
configured skill injection must resolve the runtime’s declared methodology
skills. Without it, skill injection is absent; report that limitation rather
than claiming the role used an installed skill. Interactive index routing and
runtime skill injection are distinct paths; validate both when enabled.

For runtimes exposing `harness_role_bindings` in `validate-context`, materialize
the checked binding in the selected harness artifact directory. First validate
context without `harness_contract_path` to obtain the supported bindings; compare
them with the project's selected methods. Write JSON containing exactly
`schema_version: 2`, `execution_owner: "smda"`, `roles` (that validated mapping),
`blocking_labels` (the project's actual unresolved gates), and `acceptance`.
The acceptance object names `child_integration: "agent"`, `parent_merge`
(`"agent"` only when authorized, otherwise `"human"`), `merge_target`, nonempty
`verification_commands` argv arrays, and repo-relative `human_review_paths`.
Choose commands/patterns from the project, not example defaults. Tracker docs
reference this policy rather than duplicate its values. Configure
`context.harness_contract_path` and `context.skills_dir`, then validate again.
Do not encode arbitrary Markdown policy as if the runtime could enforce it.
Older runtimes lacking this capability require an upgrade to enable checked
bindings; report the limitation instead of claiming validation occurred.

Version 1 bindings require explicit migration; never infer merge permission
from AFK or installation. Checked v2 supports tasks, spec-parent/child flows and roadmaps. Tasks require
one Source reference and whole-delivery QA after quality review. Roadmap members
land into their derived integration branch before aggregate QA targets the
configured branch. Human mode hands off at delivery QA; there is no
automatic human-approval resume. Agent mode requires committed approved source
and policy, fresh revision-bound QA, and successful host-run checks in a clean
candidate worktree. Keep the target branch out of active worktrees. Delivery is
local fast-forward only: remote publication and deployment need separate policy.
Show these limits before activating the consumer; unsupported required behavior
is a setup blocker, not a reason to omit `harness_contract_path`.

Generic refresh compares the harness setup contract with repo evidence; SMDA
refresh additionally checks this adapter mapping and supported runtime policy.
Neither needs an architecture-refactoring skill as a prerequisite. Never infer
workflow truth or acceptance solely from tracker projection.

## Backlog Manager Adapter

Required capabilities:

- parent/child grouping, or an equivalent parent reference;
- dependency edges, preferably native blocking relations;
- optional roadmap-to-parent references for multi-parent restructuring;
- coarse states: Todo, In Progress, Done, Blocked, Human Review, Canceled, or
  equivalent;
- comments/evidence;
- labels or metadata for SMDA parent/child execution modes.

Default Linear mapping:

- hierarchy/sub-issues: parent aggregation and human navigation;
- blocking relations: child dispatch dependencies;
- roadmap parent links or initiatives: multi-parent planning and parent
  sequencing, not child execution;
- child state `Todo`: scoped and queued, even when blocked by dependencies;
- child `Done`: SMDA internal CLOSED plus accepted commit on parent branch;
- `Blocked`: abnormal external/context/environment state, not normal waiting;
- `Canceled`: counts complete only when graph mutation records supersession.

Linear is a projection target, not the SMDA workflow database. Parent/child
phase, claims, attempts, pause gates, accepted commits, and pending tracker
writes live in the product ledger under the configured runtime state root. The
daemon records intended Linear writes in `tracker_effect_ledger` and retries
them before each scan. Setup-generated harness docs must teach fresh sessions
to inspect `smda-scheduler status` first, then use Linear as the human-visible
confirmation that projection effects were delivered.

Linear live adapter wiring uses local environment or local secrets, not
committed repo config:

- `LINEAR_API_KEY`;
- `SMDA_LINEAR_TEAM_ID`;
- `SMDA_LINEAR_STATE_TODO`, `SMDA_LINEAR_STATE_IN_PROGRESS`,
  `SMDA_LINEAR_STATE_AGENT_REVIEW`, etc., matching the repo tracker state names;
- `SMDA_LINEAR_PROJECT_ID` (optional) — scopes the scan and child creation to one
  Linear project. Set it (project-per-repo) so multiple SMDA-managed repos can
  share one team without cross-dispatching; unset means team-wide scanning.

To populate these ids, see [daemon-operations.md](daemon-operations.md) § 1 — a
read-only Linear GraphQL fetch of team/state/label ids written to a gitignored
env file, plus the env-var-name-to-tracker-name mapping rules. Execution modes
(`Execution: smda` / `smda-child`) are issue body markers, not labels, so they
need no label env entry.

`local-ledger` is the product adapter for repos whose tracker truth is a
file-backed harness ledger. Setup may configure its file paths,
but must not generate adapter code or convert the repo to a new SMDA-specific
tracker format. The local ledger remains the harness source of truth; SMDA's
runtime ledger remains the workflow source of truth.

Local-ledger config uses the product adapter id and optional path keys:

```yaml
adapters:
  backlog:
    id: local-ledger
    version_constraint: ">=0.1.0"
    scope_id: repo-local
    active_path: docs/work-ledger/active.md
    completed_path: docs/work-ledger/completed.md
    abandoned_path: docs/work-ledger/abandoned.md
```

Linear config uses the Linear adapter id and keeps live ids/secrets outside git:

```yaml
adapters:
  backlog:
    id: linear
    version_constraint: ">=0.1.0"
    scope_id: linear-project-or-team
```

Other trackers require product adapter implementations. The setup skill must not
generate GitHub or custom backlog adapter code.

## SMDA Scheduler Runtime

The SMDA Scheduler product is the deterministic runtime. Symphony/codex-symphony
are historical design sources, not repo-local runtime targets for new setup.

Target setup:

```text
Execution: smda         -> full parent-driven workflow
Execution: smda-task    -> small scoped bug or single-task implementation
Execution: smda-roadmap -> roadmap decomposition into member parents
Execution: smda-child   -> scheduler-created child handle only
Execution: manual       -> explicit routing opt-out; scheduler must not claim
```

`Execution:` is mandatory only for work that should be claimed by SMDA under
explicit routing policy. Missing `Execution:` means unmodeled or not yet routed
work. `Execution: manual` is a deliberate opt-out, not a scheduler state.

The repo must also document one policy for work without an execution mode:
require explicit `Execution: smda`, normalize eligible work into
`Execution: smda-task`, or block until parent context exists. Do not leave a
separate generic autonomous worker path in an SMDA-only setup.

Execution adapter config has two distinct provider knobs:

- `adapters.execution.provider` selects the sandbox provider, e.g. `noSandbox`
  for the local MVP.
- `adapters.execution.agent` selects the agent runtime and model:
  `provider` (`codex` or `claudeCode`), `model`, and optional `effort`
  (Codex: `low`, `medium`, `high`, `xhigh`; Claude Code also allows `max`).
  Optional `role_overrides` under `agent` may map a specific SMDA role id (for
  example `graph_decomposer`) to a different provider/model/effort.

Target repos may tune the agent model/effort in `smda.config.*` to match their
available account and quality/cost needs. Do not hard-code agent model names in
setup-generated scripts or docs when the config already supplies them.

Deferred concern follow-ups are opt-in policy:

```json
"policy": {
  "concerns": {
    "create_follow_up_issues": false,
    "labels": ["smda-follow-up"]
  }
}
```

Keep this disabled unless the repo wants `DONE_WITH_CONCERNS` reviewer reports
turned into durable manual-triage child/backlog issues.

Legacy worker or long-session orchestrator artifacts are not migrated by this
setup skill. Stop and ask for a repo-specific hard-replacement spec, or require
the user to remove legacy artifacts before setup continues.

Runtime implementations may still share low-level primitives with previous
systems:

- workspace/worktree creation;
- patch capture/apply;
- verification runner;
- commit/merge helpers;
- tracker comment/state update;
- pending tracker update retry;
- clean-worktree checks.

SMDA runtime responsibilities:

- roadmap-aware parent intake when a roadmap references multiple parent specs;
- parent run creation/resume;
- spec approval gate;
- decomposition and graph review loops;
- child issue publication;
- context packet compilation;
- child phase machine;
- graph mutation proposal evaluation;
- parent integration branch;
- parent verification/QA/remediation loop;
- durable final accept effects that close the parent tracker issue after QA
  passes.

## Target Repo Artifacts

A repo should end with Tier-3 artifacts only:

- bootloader/harness routing entries that make SMDA discoverable to new agents;
- SMDA docs or harness routing that explain the roadmap/parent/child flow;
- optional prompt wording/context overrides only when the product supports them;
- `smda.config.*` plus local secret overrides, including execution agent
  provider/model/effort when the repo needs a non-default model;
- runtime state directory ignored by git;
- tracker setup notes for SMDA parent/child labels/states/relations;
- status/operator notes that distinguish SMDA local ledger truth from tracker
  projection and point to `smda-scheduler status` `tracker_effects` for pending
  or failed Linear writes;
- roadmap management notes for multi-parent work and parent dependencies;
- issue-entry policy for unmodeled work;
- validation commands.
- optional live daemon command using the product runtime, when explicitly
  approved.

Do not install prompt templates, report templates, schemas, manifests, or
runtime package artifacts into the target repo unless the user is developing the
SMDA Scheduler product itself.

## Refresh And Legacy Detection

Refresh mode should:

- detect legacy Symphony `WORKFLOW.md`, `ORCHESTRATOR.md`, `REVIEW.md`;
- stop when legacy worker/orchestrator paths are present;
- report that the repo needs a hard-replacement spec or explicit legacy
  artifact removal before SMDA setup continues;
- warn when tracker states/labels drift from the harness;
- never start the daemon or publish live child issues during setup refresh.

## Validation

Non-live validation should check:

- bootloader and harness routing point to SMDA docs/state without duplicating
  tracker facts;
- roadmap policy exists or the repo explicitly says roadmap management is not
  used;
- roadmap-to-parent references and parent dependencies are visible to fresh
  sessions when roadmap management is used;
- approved spec front matter rules;
- product graph/schema compatibility and acyclicity, when product validation is
  available;
- required context packet fields;
- prompt override compatibility, only when overrides are configured;
- plugin-bundled runtime package availability outside the target repo;
- tracker mapping consistency;
- issue-entry policy is documented and has no generic autonomous worker bypass;
- verification command presence;
- dry-run child publication if supported.

Live actions require explicit user approval:

- create tracker states/labels;
- create a tracker project (per-repo onboarding to a shared team);
- publish child issues;
- start daemon/autonomous loop;
- accept/merge branches.


## Consumer path compatibility (0.3.1)

Parent and roadmap intake resolve the approved Markdown source within configured
`context.spec_locations`, including feature-packet layouts. Use one explicit
`Source: docs/features/.../spec.md`; ambiguous sources and resolved path escapes
are rejected. Source files still require complete approval metadata.

`context.skills_dir` accepts a repo-relative directory or an explicitly selected
absolute path (including `~/`) to installed methodology skills. Only this field
permits an external root; other context paths remain repo-bound. Relative traversal
and individual skill symlinks escaping the selected root are rejected. Pin the
installed plugin version in the path and refresh deliberately; do not copy skills
or runtime code into consumer repos just to satisfy path restrictions.
