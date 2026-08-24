"""
tests/test_integrity.py

Phase 1 integrity hardening tests.

Covers:
1. certificate_hash tamper tests — proves that mutating any included field breaks verification.
2. semantic_replay_hash consistency tests — proves that equivalent runs produce identical values.
3. Audit-chain tamper tests — proves that chain linkage is detectable.
4. Pre-image hash binding tests — proves mie_hash, arrival_state_hash, patch_hash change
   when their source inputs change.
"""

from __future__ import annotations

import copy

import pytest

from echolock.certificate_builder import (
    append_audit,
    clear_audit_log,
    get_audit_log,
    verify_log_chain,
)
from echolock.models import (
    AuditEntry,
    SafetyCheckResult,
    VerdictStatus,
    verify_audit_chain,
)
from echolock.pipeline import run
from echolock.simulator import SimulatorSeed


# ===========================================================================
# 1. certificate_hash tamper tests
# ===========================================================================


class TestCertificateHashTamperDetection:
    """Mutating any field included in certificate_hash must break verify_hash()."""

    def _cert(self, sealed_command, envelope):
        clear_audit_log()
        return run(sealed_command, envelope, seed=SimulatorSeed.LOW_BATTERY, record_audit=False)

    def test_tamper_certificate_id(self, sealed_command, envelope) -> None:
        from uuid import uuid4
        cert = self._cert(sealed_command, envelope)
        tampered = cert.model_copy(update={"certificate_id": uuid4()})
        assert tampered.verify_hash() is False

    def test_tamper_verdict(self, sealed_command, envelope) -> None:
        cert = self._cert(sealed_command, envelope)
        # Flip ADAPT → EXECUTE
        tampered = cert.model_copy(update={"verdict": VerdictStatus.EXECUTE})
        assert tampered.verify_hash() is False

    def test_tamper_verdict_precedence_step(self, sealed_command, envelope) -> None:
        cert = self._cert(sealed_command, envelope)
        tampered = cert.model_copy(update={"verdict_precedence_step": 99})
        assert tampered.verify_hash() is False

    def test_tamper_gps(self, sealed_command, envelope) -> None:
        cert = self._cert(sealed_command, envelope)
        tampered = cert.model_copy(update={"gps": 0.9999})
        assert tampered.verify_hash() is False

    def test_tamper_decision_timestamp(self, sealed_command, envelope) -> None:
        from datetime import datetime, timezone, timedelta
        cert = self._cert(sealed_command, envelope)
        new_ts = cert.decision_timestamp + timedelta(seconds=1)
        tampered = cert.model_copy(update={"decision_timestamp": new_ts})
        assert tampered.verify_hash() is False

    def test_tamper_original_command_fingerprint(self, sealed_command, envelope) -> None:
        cert = self._cert(sealed_command, envelope)
        tampered = cert.model_copy(update={"original_command_fingerprint": "deadbeef" * 8})
        assert tampered.verify_hash() is False

    def test_tamper_original_command_id(self, sealed_command, envelope) -> None:
        from uuid import uuid4
        cert = self._cert(sealed_command, envelope)
        tampered = cert.model_copy(update={"original_command_id": uuid4()})
        assert tampered.verify_hash() is False

    def test_tamper_mie_hash(self, sealed_command, envelope) -> None:
        cert = self._cert(sealed_command, envelope)
        tampered = cert.model_copy(update={"mie_hash": "0" * 64})
        assert tampered.verify_hash() is False

    def test_tamper_arrival_state_hash(self, sealed_command, envelope) -> None:
        cert = self._cert(sealed_command, envelope)
        tampered = cert.model_copy(update={"arrival_state_hash": "0" * 64})
        assert tampered.verify_hash() is False

    def test_tamper_patch_hash(self, sealed_command, envelope) -> None:
        cert = self._cert(sealed_command, envelope)
        tampered = cert.model_copy(update={"patch_hash": "0" * 64})
        assert tampered.verify_hash() is False

    def test_tamper_patch_id(self, sealed_command, envelope) -> None:
        """patch_id is included in certificate_hash — changing it must break verification."""
        from uuid import uuid4
        cert = self._cert(sealed_command, envelope)
        assert cert.applied_patch is not None
        new_patch = cert.applied_patch.model_copy(update={"patch_id": uuid4()})
        tampered = cert.model_copy(update={"applied_patch": new_patch})
        assert tampered.verify_hash() is False

    def test_tamper_hi_check_result(self, sealed_command, envelope) -> None:
        """Flipping a PASS to FAIL_CLOSED in invariant results must break verification."""
        cert = self._cert(sealed_command, envelope)
        checks = list(cert.hi_check_results)
        # flip the first check result
        first = checks[0]
        flipped_result = (
            SafetyCheckResult.FAIL_CLOSED
            if first.result == SafetyCheckResult.PASS
            else SafetyCheckResult.PASS
        )
        flipped = first.model_copy(update={"result": flipped_result})
        new_checks = [flipped] + checks[1:]
        tampered = cert.model_copy(update={"hi_check_results": new_checks})
        assert tampered.verify_hash() is False

    def test_tamper_verifier_version(self, sealed_command, envelope) -> None:
        cert = self._cert(sealed_command, envelope)
        tampered = cert.model_copy(update={"verifier_version": "0.0.0"})
        assert tampered.verify_hash() is False

    def test_tamper_scenario_id(self, sealed_command, envelope) -> None:
        cert = self._cert(sealed_command, envelope)
        tampered = cert.model_copy(update={"scenario_id": "TAMPERED_SCENARIO"})
        assert tampered.verify_hash() is False

    def test_valid_cert_verifies(self, sealed_command, envelope) -> None:
        """Baseline: an untampered certificate must verify."""
        cert = self._cert(sealed_command, envelope)
        assert cert.verify_hash() is True


