# EchoLock Phase 2 Evaluation

- Scenarios: 60 (15 per verdict)
- Verdict counts: {'EXECUTE': 15, 'ADAPT': 15, 'DEFER': 15, 'REJECT': 15}
- Safety violation rate: 0.00%
- Unsafe-command interception recall: 100.00%
- Safe-command false rejection rate: 0.00%
- Mean goal-preservation score: 0.7195
- Mean battery margin above 20% floor: 37.5200 percentage points
- Adaptation success rate: 100.00%
- Mean measured decision latency: 6.5306 ms
- Deterministic replay consistency: 100.00%

The spacecraft physics and thermal behavior are deterministic toy models for a PoC,
not flight-accurate predictions. Measured latency varies by host; decisions and all
non-latency metrics are deterministic.
