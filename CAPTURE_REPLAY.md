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


## HTTPS certificate errors during capture

If Playwright prints `ERR_CERT_AUTHORITY_INVALID`, Chrome refused to
validate the live site's certificate **before recording started**. This is
not an HAR problem. The recorder now writes `capture_failure.json` and exits
without storing an invalid capture.

In a disposable research VM, check whether the regular browser also reports
a certificate warning for that destination. Inspect the certificate issuer,
subject/hostname and dates without proceeding past the warning. If the issuer
is a locally configured HTTPS inspection proxy, verify its intended CA is
properly installed in the dedicated test environment. If the live site's
certificate itself is invalid, treat it as a security observation and use a
different authorized capture target or a properly configured local mock.

The recorder deliberately does not set `ignore_https_errors`, disable
certificate checks or auto-click Chrome's certificate interstitial.
Those workarounds would hide a security signal from the research experiment.


## Debugging unresponsive buttons in offline replay

The old recorder watched only native buttons, links, and explicit ARIA
buttons. Real sites sometimes implement clickable DIV or SPAN elements.
The recorder and local replay now accept non-button click targets and retain
`action-events.json`, which contains only the event type, element selector,
and graph state index (never typed form values).

When capture finishes, compare **Captured N clicks**, **Saved N states**,
and **N action edges** in the console. Inspect `transitions.json`: the
first captured page normally has `from: 0` edges for actions that reached
new states. If the recorder saved many screens but no edges, the replay
cannot safely guess what button led where. Those old recordings need a
fresh recording or separately verified manual mappings.

Open the proxy browser's developer console when a replay click does not
move. `No recorded transition for clicked element` means that the
element has no matching recorded graph edge. Read `http://mock.test/__mock_capture/events`
in the same proxy browser to inspect which events were locally observed.

Clicks within cross-origin frames, separate pop-up windows or navigation
blocked by the recorder's read-only network guard may still be unrecorded.
Only user-observed transitions can be replayed. Do not disable the guard
or provide genuine account credentials to force an inaccessible screen.


## Why the first replay screen may not be step 0

The recorder starts at DOMContentLoaded, when many sites are still rendering.
It can save several automatic DOM-only snapshots before a user action.
An original recording with only an edge such as `23 -> 24 change` has
no observed action edges from steps 0 through 22.

For the initial entry URL, the replay now shows the source state of the
first observed click, submit or change recorded on that same path. The
runner prints `Initial displayed state: N`. You may still inspect exact
screens with `?__mock_step=0` etc.

This is a best-effort entry-state selection, not a reconstruction of missing
actions. Previously unrecorded clicks cannot be inferred from HAR alone.


## Fix for a broad click swallowing a specific button transition

Some recordings have both a broad `no-change` edge (for example
`1 -> 1 click body > main`) and a deeper `changed` edge
(`1 -> 2 click body > main > div:nth-of-type(12)`).
The old replay selected the **first matching edge**. Since every child
inside `main` also matches `body > main`, that no-op edge intercepted
real navigation clicks.

The simulator now selects the **closest, most specific matching recorded
element**, and prefers a changed edge when matching selectors are otherwise
equivalent. This only selects among actually observed edges; it does not
invent transitions or allow original scripts to run.

This fix applies to existing recordings. Pull the latest main, stop the
current mock proxy and restart it with the **same recording folder**;
no new live-site capture is needed for this issue.


## Broad no-change clicks can falsely appear as successful events

The replay event endpoint reports `observed_transition: true` when a
click matches an existing graph edge, even if that edge was `1 -> 1`
and the screen did not change. On a recording that contains `click
body > main no-change`, every click inside `main` could previously
appear as an observed no-op.

The replay now accepts recorded no-change edges only for the **exact
clicked element or its interactive control ancestor**, not a generic
ancestor container. When a click has no supported edge, the proxy logs
it with `observed_transition: false`. The browser console logs the
current step and recorded selectors (without typed field values).
A valid narrower `changed` edge continues to navigate to its
recorded next state.

This fix does not reconstruct unrecorded page transitions or duplicate
live-server POST behavior. To investigate missing paths, check the
existing `transitions.json`, the console warning, and the local event
list before re-recording.


## Analyze HTML + captured JavaScript navigation (without running source code)

The saved HAR already retains inert JavaScript GET/HEAD resource bodies.
To inspect an **existing** recording (no new live access needed), run:

    .venv\Scripts\python.exe navigation_analysis.py ".\recordings\mercadolivre\auto-flow-fixed-20261021T020202Z"

This creates `navigation-analysis.json`, containing:
- `html_routes`: literal same-origin `<a href>` and `<form action>` destinations from each saved DOM state
- `js_route_hints`: literal paths from common JS navigation idioms such as `navigate("/path")`,
  `router.push("/path")`, `location.assign("/path")` and `location.href = "/path"`
- Recorded state/transition counts for comparison

HTML hints and JS hints are **not verified user actions**. JavaScript can use
computed paths, event delegation, minified frameworks, closures, server-side
responses and dynamic values, none of which can be completely resolved from
static HTML/JS text. This report strips query strings and excludes external
targets. Source scripts are never executed to produce the report.

Offline replay can additionally follow an inferred **same-origin HTML anchor
link** if its destination path maps to exactly one recorded HTML state.
The local proxy independently validates this match. Events for these paths
have `static_navigation: true` and `observed_transition: false` to prevent
mistaking inferred routes for experimentally observed outcomes.
Forms, JavaScript-only routes, external origins, and ambiguous SPA paths
are **not** automatically followed.

New automatic captures also save `navigation-events.json`, containing
metadata-only observations of History API push/replace state, popstate,
hashchange and main-frame document navigations. These help build cycles and
revisit edges without executing captured source scripts during offline replay.
History events do not reliably distinguish toolbar Back from programmatic
history movement; the recorded operation names reflect that uncertainty.

Do not re-enable recorded `<script>`, `onclick` or remote resources inside
the replay. Doing so would make the security experiment capable of issuing
uncontrolled network requests and would undermine its local-only guarantees.


## When navigation-analysis.json shows zero HTML and JS targets

A zero count is **not** evidence of a failed recording. SPA applications
frequently use JS event handlers and in-memory state, not `href`/route
literals. Auto-saved HTML intentionally lacks `<script>` and `onclick`,
and not every JavaScript file's response body is preserved in the HAR.

The enhanced analyzer distinguishes:
- `html_coverage`: number of anchor, form, button and role-button tags
  in saved HTML snapshots
- `har_coverage`: number of script GET/HEAD resources, categorized by
  first-party vs external/CDN origin, and how many bodies were inspectable
- `graph`: actually observed navigation edges, which states are reachable
  from the first recorded navigation, and which are disconnected

It now **inspects** script bodies from external/CDN origins as well, but labels
their literal path candidates `script_origin: external`, `verified: false`.
Vendor JS may contain unrelated paths; no such hint becomes an observed
transition or an automatic replay edge.

Run `navigation_analysis.py` again on an old recording to get the extended
diagnostics. If `js_route_hint_count` remains 0 despite script bodies being
analyzed, that's compatible with dynamic framework navigation or purely
in-memory UI changes. The **observed click graph** remains the primary
source of evidence. Avoid re-enabling untrusted site scripts in the offline
proxy just to make buttons work.
