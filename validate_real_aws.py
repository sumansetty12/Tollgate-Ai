#!/usr/bin/env python3
"""Validates Tollgate AI against a REAL AWS account. Run this on your own machine with
your own AWS credentials already configured (AWS CLI profile or env vars) - never paste
credentials into a chat or commit them anywhere.

What this does, safely:
  1. A read-only DescribeInstances call - always allowed, proves the wrapper passes
     read-only calls straight through to real boto3.
  2. An attempted StopInstances with NO evidence attached - this should be BLOCKED, and
     the script then verifies via a real DescribeInstances call that the instance's
     state did NOT change (proving a block really means boto3 was never called).
  3. A fully-satisfied StopInstances (evidence + rollback + approval attached) on the
     SAME instance - this should be ALLOWED, and the script verifies via a real
     DescribeInstances call that the instance actually did stop.
  4. Starts the instance back up at the end, so you're not left paying for a stopped-
     but-still-allocated instance longer than needed (adjust if you'd rather leave it).

BEFORE RUNNING:
  - Set INSTANCE_ID below to a real, DISPOSABLE EC2 instance you don't mind stopping and
    starting (a free-tier t2.micro/t3.micro you created just for this is ideal).
  - Make sure your AWS credentials have at minimum: ec2:DescribeInstances,
    ec2:StopInstances, ec2:StartInstances on that instance - nothing broader.
  - This incurs no extra cost beyond what the instance already costs you; stopping it
    briefly does not create new charges.
"""
import sys

import boto3

from tollgate.gate import TollgateService
from tollgate.gateway_aws import GatedAWSClient
from tollgate.tiers import Evidence, EvidenceKind, RollbackPlan, Tier

INSTANCE_ID = "i-REPLACE-ME"  # <-- set this to your real, disposable test instance


def instance_state(ec2, instance_id: str) -> str:
    resp = ec2.describe_instances(InstanceIds=[instance_id])
    return resp["Reservations"][0]["Instances"][0]["State"]["Name"]


def main():
    if INSTANCE_ID == "i-REPLACE-ME":
        print("Set INSTANCE_ID to a real, disposable EC2 instance id before running this.")
        sys.exit(1)

    ec2 = boto3.client("ec2")  # uses your already-configured credentials
    gate = TollgateService()
    wrapped = GatedAWSClient(ec2, "ec2", gate)

    print("1) Read-only call (should always be ALLOWED, real boto3 call made)")
    decision, resp = wrapped.call(agent="validator", tier=Tier.READ_ONLY,
                                   action="DescribeInstances", params={"InstanceIds": [INSTANCE_ID]})
    print(f"   -> {decision['outcome']}")
    assert decision["outcome"] == "ALLOWED"
    state_before = resp["Reservations"][0]["Instances"][0]["State"]["Name"]
    print(f"   current real state: {state_before}")

    print("\n2) StopInstances with NO evidence (should be BLOCKED, boto3 never called)")
    decision, resp = wrapped.call(agent="validator", tier=Tier.EXECUTE_WITH_APPROVAL,
                                   action="StopInstances", params={"InstanceIds": [INSTANCE_ID]},
                                   resources=[INSTANCE_ID])
    print(f"   -> {decision['outcome']}")
    assert decision["outcome"] == "BLOCKED_NO_EVIDENCE"
    assert resp is None
    state_after_block = instance_state(ec2, INSTANCE_ID)
    print(f"   real state after the block: {state_after_block} (should be unchanged: {state_before})")
    assert state_after_block == state_before, "a blocked decision must never have touched real AWS state"

    print("\n3) StopInstances WITH full evidence+rollback+approval (should be ALLOWED, real stop happens)")
    decision, resp = wrapped.call(
        agent="validator", tier=Tier.EXECUTE_WITH_APPROVAL, action="StopInstances",
        params={"InstanceIds": [INSTANCE_ID]}, resources=[INSTANCE_ID],
        evidence=[Evidence(EvidenceKind.METRIC_THRESHOLD, "validation-run:manual-trigger"),
                  Evidence(EvidenceKind.HUMAN_APPROVAL, "approver:you")],
        rollback=RollbackPlan("start_instances will bring it back up", tested=True),
    )
    print(f"   -> {decision['outcome']}")
    assert decision["outcome"] == "ALLOWED"
    state_after_allow = instance_state(ec2, INSTANCE_ID)
    print(f"   real state after the allow: {state_after_allow} (should be 'stopping' or 'stopped')")
    assert state_after_allow in ("stopping", "stopped")

    print("\n4) Starting it back up (cleanup)")
    ec2.start_instances(InstanceIds=[INSTANCE_ID])
    print("   -> start_instances called directly to restore state")

    print("\nAll three checks passed against a REAL AWS account. Validation complete.")


if __name__ == "__main__":
    main()
