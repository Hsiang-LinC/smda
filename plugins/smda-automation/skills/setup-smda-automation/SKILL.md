---
name: setup-smda-automation
description: Use when a repo needs reusable SMDA-only State-Machine-Driven Automation, when installing or refreshing autonomous issue-graph development workflows, or when wiring Codex harness context, a backlog manager, and the SMDA Scheduler product together.
---

# Setup SMDA Automation

Install or refresh a repo-local SMDA operating model; the bundled SMDA Scheduler
product runtime is the runtime truth. This skill is the Tier-3 config surface
only.
It requires the target repo to already have
`engineering:setup-codex-development-harness` output or an equivalent harness
contract; it does not install or refresh the generic development harness.

Core idea:

```text
roadmap, for multi-parent restructuring only
-> spec parent issue(s)
-> approved parent spec
-> reviewed task graph
-> child tasks in Linear or another product-supported backlog adapter
-> child phase machine: implement -> spec review -> quality review -> fix loops
-> serialized accept into parent integration branch
-> parent verification + QA/human gate
-> durable final accept / Done tracker effect
```

Read the references before writing:

- [methodology.md](methodology.md) — SMDA contract and state model.
- [adapters.md](adapters.md) — Codex harness, backlog, and SMDA Scheduler
  runtime adapters.
- [daemon-operations.md](daemon-operations.md) — optional, approval-gated:
  populating the Linear adapter env (read-only id fetch), the daemon invocation
  model (`--max-ticks` default 1), the daemon controller template
  (start/stop/restart/status) with a single-daemon guard, and the macOS TCC
  caveat for launchd/cron. Also covers the runtime-ledger-vs-tracker-projection
  status check that fresh sessions use to diagnose backlog projection lag.
- Product docs when available: `docs/contracts.md` and `docs/product-spec.md`
  (relative to the SMDA Scheduler product repo root — this skill is hosted from
  that repo).
- Product-owned prompts/schemas/manifests live in the bundled SMDA Scheduler
  product runtime. This skill does not write runtime prompt templates, schemas,
  contracts, or report envelopes into target repos. Repo-local prompt overrides
  are config references only.
- Product-owned execution code also lives in the plugin bundle: the Python
  scheduler launches the plugin-local Sandcastle runner artifact for role
  attempts instead of using target-repo runner files or Node dependencies.
- [fixtures/README.md](fixtures/README.md) — clean-room validation scenarios.

## Hard Gates

Stop and report clearly when any required adapter is missing:

1. No repo context substrate: run or recommend
   `engineering:setup-codex-development-harness`, or create an equivalent
   harness with an index, tracker contract, domain-doc routing, and quality-gate
   contract first.
2. No tracker/backlog surface: choose a product-supported backlog adapter
   (`linear` or `local-ledger`). GitHub/custom trackers require a product
   adapter; do not invent one in setup.
3. No installed SMDA plugin/runtime bundle: stop before claiming runtime
   automation is active. Do not vendor engine or adapter code into the target
   repo.
4. Unsupported tracker or orchestrator: name the adapter interface to implement.
5. Legacy worker/orchestrator artifacts: stop and require a repo-specific
  hard-replacement spec or explicit artifact removal first.
6. Rough-intake parent specs require Human Review before `SPEC_FINALIZED`.
7. Setup output would include executable runtime/adapter code: stop. A new
   adapter is product code, not setup-skill output.

## Process

### 1. Explore

Read the target repo's bootloader, harness/tracker docs if present, quality
gates, roadmap/spec/ADR locations, current or legacy orchestrator artifacts,
and tracker evidence. Detect setup, refresh, legacy blockers, or drift repair.

### 2. Propose

Show the detected stack and the SMDA adapter plan before writing:

- context substrate: Codex harness or equivalent;
- tracker/backlog manager: Linear by default, or another product-supported
  adapter;
- orchestration engine: SMDA Scheduler product or missing;
- bootloader/harness routing and handoff pointers for fresh sessions;
- roadmap location and policy for multi-parent restructuring;
- parent spec path/status policy;
- child graph publication policy;
- parent integration branch and merge strategy;
- verification/QA gates; legacy blockers if detected.
- runtime observability: local SMDA ledger/status is workflow truth; Linear is
  tracker projection; `smda-scheduler status` and the daemon controller `status`
  are the read-only checks fresh sessions should run before judging progress.

### Backlog adapter choice

Choose one backlog adapter before writing config:

- Linear: use `adapters.backlog.id: linear` when the repo has a Linear tracker
  and the operator can provide local Linear env values. Setup writes the adapter
  id/scope in config and points to the gitignored env file; it does not commit
  Linear secrets.
