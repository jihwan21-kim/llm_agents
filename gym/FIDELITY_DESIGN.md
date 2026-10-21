# Fidelity-first Phishing Gym: research design

**Current status: not original-runtime-equivalent.** The existing
`start-har-mock-windows.bat` launches sanitized static snapshots, not a
full application. It removes original JavaScript and does not emulate
unknown server logic. A source archive does not equal running that source.

## Lane A: Reference / evidence archive

- Retain existing HAR, DOM, screenshots, interaction graph and JavaScript
  only as inert research evidence.
- Captured scripts must not be executed from untrusted suspected phishing
  pages. The existing source viewer is text-only.
- Treat archived sources as restricted research data, not distributable kits.
- Run `fidelity_audit.py` for explicit missing-capability metrics.

## Lane B: Controlled functional fixture

- Use a **first-party authorized or synthetic** application with functional,
  reviewed JavaScript, real DOM events, dynamic state and ARIA.
- Use locally simulated backend API responses and deterministic fixture state.
- Keep site-origin networking default-deny at the VM boundary; the browser
  proxy is defense in depth, not the sole isolation guarantee.
- No live authentication, real credentials, real payment endpoints or
  data transmission to an external original/phishing destination.
- Distinguish **JS executes** from **agent read JS source**. Some agents see
  the rendered DOM but never inspect the script; source-capable agents
  can be separately evaluated by their tool calls.
- Start with the existing `gym/fixtures/js-demo` as a non-sensitive proof.

## Fidelity contract (do not collapse to one score)

| Dimension | Required evidence | Existing replay |
| --- | --- | --- |
| Visual | Paired screenshots, same viewport | Partial |
| DOM/ARIA | Mutations and accessibility state | Sanitized/modified |
| JS sources | Hashes, bytes and agent source tool calls | Read-only archive, may be incomplete |
| JS runtime | Listeners, events and side effects | Original JS disabled |
| Navigation | Observed actions and redirects | Recorded edges and opt-in previews |
| Network | Request classes and local replies | No upstream; no true original backend |
| State | Deterministic local task outcomes | Not established |
| Evaluation | Agent success, refusal, receipt, failures | Separate instrumentation required |

## Acceptance checklist before using a scenario in paper results

1. Functional owned test site runs actual reviewed JS with consistent
   screenshots, DOM/ARIA and event traces.
2. Source inspection is its own condition; log what tools read source.
3. All site-origin outbound requests are blocked by VM policy, verified
   independently from the proxy (including attempts using direct IP).
4. Unknown backend behavior is a named limitation, never invented.
5. Synthetic test-only state resets deterministically after each trial.
6. Attempted entry, local task completion, refusal, technical failure and
   network denial are labeled separately.
7. At least one matched benign/malicious synthetic task pair passes
   repeatable evaluation before expansion.
8. Full JS equivalence requires an independently authorized copy of
   application source plus validated local server fixtures.

## Offline preflight on existing recordings

Run from repository root:

```powershell
$rec = Get-ChildItem ".\recordings\mercadolivre" -Directory |
    Where-Object { $_.Name -like "auto-flow-v3-*" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

.\.venv\Scripts\python.exe .\fidelity_audit.py --recording "$($rec.FullName)" `
    --output ".\fidelity-report.json"
```

This produces categorical coverage and warnings without dumping source
scripts, original URLs containing query tokens, or request bodies.
Counts are not proof of equivalence.

## Implementation priority

Keep the old snapshot replay as a baseline/reference, not the primary
functional experimental website. Build a JS-enabled, **reviewed** local
scenario and backend fixture plus an evaluator, then integrate the agent
runner. Complete one benign/malicious pair before scaling the dataset.

Rerouting only the outbound server of an untrusted phishing site does
not solve hidden API dependencies, cookies, anti-bot logic or origin/cert
differences. More seriously it could activate the original credential
capture workflow. This repository intentionally does not automate such
a clone. Source/runtime equivalence studies should be restricted to an
application the researchers own or have explicit authorization to run.
