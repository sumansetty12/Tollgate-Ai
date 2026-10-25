"""Autonomy tiers and evidence types - the core vocabulary Tollgate AI gates on.

v1 implements three tiers. A fourth ("autonomous within a pre-declared blast radius,
no per-action approval") is documented in the design but deliberately NOT implemented
here - it needs a safe way to check invariants across multi-step rollouts, which is an
open research problem (see the project README), not something to fake with a shortcut.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class Tier(IntEnum):
    READ_ONLY = 0        # describe/list/get calls only
    PROPOSE = 1          # may draft a change; may not execute it
    EXECUTE_WITH_APPROVAL = 2  # may execute, but only with evidence + a human approval token


class EvidenceKind(IntEnum):
    LOG_CITATION = 1      # a specific, quotable log line or query result
    METRIC_THRESHOLD = 2  # a named metric crossing a named threshold
    RUNBOOK_MATCH = 3     # a matched, identified runbook entry
    HUMAN_APPROVAL = 4    # a human's explicit approval token


DIAGNOSTIC_KINDS = {EvidenceKind.LOG_CITATION, EvidenceKind.METRIC_THRESHOLD, EvidenceKind.RUNBOOK_MATCH}


@dataclass(frozen=True)
class Evidence:
    """One piece of named, checkable evidence. `reference` must point at something a
    human could go look up - a log query id, a metric name, a runbook id - never a
    free-text justification standing in for the real thing."""
    kind: EvidenceKind
    reference: str
    note: str = ""

    def __post_init__(self):
        if not self.reference.strip():
            raise ValueError(f"{self.kind.name} evidence needs a real reference, not an empty string")


@dataclass(frozen=True)
class RollbackPlan:
    description: str
    tested: bool

    def __post_init__(self):
        if not self.description.strip():
            raise ValueError("a rollback plan needs a real description")


@dataclass(frozen=True)
class TierRequirements:
    """What a given tier demands before a mutating action is allowed through."""
    needs_diagnostic_evidence: bool
    needs_rollback_plan: bool
    needs_rollback_tested: bool
    needs_human_approval: bool
    max_resources: int | None  # blast-radius cap; None = tier doesn't permit mutation at all


REQUIREMENTS: dict[Tier, TierRequirements] = {
    Tier.READ_ONLY: TierRequirements(False, False, False, False, max_resources=None),
    # PROPOSE's max_resources=None means: like READ_ONLY, it can never execute a
    # mutating action through `TollgateService.check` - that call always resolves to
    # BLOCKED_TIER before evidence is even considered. needs_diagnostic_evidence=True
    # here is NOT dead weight; it documents the requirement for a separate, not-yet-
    # implemented `propose()` draft-submission flow (recording what evidence backs a
    # DRAFT, before any execution is even requested). Gating that draft step is real
    # scope left for a later milestone, not something this v1 fakes by reusing `check`.
    Tier.PROPOSE: TierRequirements(True, False, False, False, max_resources=None),
    Tier.EXECUTE_WITH_APPROVAL: TierRequirements(True, True, True, True, max_resources=5),
}


def is_read_only_action(action: str) -> bool:
    """AWS's own naming convention: Describe*/List*/Get* never mutate state.
    Everything else is treated as mutating unless explicitly told otherwise."""
    return action.startswith(("Describe", "List", "Get"))
