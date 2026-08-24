"""
EchoLock data models — all Pydantic v2, all fields explicit with units.

Design rules enforced here:
- RawCommand is immutable after construction (model_config frozen=True).
  CommandSealer computes fingerprint over all fields except the fingerprint field.
- MissionIntentEnvelope is immutable after construction (model_config frozen=True).
  MIESealer computes mie_fingerprint over all fields except mie_fingerprint itself.
  send_time_assumptions is recursively frozen, including nested mappings and sequences.
- All timestamps are datetime with timezone UTC.
- StateSnapshot carries explicit unit annotations in field descriptions.
- DeltaCertificate carries TWO distinct hash fields:
    certificate_hash      — full cryptographic integrity over ALL certificate fields
                            EXCEPT certificate_hash itself (but INCLUDING semantic_replay_hash).
                            ANY field change — including to semantic_replay_hash — breaks verification.
    semantic_replay_hash  — deterministic across equivalent repeated runs;
                            normalises out volatile UUIDs and absolute timestamps
                            so that the same logical decision always yields the same value.
                            Computed FIRST; then certificate_hash is computed over all
                            remaining fields plus the already-set semantic_replay_hash.

Semantic normalisation contract (semantic_replay_hash):

  Separation of cryptographic source identity vs semantic replay identity:
    cryptographic source identity = content_hash() on each source object —
        includes ALL fields including volatile UUIDs and absolute timestamps.
        Stored as mie_hash, arrival_state_hash, patch_hash (in the certificate).
        Changing the same logical object produces a different content_hash.
    semantic replay identity = semantic_content_hash() on each source object —
        strips volatile UUIDs and absolute timestamps; uses only relative timing.
        Used inside semantic_replay_hash so that two runs processing the same
        logical input (different UUIDs, shifted clocks) produce the same hash.

  Excluded from semantic_replay_hash (volatile — changes every run even for identical decisions):
        certificate_id              new UUID each run
        decision_timestamp          wall-clock time
        sdr.command_id              derived from the original command UUID
        applied_patch.patch_id      new UUID each run
        applied_patch.ai_explanation  may vary
        ai_explanation              may vary
        counterfactual.command_id   UUID
        command semantic: command_id, envelope_id, absolute timestamps (sent_at, arrived_at,
            intended_execution_at, expires_at) — replaced by relative durations
        mie semantic: envelope_id, absolute timestamps — replaced by relative durations
        arrival state semantic: timestamp, next_comm_window_open (absolute) — replaced by relative

  Included in semantic_replay_hash (stable decision content):
        verifier_version, scenario_id,
        command_semantic_hash  (command content without volatile UUID/timestamps),
        mie_semantic_hash      (MIE content without volatile UUID/timestamps),
        arrival_state_semantic_hash  (state content without volatile timestamps),
        patch_semantic_hash,
        all SDR delta fields (field, expected_value, actual_value, severity, impact_description),
        SDR relative timing (arrival_state_timestamp - send_state_timestamp as seconds),
        applied_patch decision fields (adaptation_types, adapted_*, gps, rationale,
            compression_applied, delay_minutes, batch_count),
        preserved_goals,
        hi_check_results — semantically stable fields only (invariant_id, description,
            result, evaluation_source); evaluated_value and threshold excluded because
            HI-4 stores absolute expiry timestamps there,
        gps,
        counterfactual branches (excluding command_id and arrival_state_timestamp),
        verdict, verdict_precedence_step.

  Two runs processing logically identical input MUST produce identical semantic_replay_hash
  values even when object UUIDs, absolute timestamps, and fingerprints differ.

  Any meaningful change — to command content, intent, assumptions, hard invariants,
  adaptation authority, arrival state values, patch, GPS, invariant results, or verdict —
  MUST produce a different semantic_replay_hash value.

- AuditEntry carries entry_hash (full integrity) and chains via previous_entry_hash.
  sequence_number provides an explicit monotone index.
  NOTE: This is an in-memory hash-linked audit chain, not a persisted append-only log.
  Tail-truncation is a known limitation documented in KNOWN_LIMITATIONS.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FrozenDict(dict[str, Any]):
    """JSON-object-compatible mapping that rejects every mutation operation."""

    @staticmethod
    def _immutable(*_args: Any, **_kwargs: Any) -> None:
        raise TypeError("FrozenDict is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable

    def __copy__(self) -> "FrozenDict":
        return self

    def __deepcopy__(self, _memo: dict[int, Any]) -> "FrozenDict":
        return self


def _deep_freeze_json(value: Any) -> Any:
    """Recursively convert mutable JSON containers to immutable equivalents."""
    if isinstance(value, dict):
        return FrozenDict({key: _deep_freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze_json(item) for item in value)
    if isinstance(value, set):
        return frozenset(_deep_freeze_json(item) for item in value)
    return value

# ---------------------------------------------------------------------------
# Schema version — increment when the certificate schema changes
# ---------------------------------------------------------------------------

VERIFIER_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class CommWindowStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EmergencyBeaconStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ImageResolution(str, Enum):
    K4 = "4K"
    P1080 = "1080p"


class VerdictStatus(str, Enum):
    EXECUTE = "EXECUTE"
    ADAPT = "ADAPT"
    DEFER = "DEFER"
    REJECT = "REJECT"


class DriftSeverity(str, Enum):
    BROKEN_ASSUMPTION = "BROKEN_ASSUMPTION"
    VIOLATED_INVARIANT = "VIOLATED_INVARIANT"


class SafetyCheckResult(str, Enum):
    PASS = "PASS"
    FAIL_CLOSED = "FAIL_CLOSED"


class AdaptationType(str, Enum):
    DELAY = "DELAY"
    REDUCE_IMAGE_COUNT = "REDUCE_IMAGE_COUNT"
    REDUCE_RESOLUTION = "REDUCE_RESOLUTION"
    APPLY_COMPRESSION = "APPLY_COMPRESSION"
    REDUCE_POWER = "REDUCE_POWER"
    SPLIT_BATCHES = "SPLIT_BATCHES"


# ---------------------------------------------------------------------------
# Canonical hashing helpers
# ---------------------------------------------------------------------------


def _canonical_sha256(obj: dict[str, Any]) -> str:
    """SHA-256 over a deterministic JSON serialisation of obj."""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str).encode()
    ).hexdigest()


# ---------------------------------------------------------------------------
# State snapshot — frozen Q4 field definitions
# ---------------------------------------------------------------------------


def _utc(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware UTC."""
    if dt.tzinfo is None:
        raise ValueError("Datetime must include timezone info (use UTC).")
    return dt.astimezone(timezone.utc)


