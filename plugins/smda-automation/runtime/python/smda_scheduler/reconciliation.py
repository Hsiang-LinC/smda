from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from smda_scheduler.phase_ledger import PhaseLedger


class TrackerEffectSender(Protocol):
    def comment(self, issue_id: str, body: str) -> None: ...

    def set_coarse_state(self, issue_id: str, state: str) -> None: ...

    def create_child(
        self,
        *,
        parent_id: str,
        title: str,
        body: str,
        labels: set[str] | frozenset[str] | None = None,
    ) -> object: ...


@dataclass(frozen=True)
class ReconciliationResult:
    sent_effect_ids: tuple[str, ...]
    failed_effect_ids: tuple[str, ...]


def retry_pending_tracker_effects(
    ledger: PhaseLedger,
    tracker: TrackerEffectSender,
) -> ReconciliationResult:
    sent: list[str] = []
    failed: list[str] = []

    for effect in ledger.load_pending_tracker_effects():
        effect_id = effect["effect_id"]
        try:
            _send_effect(tracker, effect)
        except Exception as error:
            ledger.mark_tracker_effect_failed(effect_id, str(error))
            failed.append(effect_id)
            continue

        ledger.mark_tracker_effect_sent(effect_id)
        sent.append(effect_id)

    return ReconciliationResult(
        sent_effect_ids=tuple(sent),
        failed_effect_ids=tuple(failed),
    )


def _send_effect(tracker: TrackerEffectSender, effect: dict) -> None:
    effect_type = effect["effect_type"]
    target_id = effect["target_id"]
    payload = effect["payload"]
    if effect_type == "comment":
        tracker.comment(target_id, str(payload["body"]))
        return
    if effect_type == "set_state":
        tracker.set_coarse_state(target_id, str(payload["state"]))
        return
    if effect_type == "create_child":
        labels = payload.get("labels", [])
        tracker.create_child(
            parent_id=str(payload.get("parent_id", target_id)),
            title=str(payload["title"]),
            body=str(payload["body"]),
            labels={str(label) for label in labels},
        )
        return
    raise ValueError(f"Unsupported tracker effect type: {effect_type}")
