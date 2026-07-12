---
status: accepted
---

# Admitted work converges from Runtime Ledger truth

After Admission, SMDA derives runnable work from the Runtime Ledger and
Workflow Graph rather than rediscovering progression from Backlog states. The
Backlog remains the ingress for new Requests and typed Control Events and the
target of eventual Backlog Projections. One Coordinator with a bounded local
worker pool provides parallelism; timer wakeups only initiate eligibility and
atomic-claim evaluation, never duplicate an active Stage.

Accepted specs are immutable Git-backed Artifacts. Retry, Control Events, and
typed Escalations are orthogonal to workflow Phase, so a human or operator
resolves a domain action instead of choosing an internal Phase. Fenced atomic
commits require active ownership and expected Request, Spec, Workflow Graph,
and Phase versions. This architecture is detailed in
[`2026-07-12-unattended-request-convergence-design.md`](../superpowers/specs/2026-07-12-unattended-request-convergence-design.md).

We rejected continued Backlog-driven progression because projection lag can
stall admitted work, and rejected a broker/event-sourced runtime because
single-host parallel agent execution does not require distributed coordination.
Remote workers or event sourcing require measured coordinator, host, SQLite,
high-availability, replay, or multi-consumer needs.

## Consequences

- Supersedes ADR-0002's requirement that Roadmap direction always be agreed
  outside the daemon; raw Roadmap Requests may pass automated spec intake.
- Retains ADR-0003 and ADR-0006 integration and bounded-policy behavior, but
  replaces generic `HUMAN_REVIEW_REQUIRED` Phase targets with typed
  Escalations.
- Extends ADR-0009 and ADR-0010 from Parent projection and transition gaps to
  all admitted workflow commits, publication intents, and stale-worker fences.
- Keeps `force-phase` only as an audited break-glass repair tool.