class StateSnapshot(BaseModel):
    """Spacecraft state at a specific point in time.

    All numeric fields carry their units in the description.
    """

    model_config = ConfigDict(frozen=True)

    battery_soc: Annotated[
        float, Field(ge=0.0, le=100.0, description="Battery state of charge [%]")
    ]
    equipment_temp_c: Annotated[
        float, Field(description="Wheel/equipment temperature [°C]")
    ]
    comm_window_status: CommWindowStatus
    next_comm_window_open: datetime | None = Field(
        default=None,
        description="Next comm-window open time (ISO-8601 UTC); null when OPEN.",
    )
    emergency_beacon: EmergencyBeaconStatus
    stored_image_count: Annotated[
        int, Field(ge=0, description="Images currently in onboard storage [count]")
    ]
    transmission_power_pct: Annotated[
        float,
        Field(ge=0.0, le=100.0, description="Available transmission power [% nominal]"),
    ]
    available_resolution: ImageResolution
    timestamp: datetime = Field(description="Snapshot capture time (ISO-8601 UTC)")

    @field_validator("timestamp", "next_comm_window_open", mode="before")
    @classmethod
    def _ensure_utc(cls, v: Any) -> Any:  # noqa: ANN401
        if isinstance(v, datetime):
            return _utc(v)
        return v

    @model_validator(mode="after")
    def _comm_window_consistency(self) -> "StateSnapshot":
        if self.comm_window_status == CommWindowStatus.CLOSED and self.next_comm_window_open is None:
            raise ValueError(
                "next_comm_window_open must be set when comm_window_status is CLOSED."
            )
        return self

    def content_hash(self) -> str:
        """SHA-256 over the full snapshot content (all fields including timestamp)."""
        return _canonical_sha256(self.model_dump(mode="json"))

    def semantic_content_hash(self) -> str:
        """SHA-256 over stable state content, excluding volatile timestamps.

        Excluded (volatile — changes with absolute time even for logically identical states):
            timestamp              absolute capture time — excluded
            next_comm_window_open  absolute time — replaced by minutes_until_next_window
                                   (None when comm window is OPEN)

        Included (stable state content):
            battery_soc, equipment_temp_c, comm_window_status,
            minutes_until_next_window (float or None),
            emergency_beacon, stored_image_count,
            transmission_power_pct, available_resolution.

        Two StateSnapshot objects with the same field values but different absolute
        timestamps must produce the same hash.
        """
        minutes_until_next_window: float | None = None
        if self.next_comm_window_open is not None:
            minutes_until_next_window = (
                self.next_comm_window_open - self.timestamp
            ).total_seconds() / 60.0

        data = {
            "battery_soc": self.battery_soc,
            "equipment_temp_c": self.equipment_temp_c,
            "comm_window_status": self.comm_window_status.value,
            "minutes_until_next_window": minutes_until_next_window,
            "emergency_beacon": self.emergency_beacon.value,
            "stored_image_count": self.stored_image_count,
            "transmission_power_pct": self.transmission_power_pct,
            "available_resolution": self.available_resolution.value,
        }
        return _canonical_sha256(data)


