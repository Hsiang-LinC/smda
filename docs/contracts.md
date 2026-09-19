# SMDA Contracts — Boot Contract (config, adapters, versions)

Status: draft for review (skeleton; shapes and rules fixed, exact signatures
deferred to implementation)

This document defines the contracts that let the SMDA Scheduler product start
against a given repo and adapter set. Three things are one coupled cluster — the
**boot contract** — and are specified together here: the config surface (Tier
3), the adapter interface + capability negotiation (Tier 2), and the version
compatibility matrix that the setup skill verifies before the daemon starts.

Override-compatibility for prompts/templates and provider-selection ownership
are included because they share the same validation gate.

---

## 1. Config surface (Tier 3)

Config is a first-class, versioned contract — not loose flags.

- **Residence:** `smda.config.yaml` (or `.json`) at the repo root, plus optional
  `smda.config.local.*` for secrets/overrides not committed.
- **Versioned:** carries `config_schema_version`. The daemon refuses to start on
  an unknown/incompatible config schema version (see §4).
- **Precedence (lowest → highest):** product defaults < repo `smda.config.*` <
  `smda.config.local.*` < environment variables < CLI flags. Higher wins per
  key; merges are shallow per top-level section unless a section documents deep
  merge.

Required top-level fields (skeleton):

```yaml
config_schema_version: <int>
runtime:
  version_constraint: <range>          # acceptable runtime versions
  state_root: .smda/state              # optional; product default shown
  artifact_root: .smda/artifacts       # optional; product default shown
adapters:
  execution:
    id: sandcastle
    version_constraint: <range>
    provider: noSandbox                  # sandbox provider
    agent:
      provider: codex                    # agent provider: codex | claudeCode
      model: gpt-5-codex                 # repo-tunable model name
      effort: high                       # optional; provider-specific values
      role_overrides:                    # optional role id -> agent selection
        graph_decomposer:
          provider: codex
          model: gpt-5.5
          effort: high
  backlog:
    id: linear | local-ledger
    version_constraint: <range>
    scope_id: <string>
    active_path: docs/work-ledger/active.md       # local-ledger default
    completed_path: docs/work-ledger/completed.md # local-ledger default
    abandoned_path: docs/work-ledger/abandoned.md # local-ledger default
  context:   { id: codex-harness, version_constraint: <range> }
schemas:
  role_schema_package_version: <range> # accepted for forward compatibility
context:
  bootloader_path: <path>
  spec_locations: [ <path>, ... ]
  adr_locations: [ <path>, ... ]
  quality_gates: [ <command>, ... ]
  skills_dir: <repo-relative path or null>
  harness_contract_path: <repo-relative JSON path or null>
policy:
  issue_entry: explicit-only | implicit-one-child | blocked
  qa:
    max_same_feedback_fingerprint: <int>
    max_total_remediation_children: <int>
    max_parent_qa_cycles: <int>
  concerns:
    create_follow_up_issues: false
    labels: [smda-follow-up]
prompts:
  overrides_dir: <path or null>        # Tier-3 wording/context only (see §3)
labels:
  ...tracker-specific handles...
```

The setup skill writes this file. It writes nothing else executable.

### Shared harness binding (opt-in)

`context.harness_contract_path` enables a machine-checked projection of the
repo harness policy. It is a binding to existing product roles, not a workflow
language: it cannot add roles, transitions or tools. Version 2 adds an explicit
project-owned acceptance policy for tasks, spec parents and roadmaps.
Existing configurations without this path keep their prior behavior;
`validate-context` reports `harness_contract_path: null` in that case.

The referenced JSON object contains exactly these fields:

| Field | Required value |
|---|---|
| `schema_version` | Integer `2`; v1 must be migrated explicitly |
| `execution_owner` | `"smda"` |
| `roles` | The `harness_role_bindings` object returned by `validate-context`: each role declares its shared `phase` and ordered `skills` list |
| `blocking_labels` | List of distinct, nonempty tracker label names; an explicit empty list disables this check |
| `acceptance` | Project-authorized acceptance policy below |

