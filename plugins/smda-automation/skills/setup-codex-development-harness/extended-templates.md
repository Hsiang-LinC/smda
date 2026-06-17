# Extended Templates

Read only when refresh mode upgrades a repo to the **extended** topology, or
when setup detects thresholds already exceeded (then propose extended at
setup). A split **moves** a section out of `index.md` and leaves a one-line
pointer in its place — it never copies.

Every generated file gets the standard header
`<!-- codex-harness: generated {DATE} -->` and `Last verified: {DATE}` line.

## `docs/architecture/index.md`

```markdown
# Architecture Index

## System Shape

{one paragraph: current architecture}

## Major Modules

### {module-name}
- owns: {responsibility}
- interface: {what callers need to know}
- depends-on: {dependencies}
- warnings: {invariants / common wrong edits, or none}

## Runtime Boundaries

### {boundary-name}
- producer: {module/process}
- consumer: {module/process}
- contract: {doc or contract path}
```

## `docs/architecture/module-map.md`

```markdown
# Module Map

### {module-name}
- owns: {responsibility}
- interface: {public seams}
- tests: {test files or commands}
- context: {related docs/ADRs}
- do-not: {outdated patterns to avoid, or none}

## Cross-Module Flows

### {flow-name}
- steps: {module A -> module B -> module C}
- source-of-truth: {doc or contract}
```

(Monorepo: section the map by package under `## {package-name}` headings —
still one file.)

## `docs/harness/decision-routing.md` (split from index.md)

```markdown
# Decision Routing

Where decisions belong. Split out of `index.md`; the index links here.

| Decision type | Write/update | Escalate to ADR when |
|---|---|---|
| Product capability | {docs/product/ if track exists, else README/specs} | it changes product direction |
| Architecture / module design | docs/architecture/ | hard to reverse or surprising |
| API / schema / contract | {docs/contracts/ if track exists} | consumers depend on it |
| Data model / persistence | {docs/data-model/ if track exists} | usually |

ADR threshold: hard to reverse + surprising without context + real trade-off.
```

## `docs/harness/context-routing.md` (split from index.md)

```markdown
# Context Routing

What to read before touching an area. Split out of `index.md`; the index links here.

### {area/module}
- read-first: {path}
- also: {path}
- notes: {source of truth, invariants, warnings}
```

## Optional track indexes

Create a track only when real material for it exists (threshold rule). Each
follows the same shape — an index of facts with residences, not prose:

`docs/product/index.md` — capability / user value / status / related docs.
`docs/contracts/index.md` — contract / producer / consumer / stability / path.
`docs/ui/index.md` — flow or view / user goal / data dependencies / related docs.
`docs/agent-system/index.md` — agent or workflow / responsibility / knowledge sources / tools / contracts.
`docs/data-model/index.md` — concept / source of truth / consumers / invariants.
`docs/ops/index.md` — runtime concern / command or location / owner / warnings.

Use section-entry format (like the architecture files above), one `###` per
row-equivalent. When a track is created, add one row to the index.md Task
Routing "Read first" column where relevant — that is the only index.md change
a track addition makes.
