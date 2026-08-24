# Submission Copy and Asset Plan

## Event Platform copy

**Title**  
EchoLock AI — Intent Escrow for Delayed Deep-Space Commands

**One-line description**  
EchoLock revalidates a delayed command when it arrives, preserves its mission
intent with a verified safe patch, and proves every decision cryptographically.

**Problem**  
A deep-space command can be safe when Earth sends it and dangerous when a
spacecraft receives it minutes later. Battery, temperature, communications, and
mission state drift in transit. Blind execution risks the vehicle; blanket
rejection wastes mission value.

**Solution**  
EchoLock seals the original command and a Mission Intent Envelope containing its
goal, assumptions, hard invariants, and authorised adaptation limits. At arrival
it returns `EXECUTE`, `ADAPT`, `DEFER`, or `REJECT`. It compares forcing the
original, rejecting everything, and applying the verified action, then issues a
Delta Certificate and hash-linked audit entry. The original command is never
mutated.

**AI and technical approach**  
IBM Bob was the principal AI development partner for the initial architecture and
core Phase 0/1 implementation, including schemas, sealing, safety rules, patch
boundaries, and automated tests. Codex independently audited and corrected those
phases, then built Phase 2 and the local demo. Runtime execution authority remains
deterministic by design: future AI proposers may suggest patches or explanations,
but they cannot bypass seal verification, hard invariants, the 0.70
goal-preservation threshold, or verdict precedence. The PoC uses Python, Pydantic,
FastAPI, pytest/Hypothesis, canonical JSON, and SHA-256.

**Why it matters**  
Communication delay makes continuous ground control impossible for distant
assets. EchoLock supplies a testable contract between operator intent and onboard
autonomy: adapt only within explicit authority, preserve useful mission value
when safe, and return evidence that operators can verify.

**Evaluation disclaimer**  
The reported 100% interception, 0% safety violations, and 100% replay consistency
are results from 60 fixed, balanced, deterministic synthetic PoC scenarios. They
are not estimates of performance on flight telemetry or an operational mission
distribution. Physics and thermal behavior are toy models.

## Representative image plan

Create one 16:9 image from the local UI—no invented spacecraft photo needed.

1. Left: delayed command timeline, “SAFE WHEN SENT,” battery 62%.
2. Center: arrival state, “14 MIN LATER,” battery 24%.
3. Right: the three futures. Force Original red (reserve violated), Reject Entirely
   gray (zero science), EchoLock Verified green (safe reduced science).
4. Bottom-right: Delta Certificate “HASH VERIFIED.”
5. Footer: “Deterministic synthetic PoC— not flight performance.”

The judge should understand the conflict and the third option without reading a
paragraph. Use actual demo values and an actual certificate status.

## IBM Bob evidence checklist

Store public-safe evidence under `docs/evidence/ibm-bob/` only after redaction.

- [ ] Bob welcome/instance screen with email, subscription ID, and account details redacted.
- [ ] Initial EchoLock readiness prompt sent to Bob.
- [ ] Bob-generated architecture/core file or test diff with timestamp/context.
- [ ] Bob Phase 1 completion summary and test result.
- [ ] Bob usage/completion screen; crop or redact private account information.
- [ ] IBM SkillsBuild completion certificate, with unnecessary identifiers redacted.
- [ ] Short `EVIDENCE.md` mapping each artifact to the exact Bob contribution.
- [ ] Confirm no screenshot exposes desktop filenames, email, tokens, or unrelated personal data.

## Reproduction checklist

- [ ] Python 3.11+ clean environment.
- [ ] `python -m pip install -e ".[dev]"` succeeds.
- [ ] Test command reports 243/243 and 94.32% on the baseline.
- [ ] Evaluation produces 60 records and four groups of 15.
- [ ] Certificate verification is 60/60; semantic replay verification is 60/60.
- [ ] All four UI cards return the labelled verdict.
- [ ] The synthetic/toy-model disclaimer is visible in README, UI, video, and submission copy.
- [ ] Public repository secret scan and license/asset review pass before publication.
