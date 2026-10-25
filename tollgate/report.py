"""A compliance-style report over the decision log - same spirit as Plumbline's SOC 2
report: summarize what was recorded, map it to a named control, and say plainly what
the report does and doesn't prove."""
from __future__ import annotations

from collections import Counter

from .clock import parse
from .gate import TollgateService

CONTROLS = [
    ("CHANGE-1", "No unreviewed production change executes without evidence",
     "Every ALLOWED mutating action had at least one diagnostic evidence item attached."),
    ("CHANGE-2", "No production change executes without a tested rollback path",
     "Every ALLOWED mutating action at a tier requiring rollback had a rollback plan marked tested."),
    ("CHANGE-3", "No change bypasses human approval at the tier that requires it",
     "Every ALLOWED mutating action at a tier requiring human approval had a HUMAN_APPROVAL evidence item."),
    ("CHANGE-4", "Blast radius is bounded",
     "No ALLOWED action touched more resources than its tier's declared cap."),
]


def build_report(gate: TollgateService, start: str, end: str) -> dict:
    s, e = parse(start), parse(end)
    decisions = [d for d in gate.decisions() if s <= parse(d["created_at"]) <= e]
    by_outcome = Counter(d["outcome"] for d in decisions)
    allowed = [d for d in decisions if d["outcome"] == "ALLOWED"]
    blocked = [d for d in decisions if d["outcome"].startswith("BLOCKED")]

    return {
        "period": {"start": start, "end": end},
        "totals": {"decisions": len(decisions), **by_outcome},
        "allowed_actions": len(allowed),
        "blocked_actions": len(blocked),
        "pending_approval": by_outcome.get("PENDING_APPROVAL", 0),
        "blocked_by_reason": dict(Counter(d["outcome"] for d in blocked)),
        "controls": [
            {"id": cid, "statement": stmt, "evidence_basis": basis}
            for cid, stmt, basis in CONTROLS
        ],
        "note": ("This report summarizes what Tollgate AI recorded for agent-initiated actions "
                 "during this period. It is evidence of what the gate enforced, not a certification "
                 "that every agent action in this window was safe or correct - only that the ones "
                 "marked ALLOWED cleared the stated requirements for their tier."),
    }
