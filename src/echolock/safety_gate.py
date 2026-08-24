"""
SafetyGate — deterministic hard-invariant validator.

This module is the ONLY authority for safety verdicts.
It has zero AI dependencies — enforced by tests/test_architecture.py.

Rules implemented:
  HI-1  Post-execution battery must remain ≥ floor (default 20 %)
  HI-2  Equipment temperature must not exceed ceiling (default 75 °C)
  HI-3  Emergency beacon must never be interrupted
  HI-4  Command must not execute after expiration
  HI-5  No adaptation may itself violate HI-1 through HI-4
  HI-COMM  Immediate (delay=0) transmission requires open comm window

Forbidden adaptations (9 items from Q3):
  FA-1  Modifying or replacing the original command
  FA-2  Changing the scientific target
  FA-3  Changing the hard invariants
  FA-4  Extending command expiration time
  FA-5  Interrupting the emergency beacon
  FA-6  Lowering the minimum battery reserve
  FA-7  Raising the maximum temperature limit
  FA-8  Changing goal-preservation weights
  FA-9  Executing any candidate before deterministic validation (architectural — always enforced)

Authorized-patch enforcement rules (checked inside validate_candidate):
  APC-1  delay_minutes must be ≥ 0
  APC-2  batch_count must be ≥ 1
  APC-3  adapted_power_pct must be in [0, 100] and ≤ original requested power
  APC-4  adapted_image_count must be in [1, original image count]
  APC-5  declared adaptation_types must match actual field changes
  APC-6  supplied PatchCandidate.gps is NEVER used for eligibility;
          GPS is always recomputed deterministically by the SafetyGate

Design rule: ZERO AI imports in this module.
"""

from __future__ import annotations

from datetime import datetime

from .gps import compute_gps
from .models import (
    AdaptationType,
    EmergencyBeaconStatus,
    HardInvariantCheck,
    ImageResolution,
    MissionIntentEnvelope,
    PatchCandidate,
    RawCommand,
    SafetyCheckResult,
    StateSnapshot,
    ValidatedCandidate,
)

# ---------------------------------------------------------------------------
# Battery cost model (toy physics — PoC only, not flight-accurate)
# ---------------------------------------------------------------------------

# Energy cost per image transmitted at 4K full power [% battery per image]
_BATTERY_COST_PER_IMAGE_4K_FULL_POWER = 1.2

# Resolution cost factor (1080p costs less)
_RESOLUTION_FACTOR = {
    "4K": 1.0,
    "1080p": 0.6,
}

# Power cost factor (linear)
_POWER_FACTOR_BASE = 100.0


def estimate_battery_cost(
    image_count: int,
    resolution_label: str,
    power_pct: float,
    batch_count: int = 1,
) -> float:
    """Estimate battery drain [% SoC] for a given transmission configuration."""
    res_factor = _RESOLUTION_FACTOR.get(resolution_label, 1.0)
    power_factor = power_pct / _POWER_FACTOR_BASE
    # Batching adds a small per-batch overhead (0.2 % per extra batch)
    batch_overhead = max(0, batch_count - 1) * 0.2
    return (
        image_count * _BATTERY_COST_PER_IMAGE_4K_FULL_POWER * res_factor * power_factor
        + batch_overhead
    )


# ---------------------------------------------------------------------------
# Hard-invariant checkers (one function per HI)
# ---------------------------------------------------------------------------


def _check_hi1_battery(
    current_battery_soc: float,
    estimated_drain: float,
    floor: float,
) -> HardInvariantCheck:
    post = current_battery_soc - estimated_drain
    result = SafetyCheckResult.PASS if post >= floor else SafetyCheckResult.FAIL_CLOSED
    return HardInvariantCheck(
        invariant_id="HI-1",
        description=f"Post-execution battery must be ≥ {floor:.0f} %",
        result=result,
        evaluated_value=round(post, 2),
        threshold=floor,
        evaluation_source="DETERMINISTIC",
    )


def _check_hi2_temperature(
    current_temp_c: float,
    ceiling: float,
) -> HardInvariantCheck:
    result = (
        SafetyCheckResult.PASS if current_temp_c <= ceiling else SafetyCheckResult.FAIL_CLOSED
    )
    return HardInvariantCheck(
        invariant_id="HI-2",
        description=f"Equipment temperature must be ≤ {ceiling:.0f} °C",
        result=result,
        evaluated_value=round(current_temp_c, 2),
        threshold=ceiling,
        evaluation_source="DETERMINISTIC",
    )


