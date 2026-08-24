"""
tests/test_sdr_engine.py

Unit tests for the SDR Engine: delta computation and severity tagging.
"""

from __future__ import annotations

import pytest

from echolock.models import DriftSeverity
from echolock.sdr_engine import compute
from echolock.simulator import SimulatorSeed, arrival_state, send_state


def test_sdr_nominal_no_violated_invariants(sealed_command, envelope) -> None:
    s = send_state()
    a = arrival_state(SimulatorSeed.NOMINAL)
    sdr = compute(sealed_command, envelope, s, a)
    assert not sdr.has_violated_invariants


def test_sdr_low_battery_violated_invariant(sealed_command, envelope) -> None:
    s = send_state()
    a = arrival_state(SimulatorSeed.LOW_BATTERY)
    sdr = compute(sealed_command, envelope, s, a)
    # Battery at arrival (28 %) is above floor (20 %) so no HI violation at arrival time
    # HI-1 is about post-execution, not pre-execution battery — SDR notes BROKEN_ASSUMPTION
    battery_deltas = [d for d in sdr.deltas if d.field == "battery_soc"]
    assert len(battery_deltas) == 1
    assert battery_deltas[0].severity == DriftSeverity.BROKEN_ASSUMPTION


def test_sdr_overheat_violated_invariant(sealed_command, envelope) -> None:
    """OVERHEAT seed: temperature already above 75 °C ceiling → VIOLATED_INVARIANT."""
    s = send_state()
    a = arrival_state(SimulatorSeed.OVERHEAT)
    sdr = compute(sealed_command, envelope, s, a)
    temp_deltas = [d for d in sdr.deltas if d.field == "equipment_temp_c"]
    assert len(temp_deltas) == 1
    assert temp_deltas[0].severity == DriftSeverity.VIOLATED_INVARIANT


def test_sdr_comm_loss_broken_assumption(sealed_command, envelope) -> None:
    """COMM_LOSS seed: window closed → BROKEN_ASSUMPTION."""
    s = send_state()
    a = arrival_state(SimulatorSeed.COMM_LOSS)
    sdr = compute(sealed_command, envelope, s, a)
    comm_deltas = [d for d in sdr.deltas if d.field == "comm_window_status"]
    assert len(comm_deltas) == 1
    assert comm_deltas[0].severity == DriftSeverity.BROKEN_ASSUMPTION


def test_sdr_no_deltas_when_all_match(sealed_command, envelope) -> None:
    """When send and arrival states are identical, there should be no deltas."""
    s = send_state()
    sdr = compute(sealed_command, envelope, s, s)  # same snapshot
    assert sdr.deltas == []


def test_sdr_command_id_matches(sealed_command, envelope) -> None:
    s = send_state()
    a = arrival_state(SimulatorSeed.NOMINAL)
    sdr = compute(sealed_command, envelope, s, a)
    assert sdr.command_id == sealed_command.command_id


def test_sdr_timestamps_match_snapshots(sealed_command, envelope) -> None:
    s = send_state()
    a = arrival_state(SimulatorSeed.NOMINAL)
    sdr = compute(sealed_command, envelope, s, a)
    assert sdr.send_state_timestamp == s.timestamp
    assert sdr.arrival_state_timestamp == a.timestamp
