<!-- codex-harness: generated 2026-06-17 -->
# Follow-ups

Known debt and opportunities. Entry format: see `docs/harness/index.md` § Conventions.

## auto-follow-up-issue-for-concerns
- status: planned
- source: `docs/known-gaps.md` "Future idea: auto follow-up issue for deferred concerns"
- next: design a config-gated path where a `DONE_WITH_CONCERNS` verdict opens a
  low-priority follow-up child/backlog issue carrying the concern report
  (reuses child-publication + tracker-effect machinery).
- updated: 2026-06-17

## difficulty-aware-model-selection
- status: planned
- source: `docs/known-gaps.md` "Future idea: difficulty-aware model selection"
- next: resolve `AgentSelection` per attempt from a config-driven
  role/difficulty → model map instead of one fixed value threaded through the tick.
- updated: 2026-06-17

## force-phase-operator-command
- status: planned
- source: `docs/known-gaps.md` § Operator / manual intervention model (thin spot)
- next: add an `advance` / `force-phase` operator CLI to clear a
  `HUMAN_REVIEW_REQUIRED` parking state without editing tracker inputs by hand.
- updated: 2026-06-17

## linear-scope-id-ignored
- status: planned
- source: 2026-06-17 multi-repo isolation review.
- problem: `BacklogAdapterConfig.scope_id` (the Linear project, e.g.
  `trading-advisor-41f010901151`) is parsed from config but never reaches the
  live query. `LinearBacklogAdapter.list_issues` filters only by
  `team + state + label` (+ optional parent), and `build_linear_backlog_adapter`
  reads only `SMDA_LINEAR_TEAM_ID` from env. Two repos sharing a team + the
  `agent` label + `Todo` therefore scan the same issue set and would dispatch
  each other's work — project scope gives no isolation.
- next: spec drafted —
  `docs/superpowers/specs/2026-06-17-linear-project-scope-isolation.md` (status:
  draft, awaiting human approval before SPEC_FINALIZED). Approach: thread a
  `SMDA_LINEAR_PROJECT_ID` env id into both the `list_issues` project filter and
  `create_issue` projectId stamp (both halves required). Until landed, isolate
  multiple repos by separate Linear team.
- updated: 2026-06-17

## mcp-operator-interface
- status: deferred (do not build by default)
- source: 2026-06-17 design discussion; surfacing decision recorded in
  `plugins/smda-automation/skills/setup-smda-automation/daemon-operations.md` § 4.
- rationale: the documented shell-command surface (operator CLI run via Bash) is
  the default and is cheaper on context — it is pay-per-use (the agent reads the
  harness doc only when it routes to the task), whereas MCP tool definitions/names
  sit in the tool list every turn. The operator commands also take simple args
  (config + `--repo-root`, occasional `--parent`) and already return compact JSON,
  so a typed MCP schema adds little. Keep the CLI surface as the answer.
- triggers (only pursue MCP if one holds): (1) high-frequency model-driven
  control where re-reading the doc each time costs more than a resident schema;
  (2) a non-harness runtime that must discover the tools without harness routing.
- next (if triggered): expose the operator CLI (`status`, `pause`, `resume`,
  `reconcile-claims`, plus `force-phase` once it exists) as a product-owned MCP
  server entrypoint (e.g. `smda-scheduler mcp`, stdio); target repos consume it
  via a `.mcp.json` pointer written by setup. The setup skill must NOT generate
  the server itself (Tier-3 boundary, Hard Gate 7). Gate mutating tools
  (`pause`/`resume`) behind approval; never expose the autonomous `daemon` as a
  tool. Pairs with `force-phase-operator-command`.
- updated: 2026-06-17
