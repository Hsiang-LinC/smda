# SMDA Adapters

SMDA is method-first. These adapters describe the default deployment shape.

## Codex Development Harness Adapter

Use `setup-codex-development-harness` or an equivalent context substrate before
SMDA. The harness should provide:

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

Linear live adapter wiring uses local environment or local secrets, not
committed repo config:

- `LINEAR_API_KEY`;
- `SMDA_LINEAR_TEAM_ID`;
- `SMDA_LINEAR_STATE_TODO`, `SMDA_LINEAR_STATE_IN_PROGRESS`,
  `SMDA_LINEAR_STATE_AGENT_REVIEW`, etc., matching the repo tracker state names.

To populate these ids, see [daemon-operations.md](daemon-operations.md) § 1 — a
read-only Linear GraphQL fetch of team/state/label ids written to a gitignored
env file, plus the env-var-name-to-tracker-name mapping rules. Execution modes
(`Execution: smda` / `smda-child`) are issue body markers, not labels, so they
need no label env entry.

Other trackers require product adapter implementations. The setup skill must not
generate GitHub, local-file, or custom backlog adapter code.

## SMDA Scheduler Runtime

The SMDA Scheduler product is the deterministic runtime. Symphony/codex-symphony
are historical design sources, not repo-local runtime targets for new setup.

Target setup:

```text
Execution: smda       -> SMDA Scheduler parent
Execution: smda-child -> SMDA Scheduler child handle
```

The repo must also document one policy for work without an execution mode:
require explicit `Execution: smda`, normalize eligible work into implicit
one-child SMDA, or block until parent context exists. Do not leave a separate
generic autonomous worker path in an SMDA-only setup.

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
- `smda.config.*` plus local secret overrides;
- runtime state directory ignored by git;
- tracker setup notes for SMDA parent/child labels/states/relations;
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
- runtime package availability outside the target repo;
- tracker mapping consistency;
- issue-entry policy is documented and has no generic autonomous worker bypass;
- verification command presence;
- dry-run child publication if supported.

Live actions require explicit user approval:

- create tracker states/labels;
- publish child issues;
- start daemon/autonomous loop;
- accept/merge branches.
