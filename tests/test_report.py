from datetime import datetime, timezone

import pytest

from tollgate.clock import iso
from tollgate.db import Database
from tollgate.gate import TollgateService
from tollgate.report import build_report
from tollgate.tiers import Evidence, EvidenceKind, RollbackPlan, Tier

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T1 = datetime(2026, 1, 2, tzinfo=timezone.utc)


@pytest.fixture
def gate():
    return TollgateService(db=Database(), clock=lambda: T0)


def test_report_counts_allowed_and_blocked_separately(gate):
    gate.check(agent="a", action="DescribeInstances", service="ec2", tier=Tier.READ_ONLY, resources=[])
    gate.check(agent="a", action="StopInstances", service="ec2", tier=Tier.EXECUTE_WITH_APPROVAL, resources=["i-1"])
    gate.check(agent="a", action="StopInstances", service="ec2", tier=Tier.EXECUTE_WITH_APPROVAL,
              resources=["i-1"], evidence=[Evidence(EvidenceKind.METRIC_THRESHOLD, "cpu>90%"),
                                           Evidence(EvidenceKind.HUMAN_APPROVAL, "bob")],
              rollback=RollbackPlan("restart from AMI", tested=True))

    report = build_report(gate, iso(T0), iso(T1))
    assert report["totals"]["decisions"] == 3
    assert report["allowed_actions"] == 2  # the describe + the fully-satisfied stop
    assert report["blocked_actions"] == 1
    assert report["blocked_by_reason"] == {"BLOCKED_NO_EVIDENCE": 1}


def test_report_includes_named_controls_with_evidence_basis(gate):
    report = build_report(gate, iso(T0), iso(T1))
    ids = {c["id"] for c in report["controls"]}
    assert {"CHANGE-1", "CHANGE-2", "CHANGE-3", "CHANGE-4"} <= ids


def test_report_is_explicit_about_what_it_does_not_prove(gate):
    report = build_report(gate, iso(T0), iso(T1))
    assert "not a certification" in report["note"]