Generate `roles` from the installed runtime, then compare it with the project's
chosen methodology before adopting it. A conflicting project requirement is a
setup error, not permission to rewrite the requirement to make validation pass.
All current runtime roles must be represented. The current registry maps graph
roles and roadmap decomposition to `slice`, implementation/fixing/integration
conflict resolution to `implement`, and child/parent outcome review to `accept`.
`clarify` and `specify` remain upstream input/approval work, not new runtime roles.

A configured binding requires `context.skills_dir` and nonempty content for
every declared skill. Missing/unreadable JSON, unknown fields, incompatible
role/phase/skill mappings, wrong owner/version and escaping paths fail context
validation and configured tick construction. `validate-context` reports the
resolved contract path, loaded skills, supported bindings and blocking labels.
It verifies structural compatibility, not the meaning of arbitrary skill prose.

Each workspace scan checks `blocking_labels` before either dispatch path. A
matching item waits without a new claim, role attempt or lifecycle mutation;
removing its gate makes it eligible for reevaluation on the next scan. Gate
names are tracker-specific and matched exactly. The contract is loaded when the
tick is constructed; restart the daemon after editing it. A scan uses the
backlog snapshot, so this check does not revoke an already running attempt.

Every role prompt ends with the runtime execution boundary: perform the assigned
role and return its artifact; the runtime owns phase advancement and tracker
publication. This is instruction-level guidance, not a sandbox restriction on
external tools. Existing typed results, graph checks, approved-spec checks and
serialized acceptance remain the actual runtime transition gates. Unknown policy
fields are rejected. Cross-controller ownership transfer and deployment are not
implemented by this binding.

#### Project acceptance policy (binding v2)

The harness owns these values; SMDA executes them. Tracker docs reference this
acceptance section as the authority instead of maintaining another set of values.
Interactive agents must apply the same authority and evidence rules without SMDA.

```json
{
  "child_integration": "agent",
  "parent_merge": "agent",
  "merge_target": "main",
  "verification_commands": [["python3", "-m", "unittest", "discover"]],
  "human_review_paths": ["migrations/**", "auth/**"]
}
```

This is the `acceptance` field, not the whole binding. `parent_merge` is `agent`
or `human`; child integration currently supports `agent` only. Choose commands
and repo-relative, case-sensitive fnmatch patterns from the actual project.
`*` can span `/`; renamed protected paths remain protected. Commands are nonempty
argv arrays executed without an implicit shell, from a clean detached candidate
worktree, with a 300-second limit per command. They are operator-authorized code,
not strings supplied by worker results. Provision dependencies within those
commands/environment; no uncommitted operator checkout or installed node_modules
is silently copied. Successful commands cannot change tracked candidate content.

- Spec approval authorizes scope; an AFK assessment alone never overrides this
  merge policy. `human_approval_required` and `high_risk` Mode tags block automated
  claim even without a binding. Clear/reclassify them only after a human decision.
- Parent QA starts from the candidate commit on a fresh attempt-specific review
  branch. Successful read-only QA (`PASS` or the existing nonblocking
  `DONE_WITH_CONCERNS` result) plus host-run checks are recorded in the attempt
  ledger with candidate/base/policy, spec and graph evidence. The candidate cannot
  change the approved spec or checked policy file. Other protected paths request
  human attention; policy and actual diff are checked, not only a model verdict.
- Final acceptance rechecks current source, issue body, graph, policy and branch
  revisions. A fast-forward-only compare-and-swap updates the local target ref to
  the reviewed commit; it creates no unreviewed merge commit. Restart recovery
  accepts an already-landed exact commit. A changed base requires rebase/review.
- The target must not be checked out in any worktree; use a dedicated scheduler
  checkout. Git worktree/ref operations require normal repository permissions.
  This local delivery path does not push, invoke provider PR merge, or deploy.
  Existing external branch protection/publishing requirements still apply.