# ---------------------------------------------------------------------------
# Mission Intent Envelope
# ---------------------------------------------------------------------------


class AdaptationAuthority(BaseModel):
    """Declares what adaptations the operator permits and their boundaries."""

    model_config = ConfigDict(frozen=True)

    max_delay_minutes: Annotated[
        float, Field(ge=0.0, le=45.0, description="Maximum allowed delay [minutes]")
    ] = 45.0
    min_images: Annotated[
        int, Field(ge=3, description="Minimum images to transmit [count]")
    ] = 3
    allow_resolution_reduction: bool = True
    allow_compression: bool = True
    min_transmission_power_pct: Annotated[
        float,
        Field(ge=40.0, le=100.0, description="Minimum transmission power [% nominal]"),
    ] = 40.0
    allow_batch_split: bool = True


class MissionIntentEnvelope(BaseModel):
    """Carries the operator's goal, assumptions, hard invariants, and adaptation authority."""

    model_config = ConfigDict(frozen=True)

    envelope_id: UUID = Field(default_factory=uuid4)
    goal: str
    send_time_assumptions: dict[str, Any] = Field(default_factory=dict)
    battery_floor_pct: Annotated[float, Field(ge=0.0, le=100.0)] = 20.0
    max_equipment_temp_c: float = 75.0
    emergency_beacon_must_remain_active: bool = True
    intended_execution_at: datetime
    expires_at: datetime
    adaptation_authority: AdaptationAuthority = Field(
        default_factory=AdaptationAuthority
    )
    priority: Annotated[int, Field(ge=1)] = 1
    gps_weight_scientific_utility: float = 0.50
    gps_weight_output_quantity: float = 0.25
    gps_weight_timeliness: float = 0.15
    gps_weight_operator_preferences: float = 0.10
    # Integrity seal set by MIESealer.seal() — None until sealed
    mie_fingerprint: str | None = None

    @field_validator("send_time_assumptions", mode="after")
    @classmethod
    def _freeze_assumptions(cls, value: dict[str, Any]) -> FrozenDict:
        """Detach and recursively freeze operator assumptions at model construction."""
        return _deep_freeze_json(value)

    @field_validator("intended_execution_at", "expires_at", mode="before")
    @classmethod
    def _ensure_utc(cls, v: Any) -> Any:  # noqa: ANN401
        if isinstance(v, datetime):
            return _utc(v)
        return v

    @model_validator(mode="after")
    def _expiry_after_execution(self) -> "MissionIntentEnvelope":
        if self.expires_at <= self.intended_execution_at:
            raise ValueError("expires_at must be after intended_execution_at.")
        total = (
            self.gps_weight_scientific_utility
            + self.gps_weight_output_quantity
            + self.gps_weight_timeliness
            + self.gps_weight_operator_preferences
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"GPS weights must sum to 1.0, got {total:.6f}.")
        return self

    def content_hash(self) -> str:
        """SHA-256 over the full MIE content (all fields including envelope_id and mie_fingerprint)."""
        return _canonical_sha256(self.model_dump(mode="json"))

    def semantic_content_hash(self) -> str:
        """SHA-256 over stable MIE decision content, excluding volatile identifiers.

        Excluded (volatile — changes when the same logical MIE is recreated):
            envelope_id            new UUID each time the envelope is constructed
            mie_fingerprint        depends on envelope_id (excluded above)
            intended_execution_at  absolute timestamp — replaced by duration_until_expiry_seconds
            expires_at             absolute timestamp — replaced by duration_until_expiry_seconds

        Included (stable intent content):
            goal, send_time_assumptions (deep copy via model_dump),
            battery_floor_pct, max_equipment_temp_c,
            emergency_beacon_must_remain_active,
            duration_until_expiry_seconds  (expires_at - intended_execution_at),
            adaptation_authority (all fields),
            priority, GPS weights.

        Two MissionIntentEnvelope objects with the same logical content but different
        envelope_id values or shifted absolute timestamps must produce the same hash.
        """
        from datetime import timedelta

        data = self.model_dump(
            mode="json",
            exclude={"envelope_id", "mie_fingerprint", "intended_execution_at", "expires_at"},
        )
        # Replace absolute timestamps with relative duration
        data["duration_until_expiry_seconds"] = (
            self.expires_at - self.intended_execution_at
        ).total_seconds()
        return _canonical_sha256(data)


