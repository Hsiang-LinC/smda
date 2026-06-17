<!-- codex-harness: generated 2026-06-17 -->
# Abandoned Work

Archive — paths tried and dropped, each with a resume condition. Entry
format: see `docs/harness/index.md` § Conventions.

## dual-track-consumer-fallback
- abandoned: 2026-06-15
- why: the user dropped the planned dual-track (repo-local orchestrator +
  product) fallback in favour of a product-only consumer migration; the whole
  repo-local `symphony/` package and `smda_*` prototypes were deleted
  (see `docs/known-gaps.md` § 5).
- resume-if: a consumer repo needs repo-local orchestration when the external
  `smda-scheduler` product is unavailable.