- `parent_merge: human` hands off at the parent QA boundary; there is no synthetic
  human approval event or automatic manual-accept resume in v2. Preserve evidence
  and finish through the project's manual process. Do not weaken policy to resume.
- Checked standalone tasks require one `Source:` reference: a committed local
  Markdown source, or a direct conversation/tracker decision reference for a
  scoped small task. After quality review, the task stays In Progress until
  separate whole-delivery QA and host checks authorize the exact local merge.
- Roadmap members use the same checked parent delivery into the roadmap's derived
  integration branch. Aggregate acceptance requires complete member projections,
  accepted member QA/land records, unchanged member sources/graphs, and their
  exact accepted commits in the aggregate history. Whole-roadmap QA and host
  checks then authorize delivery into the configured target. Every member source
  is checked against the aggregate candidate, not just its historical commit.
- Tasks and roadmaps reuse the parent QA role, attempt ledger and land operations.
  Completed land operations reconcile tracker effects without repeating a merge.
  Failed/stale final QA stops for manual attention; there is no automatic retry
  or human-approval resume. Legacy configurations without a binding retain prior
  behavior but do not enforce harness acceptance. Never omit the binding to bypass
  a checked setup requirement.
- Any policy file change stops further checked dispatch until context is refreshed.
  Existing QA evidence does not authorize a new policy. Human handoff effects are
  durable; this is runtime enforcement, not tool-level isolation from agents with
  unrestricted shell/tracker access.

Migration: do not automatically translate v1 into agent permission. Obtain the
project's existing authorization, add `acceptance`, set version 2, commit approved
source and policy, and run `validate-context`. Existing unbound QA evidence must
be regenerated before automatic landing.



The runtime derives `workspace_id`; repo config does not define it by default.
Initial derivation:
`hash(canonical_repo_root + backlog_adapter_id + backlog_scope_id)`, where
`backlog_scope_id` is the tracker project/workspace id or an adapter-declared
local scope. The derived id namespaces ledger, artifacts, locks, and adapter
credentials under the configured roots. An explicit `workspace_id` override is
an advanced escape hatch only, because collisions or accidental reuse can
corrupt state.

For the MVP, role schema compatibility is owned by the Sandcastle execution
adapter and its generated/packaged schema metadata. Repo config may carry
`role_schema_package_version` for forward compatibility, but the boot gate does
not enforce a full role-schema matrix until multiple schema packages exist.

---

## 2. Adapter interface + capability negotiation (Tier 2)

Each adapter is selected by id in config and resolved by the product to a shipped
or installed implementation. Every adapter MUST expose:

- `id` and `version`;
- `capabilities() -> CapabilitySet` — what this implementation actually
  supports;
- its core methods (named below; exact signatures deferred).

The workflow engine declares, per feature it runs, which capabilities are
**required** vs **optional**. On onboard/boot the product intersects
`workflow.required_capabilities` with `adapter.capabilities()`:

- missing **required** capability → **refuse onboard** with a named error (no
  silent degrade);
- missing **optional** capability → enable the documented fallback and record it.

### Execution adapter

- Core: `runAttempt(request) -> result` (run prompt in isolation, extract typed
  output, return an Attempt Result Artifact + evidence). Default: Sandcastle.
- Config surface: `adapters.execution.provider` selects the sandbox provider
  (`noSandbox` for the local MVP). `adapters.execution.agent` selects the
  default agent runtime and model (`provider`, `model`, optional `effort`).
  Optional `role_overrides` maps role ids to role-specific agent selections.
  This is a repo-tunable Tier-3 policy surface so consumer repos can pick a
  supported model without modifying product code or setup-generated runtime
  files.
- Control boundary: every attempt produces a durable **Attempt Result Artifact**
  under `runtime.artifact_root`. The scheduler advances workflow state only from
  that artifact. stdout/stderr are **Process Logs** for evidence and snippets;
  they are never parsed as the workflow-control channel.
