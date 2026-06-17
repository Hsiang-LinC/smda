---
name: setup-smda-automation
description: Use when a repo needs reusable SMDA-only State-Machine-Driven Automation, when installing or refreshing autonomous issue-graph development workflows, or when wiring Codex harness context, a backlog manager, and the SMDA Scheduler product together.
---

# Setup SMDA Automation

Install or refresh a repo-local SMDA operating model; the SMDA Scheduler product
is the runtime truth. This skill is the Tier-3 config surface only.

Core idea:

```text
roadmap, for multi-parent restructuring only
-> spec parent issue(s)
-> approved parent spec
-> reviewed task graph
-> Linear child tasks (MVP) or another product-supported backlog adapter
-> child phase machine: implement -> spec review -> quality review -> fix loops
-> serialized accept into parent integration branch
-> parent verification + QA/human gate
-> durable final accept / Done tracker effect
```

Read the references before writing:

- [methodology.md](methodology.md) — SMDA contract and state model.
- [adapters.md](adapters.md) — Codex harness, backlog, and SMDA Scheduler
  runtime adapters.
- Product docs when available: `docs/contracts.md` and `docs/product-spec.md`
  (relative to the SMDA Scheduler product repo root — this skill is hosted from
  that repo).
- Product-owned prompts/schemas/manifests live in the SMDA Scheduler product.
  This skill does not bundle runtime prompt templates, schemas, contracts, or
  report envelopes. Repo-local prompt overrides are config references only.
- [fixtures/README.md](fixtures/README.md) — clean-room validation scenarios.

## Hard Gates

Stop and report clearly when any required adapter is missing:

1. No repo context substrate: run or recommend `setup-codex-development-harness`,
   or create an equivalent map/tracker/quality-gate contract first.
2. No tracker/backlog surface: default to Linear for MVP. GitHub/local-file
   require a product adapter; do not invent one in setup.
3. No SMDA Scheduler product/runtime: write config and stop before claiming
   runtime automation is active. Do not vendor engine or adapter code into the
   target repo.
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

Recommend the default stack when available: Codex harness + Linear hierarchy /
blocking relations + SMDA Scheduler. New repos get SMDA-only wiring. Wait for
approval before first-time writes.

### 3. Write Or Refresh

Create/update approved SMDA Tier-3 artifacts:

- `smda.config.yaml` or `.json` with runtime version constraint, adapter ids,
  provider choice, context paths, quality gates, policy numbers, prompt override
  location, labels, and schema package range;
- optional `smda.config.local.*` for secrets or local-only overrides;
- repo/harness/bootloader routing, quality gates, and handoff pointers that
  tell fresh agents SMDA Scheduler is active;
- roadmap/spec routing pointers for large changes and parent dependencies;
- optional prompt wording/context overrides only. Overrides must preserve
  product-owned role schemas, required report sections, and transition
  semantics;
- tracker setup notes; live labels/states require approved adapter commands;
- `.gitignore` entries for runtime state/workspaces;
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

### 5. Report

Report: what was installed/refreshed;
- which adapters are active;
- which manual live steps remain and legacy blockers found, if setup stopped;
- validation outcomes and follow-ups before full automation.