# ---------------------------------------------------------------------------
# Raw command — immutable after construction
# ---------------------------------------------------------------------------


class RawCommand(BaseModel):
    """The original operator command — immutable after sealing."""

    model_config = ConfigDict(frozen=True)

    command_id: UUID = Field(default_factory=uuid4)
    description: str
    image_count: Annotated[int, Field(ge=1, description="Images to transmit [count]")]
    requested_resolution: ImageResolution = ImageResolution.K4
    requested_power_pct: Annotated[
        float,
        Field(ge=0.0, le=100.0, description="Requested transmission power [% nominal]"),
    ] = 100.0
    sent_at: datetime
    arrived_at: datetime
    intended_execution_at: datetime
    expires_at: datetime
    fingerprint: str | None = None

    @field_validator(
        "sent_at", "arrived_at", "intended_execution_at", "expires_at", mode="before"
    )
    @classmethod
    def _ensure_utc(cls, v: Any) -> Any:  # noqa: ANN401
        if isinstance(v, datetime):
            return _utc(v)
        return v

    def semantic_content_hash(self) -> str:
        """SHA-256 over stable command content, excluding volatile identifiers.

        Excluded (volatile — changes when the same logical command is recreated):
            command_id              new UUID each time the command is constructed
            fingerprint             depends on command_id (excluded above)
            sent_at                 absolute timestamp — replaced by relative durations
            arrived_at              absolute timestamp — replaced by relative durations
            intended_execution_at   absolute timestamp — replaced by relative durations
            expires_at              absolute timestamp — replaced by relative durations

        Included (stable command content):
            description, image_count, requested_resolution, requested_power_pct,
            comm_delay_seconds        (arrived_at - sent_at),
            exec_delay_seconds        (intended_execution_at - sent_at),
            duration_until_expiry_seconds  (expires_at - sent_at).

        Two RawCommand objects with the same logical content but different command_id
        values or shifted absolute timestamps must produce the same hash.
        """
        data = {
            "description": self.description,
            "image_count": self.image_count,
            "requested_resolution": self.requested_resolution.value,
            "requested_power_pct": self.requested_power_pct,
            "comm_delay_seconds": (self.arrived_at - self.sent_at).total_seconds(),
            "exec_delay_seconds": (self.intended_execution_at - self.sent_at).total_seconds(),
            "duration_until_expiry_seconds": (self.expires_at - self.sent_at).total_seconds(),
        }
        return _canonical_sha256(data)


# ---------------------------------------------------------------------------
# State Drift Report
# ---------------------------------------------------------------------------


class DriftEntry(BaseModel):
    """One field-level delta in the State Drift Report."""

    model_config = ConfigDict(frozen=True)

    field: str
    expected_value: Any
    actual_value: Any
    severity: DriftSeverity
    impact_description: str


