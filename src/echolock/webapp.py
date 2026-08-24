"""FastAPI application for the local EchoLock judge demo."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .demo_service import audit_snapshot, evaluation_summary, run_demo, scenario_catalog
from .simulator import SimulatorSeed

WEB_DIR = Path(__file__).with_name("web")

app = FastAPI(
    title="EchoLock AI — Judge Demo",
    description="Intent-preserving safety verification for delayed deep-space commands.",
    version="2.1.0",
)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (WEB_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "mode": "deterministic-local-demo"}


@app.get("/api/scenarios")
def scenarios() -> list[dict]:
    return scenario_catalog()


@app.get("/api/scenarios/{seed}")
def scenario(seed: SimulatorSeed) -> dict:
    return run_demo(seed)


@app.get("/api/audit")
def audit() -> dict:
    return audit_snapshot()


@app.get("/api/evaluation")
def evaluation() -> dict:
    return evaluation_summary()
