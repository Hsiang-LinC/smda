from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParentDependencyGateResult:
    eligible: bool
    blocked_by: tuple[str, ...] = ()
    reason: str = ""


def parent_dependency_gate(
    *,
    parent_id: str,
    blockers: tuple[str, ...],
    final_accepted_parent_ids: frozenset[str],
) -> ParentDependencyGateResult:
    """Gate a parent's dispatch on its upstream roadmap blockers.

    Mirror of child_dependency_gate at the parent tier: a parent is eligible
    only once every blocking upstream parent is FINAL_ACCEPTED. Pure function —
    the workspace tick supplies the blockers and the accepted set.
    """
    waiting = tuple(b for b in blockers if b not in final_accepted_parent_ids)
    if not waiting:
        return ParentDependencyGateResult(eligible=True)
    return ParentDependencyGateResult(
        eligible=False,
        blocked_by=waiting,
        reason=(
            "Waiting for upstream parents to be FINAL_ACCEPTED: "
            + ", ".join(waiting)
        ),
    )
