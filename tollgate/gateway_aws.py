"""Wraps an AWS SDK client so every mutating call routes through the gate first.

This is the "SDK wrapper" interception choice (over a network proxy): the agent's tool
code calls `GatedAWSClient.call(...)` instead of the boto3 client directly. Simpler to
build and reason about than a transparent network proxy, at the cost of requiring the
agent's tool-calling code to go through this wrapper rather than bypassing it - a real
limitation, written up as such rather than glossed over.
"""
from __future__ import annotations

import re

from .gate import TollgateService
from .tiers import Evidence, RollbackPlan, Tier


def _to_snake(action: str) -> str:
    """AWS action names are PascalCase ('StopInstances'); boto3 methods are snake_case
    ('stop_instances'). This converts one to the other."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", action).lower()


class GateBlocked(Exception):
    def __init__(self, decision: dict):
        self.decision = decision
        super().__init__(f"{decision['outcome']}: {decision['reason']}")


class GatedAWSClient:
    """Wraps any boto3-shaped client (real or fake - both just need snake_case methods
    matching AWS's action names)."""

    def __init__(self, client, service: str, gate: TollgateService):
        self.client, self.service, self.gate = client, service, gate

    def call(self, *, agent: str, tier: Tier, action: str, params: dict | None = None,
              resources: list[str] | None = None, evidence: list[Evidence] | None = None,
              rollback: RollbackPlan | None = None):
        """Returns (decision, response). response is None if the action was blocked -
        the underlying client method is never invoked unless the gate says ALLOWED."""
        params = params or {}
        resources = resources or []
        decision = self.gate.check(agent=agent, action=action, service=self.service, tier=tier,
                                   resources=resources, evidence=evidence, rollback=rollback)
        if decision["outcome"] != "ALLOWED":
            return decision, None
        method = getattr(self.client, _to_snake(action))
        return decision, method(**params)


class FakeAWSClient:
    """In-memory stand-in with just enough of EC2's shape to test the gate against -
    no real AWS account needed. Mirrors Plumbline's FakeGateway pattern."""

    def __init__(self):
        self.instances: dict[str, str] = {}  # instance_id -> state
        self.calls: list[tuple[str, dict]] = []

    def describe_instances(self, **kwargs):
        self.calls.append(("describe_instances", kwargs))
        return {"Reservations": [{"Instances": [{"InstanceId": i, "State": {"Name": s}}
                                                  for i, s in self.instances.items()]}]}

    def stop_instances(self, InstanceIds: list[str]):
        self.calls.append(("stop_instances", {"InstanceIds": InstanceIds}))
        for i in InstanceIds:
            self.instances[i] = "stopped"
        return {"StoppingInstances": [{"InstanceId": i, "CurrentState": {"Name": "stopped"}} for i in InstanceIds]}

    def start_instances(self, InstanceIds: list[str]):
        self.calls.append(("start_instances", {"InstanceIds": InstanceIds}))
        for i in InstanceIds:
            self.instances[i] = "running"
        return {"StartingInstances": [{"InstanceId": i, "CurrentState": {"Name": "running"}} for i in InstanceIds]}

    def terminate_instances(self, InstanceIds: list[str]):
        self.calls.append(("terminate_instances", {"InstanceIds": InstanceIds}))
        for i in InstanceIds:
            self.instances[i] = "terminated"
        return {"TerminatingInstances": [{"InstanceId": i, "CurrentState": {"Name": "terminated"}} for i in InstanceIds]}