class StateDriftReport(BaseModel):
    """Comparison of send-time assumptions vs arrival-time state."""

    model_config = ConfigDict(frozen=True)

    command_id: UUID
    send_state_timestamp: datetime
    arrival_state_timestamp: datetime
    deltas: list[DriftEntry] = Field(default_factory=list)

    @property
    def has_violated_invariants(self) -> bool:
        return any(d.severity == DriftSeverity.VIOLATED_INVARIANT for d in self.deltas)

    @property
    def has_broken_assumptions(self) -> bool:
        return any(d.severity == DriftSeverity.BROKEN_ASSUMPTION for d in self.deltas)


# ---------------------------------------------------------------------------
# Intent-Safe Patch candidates
# ---------------------------------------------------------------------------


class PatchCandidate(BaseModel):
    """A proposed adaptation within MIE-authorised boundaries."""

    model_config = ConfigDict(frozen=True)

    patch_id: UUID = Field(default_factory=uuid4)
    adaptation_types: list[AdaptationType]
    adapted_image_count: int | None = None
    adapted_resolution: ImageResolution | None = None
    adapted_power_pct: float | None = None
    compression_applied: bool = False
    delay_minutes: float = 0.0
    batch_count: int = 1
    gps: float = Field(ge=0.0, le=1.0, default=0.0)
    rationale: str = ""
    ai_explanation: str | None = None
    ai_explanation_label: str = "AI-generated"

    def content_hash(self) -> str:
        """SHA-256 over the full patch content (all fields including patch_id)."""
        return _canonical_sha256(self.model_dump(mode="json"))

    def semantic_hash(self) -> str:
        """SHA-256 over the decision-content of the patch, excluding patch_id (volatile UUID).

        Two logically identical patches produced on different runs yield the same semantic hash.
        """
        data = self.model_dump(mode="json", exclude={"patch_id", "ai_explanation"})
        return _canonical_sha256(data)


class ValidatedCandidate(BaseModel):
    """A patch candidate after Safety Gate evaluation."""

    model_config = ConfigDict(frozen=True)

    candidate: PatchCandidate
    safety_result: SafetyCheckResult
    violated_invariants: list[str] = Field(default_factory=list)
    eligibility_gps: float = Field(ge=0.0, le=1.0, default=0.0)


# ---------------------------------------------------------------------------
# Counterfactual bundle
# ---------------------------------------------------------------------------


class CounterfactualBranch(BaseModel):
    """Predicted outcome of one execution strategy."""

    model_config = ConfigDict(frozen=True)

    strategy: str
    predicted_battery_after_pct: float | None = None
    predicted_temp_after_c: float | None = None
    predicted_images_transmitted: int | None = None
    predicted_comm_window_used: bool | None = None
    predicted_gps: float | None = None
    scientific_value: float = Field(ge=0.0, le=1.0, default=0.0)
    final_battery_pct: float | None = None
    maximum_temp_c: float | None = None
    safety_violations: list[str] = Field(default_factory=list)
    goal_preservation_score: float = Field(ge=0.0, le=1.0, default=0.0)
    available: bool = True
    notes: str = ""


class CounterfactualBundle(BaseModel):
    """All three baseline branches for comparison."""

    model_config = ConfigDict(frozen=True)

    command_id: UUID
    arrival_state_timestamp: datetime
    branches: list[CounterfactualBranch]


# ---------------------------------------------------------------------------
# Delta Certificate — dual-hash integrity model
# ---------------------------------------------------------------------------


class HardInvariantCheck(BaseModel):
    """Result of one hard-invariant evaluation."""

    model_config = ConfigDict(frozen=True)

    invariant_id: str
    description: str
    result: SafetyCheckResult
    evaluated_value: Any
    threshold: Any
    evaluation_source: str = "DETERMINISTIC"


