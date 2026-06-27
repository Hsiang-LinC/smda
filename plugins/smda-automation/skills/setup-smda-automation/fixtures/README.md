# setup-smda-automation — clean-room fixtures

These fixtures validate skill wording and setup behavior. They are prompt-run
scenarios, not a pytest suite.

## Fixture A — harness-linear-smda-scheduler

Setup: repo has a Codex development harness with Linear tracker contract and a
configured SMDA Scheduler product runtime.

Expected:

- skill detects harness/tracker/quality gates;
- proposes Codex harness + Linear + SMDA Scheduler adapter plan;
- uses SMDA-only target wiring because no legacy orchestration exists;
- updates bootloader/harness routing so fresh sessions can find SMDA docs,
  runtime state, issue context, and branch/artifact handoff pointers;
- documents that local SMDA ledger/status is workflow truth and Linear is a
  tracker projection;
- points fresh sessions to `smda-scheduler status` for parent/child phase and
  `tracker_effects` before judging Linear sync;
- writes or refreshes SMDA config/docs only after approval;
- validates non-live config;
- does not install product-owned prompt templates, result schemas, workflow
  manifests, or report envelopes into the target repo;
- does not publish child issues or start daemon.

## Fixture A1 — harness-local-ledger-smda-scheduler

Setup: repo has a Codex development harness whose tracker truth is
`docs/work-ledger/active.md`, `completed.md`, and `abandoned.md`, plus a bundled
SMDA Scheduler runtime.

Expected:

- skill detects the file-backed harness tracker;
- proposes `adapters.backlog.id: local-ledger`;
- emits `active_path`, `completed_path`, and `abandoned_path` only when the repo
  uses non-default ledger locations;
- documents that the local ledger remains the harness source of truth and the
  SMDA runtime ledger remains workflow truth;
- does not generate adapter code, rewrite the harness ledger format, publish
  child issues, or start daemon.

## Fixture A2 — harness-missing-smda-routing

Setup: repo has a Codex development harness and Symphony SMDA config, but
`AGENTS.md` / harness routing never mention SMDA or where handoff state lives.

Expected:

- skill classifies this as refresh or runtime drift repair;
- proposes bootloader/harness routing updates before claiming setup complete;
- validates that fresh-session handoff points to tracker issue context,
  runtime state, branch/artifacts, and verification evidence.

## Fixture A4 — linear-projection-lag-status

Setup: repo has a Codex harness, Linear tracker, SMDA Scheduler config, and a
daemon controller script. Linear shows an issue in an older state than the SMDA
local ledger.

Expected:

- skill classifies this as an operations/status interpretation case, not a
  config rewrite by itself;
- tells the agent to run the daemon controller `status` for process liveness;
- tells the agent to run `smda-scheduler status <config> --repo-root <repo>` for
  local workflow truth and `tracker_effects`;
- explains that `tracker_effects.pending` without errors can be normal
  projection lag until the next daemon tick;
- treats `pending_with_errors` or `recent_errors` as tracker projection failure
  evidence;
- does not infer workflow truth from Linear alone.

## Fixture A3 — roadmap-large-restructure

Setup: repo has a harness, Linear tracker, and SMDA runtime. The user wants a
large architecture restructure that is too broad for one parent spec.

Expected:

- skill requires a durable roadmap location or equivalent tracker view;
- roadmap records direction, shared constraints, spec parent candidates, and
  parent-level dependencies;
- roadmap does not become executable work or publish child issues directly;
- each roadmap slice becomes a normal SMDA parent issue that must reach
  `SPEC_FINALIZED` before decomposition;
- fresh-session routing explains where to find roadmap context and how it maps
  to parent issues.

## Fixture B — no-harness

Setup: repo has no `docs/harness/tracker.md` and no equivalent context
contract.

Expected: skill stops and recommends
`engineering:setup-codex-development-harness` or asks for equivalent context
files; writes nothing.

## Fixture C — legacy-symphony-hard-gate

Setup: repo has legacy `WORKFLOW.md` / `ORCHESTRATOR.md` / `REVIEW.md` but no
SMDA config.

Expected:

- skill stops before writing SMDA config;
- reports detected legacy artifacts;
- requires a repo-specific hard-replacement spec or explicit legacy artifact
  removal before setup continues.

## Fixture D — unsupported-tracker

Setup: harness tracker kind is not supported by the selected orchestrator
adapter.

Expected: skill stops before writing runtime config and names the backlog
adapter interface to implement; it does not generate adapter code.

## Fixture E — approved-spec-direct-path

Setup: parent issue references a repo spec with approved front matter and
checksum evidence.

Expected: skill accepts this as the direct `SPEC_FINALIZED` input path and
does not add a rough-intake Human Review gate.

## Fixture F — draft-spec-gate

Setup: parent issue references a draft spec.

Expected: skill keeps the parent in draft/Pending Review guidance and does not
allow decomposition until approval evidence updates the spec front matter.
