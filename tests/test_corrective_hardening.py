"""
tests/test_corrective_hardening.py

Phase 1 corrective hardening regression tests.

Covers all findings from the independent Codex review:
  1. Command fingerprint enforcement (pipeline boundary)
  2. Authorized-patch enforcement (APC-1–APC-6)
  3. DEFER projected execution (selected delay ≥ next_comm_window_open)
  4. Delta Certificate self-hash (semantic_replay_hash included in certificate_hash)
  5. Semantic replay normalization (fresh IDs/timestamps → same hash; real changes → different)
  6. Audit-chain scope (sequence numbers, deletion, reordering, known-limitation assertion)
  7. Coverage gaps (genuine step-5 REJECT, AST-level AI isolation check)
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from echolock import command_sealer
from echolock.certificate_builder import (
    append_audit,
    clear_audit_log,
    get_audit_log,
    verify_log_chain,
)
from echolock.gps import compute_gps
from echolock.isp_generator import generate
from echolock.models import (
    AdaptationType,
    AuditEntry,
    HardInvariantCheck,
    ImageResolution,
    MissionIntentEnvelope,
    PatchCandidate,
    RawCommand,
    SafetyCheckResult,
    StateDriftReport,
    VerdictStatus,
    verify_audit_chain,
)
from echolock.pipeline import run
from echolock.safety_gate import validate_candidate, validate_original_command
from echolock.sdr_engine import compute as compute_sdr
from echolock.simulator import SimulatorSeed, arrival_state, base_timestamps, send_state
from echolock.verdict_engine import GPS_THRESHOLD, decide

UTC = timezone.utc


# ===========================================================================
# 1. Command fingerprint enforcement at pipeline boundary
# ===========================================================================

class TestPipelineFingerprintEnforcement:
    """Pipeline must reject commands with missing or invalid fingerprints before any SDR."""

    def setup_method(self):
        clear_audit_log()

    def test_unsealed_command_produces_reject(self, base_command, envelope) -> None:
        """A command that was never sealed (no fingerprint) must REJECT at step 1."""
        assert base_command.fingerprint is None
        cert = run(base_command, envelope, seed=SimulatorSeed.NOMINAL)
        assert cert.verdict == VerdictStatus.REJECT
        assert cert.verdict_precedence_step == 1
        # Reject reason must mention fingerprint
        assert "fingerprint" in cert.hi_check_results[0].invariant_id.lower() or \
               "fingerprint" in cert.hi_check_results[0].description.lower()

    def test_tampered_command_with_old_fingerprint_produces_reject(
        self, sealed_command, envelope
    ) -> None:
        """A command modified after sealing but retaining old fingerprint must REJECT."""
        # Pydantic frozen model — use model_copy to simulate field tamper
        tampered = sealed_command.model_copy(update={"image_count": 999})
        # tampered.fingerprint still holds the original fingerprint for image_count=10
        assert tampered.fingerprint == sealed_command.fingerprint  # old fingerprint kept
        assert not command_sealer.verify(tampered)  # verify must return False

        cert = run(tampered, envelope, seed=SimulatorSeed.NOMINAL)
        assert cert.verdict == VerdictStatus.REJECT
        assert cert.verdict_precedence_step == 1

    def test_valid_sealed_command_is_not_rejected_by_fingerprint(
        self, sealed_command, envelope
    ) -> None:
        """A correctly sealed command must pass the fingerprint check."""
        cert = run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL)
        # NOMINAL should execute, not reject due to fingerprint
        assert cert.verdict == VerdictStatus.EXECUTE

    def test_fingerprint_reject_certificate_is_self_consistent(
        self, base_command, envelope
    ) -> None:
        """The REJECT certificate for a missing fingerprint must self-verify."""
        cert = run(base_command, envelope, seed=SimulatorSeed.NOMINAL)
        assert cert.verdict == VerdictStatus.REJECT
        assert cert.verify_hash() is True
        assert cert.verify_semantic_replay_hash() is True

    def test_fingerprint_reject_is_audited(self, base_command, envelope) -> None:
        """The REJECT certificate from a fingerprint failure must appear in the audit log."""
        clear_audit_log()
        run(base_command, envelope, seed=SimulatorSeed.NOMINAL, record_audit=True)
        log = get_audit_log()
        assert len(log) == 1
        assert log[0].verdict == VerdictStatus.REJECT


# ===========================================================================
# 2. Authorized-patch enforcement (APC-1–APC-6)
# ===========================================================================

class TestAuthorizedPatchEnforcement:
    """Hostile and malformed PatchCandidate inputs must be rejected by SafetyGate."""

    def _original(self) -> RawCommand:
        ts = base_timestamps()
        cmd = RawCommand(
            description="Test command",
            image_count=10,
            requested_resolution=ImageResolution.K4,
            requested_power_pct=100.0,
            **ts,
        )
        return command_sealer.seal(cmd)

    def _envelope(self) -> MissionIntentEnvelope:
        from echolock.models import AdaptationAuthority
        ts = base_timestamps()
        return MissionIntentEnvelope(
            goal="Test goal",
            battery_floor_pct=20.0,
            max_equipment_temp_c=75.0,
            intended_execution_at=ts["intended_execution_at"],
            expires_at=ts["expires_at"],
            adaptation_authority=AdaptationAuthority(
                max_delay_minutes=45.0,
                min_images=3,
                allow_resolution_reduction=True,
                allow_compression=True,
                min_transmission_power_pct=40.0,
                allow_batch_split=True,
            ),
        )

    def test_negative_delay_rejected(self) -> None:
        """APC-1: negative delay_minutes must FAIL_CLOSED."""
        orig = self._original()
        env = self._envelope()
        state = arrival_state(SimulatorSeed.NOMINAL)
        patch = PatchCandidate(
            adaptation_types=[AdaptationType.DELAY],
            delay_minutes=-5.0,
        )
        vc = validate_candidate(patch, env, orig, state)
        assert vc.safety_result == SafetyCheckResult.FAIL_CLOSED
        assert any("APC-1" in v for v in vc.violated_invariants)

    def test_batch_count_zero_rejected(self) -> None:
        """APC-2: batch_count=0 must FAIL_CLOSED."""
        orig = self._original()
        env = self._envelope()
        state = arrival_state(SimulatorSeed.NOMINAL)
        patch = PatchCandidate(
            adaptation_types=[AdaptationType.SPLIT_BATCHES],
            batch_count=0,
        )
        vc = validate_candidate(patch, env, orig, state)
        assert vc.safety_result == SafetyCheckResult.FAIL_CLOSED
        assert any("APC-2" in v for v in vc.violated_invariants)

    def test_power_above_100_rejected(self) -> None:
        """APC-3: adapted_power_pct > 100 must FAIL_CLOSED."""
        orig = self._original()
        env = self._envelope()
        state = arrival_state(SimulatorSeed.NOMINAL)
        patch = PatchCandidate(
            adaptation_types=[AdaptationType.REDUCE_POWER],
            adapted_power_pct=150.0,
        )
        vc = validate_candidate(patch, env, orig, state)
        assert vc.safety_result == SafetyCheckResult.FAIL_CLOSED
        assert any("APC-3" in v for v in vc.violated_invariants)

    def test_power_above_original_rejected(self) -> None:
        """APC-3: power may only decrease — adapted_power > original must FAIL_CLOSED."""
        orig = self._original()  # requested_power_pct=100
        env = self._envelope()
        state = arrival_state(SimulatorSeed.NOMINAL)
        # Try to increase power from 100 % (already max, but test with a lower original)
        ts = base_timestamps()
        cmd_low_power = command_sealer.seal(RawCommand(
            description="Low power command",
            image_count=5,
            requested_resolution=ImageResolution.K4,
            requested_power_pct=60.0,
            **ts,
        ))
        patch = PatchCandidate(
            adaptation_types=[AdaptationType.REDUCE_POWER],
            adapted_power_pct=80.0,  # higher than original 60 %
        )
        vc = validate_candidate(patch, env, cmd_low_power, state)
        assert vc.safety_result == SafetyCheckResult.FAIL_CLOSED
        assert any("APC-3" in v and "exceed" in v for v in vc.violated_invariants)

    def test_image_count_zero_rejected(self) -> None:
        """APC-4: adapted_image_count=0 must FAIL_CLOSED."""
        orig = self._original()
        env = self._envelope()
        state = arrival_state(SimulatorSeed.NOMINAL)
        patch = PatchCandidate(
            adaptation_types=[AdaptationType.REDUCE_IMAGE_COUNT],
            adapted_image_count=0,
        )
        vc = validate_candidate(patch, env, orig, state)
        assert vc.safety_result == SafetyCheckResult.FAIL_CLOSED
        assert any("APC-4" in v for v in vc.violated_invariants)

    def test_image_count_above_original_rejected(self) -> None:
        """APC-4: adapted_image_count > original must FAIL_CLOSED."""
        orig = self._original()  # image_count=10
        env = self._envelope()
        state = arrival_state(SimulatorSeed.NOMINAL)
        patch = PatchCandidate(
            adaptation_types=[AdaptationType.REDUCE_IMAGE_COUNT],
            adapted_image_count=20,
        )
        vc = validate_candidate(patch, env, orig, state)
        assert vc.safety_result == SafetyCheckResult.FAIL_CLOSED
        assert any("APC-4" in v for v in vc.violated_invariants)

    def test_undeclared_adaptation_type_rejected(self) -> None:
        """APC-5: actual power reduction without REDUCE_POWER in adaptation_types must FAIL_CLOSED."""
        orig = self._original()
        env = self._envelope()
        state = arrival_state(SimulatorSeed.NOMINAL)
        patch = PatchCandidate(
            adaptation_types=[AdaptationType.REDUCE_IMAGE_COUNT],  # REDUCE_POWER not declared
            adapted_image_count=5,
            adapted_power_pct=70.0,  # actual change not declared
        )
        vc = validate_candidate(patch, env, orig, state)
        assert vc.safety_result == SafetyCheckResult.FAIL_CLOSED
        assert any("APC-5" in v for v in vc.violated_invariants)

    def test_phantom_adaptation_type_rejected(self) -> None:
        """APC-5: declaring DELAY but delay_minutes=0 (no actual change) must FAIL_CLOSED."""
        orig = self._original()
        env = self._envelope()
        state = arrival_state(SimulatorSeed.NOMINAL)
        patch = PatchCandidate(
            adaptation_types=[AdaptationType.DELAY, AdaptationType.REDUCE_IMAGE_COUNT],
            adapted_image_count=5,
            delay_minutes=0.0,  # DELAY declared but no actual delay
        )
        vc = validate_candidate(patch, env, orig, state)
        assert vc.safety_result == SafetyCheckResult.FAIL_CLOSED
        assert any("APC-5" in v and "phantom" in v.lower() or
                   "APC-5" in v and "not correspond" in v for v in vc.violated_invariants)

    def test_resolution_increase_rejected(self) -> None:
        """APC-5/AT-3: adapted_resolution higher quality than original must FAIL_CLOSED."""
        ts = base_timestamps()
        cmd_1080p = command_sealer.seal(RawCommand(
            description="1080p command",
            image_count=5,
            requested_resolution=ImageResolution.P1080,
            requested_power_pct=100.0,
            **ts,
        ))
        env = self._envelope()
        state = arrival_state(SimulatorSeed.NOMINAL)
        patch = PatchCandidate(
            adaptation_types=[AdaptationType.REDUCE_RESOLUTION],
            adapted_resolution=ImageResolution.K4,  # 4K > 1080p — this is an increase
        )
        vc = validate_candidate(patch, env, cmd_1080p, state)
        assert vc.safety_result == SafetyCheckResult.FAIL_CLOSED
        assert any("APC-5" in v or "AT-3" in v for v in vc.violated_invariants)

    def test_supplied_gps_ignored_eligibility_recomputed(self) -> None:
        """APC-6: a candidate with gps=0.0 but passing all HI must still receive non-zero eligibility_gps."""
        orig = self._original()
        env = self._envelope()
        state = arrival_state(SimulatorSeed.NOMINAL)
        patch = PatchCandidate(
            adaptation_types=[AdaptationType.REDUCE_IMAGE_COUNT, AdaptationType.REDUCE_POWER],
            adapted_image_count=5,
            adapted_power_pct=70.0,
            gps=0.0,  # deliberately zeroed — SafetyGate must ignore this
        )
        vc = validate_candidate(patch, env, orig, state)
        assert vc.safety_result == SafetyCheckResult.PASS
        # The recomputed GPS must be non-zero (5 images at 70 % power has real utility)
        assert vc.eligibility_gps > 0.0
        # And it must equal compute_gps directly
        expected = compute_gps(patch, orig, env)
        assert vc.eligibility_gps == pytest.approx(expected, abs=0.0001)

    def test_supplied_gps_inflated_does_not_elevate_eligibility(self) -> None:
        """APC-6: a candidate with gps=0.99 inflated must have eligibility_gps == recomputed value."""
        orig = self._original()
        env = self._envelope()
        state = arrival_state(SimulatorSeed.NOMINAL)
        patch = PatchCandidate(
            adaptation_types=[AdaptationType.REDUCE_IMAGE_COUNT],
            adapted_image_count=3,
            gps=0.99,  # inflated — SafetyGate must ignore this
        )
        vc = validate_candidate(patch, env, orig, state)
        expected = compute_gps(patch, orig, env)
        assert vc.eligibility_gps == pytest.approx(expected, abs=0.0001)
        assert vc.eligibility_gps != pytest.approx(0.99, abs=0.001)


# ===========================================================================
# 3. DEFER projected execution
# ===========================================================================

class TestDeferProjectedExecution:
    """Deferred candidates must execute no earlier than next_comm_window_open."""

    def setup_method(self):
        clear_audit_log()

    def test_defer_selected_delay_gte_window_delay(self, sealed_command, envelope) -> None:
        """COMM_LOSS: next window at 30 min — selected delay must be ≥ 30 min."""
        cert = run(sealed_command, envelope, seed=SimulatorSeed.COMM_LOSS)
        assert cert.verdict == VerdictStatus.DEFER
        if cert.applied_patch is not None:
            assert cert.applied_patch.delay_minutes >= 30.0, (
                f"Deferred patch delay {cert.applied_patch.delay_minutes} min "
                f"is less than comm window at 30 min"
            )

    def test_defer_15min_candidate_not_selected_when_window_at_30min(
        self, sealed_command, envelope
    ) -> None:
        """A 15-min delay candidate must NOT be selected when the comm window opens at 30 min."""
        s = send_state()
        a = arrival_state(SimulatorSeed.COMM_LOSS)  # next_comm_window_open = arrival + 30 min
        sdr = compute_sdr(sealed_command, envelope, s, a)
        candidates = generate(sealed_command, envelope)
        validated = [validate_candidate(c, envelope, sealed_command, a) for c in candidates]
        result = decide(sealed_command, envelope, a, sdr, validated)

        assert result.verdict == VerdictStatus.DEFER
        if result.winning_candidate is not None:
            delay = result.winning_candidate.candidate.delay_minutes
            assert delay >= 30.0, (
                f"Selected delay {delay} min precedes comm window opening at 30 min"
            )

    def test_defer_selected_delay_within_max_delay(self, sealed_command, envelope) -> None:
        """Selected deferred candidate must have delay ≤ max_delay_minutes (45 min)."""
        cert = run(sealed_command, envelope, seed=SimulatorSeed.COMM_LOSS)
        assert cert.verdict == VerdictStatus.DEFER
        if cert.applied_patch is not None:
            assert cert.applied_patch.delay_minutes <= envelope.adaptation_authority.max_delay_minutes

    def test_defer_before_mie_expiration(self, sealed_command, envelope) -> None:
        """Selected deferred candidate must execute before MIE expiration."""
        from echolock.simulator import _ARRIVAL_TIME  # type: ignore[attr-defined]
        cert = run(sealed_command, envelope, seed=SimulatorSeed.COMM_LOSS)
        assert cert.verdict == VerdictStatus.DEFER
        if cert.applied_patch is not None:
            a = arrival_state(SimulatorSeed.COMM_LOSS)
            projected_exec = envelope.intended_execution_at + timedelta(
                minutes=cert.applied_patch.delay_minutes
            )
            assert projected_exec <= envelope.expires_at, (
                f"Projected execution {projected_exec} is after expiry {envelope.expires_at}"
            )


# ===========================================================================
# 4. Delta Certificate self-hash — semantic_replay_hash included
# ===========================================================================

class TestCertificateHashIncludesSemanticReplayHash:
    """certificate_hash must include semantic_replay_hash — changing it must break verification."""

    def setup_method(self):
        clear_audit_log()

    def test_tamper_semantic_replay_hash_breaks_certificate_hash(
        self, sealed_command, envelope
    ) -> None:
        """Changing semantic_replay_hash on a complete certificate must invalidate certificate_hash."""
        cert = run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL, record_audit=False)
        tampered = cert.model_copy(update={"semantic_replay_hash": "0" * 64})
        # certificate_hash is over all fields including semantic_replay_hash
        assert tampered.verify_hash() is False

    def test_certificate_hash_changes_when_semantic_replay_hash_changes(
        self, sealed_command, envelope
    ) -> None:
        """Two certificates with identical content but different semantic_replay_hash must
        produce different certificate_hash values."""
        cert = run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL, record_audit=False)
        modified_srh = cert.model_copy(update={"semantic_replay_hash": "aaaa" + cert.semantic_replay_hash[4:]})
        assert modified_srh.compute_hash() != cert.compute_hash()

    def test_semantic_replay_hash_computed_before_certificate_hash(
        self, sealed_command, envelope
    ) -> None:
        """A freshly built certificate must have semantic_replay_hash set before certificate_hash."""
        cert = run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL, record_audit=False)
        assert cert.semantic_replay_hash is not None
        assert cert.certificate_hash is not None
        # Verify both independently
        assert cert.verify_semantic_replay_hash() is True
        assert cert.verify_hash() is True


# ===========================================================================
# 5. Semantic replay normalization
# ===========================================================================

class TestSemanticReplayNormalization:
    """semantic_replay_hash behaviour under the explicit normalisation contract."""

    def setup_method(self):
        clear_audit_log()

    def test_fresh_ids_and_timestamps_same_semantic_hash(
        self, sealed_command, envelope
    ) -> None:
        """Two certificates built with fresh UUIDs and wall-clock timestamps but
        identical logical decision must produce the same semantic_replay_hash."""
        cert_a = run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL, record_audit=False)
        cert_b = run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL, record_audit=False)

        # Verify they differ in volatile fields
        assert cert_a.certificate_id != cert_b.certificate_id
        # semantic_replay_hash must be identical
        assert cert_a.semantic_replay_hash == cert_b.semantic_replay_hash

    def test_verdict_change_produces_different_semantic_hash(
        self, sealed_command, envelope
    ) -> None:
        """Different verdicts (NOMINAL vs LOW_BATTERY) must produce different semantic_replay_hash."""
        cert_exec = run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL, record_audit=False)
        cert_adapt = run(sealed_command, envelope, seed=SimulatorSeed.LOW_BATTERY, record_audit=False)
        assert cert_exec.semantic_replay_hash != cert_adapt.semantic_replay_hash

    def test_arrival_state_change_produces_different_semantic_hash(
        self, sealed_command, envelope
    ) -> None:
        """Different arrival states (NOMINAL vs COMM_LOSS) must produce different semantic hashes."""
        cert_nominal = run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL, record_audit=False)
        cert_defer = run(sealed_command, envelope, seed=SimulatorSeed.COMM_LOSS, record_audit=False)
        assert cert_nominal.semantic_replay_hash != cert_defer.semantic_replay_hash

    def test_certificate_id_excluded_from_semantic_hash(
        self, sealed_command, envelope
    ) -> None:
        """certificate_id must NOT affect semantic_replay_hash (it is volatile)."""
        cert = run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL, record_audit=False)
        new_cert_id = cert.model_copy(update={"certificate_id": uuid4()})
        # Recompute — should give same semantic hash
        assert new_cert_id.compute_semantic_replay_hash() == cert.semantic_replay_hash

    def test_decision_timestamp_excluded_from_semantic_hash(
        self, sealed_command, envelope
    ) -> None:
        """decision_timestamp must NOT affect semantic_replay_hash."""
        cert = run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL, record_audit=False)
        future_ts = cert.decision_timestamp + timedelta(hours=24)
        shifted = cert.model_copy(update={"decision_timestamp": future_ts})
        assert shifted.compute_semantic_replay_hash() == cert.semantic_replay_hash

    def test_gps_change_produces_different_semantic_hash(
        self, sealed_command, envelope
    ) -> None:
        """Changing GPS (a meaningful decision field) must produce a different semantic_replay_hash."""
        cert = run(sealed_command, envelope, seed=SimulatorSeed.LOW_BATTERY, record_audit=False)
        tampered = cert.model_copy(update={"gps": 0.0001})
        assert tampered.compute_semantic_replay_hash() != cert.semantic_replay_hash

    def test_hi_check_results_change_produces_different_semantic_hash(
        self, sealed_command, envelope
    ) -> None:
        """Changing an HI check result must produce a different semantic_replay_hash."""
        cert = run(sealed_command, envelope, seed=SimulatorSeed.LOW_BATTERY, record_audit=False)
        checks = list(cert.hi_check_results)
        first = checks[0]
        flipped = first.model_copy(update={
            "result": SafetyCheckResult.FAIL_CLOSED
            if first.result == SafetyCheckResult.PASS
            else SafetyCheckResult.PASS
        })
        tampered = cert.model_copy(update={"hi_check_results": [flipped] + checks[1:]})
        assert tampered.compute_semantic_replay_hash() != cert.semantic_replay_hash

    def test_all_seeds_semantic_hash_stable_over_10_runs(
        self, sealed_command, envelope
    ) -> None:
        """Across all seeds, 10 repetitions must yield identical semantic_replay_hash values."""
        for seed in SimulatorSeed:
            hashes = [
                run(sealed_command, envelope, seed=seed, record_audit=False).semantic_replay_hash
                for _ in range(10)
            ]
            assert len(set(hashes)) == 1, (
                f"Seed {seed.value}: semantic_replay_hash not stable: {set(hashes)}"
            )


# ===========================================================================
# 6. Audit-chain scope — sequence numbers, deletion/reordering, known limitation
# ===========================================================================

class TestAuditChainScope:
    """In-memory hash-linked chain: sequence numbers, deletion, reordering detection."""

    def setup_method(self):
        clear_audit_log()

    def test_sequence_numbers_are_sequential(self, sealed_command, envelope) -> None:
        """Appended entries must have sequence_number 0, 1, 2, ..."""
        for seed in [SimulatorSeed.NOMINAL, SimulatorSeed.LOW_BATTERY, SimulatorSeed.OVERHEAT]:
            run(sealed_command, envelope, seed=seed)
        entries = get_audit_log()
        for i, entry in enumerate(entries):
            assert entry.sequence_number == i, (
                f"Entry {i} has sequence_number {entry.sequence_number}"
            )

    def test_sequence_number_included_in_entry_hash(self, sealed_command, envelope) -> None:
        """Tampering sequence_number must invalidate entry_hash."""
        run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL)
        entries = get_audit_log()
        tampered = entries[0].model_copy(update={"sequence_number": 99})
        assert tampered.verify_integrity() is False

    def test_interior_entry_deletion_detected(self, sealed_command, envelope) -> None:
        """Removing the middle entry of a 3-entry chain must fail chain verification."""
        for seed in [SimulatorSeed.NOMINAL, SimulatorSeed.LOW_BATTERY, SimulatorSeed.OVERHEAT]:
            run(sealed_command, envelope, seed=seed)
        entries = list(get_audit_log())
        assert len(entries) == 3
        # Delete the middle entry
        chain_without_middle = [entries[0], entries[2]]
        ok, reason = verify_audit_chain(chain_without_middle)
        assert ok is False, "Interior deletion should be detected"

    def test_entry_reordering_detected(self, sealed_command, envelope) -> None:
        """Swapping entries 0 and 1 must fail chain verification."""
        for seed in [SimulatorSeed.NOMINAL, SimulatorSeed.LOW_BATTERY]:
            run(sealed_command, envelope, seed=seed)
        entries = list(get_audit_log())
        reversed_chain = [entries[1], entries[0]]
        ok, reason = verify_audit_chain(reversed_chain)
        assert ok is False, "Reordering should be detected"

    def test_sequence_number_mismatch_detected(self, sealed_command, envelope) -> None:
        """Manually constructing a chain with out-of-order sequence numbers must fail."""
        run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL)
        entries = list(get_audit_log())
        # Inject a second entry with wrong sequence_number (2 instead of 1)
        entry0 = entries[0]
        entry1_raw = AuditEntry(
            sequence_number=2,  # wrong — should be 1
            certificate_id=uuid4(),
            certificate_hash="a" * 64,
            semantic_replay_hash="b" * 64,
            verdict=VerdictStatus.EXECUTE,
            decision_timestamp=datetime.now(UTC),
            command_id=entry0.command_id,
            command_fingerprint=entry0.command_fingerprint,
            previous_entry_hash=entry0.entry_hash or "",
        )
        entry1 = entry1_raw.model_copy(update={"entry_hash": entry1_raw.compute_hash()})
        chain = [entry0, entry1]
        ok, reason = verify_audit_chain(chain)
        assert ok is False
        assert "sequence_number" in reason

    def test_known_limitation_tail_truncation_not_detected(
        self, sealed_command, envelope
    ) -> None:
        """Document that tail-truncation is NOT detected by the current in-memory chain.

        This test asserts the limitation rather than a desired property.
        The truncated chain (entries 0..n-1) is a valid prefix and verify_audit_chain
        will return True because there is no persisted trusted head anchor.
        """
        for seed in [SimulatorSeed.NOMINAL, SimulatorSeed.LOW_BATTERY, SimulatorSeed.OVERHEAT]:
            run(sealed_command, envelope, seed=seed)
        entries = list(get_audit_log())
        assert len(entries) == 3
        # Truncate to first two — this is the known limitation
        truncated = entries[:2]
        ok, _ = verify_audit_chain(truncated)
        # This PASSES — documenting the limitation
        assert ok is True, (
            "Known limitation: tail-truncation is not detected without a persisted trusted head anchor"
        )

    def test_audit_chain_clear_is_for_testing_only(self, sealed_command, envelope) -> None:
        """clear_audit_log() resets the chain — documents that this is NOT append-only storage."""
        run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL)
        assert len(get_audit_log()) == 1
        clear_audit_log()
        assert len(get_audit_log()) == 0
        # After clearing, next appended entry gets sequence_number 0 again
        run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL)
        entries = get_audit_log()
        assert entries[0].sequence_number == 0


# ===========================================================================
# 7. Coverage gaps — genuine step-5 REJECT, AST-level AI isolation
# ===========================================================================

class TestCoverageGaps:
    """Tests for previously uncovered branches."""

    def setup_method(self):
        clear_audit_log()

    def test_genuine_step5_reject_no_valid_option(self, sealed_command, envelope) -> None:
        """Step 5 REJECT: no execute, no adapt, no defer option exists.

        Force by using an envelope with expiry in the near future so that
        DEFER is impossible (window would open past expiry), no adapt (battery fine,
        but comm window is closed and there is no valid delay window).
        We use a custom state where comm is closed and next window opens beyond max_delay.
        """
        from echolock.models import CommWindowStatus, EmergencyBeaconStatus, StateSnapshot
        from echolock.models import AdaptationAuthority

        ts = base_timestamps()
        # Short-window envelope: expires only 20 min after intended execution
        narrow_envelope = MissionIntentEnvelope(
            goal="Narrow window test",
            battery_floor_pct=20.0,
            max_equipment_temp_c=75.0,
            intended_execution_at=ts["intended_execution_at"],
            expires_at=ts["intended_execution_at"] + timedelta(minutes=20),
            adaptation_authority=AdaptationAuthority(
                max_delay_minutes=10.0,   # only 10 minutes allowed
                min_images=3,
                allow_resolution_reduction=True,
                allow_compression=True,
                min_transmission_power_pct=40.0,
                allow_batch_split=True,
            ),
        )
        # State: comm window is closed, next window opens in 50 minutes — beyond max_delay=10
        bad_state = StateSnapshot(
            battery_soc=30.0,          # low — adapted candidates will likely fail HI-1
            equipment_temp_c=50.0,
            comm_window_status=CommWindowStatus.CLOSED,
            next_comm_window_open=ts["intended_execution_at"] + timedelta(minutes=50),
            emergency_beacon=EmergencyBeaconStatus.ACTIVE,
            stored_image_count=0,
            transmission_power_pct=100.0,
            available_resolution=ImageResolution.K4,
            timestamp=ts["intended_execution_at"],
        )

        s = send_state()
        sdr = compute_sdr(sealed_command, narrow_envelope, s, bad_state)
        candidates = generate(sealed_command, narrow_envelope)
        validated = [validate_candidate(c, narrow_envelope, sealed_command, bad_state) for c in candidates]
        result = decide(sealed_command, narrow_envelope, bad_state, sdr, validated)

        assert result.verdict == VerdictStatus.REJECT
        assert result.precedence_step == 5

    def test_architecture_ast_safety_gate_has_no_ai_imports(self) -> None:
        """AST-level check: safety_gate.py source must have no import referencing AI/LLM packages.

        This is stronger than the runtime attribute check in test_architecture.py because
        it verifies the source text before any conditional/lazy imports could hide the dependency.
        """
        import pathlib
        sg_path = pathlib.Path("src/echolock/safety_gate.py")
        assert sg_path.exists(), f"Expected safety_gate.py at {sg_path}"
        source = sg_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(sg_path))

        _FORBIDDEN = {
            "openai", "anthropic", "watsonx", "ibm_generative", "ibm_watson",
            "langchain", "llama_cpp", "transformers", "torch", "tensorflow",
            "cohere", "mistralai", "google",
        }

        ai_imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(alias.name.startswith(f) for f in _FORBIDDEN):
                        ai_imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if any(module.startswith(f) for f in _FORBIDDEN):
                    ai_imports.append(module)

        assert ai_imports == [], (
            f"safety_gate.py source contains AI/LLM imports: {ai_imports}"
        )
