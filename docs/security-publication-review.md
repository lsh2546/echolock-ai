# Public Release Security and Privacy Review

Review date: 2026-08-24. Scope: the clean release workspace.

## Results

- No real API key, token, password, private key, email, subscription ID, payment
  detail, or authentication cookie was found in public project content.
- `.env.example` contains commented placeholders only; external AI is disabled.
- No Windows user path, `AppData`, OneDrive path, temporary path, or `file://` URI
  is present in public content.
- `127.0.0.1` appears only in local reproduction instructions.
- Caches, virtual environments, coverage data, build outputs, `.env`, keys, and
  local audit artifacts are excluded by `.gitignore`.
- The UI has no remote fonts, analytics, cookies, tracking scripts, third-party
  images, or external JavaScript.
- Bob evidence was copied only after cropping unrelated desktop content. No IBM
  account email, subscription ID, payment data, or token is visible.
- GitHub Actions use immutable action SHAs. Secret-scan failure is not ignored.

## Known publication risks

1. Photographs are provenance context, not signed evidence or IBM endorsement.
2. Create public Git history from this clean workspace, never its parent folders.
3. The SkillsBuild certificate file is absent. Do not invent a substitute.
4. Public deployment exposes a toy PoC and must retain the synthetic disclaimer.

## Release gates

- [x] Local secret and personal-path scan
- [x] Evidence privacy inspection
- [x] Dependency/license notice
- [x] CI actions pinned to immutable SHAs
- [x] CI command covers all 243 baseline tests
- [x] Secret scan is blocking
- [ ] Fresh public GitHub Actions run succeeds
- [ ] Public demo health and four-verdict smoke test succeeds
- [ ] Uploaded video is under 3:00 and shows the synthetic disclaimer