# ===========================================================================
# 2. semantic_replay_hash — equivalent runs produce identical values
# ===========================================================================


class TestSemanticReplayHash:
    """Equivalent repeated runs must yield identical semantic_replay_hash."""

    @pytest.mark.parametrize("seed", list(SimulatorSeed))
    def test_semantic_replay_hash_stable_across_10_runs(
        self, seed, sealed_command, envelope
    ) -> None:
        clear_audit_log()
        hashes = [
            run(sealed_command, envelope, seed=seed, record_audit=False).semantic_replay_hash
            for _ in range(10)
        ]
        assert len(set(hashes)) == 1, (
            f"Seed {seed.value}: semantic_replay_hash differs across runs: {set(hashes)}"
        )

    def test_certificate_hash_differs_from_semantic_replay_hash(
        self, sealed_command, envelope
    ) -> None:
        """The two hashes must be distinct values (they cover different content)."""
        clear_audit_log()
        cert = run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL, record_audit=False)
        assert cert.certificate_hash != cert.semantic_replay_hash

    def test_different_decisions_produce_different_semantic_hashes(
        self, sealed_command, envelope
    ) -> None:
        """Different seed (different arrival state = different decision) → different semantic hash."""
        clear_audit_log()
        cert_nominal = run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL, record_audit=False)
        cert_low = run(sealed_command, envelope, seed=SimulatorSeed.LOW_BATTERY, record_audit=False)
        assert cert_nominal.semantic_replay_hash != cert_low.semantic_replay_hash

    def test_semantic_hash_verifies_on_every_run(self, sealed_command, envelope) -> None:
        for seed in SimulatorSeed:
            clear_audit_log()
            cert = run(sealed_command, envelope, seed=seed, record_audit=False)
            assert cert.verify_semantic_replay_hash() is True

    def test_tamper_decision_breaks_semantic_replay_hash(
        self, sealed_command, envelope
    ) -> None:
        """Changing the verdict must also break the semantic_replay_hash."""
        clear_audit_log()
        cert = run(sealed_command, envelope, seed=SimulatorSeed.LOW_BATTERY, record_audit=False)
        tampered = cert.model_copy(update={"verdict": VerdictStatus.REJECT})
        assert tampered.verify_semantic_replay_hash() is False

    def test_tamper_gps_breaks_semantic_replay_hash(self, sealed_command, envelope) -> None:
        clear_audit_log()
        cert = run(sealed_command, envelope, seed=SimulatorSeed.LOW_BATTERY, record_audit=False)
        tampered = cert.model_copy(update={"gps": 0.0001})
        assert tampered.verify_semantic_replay_hash() is False

    def test_tamper_mie_semantic_hash_breaks_semantic_replay_hash(
        self, sealed_command, envelope
    ) -> None:
        """mie_semantic_hash (not mie_hash) is the semantic replay identity for MIE content."""
        clear_audit_log()
        cert = run(sealed_command, envelope, seed=SimulatorSeed.LOW_BATTERY, record_audit=False)
        tampered = cert.model_copy(update={"mie_semantic_hash": "0" * 64})
        assert tampered.verify_semantic_replay_hash() is False

    def test_tamper_mie_hash_does_not_break_semantic_replay_hash(
        self, sealed_command, envelope
    ) -> None:
        """mie_hash is a cryptographic source-identity field (not semantic).
        Changing it changes certificate_hash but not semantic_replay_hash."""
        clear_audit_log()
        cert = run(sealed_command, envelope, seed=SimulatorSeed.LOW_BATTERY, record_audit=False)
        tampered = cert.model_copy(update={"mie_hash": "0" * 64})
        # semantic_replay_hash uses mie_semantic_hash, not mie_hash
        assert tampered.verify_semantic_replay_hash() is True
        # But certificate_hash IS broken (mie_hash is included in it)
        assert tampered.verify_hash() is False

    def test_patch_id_does_not_affect_semantic_replay_hash(
        self, sealed_command, envelope
    ) -> None:
        """patch_id is excluded from semantic_replay_hash — changing it must NOT break it."""
        from uuid import uuid4
        clear_audit_log()
        cert = run(sealed_command, envelope, seed=SimulatorSeed.LOW_BATTERY, record_audit=False)
        assert cert.applied_patch is not None
        # Recompute the patch_hash for the new patch_id so patch_hash stays consistent
        new_patch = cert.applied_patch.model_copy(update={"patch_id": uuid4()})
        new_patch_hash = new_patch.content_hash()
        tampered = cert.model_copy(update={
            "applied_patch": new_patch,
            "patch_hash": new_patch_hash,
        })
        # semantic_replay_hash uses patch_hash (not patch_id directly), so it must
        # change when patch_hash changes.  But if we keep patch_hash the same only
        # changing patch_id, semantic_replay_hash is unaffected.
        cert_same_patch_hash = cert.model_copy(update={"applied_patch": new_patch})
        # patch_hash was NOT updated — semantic content unchanged
        assert cert_same_patch_hash.verify_semantic_replay_hash() is True

    def test_decision_timestamp_does_not_affect_semantic_replay_hash(
        self, sealed_command, envelope
    ) -> None:
        """decision_timestamp is excluded from semantic_replay_hash."""
        from datetime import timedelta
        clear_audit_log()
        cert = run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL, record_audit=False)
        new_ts = cert.decision_timestamp + timedelta(hours=1)
        tampered = cert.model_copy(update={"decision_timestamp": new_ts})
        assert tampered.verify_semantic_replay_hash() is True


