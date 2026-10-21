# Unified recorder + HAR/DOM to offline mitmproxy mock

This single repository now contains the Playwright recorder and local
mitmproxy replay server. The recorder is an independent Python implementation,
not a copy of Nevin's private agent-sandbox code.

## Automatic workflow capture (updated)

The Windows recorder now automatically saves a DOM + screenshot when a click,
form submission, change, URL navigation, or significant DOM mutation produces
a new screen. There is no need to type 's' after every button. It also
records action selectors and their observed next state in transitions.json
and bundle.json. Press **q + Enter** in the terminal to finish; **s + Enter**
remains available for a manual snapshot when desired.

    .\record-site-windows.bat --app sample --url "https://example.com/" --name auto-test

The file assets.json catalogs exported CSS, images and fonts from the embedded
HAR, alongside the copied files under assets/. HAR still contains captured
static resources and inert JavaScript bytes, but replay **never executes the
original JavaScript**. Complete script-driven UI fidelity is not guaranteed.

Replay now follows observed action-to-state edges, not a universal next-step
counter. Unobserved buttons remain on the current state and produce a local
event marked as not observed. For branching flows, return to the earlier
page in the recording browser and capture the alternative path. Changing
input values may produce additional states that must be recorded separately.

The automatic recorder blocks live POST/PUT/PATCH/DELETE requests by default.
GET/HEAD/OPTIONS are still sent to load the source page and its static assets.
Consequently, server-driven transitions after a blocked write cannot be
captured as genuine downstream states. Record only authorized workflows in
a disposable isolated VM; never input real credentials or payment details.

## Features

1. Capture a live authorized site with Playwright: HAR, HTML snapshots,
   screenshots, and metadata-only browser action events.
2. Sanitize and retain GET/HEAD HAR resource responses (not POST bodies or
   auth headers). DOM snapshots may still contain private information.
3. Intercept the original recorded hostname and URL path using the existing
   upstream-blocking mitmproxy. Replay the captured HTML/CSS/images locally.
4. Remove recorded JavaScript and unsafe external links. Simulate transitions
   using a small local-only form/button handler. It records only filled field
   TYPES, never values, and displays the next recorded snapshot.

Simulated progression is NOT a reproduction of an original backend response,
not proof of successful login and not an authentic server receipt.

## Windows quick start

Requires Python 3.12+, Google Chrome and Git.

    git clone https://github.com/jihwan21-kim/llm_agents.git
    cd llm_agents
    .\setup-windows.bat
    .\setup-capture-windows.bat

First record an innocuous example:

    .\record-site-windows.bat --app sample --url "https://example.com/" --name first-run

For an authorized research site, use its URL instead. Use the separate
Chrome window to navigate. In the recording PowerShell console, type:
- No key required: changed screens and action transitions are saved automatically.
- s then Enter: optionally force a manual snapshot.
- q then Enter: save final state, close browser, write HAR and metadata.

The console prints the exact recording directory. Example (replace date):

    recordings\sample\first-run-20261020T201500Z\

Use ONLY invented test data while recording. Never use real passwords,
OTP codes, personal data, or payment details. Live capture visits a genuine
external site, so use an isolated research VM.

## Run the captured site through the local MITM proxy

Close other processes using port 8080, then start:

    .\start-har-mock-windows.bat ".\recordings\sample\first-run-20261020T201500Z"

Keep that window open, then launch the dedicated proxy Chrome profile:

    .\open-chrome-windows.bat

In this browser only, navigate to the original recording URL shown in the
replay console. Despite the displayed original hostname, this browser uses
the local MITM proxy, which denies all upstream server connections.
DO NOT navigate to that original URL with your regular browser.

For recorded HTTPS sites, trust the existing mitmproxy test CA in your
isolated experiment VM following the main README certificate instructions.
Do not turn off certificate validation to bypass warnings.

The page follows recorded action selectors to saved snapshots using simulated
form submits or buttons. The URL retains its hostname and recorded paths;
a query parameter __mock_step=1 selects subsequent snapshots. For manual
inspection, append that parameter at the recorded entry path.

Review local simulated events in the proxy browser at:

    http://mock.test/__mock_capture/events

These events contain only a step index, event type, and nonempty field types.
No original server receives anything during replay. Existing legacy mocks
and the manager remain available.

## Outputs

Recordings are under recordings/<app>/<run-id>/:
- bundle.json: workflow metadata and snapshot URLs
- trace.har: sanitized GET/HEAD response bodies for offline assets
- step-000.html and step-000.png: HTML and screenshot
- transitions.json: recorded action selector, source and destination state
- assets.json and assets/: extracted CSS, image and font files
- actions are retained in transitions.json, without typed values

Recordings are gitignored but can still contain private DOM content, assets,
query strings, and screenshots. Review before sharing.

Proxy request metadata is logged without captured request bodies or cookies.
Original JavaScript is disabled, external navigation is blocked, and
unrecorded resource paths get 404. CSS/images depend on recorded HAR coverage.
Some single-page app flows will not function because their scripts are removed.
Multi-origin authentication, dynamic remote backends and arbitrary unknown
HTML paths are NOT supported by this generic replay.

Only traffic routed through the proxy is isolated. For stronger guarantees
use an isolated VM and deny all external network traffic at the VM boundary.

## Offline unit test

    python -m unittest discover -s tests -p "test_capture_replay.py" -v

See the GitHub Actions check for a repeatable test run.