class DeltaCertificate(BaseModel):
    """Complete evidence record for one decision.

    Two hash fields serve distinct purposes:

    certificate_hash (cryptographic integrity)
    ==========================================
    SHA-256 over ALL certificate fields EXCEPT certificate_hash itself.
    semantic_replay_hash IS included — changing the semantic form of the
    decision breaks this hash too.
    Every field — including certificate_id, patch_id, decision_timestamp,
    mie_hash, arrival_state_hash, patch_hash, patch_semantic_hash,
    semantic_replay_hash, verifier_version — is included.
    Changing ANY field invalidates this hash.

    Build order: semantic_replay_hash is computed FIRST; then certificate_hash
    is computed over all fields including the set semantic_replay_hash value.

    semantic_replay_hash (deterministic equivalence)
    ================================================
    SHA-256 over the decision-content fields only.
    See module-level docstring for the full semantic normalisation contract.
    """

    model_config = ConfigDict(frozen=True)

    # --- Identity ---
    certificate_id: UUID = Field(default_factory=uuid4)
    verifier_version: str = VERIFIER_VERSION
    scenario_id: str = ""  # operator-assigned scenario label; empty string for ad-hoc runs

    # --- Original command reference ---
    original_command_id: UUID
    original_command_fingerprint: str  # SHA-256 from CommandSealer

    # --- Pre-image hashes (cryptographic source identity — bind cert to specific object instances) ---
    mie_hash: str = ""                # SHA-256 of the full MIE (includes envelope_id); changes on every new MIE object
    arrival_state_hash: str = ""      # SHA-256 of the full arrival StateSnapshot (includes timestamp)
    patch_hash: str = ""              # SHA-256 of the applied PatchCandidate (includes volatile patch_id); empty for EXECUTE/REJECT

    # --- Semantic hashes (replay identity — stable across equivalent runs with fresh objects) ---
    patch_semantic_hash: str = ""           # SHA-256 of PatchCandidate EXCLUDING patch_id; stable across equivalent runs
    command_semantic_hash: str = ""         # SHA-256 of RawCommand stable content (no command_id, no abs timestamps)
    mie_semantic_hash: str = ""             # SHA-256 of MIE stable content (no envelope_id, no abs timestamps)
    arrival_state_semantic_hash: str = ""   # SHA-256 of StateSnapshot stable content (no absolute timestamps)

    # --- Decision content ---
    sdr_summary: StateDriftReport
    applied_patch: PatchCandidate | None = None
    preserved_goals: list[str] = Field(default_factory=list)
    hi_check_results: list[HardInvariantCheck] = Field(default_factory=list)
    gps: float | None = None
    counterfactual: CounterfactualBundle | None = None
    verdict: VerdictStatus
    verdict_precedence_step: int
    decision_timestamp: datetime

    # --- AI explanation (labelled; never used for safety decisions) ---
    ai_explanation: str | None = None
    ai_explanation_label: str = "AI-generated"

    # --- Integrity hashes (build order: semantic_replay_hash first, then certificate_hash) ---
    certificate_hash: str | None = None
    semantic_replay_hash: str | None = None

    # -----------------------------------------------------------------------
    # Cryptographic integrity hash
    # -----------------------------------------------------------------------

    def compute_hash(self) -> str:
        """SHA-256 over ALL fields except certificate_hash itself.

        Includes: certificate_id, verifier_version, scenario_id,
                  original_command_id, original_command_fingerprint,
                  mie_hash, arrival_state_hash, patch_hash, patch_semantic_hash,
                  sdr_summary, applied_patch (including patch_id),
                  preserved_goals, hi_check_results, gps, counterfactual,
                  verdict, verdict_precedence_step, decision_timestamp,
                  ai_explanation, ai_explanation_label,
                  semantic_replay_hash  ← INCLUDED (changing it invalidates this hash).

        Any change to any included field invalidates this hash.
        Caller MUST compute and set semantic_replay_hash before calling this method.
        """
        data = self.model_dump(
            mode="json",
            exclude={"certificate_hash"},  # only exclude the hash being computed
        )
        return _canonical_sha256(data)

    def verify_hash(self) -> bool:
        """Return True if the stored certificate_hash matches the recomputed value."""
        if self.certificate_hash is None:
            return False
        return self.certificate_hash == self.compute_hash()

    # -----------------------------------------------------------------------
    # Semantic replay hash
    # -----------------------------------------------------------------------

    def compute_semantic_replay_hash(self) -> str:
        """SHA-256 over stable decision content, normalising out volatile identifiers.

        See module-level docstring for the full semantic normalisation contract.

        Key design: uses semantic_content_hash() values (not content_hash() values)
        for the command, MIE, and arrival state so that two runs with fresh object
        IDs and shifted absolute timestamps still produce the same hash when the
        logical decision content is identical.

        Excluded (volatile across equivalent runs):
          certificate_hash, semantic_replay_hash   (what we compute)
          certificate_id                           (new UUID each run)
          decision_timestamp                       (wall-clock time)
          sdr_summary.command_id                   (derived from command UUID)
          applied_patch.patch_id                   (new UUID each run)
          applied_patch.ai_explanation             (may vary)
          ai_explanation                           (may vary)
          counterfactual.command_id                (UUID)
          mie_hash, arrival_state_hash             (full content_hash — includes volatile UUIDs/timestamps)
          original_command_id, original_command_fingerprint  (per-run volatile)

        Included (stable decision content):
          verifier_version, scenario_id,
          command_semantic_hash  (stable command content hash),
          mie_semantic_hash      (stable MIE content hash),
          arrival_state_semantic_hash  (stable state content hash),
          patch_semantic_hash,
          sdr_relative_delay_seconds, sdr deltas,
          applied_patch decision fields,
          preserved_goals, hi_check_results, gps,
          counterfactual branches,
          verdict, verdict_precedence_step.

        NOTE: command_semantic_hash, mie_semantic_hash, and arrival_state_semantic_hash
        are stored in the certificate (computed externally in certificate_builder.build())
        so they are available here without needing access to the original source objects.
        """
        # Build a normalised representation of the SDR deltas (strip command UUID, absolute timestamps)
        sdr_relative_delay = (
            self.sdr_summary.arrival_state_timestamp - self.sdr_summary.send_state_timestamp
        ).total_seconds()
        sdr_data = {
            "relative_delay_seconds": sdr_relative_delay,
            "deltas": [
                {
                    "field": d.field,
                    "expected_value": d.expected_value,
                    "actual_value": d.actual_value,
                    "severity": d.severity,
                    "impact_description": d.impact_description,
                }
                for d in self.sdr_summary.deltas
            ],
        }

        # Normalised patch representation (strip patch_id and ai_explanation)
        patch_data: dict[str, Any] | None = None
        if self.applied_patch is not None:
            patch_data = self.applied_patch.model_dump(
                mode="json",
                exclude={"patch_id", "ai_explanation"},
            )

        # Normalised counterfactual (strip command UUID and absolute timestamps)
        cf_data: dict[str, Any] | None = None
        if self.counterfactual is not None:
            cf_data = {
                "branches": [
                    b.model_dump(mode="json") for b in self.counterfactual.branches
                ],
            }

        # HI check results: include only semantically stable fields.
        # evaluated_value and threshold may contain absolute timestamps (e.g. HI-4 expiry ISO string)
        # that change when the same logical decision is replayed with shifted absolute timestamps.
        hi_semantic = [
            {
                "invariant_id": c.invariant_id,
                "description": c.description,
                "result": c.result,
                "evaluation_source": c.evaluation_source,
            }
            for c in self.hi_check_results
        ]

        payload: dict[str, Any] = {
            "verifier_version": self.verifier_version,
            "scenario_id": self.scenario_id,
            # Use semantic hashes (not content_hash / not command_id / not fingerprint)
            "command_semantic_hash": self.command_semantic_hash,
            "mie_semantic_hash": self.mie_semantic_hash,
            "arrival_state_semantic_hash": self.arrival_state_semantic_hash,
            "patch_semantic_hash": self.patch_semantic_hash,
            "sdr": sdr_data,
            "applied_patch": patch_data,
            "preserved_goals": self.preserved_goals,
            "hi_check_results": hi_semantic,
            "gps": self.gps,
            "counterfactual": cf_data,
            "verdict": self.verdict,
            "verdict_precedence_step": self.verdict_precedence_step,
        }
        return _canonical_sha256(payload)

    def verify_semantic_replay_hash(self) -> bool:
        """Return True if the stored semantic_replay_hash matches the recomputed value."""
        if self.semantic_replay_hash is None:
            return False
        return self.semantic_replay_hash == self.compute_semantic_replay_hash()


