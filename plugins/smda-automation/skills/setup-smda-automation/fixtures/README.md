# setup-smda-automation — clean-room fixtures

These fixtures validate skill wording and setup behavior. They are prompt-run
scenarios, not a pytest suite.

## Fixture A — harness-linear-symphony-smda

Setup: repo has a Codex development harness with Linear tracker contract and a
Symphony runtime that advertises SMDA commands/config validation.

Expected:

- skill detects harness/tracker/quality gates;
- proposes Codex harness + Linear + Symphony SMDA adapter plan;
- installs or refreshes the SMDA runtime prompt templates;
- installs or refreshes the SMDA result schemas;
- uses SMDA-only target wiring because no legacy orchestration exists;
- updates bootloader/harness routing so fresh sessions can find SMDA docs,
  runtime state, issue context, and branch/artifact handoff pointers;
- writes or refreshes SMDA config/docs only after approval;
- validates non-live config;
- does not publish child issues or start daemon.

## Fixture A2 — harness-missing-smda-routing

Setup: repo has a Codex development harness and Symphony SMDA config, but
`AGENTS.md` / harness routing never mention SMDA or where handoff state lives.

Expected:

- skill classifies this as refresh or runtime drift repair;
- proposes bootloader/harness routing updates before claiming setup complete;
- validates that fresh-session handoff points to tracker issue context,
  runtime state, branch/artifacts, and verification evidence.

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

Expected: skill stops and recommends `setup-codex-development-harness` or asks
for equivalent context files; writes nothing.

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
adapter interface to implement.

## Fixture E — approved-spec-direct-path

Setup: parent issue references a repo spec with approved front matter and
checksum evidence.

Expected: skill accepts this as the direct `SPEC_FINALIZED` input path and
does not add a rough-intake Human Review gate.

## Fixture F — draft-spec-gate

Setup: parent issue references a draft spec.

Expected: skill keeps the parent in draft/Pending Review guidance and does not
allow decomposition until approval evidence updates the spec front matter.
