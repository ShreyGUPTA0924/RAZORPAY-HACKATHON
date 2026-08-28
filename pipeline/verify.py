"""
Deterministic compatibility verification -- Tier 1.

NO LLM IMPORTS IN THIS FILE. This is a non-negotiable architectural rule
(see CLAUDE.md) -- the LLM proposes, this module verifies, and that
boundary must stay visible and literal, not just a convention.

pipeline/compat.py (not yet built -- deferred pending LLM quota, see the
Block B build notes) is where an LLM PROPOSES a compatibility relationship
("this accessory fits that phone model"). This module VERIFIES a proposal
against a SKU's own already-extracted, quarantine-gated
pipeline.schema.ProductAttributes and either produces a machine-checkable
proof or rejects it. Nothing here trusts a proposal's claimed_basis at face
value -- it re-derives the fact independently from the SKU's attributes,
exactly the way surface/mandate.py treats an Intent Mandate as untrusted
input rather than a fact.

Every published compatibility edge must carry a proof like:
  {"model_compat_match": "samsung_galaxy_j7"}
or
  {"wattage_sufficient": {"required": 45.0, "actual": 65.0}}
An unverifiable proposal is dropped and logged (VerificationResult.reason),
never guessed into being true.
"""

from dataclasses import dataclass, field
from typing import Any

from pipeline.schema import ProductAttributes


@dataclass(frozen=True)
class CompatibilityProposal:
    """What pipeline/compat.py (LLM) would propose -- untrusted input to
    this module."""

    sku_id: str
    claimed_model: str  # e.g. "Samsung Galaxy J7" -- compared case/spacing-insensitively against model_compat
    claimed_basis: str  # "model_compat_match" | "wattage_sufficient" -- must match a known, deterministic check
    required_wattage_w: float | None = None  # only meaningful when claimed_basis == "wattage_sufficient"


@dataclass(frozen=True)
class VerificationResult:
    verified: bool
    proof: dict[str, Any] = field(default_factory=dict)
    reason: str = ""  # populated when verified=False -- why the proposal was rejected


def _normalize(s: str) -> str:
    return s.strip().lower().replace(" ", "_").replace("-", "_")


def verify_model_compat_match(proposal: CompatibilityProposal, attrs: ProductAttributes) -> VerificationResult:
    """Verified if the SKU's own extracted model_compat actually contains
    the claimed model. An explicit empty list ([]) means "universal" per
    pipeline.schema's own documented semantics -- verifies against ANY
    claimed model. None means unknown -- verifies against nothing; unknown
    is not evidence of universality."""
    model_compat = attrs.model_compat
    if model_compat.value is None:
        return VerificationResult(verified=False, reason="model_compat is unknown (null) for this SKU -- nothing to verify a claim against")

    if model_compat.value == []:
        return VerificationResult(verified=True, proof={"model_compat_match": "universal (SKU's model_compat is an explicit empty list)"})

    claimed_norm = _normalize(proposal.claimed_model)
    if any(_normalize(m) == claimed_norm for m in model_compat.value):
        return VerificationResult(verified=True, proof={"model_compat_match": proposal.claimed_model})

    return VerificationResult(
        verified=False,
        reason=f"'{proposal.claimed_model}' not found in extracted model_compat {model_compat.value}",
    )


def verify_wattage_sufficient(proposal: CompatibilityProposal, attrs: ProductAttributes) -> VerificationResult:
    """Verified if the SKU's extracted wattage_w meets or exceeds the
    proposal's claimed required wattage (e.g. "this 65W charger is
    compatible with a phone requiring 45W or less")."""
    if proposal.required_wattage_w is None:
        return VerificationResult(verified=False, reason="proposal is missing required_wattage_w")

    wattage = attrs.wattage_w
    if wattage.value is None:
        return VerificationResult(verified=False, reason="wattage_w is unknown (null) for this SKU -- nothing to verify a claim against")

    if wattage.value >= proposal.required_wattage_w:
        return VerificationResult(
            verified=True,
            proof={"wattage_sufficient": {"required": proposal.required_wattage_w, "actual": wattage.value}},
        )
    return VerificationResult(
        verified=False,
        reason=f"wattage {wattage.value}W < required {proposal.required_wattage_w}W",
    )


_VERIFIERS = {
    "model_compat_match": verify_model_compat_match,
    "wattage_sufficient": verify_wattage_sufficient,
}


def verify_proposal(proposal: CompatibilityProposal, attrs: ProductAttributes) -> VerificationResult:
    """Dispatch on proposal.claimed_basis. An unrecognized basis is
    rejected outright -- this only ever confirms bases it has an explicit,
    deterministic check for; an LLM's claimed_basis never gets the benefit
    of the doubt just because it named a real-sounding rule."""
    verifier = _VERIFIERS.get(proposal.claimed_basis)
    if verifier is None:
        return VerificationResult(
            verified=False,
            reason=f"unrecognized claimed_basis '{proposal.claimed_basis}' -- no deterministic check exists for it",
        )
    return verifier(proposal, attrs)
