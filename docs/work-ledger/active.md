<!-- codex-harness: generated 2026-06-17 -->
# Active Work

Entry format: see `docs/harness/index.md` § Conventions.

## harness-workflow-contract-alignment
- status: blocked
- source: user-approved harness/SMDA boundary discussion, 2026-09-16
- acceptance: document shared policy/runtime boundary, single graph producer, supported acceptance and skill injection; no runtime engine changes
- verify: targeted setup documentation and context-packet tests; git diff --check. Documentation-only scope does not require runtime packaging or TypeScript gates.
- evidence: 11 targeted context/setup tests passed; 8 independent contract scenarios passed; source diff checks passed. Scheduler/runtime source unchanged.
- evidence-2026-09-17: shared phase contract and execution ownership clarified; 11 targeted context/setup tests and both repo diff checks passed. Added worker-routing and ownership-handoff scenarios; full agent execution remains unverified.
- next: human review and acceptance of shared-phase/execution-owner clarification; author does not self-accept
- updated: 2026-09-17

## shared-harness-runtime-validation
- status: blocked
- source: user request to enforce the shared harness contract in SMDA runtime, 2026-09-17
- acceptance: validate declared role/skill bindings before execution; enforce configured readiness gates on dispatch; preserve runtime lifecycle ownership and existing phase/acceptance checks
- verify: failing regression tests first, targeted and full scheduler tests, packaging parity and diff checks
- evidence: regression tests failed before implementation; 462 distinct Python tests passed across the full run and packaging retry (1 skipped, 2 deselected); 16 TypeScript tests passed (1 live test skipped); typecheck, schema export, runtime bundle sync and diff checks passed.
- verification-limits: excluded the fixture requiring /Users/danny/Desktop/GitHub/trading-advisor/smda.config.json and the CLI test launching a real agent. Git tests used init.defaultBranch=master. No live daemon or standalone native rebuild.
- follow-up: user authorized TDD runtime handoff/applicability alignment on 2026-09-17; reuse approved decisions, escalate missing behavior, verify nonbehavioral tasks without invented code tests
- handoff-evidence: three independent skill scenario checks passed; 38 role/attempt/harness tests passed; TDD skill format and five reference paths validated; both repo diff checks passed. No live agent behavior guarantee.
- next: human review/acceptance; enable the checked contract and updated skills in a consumer repo before deployment
- updated: 2026-09-17

## harness-smda-cooperation-review
- status: blocked
- source: user requested evidence-based cooperation review and local fixes, 2026-09-17
- acceptance: demonstrate both execution modes; fix dropped child constraints and contradictory actor instructions; report fundamental policy/method/schema decisions without silently redesigning them
- verify: failing prompt regression, scheduler tests, scripted DraftBox runtime probes and skill scenario review
- evidence: child prompt regression failed before fix; 463 scheduler tests passed (1 skipped, 2 deselected); three skill walkthroughs and both repo diff checks passed. DraftBox before/after probes demonstrate context delivery fix and unresolved policy/path/schema/scheduling mismatches.
- report: /Users/danny/Documents/ChatGPT/agent harness/harness-smda-review.md
- next: human review/acceptance; discuss acceptance authority, shared source contract and role methods before architectural changes
- updated: 2026-09-17

## harness-autonomous-parent-acceptance
- status: blocked
- source: user approved harness-authorized agent review and main merge with human exceptions, 2026-09-18
- acceptance: checked project policy authorizes local parent merge; explicit human/high-risk gates stop dispatch; QA and required checks bind to exact candidate/base/spec/graph; unsupported routes fail closed; deployment stays separate
- verify: real-Git acceptance tests, configured runtime QA-to-main tests including stale inputs and reviewer branch reuse, full scheduler suite, package parity, source diff checks and independent code review
- evidence: 483 Python tests passed (1 skipped, 2 environment/live-agent tests deselected); 16 TypeScript tests passed (1 live skip); typecheck, schema export, source bundle sync, packaging tests and both repo diff checks passed. Independent review findings reproduced and fixed. DraftBox human policy now stops before parent land.
- report: /Users/danny/Documents/ChatGPT/agent harness/harness-acceptance-implementation.md
- limits-at-2026-09-18: checked v2 supported spec parents/children; task/roadmap extension tracked below, human handoff has no automatic approval resume, delivery is local ff-only without push/deploy. Existing consumer configs/cache/native app not updated.
- next: human review and acceptance; select and refresh a consumer only when authorized. No self-acceptance, commit, push or rollout
- updated: 2026-09-18

