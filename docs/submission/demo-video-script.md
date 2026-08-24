# Three-Minute Demo Script and Shot List

Target runtime: **2:50–2:58**. English narration. Record at 1080p, large cursor,
browser zoom 110–125%, no email/account/private data on screen.

| Time | Screen | English narration |
|---|---|---|
| 0:00–0:20 | Full-screen command card; animate Earth → spacecraft delay, then battery 85% → 28% | “This command is safe when Earth sends it. Fourteen minutes later, it arrives to a different spacecraft: the battery has fallen from eighty-five to twenty-eight percent. Force it and the spacecraft crosses its reserve. Reject it and the mission loses the data. EchoLock finds—and proves—the third option.” |
| 0:20–0:38 | Hero and Mission Intent Envelope diagram | “EchoLock is an intent escrow for delayed space commands. It seals the untouched original command together with its goal, assumptions, hard invariants, and the adaptations the operator has authorised.” |
| 0:38–1:04 | Click EXECUTE, then ADAPT scenario | “At arrival, EchoLock verifies both seals and rechecks the command against current state. A safe command executes. When conditions drift, it can attach a separate Intent-Safe Patch. The original is never rewritten.” |
| 1:04–1:24 | Quickly click DEFER and REJECT | “If a safe opportunity exists before expiry, EchoLock defers. If integrity fails, the command expires, or no safe authorised option remains, it rejects. The precedence is deterministic and fail-closed.” |
| 1:24–1:55 | ADAPT three-branch comparison; pause on red/gray/green cards | “The Counterfactual Predictor makes the choice visible. Forcing the original violates the battery floor. Rejecting everything saves resources but returns no science. The verified adaptation preserves useful science while every hard invariant still passes. These are deterministic toy-model outcomes, not flight predictions.” |
| 1:55–2:18 | Delta Certificate hash and JSON toggle, then audit entries | “Every decision produces a Delta Certificate. Its SHA-256 self-hash binds the command, intent, arrival state, patch, verdict, checks, and counterfactual evidence. A separate semantic replay hash proves equivalent runs agree, and each audit entry links to the previous one.” |
| 2:18–2:37 | Evaluation metrics with synthetic disclaimer visible | “Across sixty fixed, balanced synthetic cases—fifteen per verdict—the pipeline reproduced every decision, verified sixty certificate hashes and sixty replay hashes, and kept zero safety violations in this constructed benchmark. These numbers do not claim operational accuracy.” |
| 2:37–2:52 | Bob evidence montage: prompt, generated core architecture/tests, completion screen; redact account data | “IBM Bob was the principal AI development partner for the initial architecture and core Phase Zero and One safety pipeline. Codex independently audited, corrected, and continued later phases. The repository records that provenance exactly.” |
| 2:52–2:58 | Logo + one-line differentiator | “EchoLock: preserve the intent, adapt the action, and prove the difference.” |

## Recording checks

- Do not say “NASA-grade,” “flight-ready,” “world first,” or “100% accurate.”
- Keep the synthetic disclaimer on screen whenever 100% or 0% metrics appear.
- Show the same ADAPT case for the hook, three futures, patch, and certificate.
- Show actual IBM Bob artifacts, not a reconstructed marketing animation.
- End before 3:00; leave 2–5 seconds of export margin.
