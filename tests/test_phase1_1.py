"""
tests/test_phase1_1.py

Phase 1.1 integrity correction tests.

Covers:
1. MIE seal enforcement — seal/verify, tamper detection on every trust field,
   send_time_assumptions nested-dict mutation, pipeline REJECT on unsealed/tampered MIE.
2. Semantic replay identity — fresh object IDs + shifted absolute timestamps produce
   the same semantic_replay_hash; meaningful changes alter it.
3. certificate_hash differs across repeated runs (explicit assertion).
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from echolock import command_sealer, mie_sealer
from echolock.certificate_builder import clear_audit_log
from echolock.models import (
    AdaptationAuthority,
    ImageResolution,
    MissionIntentEnvelope,
    RawCommand,
    VerdictStatus,
)
from echolock.pipeline import run
from echolock.simulator import SimulatorSeed, base_timestamps

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_raw_envelope(ts: dict, *, goal: str = "Test goal") -> MissionIntentEnvelope:
    """Construct an unsealed MissionIntentEnvelope with standard fields."""
    return MissionIntentEnvelope(
        goal=goal,
        send_time_assumptions={
            "battery_soc": 85.0,
            "equipment_temp_c": 42.0,
            "comm_window_status": "OPEN",
            "emergency_beacon": "ACTIVE",
        },
        battery_floor_pct=20.0,
        max_equipment_temp_c=75.0,
        emergency_beacon_must_remain_active=True,
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
        priority=1,
    )


def _make_sealed_command(ts: dict) -> RawCommand:
    cmd = RawCommand(
        description="Transmit 10 rock images at 4K resolution and high power",
        image_count=10,
        requested_resolution=ImageResolution.K4,
        requested_power_pct=100.0,
        **ts,
    )
    return command_sealer.seal(cmd)


# ===========================================================================
# 1. MIE sealer — seal / verify
# ===========================================================================

class TestMIESealer:
    """Unit tests for mie_sealer.seal() and mie_sealer.verify()."""

    def test_seal_sets_mie_fingerprint(self) -> None:
        ts = base_timestamps()
        env = _make_raw_envelope(ts)
        assert env.mie_fingerprint is None
        sealed = mie_sealer.seal(env)
        assert sealed.mie_fingerprint is not None
        assert len(sealed.mie_fingerprint) == 64  # SHA-256 hex

    def test_verify_sealed_envelope_passes(self) -> None:
        ts = base_timestamps()
        sealed = mie_sealer.seal(_make_raw_envelope(ts))
        assert mie_sealer.verify(sealed) is True

    def test_verify_unsealed_envelope_fails(self) -> None:
        ts = base_timestamps()
        env = _make_raw_envelope(ts)
        assert mie_sealer.verify(env) is False

    def test_fingerprint_is_deterministic(self) -> None:
        ts = base_timestamps()
        env = _make_raw_envelope(ts)
        a = mie_sealer.seal(env)
        b = mie_sealer.seal(env)
        assert a.mie_fingerprint == b.mie_fingerprint

    def test_original_envelope_not_modified_by_seal(self) -> None:
        ts = base_timestamps()
        env = _make_raw_envelope(ts)
        _ = mie_sealer.seal(env)
        assert env.mie_fingerprint is None  # frozen — model_copy returned a new object

    def test_seal_covers_goal(self) -> None:
        ts = base_timestamps()
        sealed = mie_sealer.seal(_make_raw_envelope(ts))
        tampered = sealed.model_copy(update={"goal": "TAMPERED GOAL"})
        assert mie_sealer.verify(tampered) is False

    def test_seal_covers_battery_floor(self) -> None:
        ts = base_timestamps()
        sealed = mie_sealer.seal(_make_raw_envelope(ts))
        tampered = sealed.model_copy(update={"battery_floor_pct": 5.0})
        assert mie_sealer.verify(tampered) is False

    def test_seal_covers_max_equipment_temp(self) -> None:
        ts = base_timestamps()
        sealed = mie_sealer.seal(_make_raw_envelope(ts))
        tampered = sealed.model_copy(update={"max_equipment_temp_c": 999.0})
        assert mie_sealer.verify(tampered) is False

    def test_seal_covers_emergency_beacon_flag(self) -> None:
        ts = base_timestamps()
        sealed = mie_sealer.seal(_make_raw_envelope(ts))
        tampered = sealed.model_copy(update={"emergency_beacon_must_remain_active": False})
        assert mie_sealer.verify(tampered) is False

    def test_seal_covers_intended_execution_at(self) -> None:
        ts = base_timestamps()
        sealed = mie_sealer.seal(_make_raw_envelope(ts))
        new_ts = ts["intended_execution_at"] + timedelta(hours=1)
        # expires_at must stay after intended_execution_at
        tampered = sealed.model_copy(update={
            "intended_execution_at": new_ts,
            "expires_at": new_ts + timedelta(hours=1),
        })
        assert mie_sealer.verify(tampered) is False

    def test_seal_covers_expires_at(self) -> None:
        ts = base_timestamps()
        sealed = mie_sealer.seal(_make_raw_envelope(ts))
        new_expiry = ts["expires_at"] + timedelta(hours=2)
        tampered = sealed.model_copy(update={"expires_at": new_expiry})
        assert mie_sealer.verify(tampered) is False

    def test_seal_covers_adaptation_authority_max_delay(self) -> None:
        ts = base_timestamps()
        sealed = mie_sealer.seal(_make_raw_envelope(ts))
        new_auth = sealed.adaptation_authority.model_copy(update={"max_delay_minutes": 1.0})
        tampered = sealed.model_copy(update={"adaptation_authority": new_auth})
        assert mie_sealer.verify(tampered) is False

    def test_seal_covers_adaptation_authority_min_images(self) -> None:
        ts = base_timestamps()
        sealed = mie_sealer.seal(_make_raw_envelope(ts))
        new_auth = sealed.adaptation_authority.model_copy(update={"min_images": 9})
        tampered = sealed.model_copy(update={"adaptation_authority": new_auth})
        assert mie_sealer.verify(tampered) is False

    def test_seal_covers_adaptation_authority_compression_flag(self) -> None:
        ts = base_timestamps()
        sealed = mie_sealer.seal(_make_raw_envelope(ts))
        new_auth = sealed.adaptation_authority.model_copy(update={"allow_compression": False})
        tampered = sealed.model_copy(update={"adaptation_authority": new_auth})
        assert mie_sealer.verify(tampered) is False

    def test_seal_covers_gps_weights(self) -> None:
        ts = base_timestamps()
        sealed = mie_sealer.seal(_make_raw_envelope(ts))
        tampered = sealed.model_copy(update={
            "gps_weight_scientific_utility": 0.25,
            "gps_weight_output_quantity": 0.25,
            "gps_weight_timeliness": 0.25,
            "gps_weight_operator_preferences": 0.25,
        })
        assert mie_sealer.verify(tampered) is False

    def test_seal_covers_priority(self) -> None:
        ts = base_timestamps()
        sealed = mie_sealer.seal(_make_raw_envelope(ts))
        tampered = sealed.model_copy(update={"priority": 99})
        assert mie_sealer.verify(tampered) is False

    def test_seal_covers_envelope_id(self) -> None:
        """Changing envelope_id after sealing must break the fingerprint."""
        ts = base_timestamps()
        sealed = mie_sealer.seal(_make_raw_envelope(ts))
        tampered = sealed.model_copy(update={"envelope_id": uuid4()})
        assert mie_sealer.verify(tampered) is False


# ===========================================================================
# 2. send_time_assumptions nested-dict mutation tests
# ===========================================================================

class TestSendTimeAssumptionsMutationDetection:
    """The MIE seal must cover send_time_assumptions including all nested values."""

    def test_seal_covers_send_time_assumptions_battery_soc(self) -> None:
        ts = base_timestamps()
        sealed = mie_sealer.seal(_make_raw_envelope(ts))
        # Simulate mutation of a nested assumption value
        new_assumptions = dict(sealed.send_time_assumptions)
        new_assumptions["battery_soc"] = 99.9  # mutated
        tampered = sealed.model_copy(update={"send_time_assumptions": new_assumptions})
        assert mie_sealer.verify(tampered) is False

    def test_seal_covers_send_time_assumptions_temp(self) -> None:
        ts = base_timestamps()
        sealed = mie_sealer.seal(_make_raw_envelope(ts))
        new_assumptions = dict(sealed.send_time_assumptions)
        new_assumptions["equipment_temp_c"] = -50.0
        tampered = sealed.model_copy(update={"send_time_assumptions": new_assumptions})
        assert mie_sealer.verify(tampered) is False

    def test_seal_covers_send_time_assumptions_added_key(self) -> None:
        ts = base_timestamps()
        sealed = mie_sealer.seal(_make_raw_envelope(ts))
        new_assumptions = dict(sealed.send_time_assumptions)
        new_assumptions["injected_key"] = "injected_value"
        tampered = sealed.model_copy(update={"send_time_assumptions": new_assumptions})
        assert mie_sealer.verify(tampered) is False

    def test_seal_covers_send_time_assumptions_removed_key(self) -> None:
        ts = base_timestamps()
        sealed = mie_sealer.seal(_make_raw_envelope(ts))
        new_assumptions = {k: v for k, v in sealed.send_time_assumptions.items()
                           if k != "emergency_beacon"}
        tampered = sealed.model_copy(update={"send_time_assumptions": new_assumptions})
        assert mie_sealer.verify(tampered) is False

    def test_seal_covers_empty_send_time_assumptions(self) -> None:
        """An empty assumptions dict seals differently than a populated one."""
        ts = base_timestamps()
        raw_with_data = _make_raw_envelope(ts)
        raw_empty = MissionIntentEnvelope(
            goal=raw_with_data.goal,
            send_time_assumptions={},
            battery_floor_pct=raw_with_data.battery_floor_pct,
            max_equipment_temp_c=raw_with_data.max_equipment_temp_c,
            intended_execution_at=ts["intended_execution_at"],
            expires_at=ts["expires_at"],
        )
        sealed_with_data = mie_sealer.seal(raw_with_data)
        sealed_empty = mie_sealer.seal(raw_empty)
        assert sealed_with_data.mie_fingerprint != sealed_empty.mie_fingerprint

    def test_send_time_assumptions_deep_copy_on_seal(self) -> None:
        """The sealed MIE is detached from the caller-owned assumptions mapping."""
        ts = base_timestamps()
        # Build with a dict we hold a reference to
        assumptions = {"battery_soc": 85.0}
        raw = MissionIntentEnvelope(
            goal="Test",
            send_time_assumptions=assumptions,
            battery_floor_pct=20.0,
            max_equipment_temp_c=75.0,
            intended_execution_at=ts["intended_execution_at"],
            expires_at=ts["expires_at"],
        )
        sealed = mie_sealer.seal(raw)
        original_fp = sealed.mie_fingerprint
        assumptions["battery_soc"] = 1.0
        assert raw.send_time_assumptions["battery_soc"] == 85.0
        assert sealed.send_time_assumptions["battery_soc"] == 85.0
        assert mie_sealer.verify(sealed) is True
        assert sealed.mie_fingerprint == original_fp

    def test_sealed_assumptions_reject_direct_mutation(self) -> None:
        sealed = mie_sealer.seal(_make_raw_envelope(base_timestamps()))
        with pytest.raises(TypeError, match="immutable"):
            sealed.send_time_assumptions["battery_soc"] = 1.0

    def test_sealed_assumptions_reject_nested_mutation(self) -> None:
        ts = base_timestamps()
        raw = MissionIntentEnvelope(
            goal="Nested",
            send_time_assumptions={"nested": {"mode": "SAFE"}, "samples": [1, 2]},
            intended_execution_at=ts["intended_execution_at"],
            expires_at=ts["expires_at"],
        )
        sealed = mie_sealer.seal(raw)
        with pytest.raises(TypeError, match="immutable"):
            sealed.send_time_assumptions["nested"]["mode"] = "UNSAFE"
        assert isinstance(sealed.send_time_assumptions["samples"], tuple)
        with pytest.raises(AttributeError):
            sealed.send_time_assumptions["samples"].append(3)

    def test_sealed_and_raw_do_not_share_nested_objects(self) -> None:
        ts = base_timestamps()
        raw = MissionIntentEnvelope(
            goal="Nested",
            send_time_assumptions={"nested": {"mode": "SAFE"}},
            intended_execution_at=ts["intended_execution_at"],
            expires_at=ts["expires_at"],
        )
        sealed = mie_sealer.seal(raw)
        assert raw.send_time_assumptions is not sealed.send_time_assumptions
        assert raw.send_time_assumptions["nested"] is not sealed.send_time_assumptions["nested"]


# ===========================================================================
# 3. Pipeline REJECT on unsealed / tampered MIE
# ===========================================================================

class TestPipelineMIESealEnforcement:
    """Pipeline must REJECT at step 1 when MIE seal is missing or invalid."""

    def setup_method(self):
        clear_audit_log()

    def test_unsealed_mie_produces_reject(self, sealed_command) -> None:
        """A MIE without a fingerprint must REJECT at pipeline boundary."""
        ts = base_timestamps()
        unsealed_env = _make_raw_envelope(ts)
        assert unsealed_env.mie_fingerprint is None

        cert = run(sealed_command, unsealed_env, seed=SimulatorSeed.NOMINAL)
        assert cert.verdict == VerdictStatus.REJECT
        assert cert.verdict_precedence_step == 1
        assert any("PIPELINE-MIE" in c.invariant_id for c in cert.hi_check_results)

    def test_tampered_mie_produces_reject(self, sealed_command) -> None:
        """A MIE tampered after sealing must REJECT at pipeline boundary."""
        ts = base_timestamps()
        sealed_env = mie_sealer.seal(_make_raw_envelope(ts))
        # Tamper: change goal after sealing, keeping the old fingerprint
        tampered_env = sealed_env.model_copy(update={"goal": "ATTACKER GOAL"})
        assert not mie_sealer.verify(tampered_env)

        cert = run(sealed_command, tampered_env, seed=SimulatorSeed.NOMINAL)
        assert cert.verdict == VerdictStatus.REJECT
        assert cert.verdict_precedence_step == 1
        assert any("PIPELINE-MIE" in c.invariant_id for c in cert.hi_check_results)

    def test_tampered_mie_battery_floor_produces_reject(self, sealed_command) -> None:
        """Lowering battery_floor after sealing must REJECT."""
        ts = base_timestamps()
        sealed_env = mie_sealer.seal(_make_raw_envelope(ts))
        tampered = sealed_env.model_copy(update={"battery_floor_pct": 0.0})
        cert = run(sealed_command, tampered, seed=SimulatorSeed.NOMINAL)
        assert cert.verdict == VerdictStatus.REJECT

    def test_tampered_mie_gps_weights_produces_reject(self, sealed_command) -> None:
        """Changing GPS weights after sealing must REJECT."""
        ts = base_timestamps()
        sealed_env = mie_sealer.seal(_make_raw_envelope(ts))
        tampered = sealed_env.model_copy(update={
            "gps_weight_scientific_utility": 0.99,
            "gps_weight_output_quantity": 0.0,
            "gps_weight_timeliness": 0.0,
            "gps_weight_operator_preferences": 0.01,
        })
        cert = run(sealed_command, tampered, seed=SimulatorSeed.NOMINAL)
        assert cert.verdict == VerdictStatus.REJECT

    def test_tampered_mie_send_time_assumptions_produces_reject(self, sealed_command) -> None:
        """Mutating send_time_assumptions after sealing must REJECT."""
        ts = base_timestamps()
        sealed_env = mie_sealer.seal(_make_raw_envelope(ts))
        new_assumptions = dict(sealed_env.send_time_assumptions)
        new_assumptions["battery_soc"] = 5.0  # adversarial assumption change
        tampered = sealed_env.model_copy(update={"send_time_assumptions": new_assumptions})
        cert = run(sealed_command, tampered, seed=SimulatorSeed.NOMINAL)
        assert cert.verdict == VerdictStatus.REJECT

    def test_mie_reject_certificate_is_self_consistent(self, sealed_command) -> None:
        """The REJECT certificate from an MIE seal failure must self-verify."""
        ts = base_timestamps()
        unsealed_env = _make_raw_envelope(ts)
        cert = run(sealed_command, unsealed_env, seed=SimulatorSeed.NOMINAL)
        assert cert.verify_hash() is True
        assert cert.verify_semantic_replay_hash() is True

    def test_sealed_mie_allows_pipeline_to_proceed(self, sealed_command, envelope) -> None:
        """A correctly sealed MIE must NOT be rejected by the pipeline."""
        assert mie_sealer.verify(envelope)
        cert = run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL)
        assert cert.verdict == VerdictStatus.EXECUTE


# ===========================================================================
# 4. Semantic replay identity — fresh objects with same logical content
# ===========================================================================

class TestSemanticReplayIdentityFreshObjects:
    """Fresh UUIDs and shifted absolute timestamps must not change semantic_replay_hash."""

    def setup_method(self):
        clear_audit_log()

    def _make_offset_run(self, offset_hours: float, seed: SimulatorSeed = SimulatorSeed.NOMINAL):
        """Build a completely fresh command + envelope with timestamps shifted by offset_hours,
        preserving all relative timing relationships."""
        ts = base_timestamps()
        delta = timedelta(hours=offset_hours)

        # Fresh command — new command_id (uuid4 default), all timestamps shifted
        raw_cmd = RawCommand(
            description="Transmit 10 rock images at 4K resolution and high power",
            image_count=10,
            requested_resolution=ImageResolution.K4,
            requested_power_pct=100.0,
            sent_at=ts["sent_at"] + delta,
            arrived_at=ts["arrived_at"] + delta,
            intended_execution_at=ts["intended_execution_at"] + delta,
            expires_at=ts["expires_at"] + delta,
        )
        fresh_cmd = command_sealer.seal(raw_cmd)

        # Fresh envelope — new envelope_id (uuid4 default), all timestamps shifted
        raw_env = MissionIntentEnvelope(
            goal="Transmit 10 high-quality rock images to Earth for geological analysis",
            send_time_assumptions={
                "battery_soc": 85.0,
                "equipment_temp_c": 42.0,
                "comm_window_status": "OPEN",
                "emergency_beacon": "ACTIVE",
            },
            battery_floor_pct=20.0,
            max_equipment_temp_c=75.0,
            emergency_beacon_must_remain_active=True,
            intended_execution_at=ts["intended_execution_at"] + delta,
            expires_at=ts["expires_at"] + delta,
            adaptation_authority=AdaptationAuthority(
                max_delay_minutes=45.0,
                min_images=3,
                allow_resolution_reduction=True,
                allow_compression=True,
                min_transmission_power_pct=40.0,
                allow_batch_split=True,
            ),
            priority=1,
        )
        fresh_env = mie_sealer.seal(raw_env)

        return run(fresh_cmd, fresh_env, seed=seed, record_audit=False)

    def test_fresh_ids_and_shifted_timestamps_same_semantic_hash(self) -> None:
        """Two runs with completely fresh object IDs and timestamps shifted by 24 hours
        must produce the same semantic_replay_hash.

        The simulator produces a fixed arrival state so arrival_state_hash is the same;
        the volatile per-run fields that do differ are certificate_id, original_command_id,
        and mie_hash (which includes the new envelope_id).
        """
        cert_base = self._make_offset_run(offset_hours=0)
        cert_shifted = self._make_offset_run(offset_hours=24)

        # Per-run volatile fields must differ
        assert cert_base.certificate_id != cert_shifted.certificate_id
        assert cert_base.original_command_id != cert_shifted.original_command_id
        assert cert_base.mie_hash != cert_shifted.mie_hash
        # arrival_state_hash may be the same: the simulator uses a fixed arrival time

        # Semantic replay hash must be identical despite the above differences
        assert cert_base.semantic_replay_hash == cert_shifted.semantic_replay_hash

    def test_fresh_ids_multiple_seeds_stable(self) -> None:
        """For each seed, running with a 48-hour timestamp offset must produce
        the same semantic_replay_hash as the baseline."""
        for seed in [SimulatorSeed.NOMINAL, SimulatorSeed.LOW_BATTERY, SimulatorSeed.OVERHEAT]:
            cert_base = self._make_offset_run(offset_hours=0, seed=seed)
            cert_shifted = self._make_offset_run(offset_hours=48, seed=seed)
            assert cert_base.semantic_replay_hash == cert_shifted.semantic_replay_hash, (
                f"Seed {seed.value}: semantic_replay_hash differs after time offset"
            )

    def test_certificate_hash_differs_across_repeated_runs(self) -> None:
        """Explicit assertion: certificate_hash includes volatile fields (certificate_id,
        decision_timestamp) so it MUST differ across repeated runs."""
        ts = base_timestamps()
        raw_env = _make_raw_envelope(ts)
        sealed_env = mie_sealer.seal(raw_env)
        raw_cmd = RawCommand(
            description="Transmit 10 rock images at 4K resolution and high power",
            image_count=10,
            requested_resolution=ImageResolution.K4,
            requested_power_pct=100.0,
            **ts,
        )
        sealed_cmd = command_sealer.seal(raw_cmd)

        certs = [run(sealed_cmd, sealed_env, seed=SimulatorSeed.NOMINAL, record_audit=False)
                 for _ in range(5)]

        # Each cert must self-verify
        for cert in certs:
            assert cert.verify_hash() is True

        # certificate_hash values must not all be identical (includes volatile timestamps)
        cert_hashes = {c.certificate_hash for c in certs}
        assert len(cert_hashes) > 1, (
            "certificate_hash must differ across runs because it includes volatile "
            "certificate_id and decision_timestamp"
        )

        # But semantic_replay_hash must be stable
        srh_values = {c.semantic_replay_hash for c in certs}
        assert len(srh_values) == 1, (
            f"semantic_replay_hash must be stable across runs: {srh_values}"
        )


# ===========================================================================
# 5. Negative replay tests — meaningful changes alter semantic_replay_hash
# ===========================================================================

class TestSemanticReplayNegative:
    """Meaningful changes to decision content must alter semantic_replay_hash."""

    def setup_method(self):
        clear_audit_log()

    def test_changed_goal_alters_semantic_hash(self, sealed_command) -> None:
        """Changing the MIE goal (different intent) must produce a different semantic_replay_hash."""
        ts = base_timestamps()
        env_a = mie_sealer.seal(_make_raw_envelope(ts, goal="Goal A"))
        env_b = mie_sealer.seal(_make_raw_envelope(ts, goal="Goal B"))
        cert_a = run(sealed_command, env_a, seed=SimulatorSeed.NOMINAL, record_audit=False)
        cert_b = run(sealed_command, env_b, seed=SimulatorSeed.NOMINAL, record_audit=False)
        assert cert_a.semantic_replay_hash != cert_b.semantic_replay_hash

    def test_changed_battery_floor_alters_semantic_hash(self, sealed_command) -> None:
        """Changing battery_floor_pct changes the MIE semantic content."""
        ts = base_timestamps()
        env_a_raw = MissionIntentEnvelope(
            goal="Test",
            battery_floor_pct=20.0,
            max_equipment_temp_c=75.0,
            intended_execution_at=ts["intended_execution_at"],
            expires_at=ts["expires_at"],
        )
        env_b_raw = MissionIntentEnvelope(
            goal="Test",
            battery_floor_pct=30.0,
            max_equipment_temp_c=75.0,
            intended_execution_at=ts["intended_execution_at"],
            expires_at=ts["expires_at"],
        )
        env_a = mie_sealer.seal(env_a_raw)
        env_b = mie_sealer.seal(env_b_raw)
        cert_a = run(sealed_command, env_a, seed=SimulatorSeed.NOMINAL, record_audit=False)
        cert_b = run(sealed_command, env_b, seed=SimulatorSeed.NOMINAL, record_audit=False)
        assert cert_a.semantic_replay_hash != cert_b.semantic_replay_hash

    def test_changed_send_time_assumptions_alters_semantic_hash(self, sealed_command) -> None:
        """Changing send_time_assumptions changes the MIE semantic content."""
        ts = base_timestamps()

        env_a_raw = MissionIntentEnvelope(
            goal="Test",
            send_time_assumptions={"battery_soc": 85.0},
            battery_floor_pct=20.0,
            max_equipment_temp_c=75.0,
            intended_execution_at=ts["intended_execution_at"],
            expires_at=ts["expires_at"],
        )
        env_b_raw = MissionIntentEnvelope(
            goal="Test",
            send_time_assumptions={"battery_soc": 50.0},  # different assumption
            battery_floor_pct=20.0,
            max_equipment_temp_c=75.0,
            intended_execution_at=ts["intended_execution_at"],
            expires_at=ts["expires_at"],
        )
        env_a = mie_sealer.seal(env_a_raw)
        env_b = mie_sealer.seal(env_b_raw)
        cert_a = run(sealed_command, env_a, seed=SimulatorSeed.NOMINAL, record_audit=False)
        cert_b = run(sealed_command, env_b, seed=SimulatorSeed.NOMINAL, record_audit=False)
        assert cert_a.semantic_replay_hash != cert_b.semantic_replay_hash

    def test_changed_command_description_alters_semantic_hash(self, envelope) -> None:
        """Changing command description changes command semantic content."""
        ts = base_timestamps()
        cmd_a = command_sealer.seal(RawCommand(
            description="Transmit 10 rock images",
            image_count=10,
            requested_resolution=ImageResolution.K4,
            requested_power_pct=100.0,
            **ts,
        ))
        cmd_b = command_sealer.seal(RawCommand(
            description="Transmit 5 rock images only",  # different
            image_count=10,
            requested_resolution=ImageResolution.K4,
            requested_power_pct=100.0,
            **ts,
        ))
        cert_a = run(cmd_a, envelope, seed=SimulatorSeed.NOMINAL, record_audit=False)
        cert_b = run(cmd_b, envelope, seed=SimulatorSeed.NOMINAL, record_audit=False)
        assert cert_a.semantic_replay_hash != cert_b.semantic_replay_hash

    def test_changed_command_image_count_alters_semantic_hash(self, envelope) -> None:
        """Changing image_count changes command semantic content."""
        ts = base_timestamps()
        cmd_a = command_sealer.seal(RawCommand(
            description="Transmit images",
            image_count=10,
            requested_resolution=ImageResolution.K4,
            requested_power_pct=100.0,
            **ts,
        ))
        cmd_b = command_sealer.seal(RawCommand(
            description="Transmit images",
            image_count=5,  # different
            requested_resolution=ImageResolution.K4,
            requested_power_pct=100.0,
            **ts,
        ))
        cert_a = run(cmd_a, envelope, seed=SimulatorSeed.NOMINAL, record_audit=False)
        cert_b = run(cmd_b, envelope, seed=SimulatorSeed.NOMINAL, record_audit=False)
        assert cert_a.semantic_replay_hash != cert_b.semantic_replay_hash

    def test_different_verdict_alters_semantic_hash(self, sealed_command, envelope) -> None:
        """Different arrival states (different verdicts) must produce different hashes."""
        cert_execute = run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL, record_audit=False)
        cert_adapt = run(sealed_command, envelope, seed=SimulatorSeed.LOW_BATTERY, record_audit=False)
        assert cert_execute.semantic_replay_hash != cert_adapt.semantic_replay_hash

    def test_different_arrival_state_alters_semantic_hash(self, sealed_command, envelope) -> None:
        """NOMINAL vs OVERHEAT arrival states must produce different semantic hashes."""
        cert_nominal = run(sealed_command, envelope, seed=SimulatorSeed.NOMINAL, record_audit=False)
        cert_overheat = run(sealed_command, envelope, seed=SimulatorSeed.OVERHEAT, record_audit=False)
        assert cert_nominal.semantic_replay_hash != cert_overheat.semantic_replay_hash

    def test_changed_adaptation_authority_alters_semantic_hash(self, sealed_command) -> None:
        """Changing adaptation_authority changes the MIE semantic content."""
        ts = base_timestamps()
        env_a_raw = MissionIntentEnvelope(
            goal="Test",
            battery_floor_pct=20.0,
            max_equipment_temp_c=75.0,
            intended_execution_at=ts["intended_execution_at"],
            expires_at=ts["expires_at"],
            adaptation_authority=AdaptationAuthority(max_delay_minutes=45.0, min_images=3),
        )
        env_b_raw = MissionIntentEnvelope(
            goal="Test",
            battery_floor_pct=20.0,
            max_equipment_temp_c=75.0,
            intended_execution_at=ts["intended_execution_at"],
            expires_at=ts["expires_at"],
            adaptation_authority=AdaptationAuthority(max_delay_minutes=10.0, min_images=5),
        )
        env_a = mie_sealer.seal(env_a_raw)
        env_b = mie_sealer.seal(env_b_raw)
        cert_a = run(sealed_command, env_a, seed=SimulatorSeed.NOMINAL, record_audit=False)
        cert_b = run(sealed_command, env_b, seed=SimulatorSeed.NOMINAL, record_audit=False)
        assert cert_a.semantic_replay_hash != cert_b.semantic_replay_hash