- Envelope ownership: the model may author the typed role payload after
  structured-output validation, but runner/adapter code authors the artifact
  envelope (`status`, schema metadata, failure metadata, commits, branch, and
  evidence handles).
- Failure semantics: missing or invalid artifacts are adapter contract
  violations. If the process exits nonzero but writes a valid artifact, the
  artifact status is authoritative and the process status/logs are evidence.
- Capabilities: `sandbox_providers: [noSandbox|docker|podman|vercel|custom]`,
  `session_resume`, `worktree_per_attempt`, `structured_output_recovery`.
- Required by workflow: `worktree_per_attempt` (concurrency safety),
  `structured_output_recovery`.

### Backlog adapter (the hard case — capability-sensitive)

- Core: `fetchIssue`, `setCoarseState`, `comment`, `createChild`,
  `linkBlocking`, `projectHierarchy`, `setLabels`.
- Capabilities: `create_child`, `coarse_states`, `comments`, `hierarchy`,
  `blocking_relations`, `labels`, `custom_fields`.
- Required by workflow: `create_child`, `coarse_states`, `comments`.
- Optional with fallback: `blocking_relations` (fallback: gate purely on SMDA
  graph DAG, skip tracker-side blocking projection), `hierarchy` (fallback: flat
  issues + parent-id label).
- Linear label projection requires configured label ids such as
  `SMDA_LINEAR_LABEL_AGENT=<label-id>`. Repo config names the semantic labels;
  adapter credentials/config map those names to tracker ids.

#### Local-ledger backlog contract

`local-ledger` is a product backlog adapter for repos whose tracker truth is a
file-backed harness ledger. It is not the SMDA phase ledger and does not replace
the harness. The adapter maps ledger entries to `BacklogIssue` records and writes
only harness-compatible projections back to the same ledger.

Default entry fields:

```markdown
## <issue-id>
- status: planned | in-progress | blocked
- execution: smda | smda-task | smda-roadmap | smda-child | manual
- parent: <parent issue id>        # required for smda-child; optional otherwise
- node-id: <SMDA graph node id>    # scheduler-created children only
- graph-checksum: <checksum>       # scheduler-created children only
- blocked-by: <issue ids, or none>
- acceptance: <observable outcome>
- verify: <commands / evidence expectation>
- next: <single next action>
- updated: YYYY-MM-DD
```

Required mapping:

- `issue_id`: section heading slug.
- `title`: first non-empty title field if present, otherwise heading slug.
- `body`: the normalized entry text. Adapter implementations may synthesize the
  existing classifier lines (`Execution:`, `Parent issue:`, `Node id:`,
  `Graph checksum:`, `Acceptance criteria:`, `Verification:`) from the default
  fields above instead of forcing those exact lines into the human ledger.
- `state`: `planned -> Todo`, `in-progress -> In Progress`, `blocked -> Blocked`
  unless `labels` or `next` indicate human review, in which case
  `Human Review`; completed entries project as `Done`; abandoned entries project
  as `Canceled`.
- `labels`: optional harness labels; SMDA execution mode is not a label.
- `comments`: append-only SMDA evidence notes under the entry; the adapter must
  preserve non-SMDA text.

Write policy:

- `createChild` appends a scheduler-owned child entry with `execution:
  smda-child`, parent id, node id, graph checksum, acceptance, verification, and
  dependency references derived from the SMDA graph.
- `setCoarseState` mutates only the local lifecycle field or moves an entry to
  the harness' completed/abandoned archive when the target repo policy allows
  the adapter to do so. It must not bypass a documented human acceptance gate.
- `comment` appends evidence; it must not rewrite the user's work description.
- `linkBlocking` uses the existing harness dependency field when available.
  Without one, the adapter declares the `blocking_relations` fallback and SMDA
  gates on its graph only.
- `projectHierarchy` uses the existing `parent:` field or declares the
  `hierarchy` fallback (`flat_issues_with_parent_label`). It does not create a
  second roadmap or tracker model.

