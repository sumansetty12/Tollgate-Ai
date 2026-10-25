# Tollgate AI

**An evidence-gated autonomy layer for AI agents acting on cloud infrastructure.**

AI agents are increasingly given tool-calling access to real cloud infrastructure - restarting
services, changing configuration, scaling resources, stopping instances. Nothing standard
enforces a checkpoint between "the agent decided to do this" and "it actually happened."
Tollgate AI is that checkpoint: it wraps an agent's AWS SDK calls, and only lets a mutating
action through if it clears the agent's current autonomy tier *and* named, checkable evidence
appropriate to that tier.

This fills a gap stated directly in recent published research. A 2026 survey on LLM-based
NetOps/AIOps agents and the SREGym benchmark for AI SRE agents both describe the idea of gating
agent autonomy behind evidence requirements - but neither publishes a working implementation.
Tollgate AI is that implementation, scoped deliberately narrow rather than broad.

> **Status: early (v0.1).** Core logic is unit-tested (25 tests) against a fake AWS client, and
> has been validated end-to-end against one real AWS account (read-only pass-through, a blocked
> action provably never touching AWS, and an allowed action actually executing - see
> `validate_real_aws.py`). It has not been run against a real AI agent in production, only
> against synthetic test scenarios and direct script calls. See
> [Limitations](#limitations) before relying on it for anything real.

## How it works

```
Agent wants to call a cloud API
        |
        v
  Is it read-only (Describe/List/Get)?  --yes--> passes straight through
        |
        no
        v
  Does the current tier permit mutation at all?  --no--> BLOCKED_TIER
        |
        yes
        v
  Is diagnostic evidence attached (log citation, metric threshold, runbook match)?  --no--> BLOCKED_NO_EVIDENCE
        |
        yes
        v
  Does this tier require a rollback plan?  --yes, missing--> BLOCKED_NO_ROLLBACK
                                            --yes, untested--> BLOCKED_ROLLBACK_UNTESTED
        |
        yes/not required
        v
  Does this tier require human approval?  --yes, missing--> PENDING_APPROVAL
        |
        yes/not required
        v
  Does the action stay within the tier's blast-radius cap?  --no--> BLOCKED_BLAST_RADIUS
        |
        yes
        v
      ALLOWED -> the real boto3 call is made
```

Every outcome - allowed or blocked - is recorded with the evidence behind it. A finding is
never recorded without the evidence that justifies it.

## What each part does

| Feature | What it does |
|---|---|
| Autonomy tiers | Three tiers: `READ_ONLY` (no mutation), `PROPOSE` (may draft a change, may never execute it, regardless of evidence), `EXECUTE_WITH_APPROVAL` (may execute, but only with diagnostic evidence, a tested rollback plan, human approval, and a blast-radius cap of 5 resources per action). |
| Named evidence | Four explicit kinds: a log citation, a metric threshold crossed, a matched runbook entry, or a human approval token. No fuzzy confidence score - every piece of evidence has to point at something a person could go check. |
| Rollback check | `EXECUTE_WITH_APPROVAL` requires a rollback plan to be attached, and requires it to be marked tested, before a mutating action can run. |
| Blast-radius cap | An action touching more resources than its tier allows is blocked even if every other requirement is satisfied. |
| AWS SDK wrapper | Wraps any boto3-shaped client. Read-only calls pass straight through; mutating calls are gated before the real client method is ever called. A blocked decision means boto3 is never invoked - verified against a real AWS account, not just asserted. |
| Audit log | Every decision - allowed, blocked, pending-approval - recorded with its evidence ids, timestamp, and the exact reason. |
| Compliance-style report | Maps the decision log to four named controls (no unreviewed change executes, no change executes without a tested rollback, no change bypasses required approval, blast radius is bounded), the same spirit as a SOC 2 evidence report: real evidence for a reviewer, not a certification. |

## What's proven, and what isn't

Being precise about this matters more than sounding finished:

- **The gate logic itself** is unit-tested (25 tests) against every tier/evidence/rollback/blast-radius
  combination, using a fake AWS client.
- **The AWS wrapper** has been validated against one real AWS account: a blocked action was
  confirmed to never change real instance state, and an allowed action was confirmed to actually
  change it (`validate_real_aws.py`).
- **The before/after fault-injection demo** (`demo_fault_injection.py` / `run_demo.py`) is
  synthetic, not drawn from real incident data: 20 hand-built scenarios, not a live environment.
  It showed a reduction in bad outcomes from 8/20 to 3/20 with the gate in place - a real,
  measured number, but on a small, constructed test set, not a claim about real-world incident
  rates.
- **It has not been run against a real AI agent** making real tool calls end-to-end; validation
  so far calls the wrapper directly, the same way a human operator or a script would.
- **Azure and GCP are not implemented.** Only AWS.
- **Tier 3 (fully autonomous within a pre-declared blast radius, no per-action approval) is not
  implemented.** Checking that an invariant holds across every intermediate state of a multi-step
  rollout - not just the final state - is an open problem that existing published research (see
  the survey cited above) hasn't solved either. Faking this tier would mean claiming a safety
  property nobody has actually verified.

## Limitations to know about

- **The gate checks that evidence exists and is well-formed. It cannot and does not check that
  evidence is true.** In the fault-injection demo, scenarios where an agent attached confident
  but *incorrect* evidence (the `confidently_wrong` category) were not caught - only scenarios
  where evidence was missing entirely (`missing_process`) were caught. This is a real limit of
  the design, not an edge case to patch around.
- **The blast-radius cap has a real cost.** Two legitimate fixes in the demo that needed to touch
  more than 5 resources at once were blocked along with the unsafe ones. A team that regularly
  needs larger-scope fixes would need a higher tier (not yet implemented) or a per-contract cap,
  not the fixed default used here.
- **`stop_instances` returning does not mean the instance has actually stopped.** AWS's own
  eventual-consistency behavior means a caller checking state immediately after a call can see a
  stale value. `validate_real_aws.py`'s cleanup step had to be changed to wait for the real
  "stopped" state before restarting the instance - the same category of gap documented in
  Plumbline's Azure/GCP revocation-timing limitations, just showing up on AWS this time.
- **Only one agent-integration pattern is supported**: code that explicitly calls
  `GatedAWSClient.call(...)` instead of boto3 directly. An agent framework that bypasses this
  wrapper bypasses the gate entirely - this is an SDK-wrapper design choice, not a network-level
  proxy, and it has that specific limitation as a result.

## Running it

No AWS account needed for the test suite or the simulated demo:

```bash
pip install -e .
python -m pytest -q        # 25 tests
python run_demo.py         # before/after fault-injection comparison
```

Real-AWS validation needs your own disposable test instance and narrowly-scoped credentials -
see the docstring in `validate_real_aws.py` for the exact IAM permissions needed (just
`ec2:DescribeInstances`, `ec2:StopInstances`, `ec2:StartInstances`) before running it.

## License

MIT. Including the limitations above - a tool that claims more certainty than it's earned is
more dangerous than one that's honest about where it still needs real-world mileage.