- Local ledger: use `adapters.backlog.id: local-ledger` when the repo harness
  tracker truth lives in files. Setup writes the local ledger paths
  (`active_path`, `completed_path`, `abandoned_path`) when they differ from
  `docs/work-ledger/active.md`, `docs/work-ledger/completed.md`, and
  `docs/work-ledger/abandoned.md`.

If the requested tracker is not `linear` or `local-ledger`, stop and name the
Tier-2 backlog adapter to implement; do not generate adapter code in setup.

Recommend the default stack when available: Codex harness + Linear hierarchy /
blocking relations + SMDA Scheduler. For file-backed harnesses, recommend Codex
harness + local-ledger + SMDA Scheduler. New repos get SMDA-only wiring. Wait
for approval before first-time writes.

### 3. Write Or Refresh

Create/update approved SMDA Tier-3 artifacts:

- `smda.config.yaml` or `.json` with runtime version constraint, adapter ids,
  sandbox provider choice, execution agent provider/model/effort, context paths,
  quality gates, policy numbers, prompt override location, labels, and schema
  package range;
- optional `smda.config.local.*` for secrets or local-only overrides;
- repo/harness/bootloader routing, quality gates, and handoff pointers that
  tell fresh agents SMDA Scheduler is active;
- harness routing text that names SMDA execution markers
  (`Execution: smda`, `Execution: smda-task`, `Execution: smda-roadmap`,
  `Execution: smda-child`, `Execution: manual`) without making `Execution:`
  mandatory for every tracker item;
- repo/harness status guidance that points agents to `smda-scheduler status`
  for parent/child phase and `tracker_effects`, and to the daemon controller
  `status` for process liveness; do not tell agents to infer runtime truth from
  Linear alone;
- roadmap/spec routing pointers for large changes and parent dependencies;
- optional prompt wording/context overrides only. Overrides must preserve
  product-owned role schemas, required report sections, and transition
  semantics;
- tracker setup notes; live labels/states require approved adapter commands;
- `.gitignore` entries for runtime state/workspaces;
- gitignored local env file (e.g. `.env`) with the Linear adapter ids/secret —
  populate per [daemon-operations.md](daemon-operations.md) § 1 using a
  read-only id fetch; never commit secrets;
- optional daemon controller script (start/stop/restart/status, single-daemon
  guard) per [daemon-operations.md](daemon-operations.md) § 3 — write only when
  the user asks to operate the daemon; this is ops glue invoking the product CLI,
  not runtime code, and is written but never started during setup;
- legacy blocker report when setup stops.

Do not copy product runtime code, adapter implementations, schema validators,
workflow manifests, or report parsers into the target repo. Link to the product
runtime and prompt/schema package instead.

Preserve user-authored content. Do not overwrite harness, tracker, or
orchestrator files without diff approval.

### 4. Verify

Run non-live validation first:

- product boot validation, when the product repo/package is available:
  `smda-scheduler validate-config <config> --repo-root <repo>`; for an
  editable local checkout, use
  `uv run --project <smda-product-root> smda-scheduler validate-config <config> --repo-root <repo>`;
- product context validation, when the product repo/package is available:
  `smda-scheduler validate-context <config> --repo-root <repo>`; for an
  editable local checkout, use
  `uv run --project <smda-product-root> smda-scheduler validate-context <config> --repo-root <repo>`;
- config validation for Tier-3 config artifacts;
- tracker and bootloader/harness consistency;
- status guidance consistency: fresh agents can distinguish the local SMDA
  ledger (`smda-scheduler status`) from Linear tracker projection and know where
  pending/failed tracker effects are reported;
- roadmap/spec routing consistency for multi-parent work;
- prompt/template path checks;
- prompt/template override compatibility for parent shaping, graph
  planning/review, child implement/review/fix, parent QA, and QA feedback
  classification;
- adapter availability and capability checks;
- role schema package compatibility through the product, not copied schema-file
  validation;
- dry-run graph publication when supported.

Do not start daemons, create live tracker states, publish child issues, or run
autonomous loops unless the user explicitly asks for the live step.

When the user explicitly asks for the live daemon step and validation has
passed, the product command shape is:

```bash
smda-scheduler daemon <config> --repo-root <repo> --state Todo --label agent --owner smda-daemon
```

For an editable local checkout during product development:

```bash
uv run --project <smda-product-root> smda-scheduler daemon <config> --repo-root <repo> --state Todo --label agent --owner smda-daemon
```

`--max-ticks` defaults to 1 (one tick, then exit); continuous running is
external. For the env prerequisites, the daemon controller template
(start/stop/restart/status) with a single-daemon guard, and the macOS TCC caveat, see
[daemon-operations.md](daemon-operations.md). Run at most one daemon per repo —
the parent intake scan has no cross-process mutex.

### 5. Report

Report: what was installed/refreshed;
- which adapters are active;
- which manual live steps remain and legacy blockers found, if setup stopped;
- validation outcomes and follow-ups before full automation.
