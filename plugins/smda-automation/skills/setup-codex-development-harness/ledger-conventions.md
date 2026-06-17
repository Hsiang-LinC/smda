# Ledger Conventions

Rules referenced by generated harness docs. When generating, copy the
*applicable* rules into `docs/harness/index.md` `## Conventions` — generated
repos must not depend on this plugin file at runtime.

## Entry Format

Section entries, never tables. Rationale: append-only, merge-friendly, and a
missing field is visibly absent (table columns get silently dropped).

### `active.md` / `follow-ups.md` — local mode only

Remote-tracker modes do not generate these files; live state lives in the
tracker per `docs/harness/tracker.md`.

```markdown
## <kebab-slug>
- status: planned | in-progress | blocked
- source: <spec / plan / conversation ref>
- next: <single concrete next action>
- updated: YYYY-MM-DD
```

Entries intended for orchestrated dispatch additionally carry `blocked-by:`
(slugs; omit when none), `acceptance:` (observable outcomes), and `verify:`
(commands + expected outcomes) — fields defined in `tracker.md` § Work Item
Format.

### `completed.md` — archive, all modes

```markdown
## <kebab-slug>
- done: YYYY-MM-DD
- summary: <what changed>
- verified: <test command run / evidence; "backfilled from git history" or
  "backfilled from <tracker> <id>" for backfill entries>
- follow-ups: <ref into follow-ups.md (local mode) or the tracker (remote modes), or none>
```

### `abandoned.md` — archive, all modes

```markdown
## <kebab-slug>
- abandoned: YYYY-MM-DD
- why: <reason>
- resume-if: <condition that would make it viable again>
```

Remote-tracker modes: archive entries may carry the tracker work-item ID in
`verified:`/`why:` — IDs inside entries are data, not tracker identity, and
do not violate the tracker-leak gate.

## Markers

- Every generated file starts with: `<!-- codex-harness: generated YYYY-MM-DD -->`
- The bootloader block is wrapped in `<!-- codex-harness:begin -->` /
  `<!-- codex-harness:end -->`
- Refresh mode patches **only inside markers**. Content outside markers is
  user-authored and untouchable without asking.

## Staleness

- Every generated doc carries `Last verified: YYYY-MM-DD` directly under its
  title. Refresh updates it after re-verifying the file's claims.
- Refresh flags any file overdue by more than 90 days.

## Archive Policy

When `completed.md` exceeds ~200 entries or spans more than 1 year, refresh
rolls the oldest entries into `docs/work-ledger/archive/completed-YYYY.md`
(same entry format, one file per year).
