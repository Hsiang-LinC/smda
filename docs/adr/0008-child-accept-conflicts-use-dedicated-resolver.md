---
status: accepted
---

# Child accept conflicts use a dedicated Parent integration resolver

When deterministic Child acceptance cannot apply a Child candidate to the
Parent integration branch, SMDA routes the Parent through a dedicated Parent
integration conflict resolver phase, `CHILD_ACCEPT_CONFLICT_RESOLVING`, instead
of generic Agent Review or immediate human review. The resolver's goal is
narrow: make `CHILDREN_PUBLISHED` child
acceptance pass for the conflicted Child. It prepares the Parent integration
branch; it does not mark accept operations completed.

The deterministic accept path remains the bookkeeping gate. After a resolver
attempt, the Parent returns to `CHILDREN_PUBLISHED` and retries the normal Child
acceptance path. If the same conflict fingerprint repeats beyond the configured
attempt cap of 2, the Parent escalates to `HUMAN_REVIEW_REQUIRED`.

The conflict fingerprint is based on the Parent id, Child id, candidate ref,
conflicted paths, and the accept failure text. The resolver may change only the
Parent integration branch, only conflict-scoped files, and only enough to make
deterministic Child acceptance pass.

Resolver control flow is binary: `DONE` with `retry_child_acceptance`, or
`BLOCKED` with `request_human_review`. Residual concerns belong in the report;
they must not create a `DONE_WITH_CONCERNS` retry path.

The resolver reuses `smda.review-result.v1` and adds only the
`retry_child_acceptance` next action. The Role Contract narrows valid resolver
outputs to `DONE` with `retry_child_acceptance`, or `BLOCKED` with
`request_human_review`.

Loop-prevention state lives with the `parent_accept_ledger` operation, not on
generic Parent state. The accept operation stores only the machine fields needed
to route safely: `conflicted_paths_json`, `conflict_fingerprint`, and
`resolver_attempts`. The resolver and human-review path must surface a compact
conflict history assembled from `parent_accept_ledger` and `attempt_ledger`:
operation id, fingerprint, attempt count, candidate ref, integration branch,
conflicted paths, last error, resolver attempt ids, resolver verdicts/actions,
and report summaries. The retry counter may stay small, but retry agents and
humans must see the trail that produced it. Report summaries are derived from
the resolver RoleAttempt rows in `attempt_ledger.result_json["report"]` when
building resolver or human-review context; they are not copied onto
`parent_accept_ledger`. `parent_accept_ledger.last_error` remains the
deterministic accept failure text.

Conflicted paths come from structured child-accept failure data at the git
integration seam. They are not parsed back out of `last_error`; stderr remains
diagnostic text, not workflow data.

The resolver report template lives in the resolver Role Contract prompt, not in
`CONTEXT.md` or a global report-template file. The shared result schema already
provides the `report` field; this role narrows its expected content to Conflict,
Resolution, Verification, and Residual risk. For `BLOCKED`, Resolution becomes
Attempted / why unsafe.

## Considered options

- **Deterministic recovery only:** rejected. It preserves a small surface but
  leaves conflicts that need code judgment in a manual stop-the-daemon path.
- **Generic Agent Review:** rejected. Agent Review is a tracker projection, not a
  workflow Stage with the Parent spec, Child criteria, candidate ref,
  integration branch, conflicted paths, and verification evidence as typed input.
- **Placeholder phase without a resolver:** rejected. In SMDA a phase is
  executable workflow data; a non-runnable phase would idle and rot.
- **Resolver marks Child accepted directly:** rejected. It would bypass the
  idempotent accept bookkeeping and split the source of truth for accepted
  candidates.

## Consequences

- A new Parent phase and Role Contract are justified because the conflict path
  needs a real workflow destination.
- The resolver runs as a Parent `RoleAttempt` Stage, not as an agent call hidden
  inside an Effect handler.
- The Parent phase is named `CHILD_ACCEPT_CONFLICT_RESOLVING` because it is
  scoped to failed Child acceptance, not general Parent integration.
- The resolver loop must be bounded by fingerprint plus attempt cap 2 to avoid
  retrying the same unresolved conflict forever.
- The resolver report carries residual risk and verification evidence, but only
  `DONE` may retry deterministic Child acceptance.
- The shared review-result schema remains the role-output contract; this slice
  does not introduce a resolver-only result schema.
- Conflict history is surfaced through the resolver RoleAttempt request and the
  human-review escalation comment/report; it is not hidden behind the retry
  counter.
- Resolver report summaries remain normalized in `attempt_ledger.result_json`;
  the accept operation ledger stores only machine retry state and
  accept-operation facts.
- Child accept conflict paths are captured as structured operation data from git
  integration, following the existing `ConflictProbeResult` pattern used by
  parent landing conflict probes.
- The resolver-specific report checklist belongs in the resolver Role Contract;
  no global report template is introduced.
- Human review remains the final escalation for public-contract changes,
  ambiguous semantic conflicts, or repeated resolver failure.