Config names the file locations and field aliases. The defaults above are the
supported harness shape; a repo with different names must configure aliases
rather than receive generated adapter code from setup.

### Context adapter

- Core: `discoverBootloader`, `discoverGates`, `resolveDocLocations`,
  `repoCommands`.
- Capabilities: `bootloader`, `spec_locations`, `repo_commands`, `roadmap`,
  `adr`, `quality_gates`.
- Required by workflow: `bootloader`, `spec_locations`.

A new adapter is **product code against these interfaces** — never a setup-skill
output (Tier-2 vs Tier-3 line).

---

## 3. Prompt / template override compatibility (Tier 3, gated)

Setup may supply config references to repo-local prompt wording/context
overrides, but must not install prompt/template artifacts or become a hidden
workflow fork.

- **Product owns (fixed):** role result schema, required report sections,
  transition semantics (`required_next_action` enum, verdict→phase routing).
- **Setup may override (Tier 3):** prompt wording and repo-specific context
  blocks by reference only.
- **Gate:** every override is run through a compatibility check — it MUST still
  satisfy the role schema through the execution adapter's structured-output
  mechanism (`Output.object` for the Sandcastle adapter) and preserve required
  report sections. Failing the check fails setup; it does not start a degraded
  daemon.

---

## 4. Version compatibility gate

The MVP boot gate is intentionally small:

```
runtime version  ↔  config_schema_version
```

- The daemon refuses unknown or incompatible `config_schema_version` values.
- Adapter ids must resolve to product-installed implementations.
- Adapter capabilities are negotiated separately in §2; missing required
  capabilities still refuse boot.

Deferred: once multiple adapter and role-schema packages exist in the wild,
expand this into the full matrix:

```text
runtime version  ↔  adapter version(s)  ↔  config_schema_version  ↔  role_schema_package_version
```

Until then, treating the full cross-product as a boot contract would create
versioning machinery without real versions to protect.

---

## 5. Runtime status and tracker projection

The status surface is a read-only product contract. It reports the local SMDA
workflow ledger and the tracker-projection outbox in one payload so operators do
not have to infer runtime truth from Linear or another backlog UI.

`smda-scheduler status <config> --repo-root <repo>` MUST include:

- workspace and ledger identity (`workspace_id`, `ledger_path`);
- parent run summaries;
- child run summaries, including phase, attempt count, claim owner/backoff, and
  current candidate/accepted refs when available;
- paused parent ids;
- `tracker_effects` summary:
  - `total`;
  - `pending`;
  - `sent`;
  - `failed` for terminal failed records, if the ledger records that status;
  - `pending_with_errors` for pending effects with `last_error`;
  - `pending_by_type`;
  - `recent_errors` with effect id, effect type, target id, and last error.

Interpretation:

- The SMDA runtime ledger is workflow truth for phase, claim, attempt, pause,
  and accepted-commit state.
- Backlog tools such as Linear are projection targets. A short mismatch between
  local status and tracker UI is normal while `pending` effects are waiting for
  the daemon's next retry pass.
- `pending_with_errors` or non-empty `recent_errors` is the signal that tracker
  projection failed and needs operator diagnosis.

Setup skills and consumer repo harness docs may reference this command and
interpretation, but must not copy status implementation logic into target repos.

---

## 6. Tier-boundary test strategy (enforcement)

These tests mechanically prevent regression to a vendored runtime and keep the
tiers honest:

- **Core tests (Tier 1):** run the scheduling + workflow engines against
  **test-only fake adapters**. No real sandbox, tracker, or repo. Asserts routing, ledger
  durability, QA bounds, dependency gating.
- **Adapter contract tests (Tier 2):** run each adapter against **shared
  fixtures** that exercise the interface + every declared capability and
  fallback. Same fixtures for all implementations of an interface.
- **Setup-skill tests (Tier 3):** assert the skill **emits config only and
  zero executable code**, and that override-compatibility (§3) and the version
  matrix (§4) checks fire. This test is the guardrail for the whole 3-tier model.
