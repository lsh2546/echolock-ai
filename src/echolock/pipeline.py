"""
EchoLock pipeline — top-level orchestrator.

Runs the full MIE → SDR → ISP → Delta Certificate pipeline for one command.

Usage:
    from echolock.pipeline import run
    result = run(command, envelope, seed=SimulatorSeed.NOMINAL)
"""

from __future__ import annotations

from datetime import datetime, timezone

from .certificate_builder import append_audit, build
from .command_sealer import verify as verify_command_fingerprint
from .counterfactual import predict as predict_counterfactual
from .mie_sealer import verify as verify_mie_fingerprint
from .isp_generator import AIExplanationProvider, generate
from .models import (
    DeltaCertificate,
    HardInvariantCheck,
    MissionIntentEnvelope,
    RawCommand,
    SafetyCheckResult,
    StateDriftReport,
    VerdictStatus,
)
from .safety_gate import validate_candidate, validate_original_command
from .sdr_engine import compute as compute_sdr
from .simulator import SimulatorSeed, arrival_state, send_state
from .verdict_engine import VerdictResult, decide

UTC = timezone.utc


def _make_reject_cert(
    command: RawCommand,
    envelope: MissionIntentEnvelope,
    seed: SimulatorSeed,
    invariant_id: str,
    description: str,
    evaluated_value: str,
    reason: str,
    ai_explanation: str | None,
    record_audit: bool,
) -> DeltaCertificate:
    """Build and return a minimal REJECT certificate for pipeline-boundary failures.

    Both command fingerprint and MIE seal failures use this path.
    The SDR is computed because the certificate builder requires it; the REJECT
    verdict and the PIPELINE-boundary HI check are the authoritative signal.
    """
    s_state = send_state()
    a_state = arrival_state(seed)
    sdr = compute_sdr(command, envelope, s_state, a_state)
    reject_check = HardInvariantCheck(
        invariant_id=invariant_id,
        description=description,
        result=SafetyCheckResult.FAIL_CLOSED,
        evaluated_value=evaluated_value,
        threshold="valid SHA-256 fingerprint",
        evaluation_source="DETERMINISTIC",
    )
    verdict_result = VerdictResult(
        verdict=VerdictStatus.REJECT,
        precedence_step=1,
        hi_checks=[reject_check],
        winning_candidate=None,
        reason=reason,
    )
    cert = build(
        command, envelope, sdr, verdict_result, a_state,
        scenario_id=seed.value,
        ai_explanation=ai_explanation,
    )
    if record_audit:
        append_audit(cert)
    return cert


def run(
    command: RawCommand,
    envelope: MissionIntentEnvelope,
    seed: SimulatorSeed = SimulatorSeed.NOMINAL,
    *,
    ai_provider: AIExplanationProvider | None = None,
    ai_explanation: str | None = None,
    record_audit: bool = True,
) -> DeltaCertificate:
    """Run the full EchoLock pipeline for one command and seed.

    Steps:
        0a. Verify command fingerprint — REJECT at step 1 if missing or invalid.
        0b. Verify MIE seal — REJECT at step 1 if missing or invalid.
        1.  Load send-state and arrival-state from the simulator.
        2.  Compute State Drift Report.
        3.  Generate Intent-Safe Patch candidates (deterministic; AI optional).
        4.  Validate all candidates through the Safety Gate.
        5.  Apply decision precedence via VerdictEngine.
        6.  Build and self-hash the Delta Certificate.
        7.  Append an AuditEntry (unless record_audit=False).

    Args:
        command:       Sealed RawCommand (fingerprint must be set and valid).
        envelope:      Sealed MissionIntentEnvelope (mie_fingerprint must be set and valid).
        seed:          Simulator seed selecting the arrival state.
        ai_provider:   Optional provider-neutral AI explanation callable.
        ai_explanation: Optional pre-computed AI explanation string.
        record_audit:  If True, append an AuditEntry to the in-memory chain.

    Returns:
        A complete, self-hashed DeltaCertificate.

    Raises:
        Nothing — all boundary failures produce a REJECT certificate at precedence
        step 1 (fail-closed). The SDR is still computed for the reject certificate.
    """
    # 0a. Command fingerprint check — fail-closed
    if not verify_command_fingerprint(command):
        reason = (
            "Command fingerprint is missing."
            if command.fingerprint is None
            else "Command fingerprint does not match command content — possible tampering."
        )
        return _make_reject_cert(
            command, envelope, seed,
            invariant_id="PIPELINE-FP",
            description="Command fingerprint must be present and valid before processing",
            evaluated_value=str(command.fingerprint),
            reason=reason,
            ai_explanation=ai_explanation,
            record_audit=record_audit,
        )

    # 0b. MIE seal check — fail-closed
    if not verify_mie_fingerprint(envelope):
        reason = (
            "MIE fingerprint is missing — envelope was not sealed before submission."
            if envelope.mie_fingerprint is None
            else "MIE fingerprint does not match envelope content — possible tampering."
        )
        return _make_reject_cert(
            command, envelope, seed,
            invariant_id="PIPELINE-MIE",
            description="MIE seal (mie_fingerprint) must be present and valid before processing",
            evaluated_value=str(envelope.mie_fingerprint),
            reason=reason,
            ai_explanation=ai_explanation,
            record_audit=record_audit,
        )

    # 1. Spacecraft states
    s_state = send_state()
    a_state = arrival_state(seed)

    # 2. State Drift Report
    sdr = compute_sdr(command, envelope, s_state, a_state)

    # 3. Generate patch candidates
    candidates = generate(original=command, envelope=envelope, ai_provider=ai_provider)

    # 4. Validate candidates through Safety Gate
    validated = [
        validate_candidate(c, envelope, command, a_state) for c in candidates
    ]

    # 5. VerdictEngine decision
    verdict_result = decide(command, envelope, a_state, sdr, validated)

    # 6. Deterministic counterfactual comparison and certificate
    counterfactual = predict_counterfactual(command, envelope, a_state, verdict_result)
    cert = build(
        command, envelope, sdr, verdict_result, a_state,
        scenario_id=seed.value,
        counterfactual=counterfactual,
        ai_explanation=ai_explanation,
    )

    # 7. Audit record
    if record_audit:
        append_audit(cert)

    return cert