# ---------------------------------------------------------------------------
# Audit record — in-memory hash-linked chain
#
# KNOWN LIMITATION: This is an IN-MEMORY hash-linked audit chain.
# It is NOT a persisted append-only log.  The list can be cleared via
# clear_audit_log() (required for test isolation) and tail-truncation
# (deleting the last N entries) is not detectably prevented.
# Sequence numbers and hash linkage detect insertion, reordering, and
# interior deletion.  Tail-truncation protection requires a persisted
# trusted head anchor and is not implemented in Phase 1.
# ---------------------------------------------------------------------------


class AuditEntry(BaseModel):
    """One immutable entry in the in-memory hash-linked audit chain.

    Chain integrity:
    - sequence_number provides an explicit monotone index (0-based).
    - previous_entry_hash links this entry to its predecessor (empty string for first entry).
    - entry_hash covers ALL fields except itself, including entry_id, sequence_number,
      certificate_id, previous_entry_hash, and decision_timestamp.
    - Mutating any field or breaking the chain is detectable via verify_chain().
    - Interior deletion or reordering is detectable (via hash linkage and sequence numbers).
    - Tail-truncation is NOT detectable without a persisted trusted head anchor.
    """

    model_config = ConfigDict(frozen=True)

    entry_id: UUID = Field(default_factory=uuid4)
    sequence_number: int = 0  # monotone 0-based index; set by append_audit
    certificate_id: UUID
    certificate_hash: str
    semantic_replay_hash: str  # carried from the certificate for quick chain queries
    verdict: VerdictStatus
    decision_timestamp: datetime
    command_id: UUID
    command_fingerprint: str
    # Chain link — SHA-256 of the previous entry (empty string for the first entry)
    previous_entry_hash: str = ""
    # SHA-256 over all fields except entry_hash itself
    entry_hash: str | None = None

    def compute_hash(self) -> str:
        """SHA-256 over all fields EXCEPT entry_hash.

        Includes: entry_id, sequence_number, certificate_id, certificate_hash,
                  semantic_replay_hash, verdict, decision_timestamp, command_id,
                  command_fingerprint, previous_entry_hash.

        Changing any of these — or severing the previous_entry_hash chain link —
        invalidates this entry's hash.
        """
        data = self.model_dump(mode="json", exclude={"entry_hash"})
        return _canonical_sha256(data)

    def verify_integrity(self) -> bool:
        """Return True if entry_hash matches the recomputed value."""
        if self.entry_hash is None:
            return False
        return self.entry_hash == self.compute_hash()


