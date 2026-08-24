# Judge Review and Award Strategy

Scores are a deliberately conservative internal estimate, not an official score.

| Criterion | Current estimate | Why it can win | Likely deduction |
|---|---:|---|---|
| Technical Execution | 4.1 / 5 | Working four-verdict pipeline, 243 tests, 94.32% branch+statement coverage, sealed intent, tamper-evident certificate, replay proof | No flight simulator; runtime AI is intentionally outside the safety authority; Bob proof must be visible |
| Innovation | 4.5 / 5 | Memorable “correct when sent, dangerous when received” framing; intent escrow and separate patch rather than command mutation | Must avoid “world first”; judges may know adjacent autonomy/command-validation work |
| Challenge Fit | 4.7 / 5 | Deep-space delay, constrained energy/thermal state, autonomous arrival-time decisions | Toy mission context can feel abstract without a crisp Mars/deep-space example |
| Implementation & Feasibility | 3.6 / 5 | Modular trust boundary permits replacement by approved digital twin/policy engine | Linear battery model, no orbital/thermal dynamics, no telemetry or hardware-in-loop validation |
| Real-World Impact (site criterion) | 3.7 / 5 | Applicable to spacecraft, rovers, lunar assets, and delayed remote operations | No mission-operator interview, agency validation, or quantified operational loss avoided |

**Official-rules estimate:** 16.9 / 20.  
**Event-page five-criterion estimate:** 20.6 / 25.

This is competitive for a finalist conversation, but not a reliable prediction of
a cash prize. The strongest award lane is Innovation; Best Technical Use of IBM
Bob depends heavily on the quality and visibility of Bob evidence.

## Highest-risk deductions, in order

1. **IBM Bob / AI credibility.** The rules say IBM Bob must be a core component.
   Show the actual Bob workflow, prompts, generated core files/tests, and completion
   screen. Explain that AI proposes and helps engineer, while deterministic policy
   remains the only execution authority. Never imply Bob built Codex work.
2. **Feasibility evidence.** The current predictor is a toy model. Show the clean
   adapter path to a mission-approved digital twin and explicitly call the current
   numbers synthetic. If time permits later, obtain one domain-expert review rather
   than adding superficial features.
3. **Perfect-looking metrics.** Balanced constructed scenarios make 100%/0%
   unsurprising. The UI and README now label them as deterministic synthetic
   benchmark results. Do not use “accuracy” or “flight-proven.”
4. **Impact validation.** The problem is plausible but not validated with operators
   or flight data. Present measurable decision evidence, not speculative mission
   savings.
5. **Submission completeness.** Public GitHub, final video, representative image,
   student proof, and Event Platform fields remain incomplete until authorised.

## Winning story

Problem → a safe Earth command ages during a 14-minute delay → execute/reject both
fail → EchoLock rechecks the Mission Intent Envelope → compares three possible
futures → attaches an authorised safe patch → proves the decision with a Delta
Certificate and linked audit entry → reports transparent synthetic evaluation.

### Differentiating sentence

**EchoLock is the intent escrow that asks whether a delayed command is still valid
when it arrives—and preserves its mission goal without rewriting the original.**

### Memorable representative scene

A three-column future comparison: **Force Original** turns red at 16% battery,
**Reject Entirely** preserves power but loses all science, and **EchoLock Verified**
stays green above the 20% reserve while retaining a reduced science return; the
Delta Certificate seal appears underneath.

### First 20-second hook

“This command is safe.” Start a 14-minute signal animation. “But while it travels,
the battery falls from 85% to 28%. Execute it and the spacecraft crosses its reserve.
Reject it and the mission loses the data. EchoLock finds—and proves—the third option.”
