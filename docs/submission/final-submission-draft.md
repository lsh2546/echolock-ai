# AI Builders Challenge Submission Draft

## Title

EchoLock AI — Intent Escrow for Delayed Deep-Space Commands

## One-line description

EchoLock revalidates delayed commands at arrival, preserves mission intent with a
verified safe patch, and proves every decision cryptographically.

## Problem

A command can be correct when Earth sends it and dangerous when a spacecraft
receives it minutes later. Battery, temperature, communications, and mission state
can drift during the delay. Blind execution risks the vehicle, while blanket
rejection discards useful mission value.

## Solution

EchoLock seals the untouched original command with a Mission Intent Envelope that
records its goal, assumptions, hard invariants, and authorised adaptation limits.
At arrival, a deterministic Safety Gate returns EXECUTE, ADAPT, DEFER, or REJECT.
When adaptation is safe and authorised, EchoLock attaches a separate Intent-Safe
Patch without rewriting the original command.

The Counterfactual Predictor compares three futures before action: forcing the
original, rejecting everything, and applying the EchoLock-verified decision. Each
decision produces a SHA-256 Delta Certificate and a hash-linked audit entry.

## Why it is different

EchoLock focuses on arrival-time stale-command revalidation at the command-execution
trust boundary. Its combination is an immutable original-command escrow, an
intent-preserving patch, a three-way counterfactual comparison, and a
cryptographically verifiable Delta Certificate. This is scoped positioning, not a
world-first or priority claim.

NASA's Ground Data Systems and Mission Operations guidance motivates the need for
execution delays, validation gates, pre-execution re-validation, and logging.
EchoLock is an independent student PoC; it is not a NASA implementation,
endorsement, certification, or flight-qualified system.

## Technology

Python, Pydantic, FastAPI, canonical JSON, SHA-256, pytest, Hypothesis, Docker,
GitHub Actions, and Render. Generative AI is deliberately isolated from execution
authority; no AI output can bypass seals, hard invariants, the 0.70
goal-preservation threshold, or verdict precedence.

## IBM Bob use

IBM Bob was the principal AI development partner for the initial architecture and
core Phase 0/1 implementation, including schemas, command and MIE sealing, safety
rules, patch boundaries, and automated tests. Codex independently audited and
corrected Phase 1/1.1, then implemented Phase 2, the FastAPI demo, and submission
preparation. Redacted, actual Bob screenshots and a file-level development log are
included in the repository.

## Evaluation

The project includes 60 fixed, balanced, deterministic synthetic scenarios: 15
each for EXECUTE, ADAPT, DEFER, and REJECT. The benchmark reproduces all decisions,
verifies 60/60 certificate hashes and 60/60 semantic replay hashes, and records
zero safety violations in this constructed dataset. These values do not claim
flight performance or operational accuracy.

## Known limitations

Battery, thermal, and communications behavior are deterministic toy models. The
audit chain is in memory and needs a persisted, externally anchored trusted head
for production. The PoC has no flight telemetry, hardware-in-the-loop validation,
external LLM integration, or flight qualification.

## Links

- GitHub: https://github.com/lsh2546/echolock-ai
- Live demo: https://echolock-ai.onrender.com/
- Demo video: https://youtu.be/Xpfskr3YJDM
- NASA motivation: https://www.nasa.gov/smallsat-institute/sst-soa/ground-data-systems-and-mission-operations/
- Adjacent paper: https://arxiv.org/abs/2604.17176
