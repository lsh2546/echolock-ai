"""
tests/test_first_slice.py

First vertical slice acceptance criteria (approved Q6).

Scenario A — EXECUTE (Nominal arrival state)
Scenario B — ADAPT  (Low-battery arrival state)

Every acceptance criterion from the Planning Package v2 §5 is tested here.
"""

from __future__ import annotations

import pytest

from echolock import command_sealer
from echolock.certificate_builder import append_audit, build, clear_audit_log
from echolock.isp_generator import generate
from echolock.models import VerdictStatus
from echolock.pipeline import run
from echolock.safety_gate import validate_candidate, validate_original_command
from echolock.sdr_engine import compute as compute_sdr
from echolock.simulator import SimulatorSeed, arrival_state, send_state
from echolock.verdict_engine import GPS_THRESHOLD, decide


# ===========================================================================
# Scenario A — EXECUTE (Nominal arrival state)
# ===========================================================================


class TestScenarioA_Execute:
    """All Scenario A acceptance criteria."""

    def setup_method(self):
        clear_audit_log()

    def _run(self, sealed_command, envelope):
        return run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL)

    def test_A1_arrival_state_has_all_assumptions_valid(self, sealed_command, envelope) -> None:
        """Arrival battery=83 %, temp=43.5 °C, window OPEN, beacon ACTIVE — all assumptions valid."""
        a = arrival_state(SimulatorSeed.NOMINAL)
        assert a.battery_soc == pytest.approx(83.0, abs=1.0)
        assert a.equipment_temp_c <= envelope.max_equipment_temp_c
        assert a.comm_window_status.value == "OPEN"
        assert a.emergency_beacon.value == "ACTIVE"

    def test_A2_all_hi_pass_on_original_command(self, sealed_command, envelope) -> None:
        a = arrival_state(SimulatorSeed.NOMINAL)
        checks, _ = validate_original_command(sealed_command, envelope, a)
        for check in checks:
            assert check.result.value == "PASS", f"{check.invariant_id} failed unexpectedly"

    def test_A3_verdict_is_execute(self, sealed_command, envelope) -> None:
        cert = self._run(sealed_command, envelope)
        assert cert.verdict == VerdictStatus.EXECUTE

    def test_A4_no_patch_applied(self, sealed_command, envelope) -> None:
        cert = self._run(sealed_command, envelope)
        assert cert.applied_patch is None

    def test_A5_original_command_fingerprint_unchanged_after_run(self, sealed_command, envelope) -> None:
        original_fp = sealed_command.fingerprint
        _ = self._run(sealed_command, envelope)
        assert sealed_command.fingerprint == original_fp

    def test_A6_delta_certificate_schema_complete(self, sealed_command, envelope) -> None:
        cert = self._run(sealed_command, envelope)
        assert cert.original_command_id == sealed_command.command_id
        assert cert.original_command_fingerprint == sealed_command.fingerprint
        assert cert.sdr_summary is not None
        assert cert.verdict is not None
        assert cert.verdict_precedence_step == 2
        assert cert.decision_timestamp is not None
        assert cert.certificate_hash is not None
        assert cert.semantic_replay_hash is not None
        assert cert.mie_hash != ""
        assert cert.arrival_state_hash != ""
        assert cert.verifier_version != ""
        assert len(cert.hi_check_results) >= 4

    def test_A7_certificate_self_hash_verifies(self, sealed_command, envelope) -> None:
        cert = self._run(sealed_command, envelope)
        assert cert.verify_hash() is True
        assert cert.verify_semantic_replay_hash() is True

    def test_A8_semantic_replay_hash_consistent_across_10_runs(
        self, sealed_command, envelope
    ) -> None:
        """Running the pipeline 10 times on the same seed must produce identical semantic_replay_hash values."""
        hashes = [
            run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL, record_audit=False).semantic_replay_hash
            for _ in range(10)
        ]
        assert len(set(hashes)) == 1, f"Semantic replay hashes are not consistent: {set(hashes)}"


# ===========================================================================
# Scenario B — ADAPT (Low-battery arrival state)
# ===========================================================================


