from __future__ import annotations

from dataclasses import dataclass


class CapabilityError(ValueError):
    """Raised when an adapter cannot satisfy workflow requirements."""


@dataclass(frozen=True)
class AdapterDescriptor:
    id: str
    version: str
    capabilities: frozenset[str]


@dataclass(frozen=True)
class WorkflowRequirements:
    required: frozenset[str]
    optional_fallbacks: dict[str, str]


@dataclass(frozen=True)
class NegotiationResult:
    adapter: AdapterDescriptor
    enabled_capabilities: frozenset[str]
    fallbacks: dict[str, str]


def negotiate_capabilities(
    adapter: AdapterDescriptor,
    requirements: WorkflowRequirements,
) -> NegotiationResult:
    missing_required = requirements.required - adapter.capabilities
    if missing_required:
        missing = ", ".join(sorted(missing_required))
        raise CapabilityError(
            f"Adapter {adapter.id} is missing required capabilities: {missing}"
        )

    enabled_optional = (
        frozenset(requirements.optional_fallbacks.keys()) & adapter.capabilities
    )
    missing_optional = {
        capability: fallback
        for capability, fallback in requirements.optional_fallbacks.items()
        if capability not in adapter.capabilities
    }

    return NegotiationResult(
        adapter=adapter,
        enabled_capabilities=requirements.required | enabled_optional,
        fallbacks=missing_optional,
    )
