"""
tests/test_verdict_engine.py

Tests for VerdictEngine: Q5 precedence, all four verdicts.
"""

from __future__ import annotations

import pytest

from echolock.isp_generator import generate
from echolock.models import VerdictStatus
from echolock.safety_gate import validate_candidate, validate_original_command
from echolock.sdr_engine import compute as compute_sdr
from echolock.simulator import SimulatorSeed, arrival_state, send_state
from echolock.verdict_engine import GPS_THRESHOLD, decide


def _run_verdict(sealed_command, envelope, seed: SimulatorSeed):
    s = send_state()
    a = arrival_state(seed)
    sdr = compute_sdr(sealed_command, envelope, s, a)
    candidates = generate(sealed_command, envelope)
    validated = [validate_candidate(c, envelope, sealed_command, a) for c in candidates]
    return decide(sealed_command, envelope, a, sdr, validated)


def test_verdict_nominal_is_execute(sealed_command, envelope) -> None:
    result = _run_verdict(sealed_command, envelope, SimulatorSeed.NOMINAL)
    assert result.verdict == VerdictStatus.EXECUTE
    assert result.precedence_step == 2


def test_verdict_low_battery_is_adapt(sealed_command, envelope) -> None:
    result = _run_verdict(sealed_command, envelope, SimulatorSeed.LOW_BATTERY)
    assert result.verdict == VerdictStatus.ADAPT
    assert result.precedence_step == 3


def test_verdict_adapt_winning_candidate_gps_above_threshold(sealed_command, envelope) -> None:
    result = _run_verdict(sealed_command, envelope, SimulatorSeed.LOW_BATTERY)
    assert result.winning_candidate is not None
    assert result.winning_candidate.eligibility_gps >= GPS_THRESHOLD


def test_verdict_overheat_is_reject(sealed_command, envelope) -> None:
    result = _run_verdict(sealed_command, envelope, SimulatorSeed.OVERHEAT)
    assert result.verdict == VerdictStatus.REJECT
    assert result.precedence_step == 1  # pre-check: temperature above ceiling


def test_verdict_comm_loss_is_defer(sealed_command, envelope) -> None:
    result = _run_verdict(sealed_command, envelope, SimulatorSeed.COMM_LOSS)
    assert result.verdict == VerdictStatus.DEFER
    assert result.precedence_step == 4


def test_verdict_precedence_adapt_before_reject(sealed_command, envelope) -> None:
    """When the original command fails HI but a valid patch exists, ADAPT wins over REJECT."""
    result = _run_verdict(sealed_command, envelope, SimulatorSeed.LOW_BATTERY)
    # Safety: ensure we did NOT get REJECT even though original command HI-1 would fail
    assert result.verdict != VerdictStatus.REJECT


def test_verdict_execute_has_no_winning_candidate(sealed_command, envelope) -> None:
    result = _run_verdict(sealed_command, envelope, SimulatorSeed.NOMINAL)
    assert result.winning_candidate is None


def test_verdict_adapt_applied_patch_is_not_none(sealed_command, envelope) -> None:
    result = _run_verdict(sealed_command, envelope, SimulatorSeed.LOW_BATTERY)
    assert result.winning_candidate is not None
    assert result.winning_candidate.candidate is not None
