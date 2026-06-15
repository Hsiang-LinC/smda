"""Live Linear backlog smoke test.

Exercises the real Linear GraphQL API through ``build_linear_backlog_adapter``
and the stdlib HTTP transport: scan -> create child -> comment -> set state.

This test MUTATES a real Linear workspace (creates an issue, posts a comment,
moves a state). It is skipped unless explicitly opted in, so it never runs in
the normal gate or CI without live credentials.

Enable by exporting, against a scratch Linear team:

    SMDA_SMOKE_LIVE_LINEAR=1
    LINEAR_API_KEY=<personal api key>
    SMDA_LINEAR_TEAM_ID=<team uuid>
    SMDA_LINEAR_STATE_TODO=<workflow state uuid>      # plus any others
    SMDA_SMOKE_LINEAR_PARENT_ID=<existing parent issue id>
    SMDA_SMOKE_LINEAR_STATE=Todo                      # optional, default Todo
    SMDA_SMOKE_LINEAR_LABEL=agent                     # optional, default agent

Then run:

    SMDA_SMOKE_LIVE_LINEAR=1 uv run pytest \
        packages/scheduler/tests/test_linear_live_smoke.py -q -s
"""

from __future__ import annotations

import os
import uuid

import pytest

from smda_scheduler.linear_backlog import build_linear_backlog_adapter

REQUIRED_ENV = (
    "LINEAR_API_KEY",
    "SMDA_LINEAR_TEAM_ID",
    "SMDA_SMOKE_LINEAR_PARENT_ID",
)


def _skip_reason() -> str | None:
    if os.environ.get("SMDA_SMOKE_LIVE_LINEAR") != "1":
        return "set SMDA_SMOKE_LIVE_LINEAR=1 to run the live Linear smoke test"
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if not any(key.startswith("SMDA_LINEAR_STATE_") for key in os.environ):
        missing.append("SMDA_LINEAR_STATE_<NAME>")
    if missing:
        return f"missing required env for live Linear smoke: {', '.join(missing)}"
    return None


@pytest.mark.skipif(_skip_reason() is not None, reason=_skip_reason() or "")
def test_linear_live_smoke_scan_create_comment_state() -> None:
    adapter = build_linear_backlog_adapter(env=dict(os.environ))
    parent_id = os.environ["SMDA_SMOKE_LINEAR_PARENT_ID"]
    scan_state = os.environ.get("SMDA_SMOKE_LINEAR_STATE", "Todo")
    scan_label = os.environ.get("SMDA_SMOKE_LINEAR_LABEL", "agent")

    # 1. Scan (read-only): proves filter + Relay paging map against live data.
    page = adapter.list_issues(
        state=scan_state, label=scan_label, parent_id=None, limit=5
    )
    assert page.issues is not None  # tuple, possibly empty

    # 2. Create child under a real parent.
    marker = uuid.uuid4().hex[:8]
    child = adapter.create_child(
        parent_id=parent_id,
        title=f"[smda-smoke] live child {marker}",
        body=(
            "Created by SMDA live Linear smoke test. Safe to delete.\n\n"
            f"marker: {marker}"
        ),
    )
    assert child.id
    assert child.parent_id is not None

    # 3. Comment on the new child.
    adapter.comment(child.id, f"smda-smoke comment {marker}")

    # 4. Move the child to a known coarse state.
    adapter.set_coarse_state(child.id, scan_state)

    # 5. Read it back and confirm hierarchy projection sees it.
    children = adapter.project_hierarchy(parent_id)
    assert child.id in children

    print(f"\nlive Linear smoke ok: created child {child.id} (marker {marker})")
