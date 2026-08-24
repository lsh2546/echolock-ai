# Video Production Kit

Target: 2:58, 1920×1080, 30 fps, English narration and burned-in English
subtitles. Use `demo-video-script.md` and `demo-video-en.srt` as the locked text.

## Verified actual-screen assets

These PNGs were captured from the running FastAPI app at a 1600×900 browser
viewport after the final 243-test release build:

| Asset | Use |
|---|---|
| `docs/assets/demo-hero-actual.png` | Opening UI and benchmark disclaimer |
| `docs/assets/demo-execute-actual.png` | EXECUTE verdict |
| `docs/assets/demo-adapt-actual.png` | ADAPT verdict and 40% power patch |
| `docs/assets/demo-defer-actual.png` | DEFER verdict |
| `docs/assets/demo-reject-actual.png` | REJECT verdict |
| `docs/assets/demo-adapt-counterfactual-actual.png` | Three futures, Delta Certificate, and CHAIN VERIFIED |
| `docs/assets/echolock-hero.png` | Opening/closing overview graphic |
| `docs/assets/architecture.png` | Trust-boundary explanation |
| `docs/evidence/ibm-bob/*.jpg` | Bob evidence montage; retain attribution caption |

## Edit order

1. 0:00–0:20: `echolock-hero.png`, then actual ADAPT screen. Animate only
   zoom/crop; do not animate new values.
2. 0:20–0:38: architecture diagram with the untrusted AI proposer highlighted.
3. 0:38–1:24: actual four-verdict frames, with ADAPT held longest.
4. 1:24–2:18: actual three-futures/certificate/audit frame. Zoom from the three
   columns to the verified certificate and CHAIN VERIFIED label.
5. 2:18–2:37: actual hero benchmark metrics with disclaimer visible.
6. 2:37–2:52: Bob evidence files 02, 04, and 05; show the attribution sentence.
7. 2:52–2:58: representative image and closing line.

## Non-negotiable overlays

- Whenever 100% or 0% appears: `60 fixed, balanced deterministic synthetic scenarios`.
- At least once during the counterfactual: `Toy model · not flight prediction`.
- During Bob evidence: `Bob: initial architecture + core Phase 0/1 · Codex: independent review, corrections + Phase 2/UI`.
- Do not display emails, account identifiers, subscriptions, desktop paths, or
  the original unredacted photographs.

No final video binary or public upload was created in this preparation step.