# ===========================================================================
# 3. Pre-image hash binding
# ===========================================================================


class TestPreImageHashes:
    """mie_hash, arrival_state_hash, and patch_hash must track their source objects."""

    def test_mie_hash_changes_when_mie_changes(self, sealed_command, envelope) -> None:
        from echolock.models import AdaptationAuthority, MissionIntentEnvelope
        from echolock.simulator import base_timestamps
        ts = base_timestamps()
        modified_envelope = MissionIntentEnvelope(
            goal="MODIFIED GOAL",
            battery_floor_pct=envelope.battery_floor_pct,
            max_equipment_temp_c=envelope.max_equipment_temp_c,
            intended_execution_at=ts["intended_execution_at"],
            expires_at=ts["expires_at"],
        )
        original_hash = envelope.content_hash()
        modified_hash = modified_envelope.content_hash()
        assert original_hash != modified_hash

    def test_arrival_state_hash_changes_when_state_changes(self, sealed_command, envelope) -> None:
        from echolock.simulator import arrival_state
        state_a = arrival_state(SimulatorSeed.NOMINAL)
        state_b = arrival_state(SimulatorSeed.LOW_BATTERY)
        assert state_a.content_hash() != state_b.content_hash()

    def test_patch_hash_changes_when_patch_changes(self, sealed_command, envelope) -> None:
        from echolock.models import AdaptationType, PatchCandidate
        patch_a = PatchCandidate(
            adaptation_types=[AdaptationType.REDUCE_IMAGE_COUNT],
            adapted_image_count=5,
            gps=0.75,
        )
        patch_b = PatchCandidate(
            adaptation_types=[AdaptationType.REDUCE_IMAGE_COUNT],
            adapted_image_count=3,  # different
            gps=0.75,
        )
        assert patch_a.content_hash() != patch_b.content_hash()

    def test_patch_semantic_hash_ignores_patch_id(self) -> None:
        from uuid import uuid4
        from echolock.models import AdaptationType, PatchCandidate
        patch = PatchCandidate(
            adaptation_types=[AdaptationType.REDUCE_IMAGE_COUNT],
            adapted_image_count=5,
            gps=0.75,
        )
        new_patch = patch.model_copy(update={"patch_id": uuid4()})
        assert patch.semantic_hash() == new_patch.semantic_hash()

    def test_cert_patch_hash_matches_applied_patch_content_hash(
        self, sealed_command, envelope
    ) -> None:
        clear_audit_log()
        cert = run(sealed_command, envelope, seed=SimulatorSeed.LOW_BATTERY, record_audit=False)
        assert cert.applied_patch is not None
        assert cert.patch_hash == cert.applied_patch.content_hash()


