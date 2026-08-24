"""FastAPI judge-demo integration tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from echolock.certificate_builder import clear_audit_log
from echolock.webapp import app

client = TestClient(app)


def setup_function() -> None:
    clear_audit_log()


def test_root_and_health_are_available() -> None:
    root = client.get("/")
    assert root.status_code == 200
    assert "A command can be correct when sent" in root.text
    assert client.get("/health").json() == {
        "status": "ok", "mode": "deterministic-local-demo"
    }


def test_catalog_contains_all_four_verdicts() -> None:
    response = client.get("/api/scenarios")
    assert response.status_code == 200
    rows = response.json()
    assert [row["id"] for row in rows] == [
        "NOMINAL", "LOW_BATTERY", "COMM_LOSS", "OVERHEAT"
    ]
    assert {row["expected_verdict"] for row in rows} == {
        "EXECUTE", "ADAPT", "DEFER", "REJECT"
    }


def test_each_scenario_returns_verified_end_to_end_evidence() -> None:
    expected = {
        "NOMINAL": "EXECUTE",
        "LOW_BATTERY": "ADAPT",
        "COMM_LOSS": "DEFER",
        "OVERHEAT": "REJECT",
    }
    for seed, verdict in expected.items():
        response = client.get(f"/api/scenarios/{seed}")
        assert response.status_code == 200
        data = response.json()
        assert data["verdict"] == verdict
        assert len(data["counterfactual"]["branches"]) == 3
        assert data["integrity"] == {
            "certificate_hash_valid": True,
            "semantic_replay_hash_valid": True,
            "mie_seal_present": True,
            "command_seal_present": True,
        }


def test_audit_trace_is_linked_after_scenario_runs() -> None:
    client.get("/api/scenarios/NOMINAL")
    client.get("/api/scenarios/LOW_BATTERY")
    audit = client.get("/api/audit").json()
    assert audit["chain_valid"] is True
    assert len(audit["entries"]) == 2
    assert audit["entries"][0]["previous_entry_hash"] == ""
    assert audit["entries"][1]["previous_entry_hash"] == audit["entries"][0]["entry_hash"]


def test_evaluation_endpoint_exposes_phase2_metrics() -> None:
    metrics = client.get("/api/evaluation").json()
    assert metrics["scenario_count"] == 60
    assert metrics["unsafe_command_interception_recall"] == 1.0
    assert metrics["safety_violation_rate"] == 0.0
    assert metrics["deterministic_replay_consistency"] == 1.0


def test_unknown_scenario_fails_validation() -> None:
    assert client.get("/api/scenarios/UNKNOWN").status_code == 422
