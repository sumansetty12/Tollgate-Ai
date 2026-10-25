"""The gate itself: checks one proposed action against a tier and a set of evidence,
and records the decision - allowed or blocked, and exactly why - with the evidence
that backed it. No finding or decision is ever recorded without the evidence that
justifies it, same rule Plumbline's evidence store enforces."""
from __future__ import annotations

import hashlib
import json
import secrets

from .clock import iso, utcnow
from .db import Database
from .tiers import REQUIREMENTS, DIAGNOSTIC_KINDS, Evidence, EvidenceKind, RollbackPlan, Tier, is_read_only_action


class GateError(Exception):
    pass


class TollgateService:
    def __init__(self, db: Database | None = None, clock=utcnow):
        self.db = db or Database()
        self.clock = clock

    # ---------- evidence ----------
    def _store_evidence(self, ev: Evidence) -> str:
        eid = "ev_" + hashlib.sha1(f"{ev.kind}|{ev.reference}".encode()).hexdigest()[:12]
        self.db.execute(
            "INSERT OR IGNORE INTO evidence (id, kind, detail_json, created_at) VALUES (?,?,?,?)",
            (eid, ev.kind.name, json.dumps({"reference": ev.reference, "note": ev.note}), iso(self.clock())),
        )
        return eid

    # ---------- the actual gate ----------
    def check(self, *, agent: str, action: str, service: str, tier: Tier,
              resources: list[str], evidence: list[Evidence] | None = None,
              rollback: RollbackPlan | None = None) -> dict:
        """Returns a decision dict and always records it, whatever the outcome.
        Raises GateError only on malformed input (unknown tier), never on a
        legitimate block - a block is a successful, correct answer, not a failure."""
        evidence = evidence or []
        if tier not in REQUIREMENTS:
            raise GateError(f"unknown tier {tier!r}")
        req = REQUIREMENTS[tier]

        if is_read_only_action(action):
            return self._record(agent, action, service, tier, "ALLOWED",
                                "read-only action; no gate applies", evidence, resources)

        if req.max_resources is None:
            return self._record(agent, action, service, tier, "BLOCKED_TIER",
                                f"tier {tier.name} does not permit any mutating action", evidence, resources)

        diag = [e for e in evidence if e.kind in DIAGNOSTIC_KINDS]
        if req.needs_diagnostic_evidence and not diag:
            return self._record(agent, action, service, tier, "BLOCKED_NO_EVIDENCE",
                                "no diagnostic evidence (log citation, metric threshold, or runbook match) attached",
                                evidence, resources)

        if req.needs_rollback_plan and rollback is None:
            return self._record(agent, action, service, tier, "BLOCKED_NO_ROLLBACK",
                                "this tier requires a rollback plan before a mutating action can run",
                                evidence, resources)
        if req.needs_rollback_tested and rollback is not None and not rollback.tested:
            return self._record(agent, action, service, tier, "BLOCKED_ROLLBACK_UNTESTED",
                                "a rollback plan was attached but has not been tested", evidence, resources)

        approvals = [e for e in evidence if e.kind == EvidenceKind.HUMAN_APPROVAL]
        if req.needs_human_approval and not approvals:
            return self._record(agent, action, service, tier, "PENDING_APPROVAL",
                                "diagnostic evidence and rollback plan are in order; waiting on human approval",
                                evidence, resources)

        if len(resources) > req.max_resources:
            return self._record(agent, action, service, tier, "BLOCKED_BLAST_RADIUS",
                                f"action touches {len(resources)} resources, over this tier's cap of {req.max_resources}",
                                evidence, resources)

        return self._record(agent, action, service, tier, "ALLOWED",
                            "evidence, rollback, and approval all satisfied", evidence, resources)

    def _record(self, agent, action, service, tier, outcome, reason, evidence, resources) -> dict:
        now = iso(self.clock())
        eids = [self._store_evidence(e) for e in evidence]
        did = "dec_" + secrets.token_hex(5)
        self.db.execute(
            "INSERT INTO decisions (id, agent, action, service, tier, outcome, reason, evidence_ids,"
            " detail_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (did, agent, action, service, int(tier), outcome, reason, json.dumps(eids),
             json.dumps({"resources": resources}), now),
        )
        return {"id": did, "agent": agent, "action": action, "service": service, "tier": int(tier),
                "outcome": outcome, "reason": reason, "evidence_ids": eids, "resources": resources,
                "created_at": now}

    def decisions(self, outcome: str | None = None) -> list[dict]:
        rows = (self.db.query("SELECT * FROM decisions WHERE outcome=? ORDER BY created_at", (outcome,))
                if outcome else self.db.query("SELECT * FROM decisions ORDER BY created_at"))
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(r) -> dict:
        return {"id": r["id"], "agent": r["agent"], "action": r["action"], "service": r["service"],
                "tier": r["tier"], "outcome": r["outcome"], "reason": r["reason"],
                "evidence_ids": json.loads(r["evidence_ids"]), "detail": json.loads(r["detail_json"]),
                "created_at": r["created_at"]}
