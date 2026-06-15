# Trading Advisor Extraction Inventory

Status: draft for review

This inventory records how existing work should influence the SMDA Scheduler
product. It is not a command to move code as-is.

## Source Repos

- Baseline scheduler: `/Users/danny/Desktop/GitHub/codex-symphony`
- SMDA prototype: `/Users/danny/Desktop/GitHub/trading-advisor/symphony`
- Setup skill: `/Users/danny/codex-local-marketplace/plugins/engineering/skills/setup-smda-automation`

## Extract From codex-symphony

Candidate product pieces:

- CLI shape;
- daemon loop;
- tracker factory;
- Linear adapter;
- dispatch eligibility;
- dependency gating through blockers;
- pending tracker update retry;
- janitor/retriage concepts;
- review/accept/reconcile primitives;
- workspace and verification helpers where still needed after Sandcastle
  boundary review.

These are scheduling/backlog primitives.

## Extract From trading-advisor SMDA Prototype

Candidate product pieces:

- execution mode classification;
- parent intake and spec approval concepts;
- graph model and graph invariant checks;
- child node and parent run phase enums;
- child phase transition semantics;
- graph review flow;
- child publication semantics;
- candidate capture and child accept semantics;
- parent verification and parent accept semantics;
- QA feedback/remediation loop;
- pause/status/validate control surfaces.

These are workflow-engine concepts.

## Replace With Sandcastle Adapter

Do not preserve as SMDA core:

- hand-written `<output>` parsing;
- YAML/JSON fallback parsing for role result text;
- jsonschema runtime validation pipeline for role attempts;
- generic format-repair prompt loop;
- attempt/workspace/session mechanics that Sandcastle already captures;
- branch/worktree lifecycle when Sandcastle owns the attempt.

Keep only the result shape and transition semantics.

## Revise Setup Skill

The setup skill should move from "vendor SMDA runtime artifacts into this repo"
to "wire this repo to the SMDA Scheduler product."

Allowed setup outputs:

- runtime config;
- prompt/report templates when local customization is requested;
- adapter setup notes;
- harness/bootloader routing;
- validation commands;
- legacy blocker report.

Avoid long-term vendoring of scheduler/runtime code into consumer repos.
