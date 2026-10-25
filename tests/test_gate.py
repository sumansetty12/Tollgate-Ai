"""Tests for the core gate: tier enforcement, evidence requirements, rollback checks,
blast-radius caps, and the end-to-end AWS wrapper - all against the fake client, no
real AWS account needed."""
from datetime import datetime, timezone

import pytest

from tollgate.db import Database
from tollgate.gate import GateError, TollgateService
from tollgate.gateway_aws import FakeAWSClient, GateBlocked, GatedAWSClient
from tollgate.tiers import Evidence, EvidenceKind, RollbackPlan, Tier

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def gate():
    return TollgateService(db=Database(), clock=lambda: T0)


@pytest.fixture
def aws():
    return FakeAWSClient()


def diag(ref="cloudwatch:cpu>90%"):
    return Evidence(EvidenceKind.METRIC_THRESHOLD, ref)


def approval(ref="approver:bob"):
    return Evidence(EvidenceKind.HUMAN_APPROVAL, ref)


def rollback(tested=True):
    return RollbackPlan("restart the instance from the last known-good AMI", tested=tested)


# ---------- read-only always passes ----------

def test_read_only_action_needs_no_evidence_at_any_tier(gate):
    d = gate.check(agent="agent-1", action="DescribeInstances", service="ec2",
                   tier=Tier.READ_ONLY, resources=[])
    assert d["outcome"] == "ALLOWED"


# ---------- tier 0 blocks all mutation ----------

def test_tier_read_only_blocks_mutating_action_even_with_everything_attached(gate):
    d = gate.check(agent="agent-1", action="StopInstances", service="ec2", tier=Tier.READ_ONLY,
                   resources=["i-1"], evidence=[diag(), approval()], rollback=rollback())
    assert d["outcome"] == "BLOCKED_TIER"


# ---------- tier 1 (propose) ----------

def test_tier_propose_cannot_execute_a_mutating_action_even_with_everything_attached(gate):
    # PROPOSE can draft, never execute - same BLOCKED_TIER as READ_ONLY, checked before
    # evidence, because no amount of evidence changes what this tier is allowed to DO.
    d = gate.check(agent="agent-1", action="StopInstances", service="ec2", tier=Tier.PROPOSE,
                   resources=["i-1"], evidence=[diag(), approval()], rollback=rollback())
    assert d["outcome"] == "BLOCKED_TIER"


def test_tier_propose_max_resources_is_none_by_design():
    from tollgate.tiers import REQUIREMENTS
    assert REQUIREMENTS[Tier.PROPOSE].max_resources is None


# ---------- tier 2 (execute with approval) ----------

def test_tier_execute_blocks_without_evidence(gate):
    d = gate.check(agent="agent-1", action="StopInstances", service="ec2",
                   tier=Tier.EXECUTE_WITH_APPROVAL, resources=["i-1"])
    assert d["outcome"] == "BLOCKED_NO_EVIDENCE"


def test_tier_execute_blocks_without_rollback_plan(gate):
    d = gate.check(agent="agent-1", action="StopInstances", service="ec2",
                   tier=Tier.EXECUTE_WITH_APPROVAL, resources=["i-1"], evidence=[diag()])
    assert d["outcome"] == "BLOCKED_NO_ROLLBACK"


def test_tier_execute_blocks_untested_rollback(gate):
    d = gate.check(agent="agent-1", action="StopInstances", service="ec2",
                   tier=Tier.EXECUTE_WITH_APPROVAL, resources=["i-1"], evidence=[diag()],
                   rollback=rollback(tested=False))
    assert d["outcome"] == "BLOCKED_ROLLBACK_UNTESTED"


def test_tier_execute_pends_approval_once_evidence_and_rollback_are_in_order(gate):
    d = gate.check(agent="agent-1", action="StopInstances", service="ec2",
                   tier=Tier.EXECUTE_WITH_APPROVAL, resources=["i-1"], evidence=[diag()],
                   rollback=rollback())
    assert d["outcome"] == "PENDING_APPROVAL"


def test_tier_execute_blocks_blast_radius_even_with_approval(gate):
    many = [f"i-{n}" for n in range(10)]
    d = gate.check(agent="agent-1", action="StopInstances", service="ec2",
                   tier=Tier.EXECUTE_WITH_APPROVAL, resources=many,
                   evidence=[diag(), approval()], rollback=rollback())
    assert d["outcome"] == "BLOCKED_BLAST_RADIUS"