## harness-checked-task-roadmap-delivery
- status: blocked
- source: user approved continuation of shared acceptance policy, 2026-09-19
- blocked-by: none
- acceptance: task final QA and roadmap member/aggregate QA share checked delivery; stale evidence and human policy cannot merge; completed operations reconcile without relanding
- verify: real-Git route regressions, full scheduler tests, plugin runtime parity and diff check; TypeScript unchanged
- evidence: 492 scheduler tests passed, 1 skipped, 2 excluded external/live-agent cases; includes 9 new real-Git route regressions and packaging parity. Plugin source runtime synchronized; independent review findings fixed and verified. Source diff check passed.
- limits: scripted agents, no live roadmap end-to-end test; manual handling for failed/stale final QA; local merge only, no commit/push/cache/native rollout. TypeScript unchanged; this continuation uses scheduler, packaging and diff gates.
- report: /Users/danny/Documents/ChatGPT/agent harness/harness-acceptance-implementation.md
- next: human review and acceptance; author does not self-accept
- updated: 2026-09-19

## harness-release-local-upgrade
- status: blocked
- source: user authorized commit, distribution release and local plugin upgrade, 2026-09-19
- blocked-by: none
- acceptance: source changes pushed; SMDA 0.3.0 built by CI and published to distribution; Engineering 0.2.0 and SMDA 0.3.0 installed locally with runtime validation
- verify: scheduler suite, TypeScript/typecheck/schema/package gates, CI result, installed manifest and native validate-context smoke
- evidence: source release 9acdea6; Engineering e2fa424. CI run 35455672101 succeeded for both native architectures and published distribution v0.3.0 at 2901f13. Local plugin manager installed Engineering 0.2.0 and SMDA 0.3.0. Native validate-context passed with installed Engineering skills, rejected v1 contract, and MCP initialize passed; installed native binary SHA256 matches distribution.
- verified: 492 Python passed, 1 skipped, 2 documented external/live-agent exclusions; 16 TypeScript passed, 1 live skip; typecheck/schema/export/package parity/diff checks passed.
- limits: existing consumer harnesses unchanged. Existing Codex task may retain old skills/MCP session; reopen/reload Codex to use new installation. No live autonomous consumer rollout performed.
- next: human acceptance of release evidence; reopen Codex before starting consumer refresh pilot
- updated: 2026-09-19

## consumer-harness-compatibility
- status: blocked
- source: PA refresh user approved runtime compatibility fix and patch release, 2026-09-20
- blocked-by: human acceptance
- acceptance: explicit installed skill roots work without vendoring; parent/roadmap intake respects configured spec roots and rejects escapes; release 0.3.1
- verify: failing regressions first, path/skill tests, full scheduler suite, package parity and independent review, CI native smoke
- evidence: 503 Python passed, 1 skipped, 2 existing external/live-agent exclusions; 11 compatibility regressions passed. Independent reviewer found unrelated-source snapshot failure; corrected and regression-covered. Runtime bundle synchronized. TypeScript unchanged.
- next: human acceptance of delivered compatibility patch; PA refresh commit 5c1df1c awaits PA-47 Human Review
- updated: 2026-09-24
- release evidence: source b6b6173; CI run 35536447887 success; distribution dbf2a6c; installed 0.3.1 through plugin installer. Native PA validate-config/context passed with installed skill root and docs/features. No live dispatch.
