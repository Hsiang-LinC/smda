---
status: accepted
---

# Backlog Projection uses a transactional outbox

A workflow transition and every required Backlog Projection effect it produces
must commit in the same Runtime Ledger transaction. Delivery happens afterward
through the configured Backlog Adapter with at-least-once retry and stable
idempotency. This prevents a crash after workflow state advances from silently
losing the corresponding projection.

## Considered options

- **Record effects after the transition:** rejected because the two commits
  leave a crash window with durable workflow state but no pending projection.
- **Call the Backlog Adapter before committing:** rejected because an external
  side effect cannot participate in the SQLite transaction and may succeed when
  the local commit fails.
- **Use a distributed transaction:** rejected because the shipped Backlog
  Adapters do not provide a compatible transaction protocol, and idempotent
  eventual delivery already supplies the required recovery semantics.

## Consequences

- The Runtime Ledger owns atomic enqueue; the Backlog Projection Module owns
  semantic effect encoding, pairing, and idempotency keys.
- Reconciliation owns delivery and retry through the Backlog Adapter. A Backlog
  may temporarily lag the Runtime Ledger without becoming workflow truth.
- Delivery is at least once, not exactly once; Adapters must honor stable
  idempotency.
- Current transition paths that record tracker effects in separate transactions
  do not yet satisfy this decision and remain a product gap until migrated.
