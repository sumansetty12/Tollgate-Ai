#!/usr/bin/env python3
"""Run this to see Tollgate AI's before/after fault-injection comparison.

Usage:
    python run_demo.py
"""
import json

from tollgate.demo_fault_injection import compare

if __name__ == "__main__":
    result = compare()
    print("=" * 60)
    print("TOLLGATE AI - before/after fault-injection comparison")
    print("=" * 60)
    print(f"\nTotal scenarios run: {result['without_gate']['total']}\n")
    print(f"Bad outcomes WITHOUT the gate: {result['summary']['bad_outcomes_without_gate']}")
    print(f"Bad outcomes WITH the gate:    {result['summary']['bad_outcomes_with_gate']}")
    print(f"Bad outcomes prevented:        {result['summary']['bad_outcomes_prevented']}")
    print(f"Legitimate actions blocked:    {result['summary']['legitimate_actions_blocked_by_gate']}")
    print(f"\nCaveat:\n{result['summary']['caveat']}\n")
    print("=" * 60)
    print("Full decision log (with gate):")
    print("=" * 60)
    for d in result["with_gate"]["decisions"]:
        print(f"  [{d['outcome']:<22}] {d['category']:<22} {d['name']}")
