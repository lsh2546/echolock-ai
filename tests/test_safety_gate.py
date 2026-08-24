"""
tests/test_safety_gate.py

Tests for SafetyGate: hard invariants, forbidden adaptations, fail-closed behaviour.
Includes property-based tests (hypothesis) for HI-1 and HI-2.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from echolock.models import (
    AdaptationType,
    ImageResolution,
    PatchCandidate,
    SafetyCheckResult,
)
from echolock.safety_gate import (
    estimate_battery_cost,
    validate_candidate,
    validate_original_command,
)
from echolock.simulator import SimulatorSeed, arrival_state


# ---------------------------------------------------------------------------
# HI-1: Battery floor
# ---------------------------------------------------------------------------


def test_hi1_original_nominal_passes(sealed_command, envelope) -> None:
    a_state = arrival_state(SimulatorSeed.NOMINAL)
    checks, _ = validate_original_command(sealed_command, envelope, a_state)
    hi1 = next(c for c in checks if c.invariant_id == "HI-1")
    assert hi1.result == SafetyCheckResult.PASS


def test_hi1_original_low_battery_fails(sealed_command, envelope) -> None:
    a_state = arrival_state(SimulatorSeed.LOW_BATTERY)
    checks, _ = validate_original_command(sealed_command, envelope, a_state)
    hi1 = next(c for c in checks if c.invariant_id == "HI-1")
    assert hi1.result == SafetyCheckResult.FAIL_CLOSED


def test_hi1_boundary_at_exactly_floor(sealed_command, envelope) -> None:
    """Post-execution battery exactly at the floor (20 %) must PASS."""
    # Drain that leaves exactly 20 % battery
    floor = envelope.battery_floor_pct
    drain = estimate_battery_cost(10, "4K", 100.0)
    start_battery = floor + drain
    from echolock.safety_gate import _check_hi1_battery
    check = _check_hi1_battery(start_battery, drain, floor)
    assert check.result == SafetyCheckResult.PASS


def test_hi1_boundary_one_below_floor(sealed_command, envelope) -> None:
    """Post-execution battery 0.01 % below floor must FAIL_CLOSED."""
    floor = envelope.battery_floor_pct
    drain = estimate_battery_cost(10, "4K", 100.0)
    start_battery = floor + drain - 0.01  # will result in post < floor
    from echolock.safety_gate import _check_hi1_battery
    check = _check_hi1_battery(start_battery, drain, floor)
    assert check.result == SafetyCheckResult.FAIL_CLOSED


@given(
    battery=st.floats(min_value=0.0, max_value=100.0),
    images=st.integers(min_value=1, max_value=10),
    power=st.floats(min_value=40.0, max_value=100.0),
)
@settings(
    max_examples=500,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_hi1_property_no_approved_action_drains_below_floor(
    battery: float, images: int, power: float, envelope
) -> None:
    """Property: a PASS verdict for HI-1 guarantees post-battery >= floor.

    The envelope fixture is read-only in this test (battery_floor_pct is constant)
    so suppressing the function_scoped_fixture health check is safe here.
    """
    from echolock.safety_gate import _check_hi1_battery
    floor = envelope.battery_floor_pct
    drain = estimate_battery_cost(images, "4K", power)
    check = _check_hi1_battery(battery, drain, floor)
    if check.result == SafetyCheckResult.PASS:
        assert check.evaluated_value >= floor


# ---------------------------------------------------------------------------
# HI-2: Temperature ceiling
# ---------------------------------------------------------------------------


def test_hi2_nominal_passes(sealed_command, envelope) -> None:
    a_state = arrival_state(SimulatorSeed.NOMINAL)
    checks, _ = validate_original_command(sealed_command, envelope, a_state)
    hi2 = next(c for c in checks if c.invariant_id == "HI-2")
    assert hi2.result == SafetyCheckResult.PASS


def test_hi2_overheat_fails(sealed_command, envelope) -> None:
    a_state = arrival_state(SimulatorSeed.OVERHEAT)
    checks, _ = validate_original_command(sealed_command, envelope, a_state)
    hi2 = next(c for c in checks if c.invariant_id == "HI-2")
    assert hi2.result == SafetyCheckResult.FAIL_CLOSED


def test_hi2_boundary_at_ceiling(envelope) -> None:
    from echolock.safety_gate import _check_hi2_temperature
    check = _check_hi2_temperature(75.0, 75.0)  # exactly at ceiling
    assert check.result == SafetyCheckResult.PASS


def test_hi2_boundary_one_above_ceiling(envelope) -> None:
    from echolock.safety_gate import _check_hi2_temperature
    check = _check_hi2_temperature(75.1, 75.0)
    assert check.result == SafetyCheckResult.FAIL_CLOSED


@given(temp=st.floats(min_value=-30.0, max_value=150.0))
@settings(
    max_examples=300,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_hi2_property_ceiling_correct(temp: float, envelope) -> None:
    from echolock.safety_gate import _check_hi2_temperature
    ceiling = envelope.max_equipment_temp_c
    check = _check_hi2_temperature(temp, ceiling)
    if temp <= ceiling:
        assert check.result == SafetyCheckResult.PASS
    else:
        assert check.result == SafetyCheckResult.FAIL_CLOSED


# ---------------------------------------------------------------------------
# HI-3: Emergency beacon
# ---------------------------------------------------------------------------


def test_hi3_active_beacon_passes(sealed_command, envelope) -> None:
    a_state = arrival_state(SimulatorSeed.NOMINAL)
    checks, _ = validate_original_command(sealed_command, envelope, a_state)
    hi3 = next(c for c in checks if c.invariant_id == "HI-3")
    assert hi3.result == SafetyCheckResult.PASS


def test_hi3_patch_interrupting_beacon_is_blocked(sealed_command, envelope) -> None:
    """A patch that would interrupt the beacon must be FAIL_CLOSED."""
    a_state = arrival_state(SimulatorSeed.NOMINAL)
    patch = PatchCandidate(
        adaptation_types=[AdaptationType.REDUCE_POWER],
        adapted_power_pct=0.0,  # zero power — FA-5 + HI-3
        gps=0.75,
    )
    vc = validate_candidate(patch, envelope, sealed_command, a_state)
    assert vc.safety_result == SafetyCheckResult.FAIL_CLOSED


# ---------------------------------------------------------------------------
# HI-4: Expiry
# ---------------------------------------------------------------------------


def test_hi4_expired_command_fails(sealed_command, envelope) -> None:
    """If arrival time is after expiry, HI-4 must fail."""
    from datetime import timedelta
    from echolock.simulator import arrival_state as get_arrival
    from echolock.models import CommWindowStatus, EmergencyBeaconStatus, ImageResolution, StateSnapshot
    # Construct an arrival state with timestamp after expiry
    expired_timestamp = envelope.expires_at + timedelta(seconds=1)
    a_state = StateSnapshot(
        battery_soc=85.0,
        equipment_temp_c=42.0,
        comm_window_status=CommWindowStatus.OPEN,
        emergency_beacon=EmergencyBeaconStatus.ACTIVE,
        stored_image_count=0,
        transmission_power_pct=100.0,
        available_resolution=ImageResolution.K4,
        timestamp=expired_timestamp,
    )
    checks, _ = validate_original_command(sealed_command, envelope, a_state)
    hi4 = next(c for c in checks if c.invariant_id == "HI-4")
    assert hi4.result == SafetyCheckResult.FAIL_CLOSED


def test_hi4_at_exact_expiry_boundary_passes(sealed_command, envelope) -> None:
    """Command arriving exactly at expiry must still pass."""
    from echolock.models import CommWindowStatus, EmergencyBeaconStatus, ImageResolution, StateSnapshot
    a_state = StateSnapshot(
        battery_soc=85.0,
        equipment_temp_c=42.0,
        comm_window_status=CommWindowStatus.OPEN,
        emergency_beacon=EmergencyBeaconStatus.ACTIVE,
        stored_image_count=0,
        transmission_power_pct=100.0,
        available_resolution=ImageResolution.K4,
        timestamp=envelope.expires_at,  # exactly at boundary
    )
    checks, _ = validate_original_command(sealed_command, envelope, a_state)
    hi4 = next(c for c in checks if c.invariant_id == "HI-4")
    assert hi4.result == SafetyCheckResult.PASS


# ---------------------------------------------------------------------------
# Forbidden adaptations
# ---------------------------------------------------------------------------


def test_at2_image_count_below_minimum_is_blocked(sealed_command, envelope) -> None:
    a_state = arrival_state(SimulatorSeed.NOMINAL)
    patch = PatchCandidate(
        adaptation_types=[AdaptationType.REDUCE_IMAGE_COUNT],
        adapted_image_count=2,  # below minimum of 3
        gps=0.3,
    )
    vc = validate_candidate(patch, envelope, sealed_command, a_state)
    assert vc.safety_result == SafetyCheckResult.FAIL_CLOSED
    assert any("AT-2" in v for v in vc.violated_invariants)


def test_at5_power_below_minimum_is_blocked(sealed_command, envelope) -> None:
    a_state = arrival_state(SimulatorSeed.NOMINAL)
    patch = PatchCandidate(
        adaptation_types=[AdaptationType.REDUCE_POWER],
        adapted_power_pct=39.0,  # below 40 % minimum
        gps=0.5,
    )
    vc = validate_candidate(patch, envelope, sealed_command, a_state)
    assert vc.safety_result == SafetyCheckResult.FAIL_CLOSED
    assert any("AT-5" in v for v in vc.violated_invariants)


def test_at1_delay_above_maximum_is_blocked(sealed_command, envelope) -> None:
    a_state = arrival_state(SimulatorSeed.NOMINAL)
    patch = PatchCandidate(
        adaptation_types=[AdaptationType.DELAY],
        delay_minutes=46.0,  # above 45-minute maximum
        gps=0.8,
    )
    vc = validate_candidate(patch, envelope, sealed_command, a_state)
    assert vc.safety_result == SafetyCheckResult.FAIL_CLOSED


def test_fail_closed_sets_eligibility_gps_to_zero(sealed_command, envelope) -> None:
    a_state = arrival_state(SimulatorSeed.NOMINAL)
    patch = PatchCandidate(
        adaptation_types=[AdaptationType.REDUCE_IMAGE_COUNT],
        adapted_image_count=2,
        gps=0.9,  # high GPS but forbidden
    )
    vc = validate_candidate(patch, envelope, sealed_command, a_state)
    assert vc.safety_result == SafetyCheckResult.FAIL_CLOSED
    assert vc.eligibility_gps == 0.0


def test_valid_adaptation_passes(sealed_command, envelope) -> None:
    """A patch reducing images to 5 and power to 70 % should pass all checks on nominal state.

    eligibility_gps is always recomputed deterministically by the SafetyGate (APC-6).
    The supplied PatchCandidate.gps value is ignored for eligibility.
    """
    from echolock.gps import compute_gps
    a_state = arrival_state(SimulatorSeed.NOMINAL)
    patch = PatchCandidate(
        adaptation_types=[AdaptationType.REDUCE_IMAGE_COUNT, AdaptationType.REDUCE_POWER],
        adapted_image_count=5,
        adapted_power_pct=70.0,
        gps=0.75,  # supplied value — NOT used by SafetyGate
    )
    vc = validate_candidate(patch, envelope, sealed_command, a_state)
    assert vc.safety_result == SafetyCheckResult.PASS
    # eligibility_gps is the deterministically recomputed value, not 0.75
    expected_gps = compute_gps(patch, sealed_command, envelope)
    assert vc.eligibility_gps == pytest.approx(expected_gps, abs=0.0001)
    # Sanity: a patch that halves image count and reduces power stays above GPS_THRESHOLD? (may not)
    # The important property is that it was NOT taken from the candidate's own .gps field.
    assert vc.eligibility_gps != pytest.approx(0.75, abs=0.0001) or expected_gps == pytest.approx(0.75, abs=0.0001)