class TestScenarioB_Adapt:
    """All Scenario B acceptance criteria."""

    def setup_method(self):
        clear_audit_log()

    def _run(self, sealed_command, envelope):
        return run(sealed_command, envelope, seed=SimulatorSeed.LOW_BATTERY)

    def test_B1_arrival_battery_causes_hi1_violation_if_forced(
        self, sealed_command, envelope
    ) -> None:
        """Executing original command at 28 % battery drains below 20 % floor."""
        from echolock.safety_gate import estimate_battery_cost
        a = arrival_state(SimulatorSeed.LOW_BATTERY)
        drain = estimate_battery_cost(
            sealed_command.image_count,
            sealed_command.requested_resolution.value,
            sealed_command.requested_power_pct,
        )
        post = a.battery_soc - drain
        assert post < envelope.battery_floor_pct, (
            f"Expected post-battery {post:.2f} % to be below floor {envelope.battery_floor_pct} %"
        )

    def test_B2_sdr_marks_battery_as_broken_assumption(self, sealed_command, envelope) -> None:
        s = send_state()
        a = arrival_state(SimulatorSeed.LOW_BATTERY)
        sdr = compute_sdr(sealed_command, envelope, s, a)
        battery_deltas = [d for d in sdr.deltas if d.field == "battery_soc"]
        assert len(battery_deltas) == 1

    def test_B3_verdict_is_not_execute(self, sealed_command, envelope) -> None:
        cert = self._run(sealed_command, envelope)
        assert cert.verdict != VerdictStatus.EXECUTE

    def test_B4_isp_generates_at_least_one_candidate(self, sealed_command, envelope) -> None:
        candidates = generate(sealed_command, envelope)
        assert len(candidates) >= 1

    def test_B5_winning_patch_passes_hi1_with_enough_margin(
        self, sealed_command, envelope
    ) -> None:
        """The winning patch must leave post-execution battery ≥ 20 %."""
        cert = self._run(sealed_command, envelope)
        assert cert.applied_patch is not None
        from echolock.safety_gate import estimate_battery_cost
        a = arrival_state(SimulatorSeed.LOW_BATTERY)
        patch = cert.applied_patch
        eff_images = patch.adapted_image_count or sealed_command.image_count
        eff_resolution = patch.adapted_resolution.value if patch.adapted_resolution else sealed_command.requested_resolution.value
        eff_power = patch.adapted_power_pct if patch.adapted_power_pct else sealed_command.requested_power_pct
        drain = estimate_battery_cost(eff_images, eff_resolution, eff_power)
        post = a.battery_soc - drain
        assert post >= envelope.battery_floor_pct, (
            f"Winning patch leaves post-battery {post:.2f} % < floor {envelope.battery_floor_pct} %"
        )

    def test_B6_winning_patch_gps_above_threshold(self, sealed_command, envelope) -> None:
        cert = self._run(sealed_command, envelope)
        assert cert.gps is not None
        assert cert.gps >= GPS_THRESHOLD

    def test_B7_verdict_is_adapt(self, sealed_command, envelope) -> None:
        cert = self._run(sealed_command, envelope)
        assert cert.verdict == VerdictStatus.ADAPT
        assert cert.verdict_precedence_step == 3

    def test_B8_original_command_is_immutable(self, sealed_command, envelope) -> None:
        """The original command must not be modified by the pipeline."""
        original_id = sealed_command.command_id
        original_fp = sealed_command.fingerprint
        original_count = sealed_command.image_count
        _ = self._run(sealed_command, envelope)
        assert sealed_command.command_id == original_id
        assert sealed_command.fingerprint == original_fp
        assert sealed_command.image_count == original_count
        assert command_sealer.verify(sealed_command)

    def test_B9_patch_stored_separately_from_original(self, sealed_command, envelope) -> None:
        cert = self._run(sealed_command, envelope)
        assert cert.applied_patch is not None
        # Patch is a different object from the original command
        assert cert.applied_patch is not sealed_command
        # Patch is not a RawCommand (it's a PatchCandidate)
        from echolock.models import PatchCandidate, RawCommand
        assert isinstance(cert.applied_patch, PatchCandidate)
        assert not isinstance(cert.applied_patch, RawCommand)

    def test_B10_delta_certificate_all_required_fields_present(
        self, sealed_command, envelope
    ) -> None:
        cert = self._run(sealed_command, envelope)
        assert cert.original_command_id == sealed_command.command_id
        assert cert.original_command_fingerprint == sealed_command.fingerprint
        assert cert.sdr_summary is not None
        assert cert.applied_patch is not None
        assert len(cert.preserved_goals) > 0
        assert len(cert.hi_check_results) >= 4
        assert cert.gps is not None
        assert cert.verdict == VerdictStatus.ADAPT
        assert cert.verdict_precedence_step == 3
        assert cert.decision_timestamp is not None
        assert cert.certificate_hash is not None
        # AI explanation label present (may be None text, but label is set)
        assert cert.ai_explanation_label == "AI-generated"

    def test_B11_certificate_self_hash_verifies(self, sealed_command, envelope) -> None:
        cert = self._run(sealed_command, envelope)
        assert cert.verify_hash() is True

    def test_B12_semantic_replay_hash_consistent_across_10_runs(
        self, sealed_command, envelope
    ) -> None:
        """The semantic_replay_hash must be identical across all equivalent runs."""
        hashes = [
            run(
                sealed_command, envelope,
                seed=SimulatorSeed.LOW_BATTERY, record_audit=False
            ).semantic_replay_hash
            for _ in range(10)
        ]
        assert len(set(hashes)) == 1, f"Semantic replay hashes inconsistent: {set(hashes)}"

    def test_B13_audit_record_appended(self, sealed_command, envelope) -> None:
        from echolock.certificate_builder import get_audit_log
        clear_audit_log()
        _ = self._run(sealed_command, envelope)
        log = get_audit_log()
        assert len(log) == 1
        entry = log[0]
        assert entry.verdict == VerdictStatus.ADAPT
        assert entry.command_id == sealed_command.command_id

    def test_B14_audit_entry_hash_verifies(self, sealed_command, envelope) -> None:
        from echolock.certificate_builder import get_audit_log
        clear_audit_log()
        _ = self._run(sealed_command, envelope)
        log = get_audit_log()
        entry = log[0]
        assert entry.entry_hash == entry.compute_hash()
