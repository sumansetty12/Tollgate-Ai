"""Tollgate AI: an evidence-gated autonomy layer for AI operations agents.

An AI agent with tool-calling access to cloud infrastructure can take real, mutating
actions - restart a service, change a security group, scale a resource - with nothing
enforced between "the agent decided to do this" and "it actually happened." Tollgate AI
sits in that gap: it wraps the cloud SDK calls an agent makes, and only lets a mutating
action through if it clears two things: the agent's current autonomy tier, and named,
checkable evidence appropriate to that tier.

This is deliberately narrow in v1: one cloud (AWS), three tiers (not the full four from
the design doc - tier 3, full autonomous-within-blast-radius, is documented as future work,
not implemented), and evidence as an explicit set of named types rather than a model score.
"""
