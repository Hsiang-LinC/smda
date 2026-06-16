---
status: accepted
---

# Zod is the canonical schema source; Python consumes generated JSON Schema

Role output schemas are authored once as Zod in `roleContracts.ts` (execution
owns output validation via Sandcastle `Output.object`). A build step exports a
JSON Schema artifact, checked into the repo, which the Python scheduler loads for
the only cross-language surface it needs: the shared verdict / next-action /
edge-type / risk vocab and the decomposer output shape it parses into the ledger
graph. A contract test asserts the checked-in artifact equals the current Zod
export, so regeneration is enforced and drift is structurally impossible. This
overturns the prior MVP allowance for a hand-duplicated Python registry: as the
role set grows (roadmap_decomposer, task, review), hand-sync becomes a real
hazard, and target-C's modular role engine multiplies the surface.

We rejected a parity-only contract test (keeps two hand-written sources; catches
drift after the fact) and a neutral JSON-Schema source (loses Zod authoring
ergonomics, adds runtime json→zod conversion on the `Output.object` path).

## Consequences

- Python `role_contracts.py` keeps its orchestration-only metadata (persona, task
  template, methodology-skill bindings, role→phase) — that is *not* duplicated in
  TS and stays Python-owned. Only the output *shapes/vocab* are generated.
- Adds a `zod-to-json-schema` build step + a generated `schemas/*.json` artifact
  to source control + a parity test in CI.