def _check_hi3_beacon(
    arrival_beacon: EmergencyBeaconStatus,
    patch_beacon_interrupted: bool,
) -> HardInvariantCheck:
    violated = (
        arrival_beacon == EmergencyBeaconStatus.INACTIVE or patch_beacon_interrupted
    )
    result = SafetyCheckResult.FAIL_CLOSED if violated else SafetyCheckResult.PASS
    return HardInvariantCheck(
        invariant_id="HI-3",
        description="Emergency beacon must never be interrupted",
        result=result,
        evaluated_value=str(arrival_beacon),
        threshold="ACTIVE",
        evaluation_source="DETERMINISTIC",
    )


def _check_hi4_expiry(
    eval_time: datetime,
    expires_at: datetime,
) -> HardInvariantCheck:
    expired = eval_time > expires_at
    result = SafetyCheckResult.FAIL_CLOSED if expired else SafetyCheckResult.PASS
    return HardInvariantCheck(
        invariant_id="HI-4",
        description="Command must not execute after expiration",
        result=result,
        evaluated_value=eval_time.isoformat(),
        threshold=expires_at.isoformat(),
        evaluation_source="DETERMINISTIC",
    )


# ---------------------------------------------------------------------------
# Forbidden adaptation checks
# ---------------------------------------------------------------------------


def _check_candidate_bounds(
    candidate: PatchCandidate,
    original: RawCommand,
) -> list[str]:
    """APC-1–APC-5: strict bounds and cross-field validation for a PatchCandidate.

    These checks are pure bounds/consistency rules that do not require the envelope.
    They are evaluated before MIE-authority checks.

    Returns a list of violation strings, empty when all pass.
    """
    violations: list[str] = []

    # APC-1: delay must not be negative
    if candidate.delay_minutes < 0:
        violations.append(
            f"APC-1: delay_minutes {candidate.delay_minutes:.1f} is negative."
        )

    # APC-2: batch_count must be ≥ 1
    if candidate.batch_count < 1:
        violations.append(
            f"APC-2: batch_count {candidate.batch_count} is below minimum of 1."
        )

    # APC-3: adapted_power_pct range and direction
    if candidate.adapted_power_pct is not None:
        if not (0.0 <= candidate.adapted_power_pct <= 100.0):
            violations.append(
                f"APC-3: adapted_power_pct {candidate.adapted_power_pct:.1f} is outside [0, 100]."
            )
        if candidate.adapted_power_pct > original.requested_power_pct:
            violations.append(
                f"APC-3: adapted_power_pct {candidate.adapted_power_pct:.1f} % exceeds "
                f"original requested power {original.requested_power_pct:.1f} % "
                "(power may only be reduced, not increased)."
            )

    # APC-4: adapted_image_count must be ≥ 1 and ≤ original
    if candidate.adapted_image_count is not None:
        if candidate.adapted_image_count < 1:
            violations.append(
                f"APC-4: adapted_image_count {candidate.adapted_image_count} is below minimum of 1."
            )
        if candidate.adapted_image_count > original.image_count:
            violations.append(
                f"APC-4: adapted_image_count {candidate.adapted_image_count} exceeds "
                f"original image_count {original.image_count} "
                "(image count may only be reduced, not increased)."
            )

    # APC-5: declared adaptation_types must match actual field changes
    #   — Every change must have a corresponding declared type.
    #   — Every declared type must correspond to an actual change.
    declared = set(candidate.adaptation_types)
    actual: set[AdaptationType] = set()

    if candidate.adapted_image_count is not None and candidate.adapted_image_count != original.image_count:
        actual.add(AdaptationType.REDUCE_IMAGE_COUNT)
    if (
        candidate.adapted_resolution is not None
        and candidate.adapted_resolution != original.requested_resolution
    ):
        actual.add(AdaptationType.REDUCE_RESOLUTION)
    if candidate.adapted_power_pct is not None and candidate.adapted_power_pct != original.requested_power_pct:
        actual.add(AdaptationType.REDUCE_POWER)
    if candidate.delay_minutes > 0:
        actual.add(AdaptationType.DELAY)
    if candidate.compression_applied:
        actual.add(AdaptationType.APPLY_COMPRESSION)
    if candidate.batch_count > 1:
        actual.add(AdaptationType.SPLIT_BATCHES)

    # Actual changes not declared in adaptation_types
    undeclared = actual - declared
    if undeclared:
        violations.append(
            f"APC-5: Actual changes {[t.value for t in sorted(undeclared, key=lambda x: x.value)]} "
            f"are not declared in adaptation_types."
        )
    # Declared types with no corresponding actual change
    phantom = declared - actual
    if phantom:
        violations.append(
            f"APC-5: Declared adaptation_types {[t.value for t in sorted(phantom, key=lambda x: x.value)]} "
            f"do not correspond to any actual field change."
        )

    # AT-3 direction: resolution may only be reduced (4K → 1080p), not increased
    if candidate.adapted_resolution is not None:
        original_res = original.requested_resolution
        adapted_res = candidate.adapted_resolution
        # 4K > 1080p in quality — a candidate proposing 4K when original is 1080p is an increase
        _quality_rank = {ImageResolution.K4: 1, ImageResolution.P1080: 0}
        if _quality_rank.get(adapted_res, 0) > _quality_rank.get(original_res, 0):
            violations.append(
                f"APC-5/AT-3: Adapted resolution {adapted_res.value} is higher quality than "
                f"original {original_res.value}; resolution may only be reduced."
            )

    return violations


