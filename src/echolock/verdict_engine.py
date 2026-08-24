"""
VerdictEngine — applies the approved Q5 five-step decision precedence.

Precedence (corrected per approved clarification):
  Step 1  REJECT  (pre-check)  — command expired, corrupted, unauthorised,
                                 OR arrival state violates a hard invariant
                                 that NO adaptation can resolve.
  Step 2  EXECUTE              — original command safe; all assumptions valid.
  Step 3  ADAPT                — an authorised patch is immediately executable,
                                 passes every HI, and GPS ≥ threshold.
  Step 4  DEFER                — no immediate safe execution / adaptation, but
                                 a future state within the delay window is safe.
  Step 5  REJECT  (final)      — no valid option within all authorised bounds.

Key clarification: if the original command fails its HI checks but a valid
ADAPT candidate exists, ADAPT is evaluated BEFORE the final REJECT.

Design rule: reads only SafetyGate-validated candidates. No AI dependency.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    HardInvariantCheck,
    MissionIntentEnvelope,
    RawCommand,
    SafetyCheckResult,
    StateSnapshot,
    StateDriftReport,
    ValidatedCandidate,
    VerdictStatus,
)
from .safety_gate import validate_original_command

GPS_THRESHOLD = 0.70  # MVP acceptance threshold (Q2)
MAX_DELAY_MINUTES = 45.0  # AT-1 hard maximum


@dataclass(frozen=True)
class VerdictResult:
    """Output of the VerdictEngine."""

    verdict: VerdictStatus
    precedence_step: int  # 1–5
    hi_checks: list[HardInvariantCheck]
    winning_candidate: ValidatedCandidate | None
    reason: str


def decide(
    command: RawCommand,
    envelope: MissionIntentEnvelope,
    arrival_state: StateSnapshot,
    sdr: StateDriftReport,
    validated_candidates: list[ValidatedCandidate],
) -> VerdictResult:
    """Apply the Q5 decision precedence and return a VerdictResult.

    Args:
        command:               The sealed original command (fingerprint verified by caller).
        envelope:              The sealed Mission Intent Envelope.
        arrival_state:         Actual spacecraft state at arrival.
        sdr:                   State Drift Report for this command.
        validated_candidates:  List of ValidatedCandidate objects from SafetyGate.
                               Must be pre-validated — this engine does not call SafetyGate itself.

    Returns:
        VerdictResult with verdict, precedence_step, and supporting evidence.
    """
    # -----------------------------------------------------------------------
    # Step 1 — REJECT (pre-check)
    # -----------------------------------------------------------------------
    original_hi_checks, _ = validate_original_command(command, envelope, arrival_state)
    pre_reject_reasons: list[str] = []

    # HI-4: expiry
    expiry_check = next((c for c in original_hi_checks if c.invariant_id == "HI-4"), None)
    if expiry_check and expiry_check.result == SafetyCheckResult.FAIL_CLOSED:
        pre_reject_reasons.append("Command has expired (HI-4).")

    # Command integrity (fingerprint must be set; caller should verify, but we check)
    if command.fingerprint is None:
        pre_reject_reasons.append("Command fingerprint is missing (not sealed).")

    # HI-3: beacon inactive at arrival — no adaptation can fix a dead beacon
    beacon_check = next((c for c in original_hi_checks if c.invariant_id == "HI-3"), None)
    if beacon_check and beacon_check.result == SafetyCheckResult.FAIL_CLOSED:
        pre_reject_reasons.append("Emergency beacon is INACTIVE at arrival (HI-3).")

    # HI-2: temperature already above ceiling — no patch lowers hardware temp
    temp_check = next((c for c in original_hi_checks if c.invariant_id == "HI-2"), None)
    if temp_check and temp_check.result == SafetyCheckResult.FAIL_CLOSED:
        pre_reject_reasons.append(
            f"Equipment temperature {temp_check.evaluated_value} °C exceeds "
            f"hard ceiling {temp_check.threshold} °C (HI-2); no patch can cool hardware."
        )

    if pre_reject_reasons:
        return VerdictResult(
            verdict=VerdictStatus.REJECT,
            precedence_step=1,
            hi_checks=original_hi_checks,
            winning_candidate=None,
            reason=" | ".join(pre_reject_reasons),
        )

    # -----------------------------------------------------------------------
    # Step 2 — EXECUTE
    # All HI checks pass for the original command as-is
    # -----------------------------------------------------------------------
    all_original_pass = all(c.result == SafetyCheckResult.PASS for c in original_hi_checks)
    no_drift = not sdr.has_broken_assumptions and not sdr.has_violated_invariants

    comm_open_for_execute = arrival_state.comm_window_status.value == "OPEN"
    if all_original_pass and no_drift and comm_open_for_execute:
        return VerdictResult(
            verdict=VerdictStatus.EXECUTE,
            precedence_step=2,
            hi_checks=original_hi_checks,
            winning_candidate=None,
            reason="All hard invariants pass and all send-time assumptions remain valid.",
        )

    # Also allow EXECUTE when HIs pass even if soft assumptions drifted slightly,
    # BUT only if the communication window is currently OPEN (cannot transmit if CLOSED).
    if all_original_pass and not sdr.has_violated_invariants and comm_open_for_execute:
        return VerdictResult(
            verdict=VerdictStatus.EXECUTE,
            precedence_step=2,
            hi_checks=original_hi_checks,
            winning_candidate=None,
            reason=(
                "All hard invariants pass. Some soft assumptions drifted but "
                "no invariant was violated and comm window is open; "
                "original command is safe to execute."
            ),
        )

    # -----------------------------------------------------------------------
    # Step 3 — ADAPT
    # Find the highest-GPS PASS candidate that requires no delay (immediate)
    # -----------------------------------------------------------------------
    immediate_candidates = [
        vc for vc in validated_candidates
        if vc.safety_result == SafetyCheckResult.PASS
        and vc.eligibility_gps >= GPS_THRESHOLD
        and vc.candidate.delay_minutes == 0.0
    ]
    if immediate_candidates:
        # Already sorted GPS descending by ISPCandidateGenerator, but re-sort defensively
        best = max(immediate_candidates, key=lambda vc: vc.eligibility_gps)
        return VerdictResult(
            verdict=VerdictStatus.ADAPT,
            precedence_step=3,
            hi_checks=original_hi_checks,
            winning_candidate=best,
            reason=(
                f"Authorised patch found: GPS={best.eligibility_gps:.4f} ≥ {GPS_THRESHOLD}. "
                f"Adaptations: {[t.value for t in best.candidate.adaptation_types]}."
            ),
        )

    # -----------------------------------------------------------------------
    # Step 4 — DEFER
    # A future state within the delay window will be safe.
    # Condition: comm window opens within max_delay, command not expired then,
    #            AND a deferred candidate's delay is ≥ window_delay so it does
    #            not execute before the comm window opens.
    # -----------------------------------------------------------------------
    if arrival_state.comm_window_status.value == "CLOSED" and arrival_state.next_comm_window_open is not None:
        from datetime import timedelta

        window_delay = (
            arrival_state.next_comm_window_open - arrival_state.timestamp
        ).total_seconds() / 60.0
        time_until_expiry = (
            envelope.expires_at - arrival_state.timestamp
        ).total_seconds() / 60.0
        max_defer = envelope.adaptation_authority.max_delay_minutes

        if 0 < window_delay <= max_defer and window_delay < time_until_expiry:
            # Deferred candidates must:
            #   a) pass all Safety Gate checks
            #   b) GPS ≥ threshold
            #   c) delay_minutes ≥ window_delay  (cannot execute before comm window opens)
            #   d) delay_minutes ≤ max_defer
            deferred_candidates = [
                vc for vc in validated_candidates
                if vc.safety_result == SafetyCheckResult.PASS
                and vc.eligibility_gps >= GPS_THRESHOLD
                and vc.candidate.delay_minutes >= window_delay  # must not precede comm window
                and vc.candidate.delay_minutes <= max_defer
            ]
            if deferred_candidates:
                best_deferred = max(deferred_candidates, key=lambda vc: vc.eligibility_gps)
                return VerdictResult(
                    verdict=VerdictStatus.DEFER,
                    precedence_step=4,
                    hi_checks=original_hi_checks,
                    winning_candidate=best_deferred,
                    reason=(
                        f"Comm window opens in {window_delay:.1f} min (≤ {max_defer:.0f} min limit). "
                        f"Deferred candidate delay={best_deferred.candidate.delay_minutes:.1f} min "
                        f"≥ window_delay={window_delay:.1f} min; "
                        f"GPS={best_deferred.eligibility_gps:.4f}."
                    ),
                )
            # No validated deferred candidate, but window opens in time — defer without patch
            return VerdictResult(
                verdict=VerdictStatus.DEFER,
                precedence_step=4,
                hi_checks=original_hi_checks,
                winning_candidate=None,
                reason=(
                    f"No comm window currently open. Next window opens in {window_delay:.1f} min "
                    f"(within {max_defer:.0f} min limit and before expiration)."
                ),
            )

    # -----------------------------------------------------------------------
    # Step 5 — REJECT (final)
    # -----------------------------------------------------------------------
    return VerdictResult(
        verdict=VerdictStatus.REJECT,
        precedence_step=5,
        hi_checks=original_hi_checks,
        winning_candidate=None,
        reason=(
            "No valid execution, adaptation, or deferral option exists within "
            "all authorised adaptation and delay boundaries."
        ),
    )