# ===========================================================================
# 4. Audit-chain tamper tests
# ===========================================================================


class TestAuditChain:
    """Audit chain integrity and tamper detection."""

    def test_single_entry_chain_is_valid(self, sealed_command, envelope) -> None:
        clear_audit_log()
        run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL)
        ok, reason = verify_log_chain()
        assert ok, f"Chain failed: {reason}"

    def test_multi_entry_chain_is_valid(self, sealed_command, envelope) -> None:
        clear_audit_log()
        for seed in [SimulatorSeed.NOMINAL, SimulatorSeed.LOW_BATTERY]:
            run(sealed_command, envelope, seed=seed)
        ok, reason = verify_log_chain()
        assert ok, f"Chain failed: {reason}"

    def test_chain_links_correctly(self, sealed_command, envelope) -> None:
        clear_audit_log()
        for seed in [SimulatorSeed.NOMINAL, SimulatorSeed.LOW_BATTERY, SimulatorSeed.OVERHEAT]:
            run(sealed_command, envelope, seed=seed)
        entries = get_audit_log()
        assert len(entries) == 3
        assert entries[0].previous_entry_hash == ""
        assert entries[1].previous_entry_hash == entries[0].entry_hash
        assert entries[2].previous_entry_hash == entries[1].entry_hash

    def test_tamper_entry_hash_detected(self, sealed_command, envelope) -> None:
        """Mutating entry_hash itself must make verify_integrity() return False."""
        clear_audit_log()
        run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL)
        entries = get_audit_log()
        entry = entries[0]
        tampered = entry.model_copy(update={"entry_hash": "0" * 64})
        assert tampered.verify_integrity() is False

    def test_tamper_certificate_hash_in_entry_detected(
        self, sealed_command, envelope
    ) -> None:
        """Changing certificate_hash inside an AuditEntry breaks entry_hash."""
        clear_audit_log()
        run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL)
        entries = get_audit_log()
        entry = entries[0]
        tampered = entry.model_copy(update={"certificate_hash": "deadbeef" * 8})
        # entry_hash no longer matches because certificate_hash is included
        assert tampered.verify_integrity() is False

    def test_tamper_verdict_in_entry_detected(self, sealed_command, envelope) -> None:
        clear_audit_log()
        run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL)
        entries = get_audit_log()
        entry = entries[0]
        tampered = entry.model_copy(update={"verdict": VerdictStatus.REJECT})
        assert tampered.verify_integrity() is False

    def test_tamper_previous_entry_hash_breaks_chain(
        self, sealed_command, envelope
    ) -> None:
        """Tampering previous_entry_hash changes the entry's content, so entry_hash verification fails.

        The chain verifier detects this via the entry_hash check (previous_entry_hash is
        included in each entry's hash computation).
        """
        clear_audit_log()
        run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL)
        run(sealed_command, envelope, seed=SimulatorSeed.LOW_BATTERY)
        entries = list(get_audit_log())
        # Tamper the second entry's previous_entry_hash (but keep entry_hash unchanged)
        tampered_second = entries[1].model_copy(update={"previous_entry_hash": "0" * 64})
        tampered_chain = [entries[0], tampered_second]
        ok, reason = verify_audit_chain(tampered_chain)
        assert ok is False
        # entry_hash verification fails because previous_entry_hash is included in it
        assert "entry_hash verification failed" in reason or "previous_entry_hash" in reason

    def test_empty_chain_is_valid(self) -> None:
        ok, reason = verify_audit_chain([])
        assert ok is True
        assert reason == ""

    def test_first_entry_must_have_empty_previous_hash(
        self, sealed_command, envelope
    ) -> None:
        clear_audit_log()
        run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL)
        entries = list(get_audit_log())
        # Inject non-empty previous_entry_hash in first entry
        tampered = entries[0].model_copy(update={"previous_entry_hash": "notempty"})
        ok, reason = verify_audit_chain([tampered])
        assert ok is False
        assert "previous_entry_hash" in reason

    def test_entry_id_included_in_entry_hash(self, sealed_command, envelope) -> None:
        """Changing entry_id must break entry_hash verification."""
        from uuid import uuid4
        clear_audit_log()
        run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL)
        entries = get_audit_log()
        entry = entries[0]
        tampered = entry.model_copy(update={"entry_id": uuid4()})
        assert tampered.verify_integrity() is False

    def test_semantic_replay_hash_carried_in_audit_entry(
        self, sealed_command, envelope
    ) -> None:
        clear_audit_log()
        cert = run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL)
        entries = get_audit_log()
        assert entries[0].semantic_replay_hash == cert.semantic_replay_hash
