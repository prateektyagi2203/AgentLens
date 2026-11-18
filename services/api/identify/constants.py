"""Shared identification constants."""

from __future__ import annotations

TIER_VERIFIED = "verified"
TIER_DECLARED = "declared"
TIER_SUSPECTED = "suspected"
TIER_HUMAN = "human"
TIER_INTERNAL = "internal"

# Strongest wins when a session mixes evidence. Internal replay traffic outranks everything so it can be excluded.
TIER_RANK = {TIER_INTERNAL: 5, TIER_VERIFIED: 4, TIER_DECLARED: 3, TIER_SUSPECTED: 2, TIER_HUMAN: 1}

# PRD 11.4: must be shown in the README and as the dashboard tooltip for identity coverage.
HONEST_LIMITATION = (
    "Agents that run inside the shopper's own browser (for example, browser extensions) look like humans at the "
    "server. AgentLens can only flag them as Suspected through behaviour, if at all. The identity coverage metric "
    "shows how much traffic is confidently identified."
)
