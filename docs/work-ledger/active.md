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
