"""
CertificateBuilder — assembles a dual-hashed DeltaCertificate and maintains
the in-memory hash-linked audit chain.

certificate_hash:      full cryptographic integrity (all fields except itself)
semantic_replay_hash:  deterministic across equivalent runs (volatile IDs/timestamps excluded);
                       uses semantic_content_hash() for command, MIE, and arrival state

Audit chain (in-memory hash-linked chain — NOT a persisted append-only log):
  Each AuditEntry links to its predecessor via previous_entry_hash.
  verify_audit_chain() checks per-entry integrity, chain linkage, and sequence numbers.
  Tail-truncation is a known limitation; see KNOWN_LIMITATIONS.

Design rule: no AI dependency.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .models import (
    AuditEntry,
    CounterfactualBundle,
    DeltaCertificate,
    MissionIntentEnvelope,
    RawCommand,
    StateSnapshot,
    StateDriftReport,
    VerdictStatus,
    verify_audit_chain,
)
from .verdict_engine import VerdictResult

UTC = timezone.utc


def build(
    command: RawCommand,
    envelope: MissionIntentEnvelope,
    sdr: StateDriftReport,
    verdict_result: VerdictResult,
    arrival_state: StateSnapshot,
    *,
    scenario_id: str = "",
    counterfactual: CounterfactualBundle | None = None,
    ai_explanation: str | None = None,
) -> DeltaCertificate:
    """Build and return a dual-hashed DeltaCertificate.

    Args:
        command:         The sealed original command.
        envelope:        The Mission Intent Envelope.
        sdr:             The State Drift Report.
        verdict_result:  Output of VerdictEngine.decide().
        arrival_state:   The arrival-time StateSnapshot (for arrival_state_hash).
        scenario_id:     Optional operator-assigned scenario label.
        counterfactual:  Optional counterfactual comparison bundle.
        ai_explanation:  Optional AI-generated explanation (labelled; not used for decisions).

    Returns:
        A DeltaCertificate with both certificate_hash and semantic_replay_hash set.
    """
    winning = verdict_result.winning_candidate
    applied_patch = winning.candidate if winning else None

    # Determine preserved goals
    preserved_goals: list[str] = []
    if verdict_result.verdict in (VerdictStatus.EXECUTE, VerdictStatus.ADAPT):
        preserved_goals.append("Transmit scientific images to Earth")
        if applied_patch and applied_patch.adapted_image_count is not None:
            n = applied_patch.adapted_image_count
            preserved_goals.append(f"Minimum image count satisfied ({n} images)")
        preserved_goals.append("Emergency beacon continuity preserved")
        preserved_goals.append("Battery reserve above floor")

    # Compute cryptographic source-identity hashes (bind cert to specific object instances)
    mie_hash = envelope.content_hash()
    arrival_state_hash = arrival_state.content_hash()
    patch_hash = applied_patch.content_hash() if applied_patch is not None else ""

    # Compute semantic replay-identity hashes (stable across equivalent runs with fresh objects)
    patch_semantic_hash = applied_patch.semantic_hash() if applied_patch is not None else ""
    command_semantic_hash = command.semantic_content_hash()
    mie_semantic_hash = envelope.semantic_content_hash()
    arrival_state_semantic_hash = arrival_state.semantic_content_hash()

    cert = DeltaCertificate(
        verifier_version=DeltaCertificate.model_fields["verifier_version"].default,
        scenario_id=scenario_id,
        original_command_id=command.command_id,
        original_command_fingerprint=command.fingerprint or "",
        mie_hash=mie_hash,
        arrival_state_hash=arrival_state_hash,
        patch_hash=patch_hash,
        patch_semantic_hash=patch_semantic_hash,
        command_semantic_hash=command_semantic_hash,
        mie_semantic_hash=mie_semantic_hash,
        arrival_state_semantic_hash=arrival_state_semantic_hash,
        sdr_summary=sdr,
        applied_patch=applied_patch,
        preserved_goals=preserved_goals,
        hi_check_results=verdict_result.hi_checks,
        gps=winning.eligibility_gps if winning else None,
        counterfactual=counterfactual,
        verdict=verdict_result.verdict,
        verdict_precedence_step=verdict_result.precedence_step,
        decision_timestamp=datetime.now(UTC),
        ai_explanation=ai_explanation,
    )

    # Build order: semantic_replay_hash FIRST, then certificate_hash over everything
    # (certificate_hash includes the already-computed semantic_replay_hash field)
    replay_hash = cert.compute_semantic_replay_hash()
    cert_with_replay = cert.model_copy(update={"semantic_replay_hash": replay_hash})
    cert_hash = cert_with_replay.compute_hash()
    return cert_with_replay.model_copy(update={"certificate_hash": cert_hash})


# ---------------------------------------------------------------------------
# In-memory hash-linked audit chain (PoC — NOT a persisted append-only log)
# ---------------------------------------------------------------------------

_AUDIT_LOG: list[AuditEntry] = []


def append_audit(cert: DeltaCertificate) -> AuditEntry:
    """Create a chained AuditEntry from a certificate and append it to the log.

    The previous_entry_hash field is set to the entry_hash of the last entry
    in the log (or "" for the first entry), establishing the chain.

    Returns the created entry.
    """
    previous_hash = _AUDIT_LOG[-1].entry_hash or "" if _AUDIT_LOG else ""
    seq = len(_AUDIT_LOG)  # 0-based sequence number

    entry = AuditEntry(
        sequence_number=seq,
        certificate_id=cert.certificate_id,
        certificate_hash=cert.certificate_hash or "",
        semantic_replay_hash=cert.semantic_replay_hash or "",
        verdict=cert.verdict,
        decision_timestamp=cert.decision_timestamp,
        command_id=cert.original_command_id,
        command_fingerprint=cert.original_command_fingerprint,
        previous_entry_hash=previous_hash,
    )
    entry_hash = entry.compute_hash()
    entry = entry.model_copy(update={"entry_hash": entry_hash})
    _AUDIT_LOG.append(entry)
    return entry


def get_audit_log() -> list[AuditEntry]:
    """Return the current audit log as a read-only copy."""
    return list(_AUDIT_LOG)


def verify_log_chain() -> tuple[bool, str]:
    """Verify the integrity and chain linkage of the entire in-memory audit log."""
    return verify_audit_chain(list(_AUDIT_LOG))


def clear_audit_log() -> None:
    """Clear the audit log (for testing only)."""
    _AUDIT_LOG.clear()