def _check_forbidden_adaptations(
    candidate: PatchCandidate,
    envelope: MissionIntentEnvelope,
    original: RawCommand,
) -> list[str]:
    """MIE-authority checks: what the operator has authorised.

    Returns a list of violation descriptions, empty when all pass.
    """
    violations: list[str] = []

    # FA-4: adapted delay must not push execution past expiry
    if candidate.delay_minutes > 0:
        from datetime import timedelta
        projected_exec = envelope.intended_execution_at + timedelta(
            minutes=candidate.delay_minutes
        )
        if projected_exec > envelope.expires_at:
            violations.append(
                f"FA-4: Delay of {candidate.delay_minutes:.1f} min would push execution "
                f"past expiration ({envelope.expires_at.isoformat()})."
            )

    # AT-1 boundary: delay must not exceed MIE max
    if candidate.delay_minutes > envelope.adaptation_authority.max_delay_minutes:
        violations.append(
            f"AT-1 violation: Delay {candidate.delay_minutes:.1f} min exceeds "
            f"authorised maximum of {envelope.adaptation_authority.max_delay_minutes:.0f} min."
        )

    # AT-2 boundary: image count must not drop below minimum
    if candidate.adapted_image_count is not None:
        if candidate.adapted_image_count < envelope.adaptation_authority.min_images:
            violations.append(
                f"AT-2 violation: Adapted image count {candidate.adapted_image_count} "
                f"is below authorised minimum of {envelope.adaptation_authority.min_images}."
            )

    # AT-3 boundary: resolution reduction must be authorised
    if candidate.adapted_resolution is not None:
        if not envelope.adaptation_authority.allow_resolution_reduction:
            violations.append("AT-3 violation: Resolution reduction not authorised by MIE.")

    # AT-4 boundary: compression must be authorised
    if candidate.compression_applied and not envelope.adaptation_authority.allow_compression:
        violations.append("AT-4 violation: Compression not authorised by MIE.")

    # AT-5 boundary: transmission power floor
    if candidate.adapted_power_pct is not None:
        if candidate.adapted_power_pct < envelope.adaptation_authority.min_transmission_power_pct:
            violations.append(
                f"AT-5 violation: Adapted power {candidate.adapted_power_pct:.0f} % is below "
                f"authorised minimum of {envelope.adaptation_authority.min_transmission_power_pct:.0f} %."
            )

    # AT-6 boundary: batch splitting must be authorised
    if candidate.batch_count > 1 and not envelope.adaptation_authority.allow_batch_split:
        violations.append("AT-6 violation: Batch splitting not authorised by MIE.")

    # FA-5: beacon interruption via patch
    # (HI-3 also covers this, but we surface it explicitly as a forbidden adaptation)
    if AdaptationType.REDUCE_POWER in candidate.adaptation_types:
        eff_power = candidate.adapted_power_pct if candidate.adapted_power_pct is not None else 100.0
        if eff_power <= 0.0:
            violations.append("FA-5: Zero transmission power would interrupt emergency beacon circuit.")

    return violations


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_original_command(
    command: RawCommand,
    envelope: MissionIntentEnvelope,
    arrival_state: StateSnapshot,
) -> tuple[list[HardInvariantCheck], list[str]]:
    """Check the original command (no adaptation) against all hard invariants.

    Returns:
        (hi_checks, forbidden_violations)
        hi_checks: list of HardInvariantCheck results
        forbidden_violations: list of forbidden-adaptation violation strings (usually empty for original)
    """
    res_label = arrival_state.available_resolution.value
    drain = estimate_battery_cost(
        image_count=command.image_count,
        resolution_label=res_label,
        power_pct=command.requested_power_pct,
    )

    hi_checks = [
        _check_hi1_battery(
            arrival_state.battery_soc, drain, envelope.battery_floor_pct
        ),
        _check_hi2_temperature(
            arrival_state.equipment_temp_c, envelope.max_equipment_temp_c
        ),
        _check_hi3_beacon(arrival_state.emergency_beacon, patch_beacon_interrupted=False),
        _check_hi4_expiry(arrival_state.timestamp, envelope.expires_at),
    ]
    return hi_checks, []


