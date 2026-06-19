---
status: accepted
---

# Attempt Result Artifact is the execution adapter control boundary

Execution adapters return one durable **Attempt Result Artifact** per role
attempt, and the scheduler advances workflow state only from that artifact.
Process stdout/stderr are **Process Logs**: evidence for diagnosis, never a
workflow-control channel. Sandcastle is the first implementation of this
adapter-wide contract and writes the artifact atomically to a scheduler-provided
`--result-file` path under the configured artifact root.

## Considered options

- **Parse stdout/stderr for JSON:** rejected. DANNY-70 showed that package
  warnings, runtime warnings, model/tooling messages, and stack traces can all
  contaminate process streams before the machine payload.
- **Dedicated file descriptor:** viable but more complex across the Python
  scheduler, Node runner, and tests. A result file gives the same separation with
  simpler process plumbing and durable evidence.
- **LLM-authored attempt envelope:** rejected. The model may author the typed
  role payload, but runner/adapter code owns the attempt envelope, failure
  status, schema metadata, branch/commit evidence, and protocol errors.

## Consequences

- Missing or invalid artifacts are adapter contract violations, not role output
  failures.
- If a process exits nonzero but writes a valid artifact, the artifact is the
  source of truth; the process status and logs remain evidence.
- No production legacy fallback parses stdout/stderr for workflow control after
  the migration.