def verify_audit_chain(entries: list[AuditEntry]) -> tuple[bool, str]:
    """Verify integrity and chain linkage for a sequence of AuditEntry objects.

    Checks:
    1. The first entry has previous_entry_hash == "" and sequence_number == 0.
    2. Each entry's entry_hash is valid (verify_integrity).
    3. Each entry's previous_entry_hash equals the entry_hash of its predecessor.
    4. Each entry's sequence_number is exactly one greater than its predecessor's.

    Detects: insertion, reordering, interior deletion, field tampering.
    Does NOT detect: tail-truncation (a known limitation of in-memory chains).

    Returns:
        (True, "") if the chain is intact.
        (False, reason) with a human-readable error message if any check fails.
    """
    if not entries:
        return True, ""

    # Check first entry has empty previous_entry_hash and sequence_number 0
    if entries[0].previous_entry_hash != "":
        return False, (
            f"Entry 0 ({entries[0].entry_id}): expected empty previous_entry_hash, "
            f"got '{entries[0].previous_entry_hash}'"
        )
    if entries[0].sequence_number != 0:
        return False, (
            f"Entry 0 ({entries[0].entry_id}): expected sequence_number 0, "
            f"got {entries[0].sequence_number}"
        )

    for i, entry in enumerate(entries):
        if not entry.verify_integrity():
            return False, f"Entry {i} ({entry.entry_id}): entry_hash verification failed"
        if i > 0:
            expected_prev = entries[i - 1].entry_hash
            if entry.previous_entry_hash != expected_prev:
                return False, (
                    f"Entry {i} ({entry.entry_id}): previous_entry_hash "
                    f"'{entry.previous_entry_hash}' does not match "
                    f"predecessor entry_hash '{expected_prev}'"
                )
            expected_seq = entries[i - 1].sequence_number + 1
            if entry.sequence_number != expected_seq:
                return False, (
                    f"Entry {i} ({entry.entry_id}): sequence_number {entry.sequence_number} "
                    f"is not sequential (expected {expected_seq})"
                )

    return True, ""