def validate_candidate(
    candidate: PatchCandidate,
    envelope: MissionIntentEnvelope,
    original: RawCommand,
    arrival_state: StateSnapshot,
) -> ValidatedCandidate:
    """Validate one PatchCandidate against all hard invariants and forbidden rules.

    GPS is ALWAYS recomputed deterministically here; the supplied PatchCandidate.gps
    value is never used for eligibility decisions (APC-6).

    Args:
        candidate:     The patch candidate to evaluate.
        envelope:      The sealed Mission Intent Envelope.
        original:      The sealed original command.
        arrival_state: The actual spacecraft state at arrival.

    Returns:
        A ValidatedCandidate with safety_result PASS or FAIL_CLOSED and a
        deterministically recomputed eligibility_gps.
    """
    # APC-1–APC-5: strict bounds and cross-field validation first
    bounds_violations = _check_candidate_bounds(candidate, original)

    # Resolve effective parameters (fall back to original if patch doesn't change them)
    eff_images = candidate.adapted_image_count if candidate.adapted_image_count is not None else original.image_count
    eff_resolution = candidate.adapted_resolution.value if candidate.adapted_resolution is not None else original.requested_resolution.value
    eff_power = candidate.adapted_power_pct if candidate.adapted_power_pct is not None else original.requested_power_pct

    # Clamp eff_images to ≥ 1 defensively (bounds violations already recorded above)
    safe_eff_images = max(1, eff_images)
    safe_eff_power = max(0.0, min(100.0, eff_power))
    safe_batch = max(1, candidate.batch_count)

    drain = estimate_battery_cost(
        image_count=safe_eff_images,
        resolution_label=eff_resolution,
        power_pct=safe_eff_power,
        batch_count=safe_batch,
    )

    # HI-COMM: transmission requires an open comm window (unless delayed)
    comm_check = None
    if candidate.delay_minutes == 0.0:
        comm_open = arrival_state.comm_window_status.value == "OPEN"
        comm_check = HardInvariantCheck(
            invariant_id="HI-COMM",
            description="Immediate transmission requires open communication window",
            result=SafetyCheckResult.PASS if comm_open else SafetyCheckResult.FAIL_CLOSED,
            evaluated_value=arrival_state.comm_window_status.value,
            threshold="OPEN",
            evaluation_source="DETERMINISTIC",
        )

    hi_checks = [
        _check_hi1_battery(arrival_state.battery_soc, drain, envelope.battery_floor_pct),
        _check_hi2_temperature(arrival_state.equipment_temp_c, envelope.max_equipment_temp_c),
        _check_hi3_beacon(arrival_state.emergency_beacon, patch_beacon_interrupted=False),
        _check_hi4_expiry(arrival_state.timestamp, envelope.expires_at),
    ]
    if comm_check is not None:
        hi_checks.append(comm_check)

    forbidden_violations = _check_forbidden_adaptations(candidate, envelope, original)

    failed_his = [c.invariant_id for c in hi_checks if c.result == SafetyCheckResult.FAIL_CLOSED]
    all_violations = bounds_violations + failed_his + forbidden_violations

    overall = (
        SafetyCheckResult.PASS
        if not all_violations
        else SafetyCheckResult.FAIL_CLOSED
    )

    # APC-6: GPS is ALWAYS recomputed deterministically — never trust the supplied value
    if overall == SafetyCheckResult.PASS:
        eligibility_gps = compute_gps(candidate, original, envelope)
    else:
        eligibility_gps = 0.0

    return ValidatedCandidate(
        candidate=candidate,
        safety_result=overall,
        violated_invariants=all_violations,
        eligibility_gps=eligibility_gps,
    )