def test_tier_execute_allows_when_everything_is_satisfied(gate):
    d = gate.check(agent="agent-1", action="StopInstances", service="ec2",
                   tier=Tier.EXECUTE_WITH_APPROVAL, resources=["i-1"],
                   evidence=[diag(), approval()], rollback=rollback())
    assert d["outcome"] == "ALLOWED"


def test_unknown_tier_raises(gate):
    with pytest.raises(GateError):
        gate.check(agent="a", action="StopInstances", service="ec2", tier=99, resources=[])


# ---------- evidence must point at something real ----------

def test_evidence_with_empty_reference_is_rejected():
    with pytest.raises(ValueError):
        Evidence(EvidenceKind.METRIC_THRESHOLD, "   ")


# ---------- every decision is recorded, blocked or not ----------

def test_blocked_decisions_are_still_recorded_in_full(gate):
    gate.check(agent="agent-1", action="StopInstances", service="ec2",
              tier=Tier.EXECUTE_WITH_APPROVAL, resources=["i-1"])
    decs = gate.decisions()
    assert len(decs) == 1 and decs[0]["outcome"] == "BLOCKED_NO_EVIDENCE"


def test_decisions_can_be_filtered_by_outcome(gate):
    gate.check(agent="a", action="DescribeInstances", service="ec2", tier=Tier.READ_ONLY, resources=[])
    gate.check(agent="a", action="StopInstances", service="ec2",
              tier=Tier.EXECUTE_WITH_APPROVAL, resources=["i-1"])
    assert len(gate.decisions(outcome="ALLOWED")) == 1
    assert len(gate.decisions(outcome="BLOCKED_NO_EVIDENCE")) == 1


# ---------- end-to-end through the AWS wrapper ----------

def test_wrapper_blocks_and_never_calls_the_real_client(gate, aws):
    aws.instances["i-1"] = "running"
    wrapped = GatedAWSClient(aws, "ec2", gate)
    decision, resp = wrapped.call(agent="agent-1", tier=Tier.EXECUTE_WITH_APPROVAL, action="StopInstances",
                                   params={"InstanceIds": ["i-1"]}, resources=["i-1"])
    assert decision["outcome"] == "BLOCKED_NO_EVIDENCE"
    assert resp is None
    assert aws.instances["i-1"] == "running"  # untouched
    assert aws.calls == []  # the fake client was never actually invoked


def test_wrapper_allows_and_actually_calls_the_client_when_satisfied(gate, aws):
    aws.instances["i-1"] = "running"
    wrapped = GatedAWSClient(aws, "ec2", gate)
    decision, resp = wrapped.call(agent="agent-1", tier=Tier.EXECUTE_WITH_APPROVAL, action="StopInstances",
                                   params={"InstanceIds": ["i-1"]}, resources=["i-1"],
                                   evidence=[diag(), approval()], rollback=rollback())
    assert decision["outcome"] == "ALLOWED"
    assert aws.instances["i-1"] == "stopped"
    assert aws.calls == [("stop_instances", {"InstanceIds": ["i-1"]})]


def test_wrapper_raises_gate_blocked_helper_can_be_used_by_callers(gate, aws):
    wrapped = GatedAWSClient(aws, "ec2", gate)
    decision, resp = wrapped.call(agent="agent-1", tier=Tier.READ_ONLY, action="StopInstances",
                                   params={"InstanceIds": ["i-1"]}, resources=["i-1"])
    assert decision["outcome"] == "BLOCKED_TIER"
    exc = GateBlocked(decision)
    assert "BLOCKED_TIER" in str(exc)


def test_read_only_call_through_wrapper_passes_straight_through(gate, aws):
    aws.instances["i-1"] = "running"
    wrapped = GatedAWSClient(aws, "ec2", gate)
    decision, resp = wrapped.call(agent="agent-1", tier=Tier.READ_ONLY, action="DescribeInstances")
    assert decision["outcome"] == "ALLOWED"
    assert resp["Reservations"][0]["Instances"][0]["InstanceId"] == "i-1"
