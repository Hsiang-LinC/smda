<!-- codex-harness: generated 2026-06-17 -->
# Active Work

Entry format: see `docs/harness/index.md` § Conventions.

## document-plugin-packaged-refresh
- status: blocked
- parent: live-integration-validation
- source: conversation 2026-06-29 after plugin-app packaging closeout
- blocked-by: none
- acceptance: README and setup skill explain the Codex plugin packaged shape,
  when existing repos need an SMDA refresh, and that refresh updates Tier-3
  config/pointers rather than installing runtime or generic harness code.
- verify: `git diff --check` -> passed;
  `UV_CACHE_DIR=/private/tmp/smda-uv-cache uv run pytest
  packages/scheduler/tests/test_packaging.py::test_setup_smda_requires_external_harness_and_documents_routing
  packages/scheduler/tests/test_packaging.py::test_setup_smda_docs_describe_product_owned_mcp_surface
  packages/scheduler/tests/test_packaging.py::test_setup_smda_docs_surface_backlog_adapter_choice
  -q` -> 3 passed.
- next: human review; on `reviewed`, archive to completed work.
- updated: 2026-06-29
