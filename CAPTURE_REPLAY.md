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

The automatic recorder blocks live POST/PUT/PATCH/DELETE requests by
**default**. If a public page's navigation depends on a POST, explicitly
opt in while recording:

```powershell
.\record-site-windows.bat --app demo --url "https://example.com/" --name public-flow --allow-live-post
```

This allows live POSTs (including automatic JavaScript POSTs) to the **real
website**, so use only a site and workflow you are authorized to exercise,
without entering real or synthetic credentials, OTPs, account details or
payment/personal information on a third-party site. PUT/PATCH/DELETE remain
blocked. The recorder saves `livePostAllowed` in `bundle.json` for
traceability. The cleaned `trace.har` retains **only GET/HEAD** entries and
omits POST bodies/headers. However, the raw HAR temporarily exists on disk
during recording, and screenshots/HTML/GET URLs can contain sensitive data.
Use a disposable VM and inspect recordings before sharing.

This live-capture option does **not** authorize sending credentials, nor does
it make captured third-party scripts executable in the offline replay.

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
Only user-observed transitions can be replayed. If an authorized public
site relies on POST for ordinary navigation, use `--allow-live-post` with
no credentials rather than disabling TLS verification. Do not provide
real account credentials to force an inaccessible screen.


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


## Diagnose disconnected snapshots after a delayed DOM update

An existing capture may contain a valid click edge `3 -> 4`, followed by
`step-005.html` with `reason: dom-change` on the *same URL*. Earlier
recorders stored step 5 without any edge from step 4, so later clicks from
step 5 are unreachable when replay starts at step 1.

Run the existing offline analyzer, without re-recording:

    .venv\Scripts\python.exe navigation_analysis.py ".\recordings\mercadolivre\auto-flow-fixed-20261021T020202Z"

The report's `graph.temporal_dom_candidates` lists conservative,
same-URL, consecutive DOM-state transitions. It also reports
`potential_reachable_states` **if** all those candidates were accepted.

**These links are not observed user actions** and never become playable
button clicks. They may be delayed rendering, animation, polling or unrelated
background changes. You must inspect the corresponding step screenshots
and action logs before attaching them to a meaningful interaction.

For new recordings, the recorder also stores DOM settling as
`kind: dom_settle`, `temporal_observation: true`, `observed: false`
in `transitions.json`. Action edges remain a separate class with
`observed: true`.

Do not modify a recorded original transition to call it a verified click
without supporting action evidence. This diagnostic does not solve missing
cross-URL navigation, browser back-button capture or server-driven POST
states; those require a different explicit capture mechanism.


## Experimental preview for disconnected same-URL DOM snapshots

A previous recording of a JavaScript-driven site showed 23 saved states,
17 observed action edges, and 8 unverified consecutive same-URL DOM
settling candidates. The strict observed graph reached 7 states, whereas
including those **hypothetical temporal** connections reached 22 states.

To visually inspect the connected recorded UI without altering the
experiment's original observations, run the server with an **explicit**
preview opt-in:

    .\start-har-mock-windows.bat ".\recordings\mercadolivre\auto-flow-fixed-20261021T020202Z" --preview-dom-settling

Without that flag the replay remains strict and unchanged. With the
flag, the local-only simulator waits a fixed 500 ms on each captured
same-URL DOM settling snapshot and replaces its displayed state with
the next time-adjacent snapshot. This delay is an arbitrary preview
convenience, **not captured page timing**. Browser history is not
expanded by the settling change, so normal Back navigation still returns
to the last user-clicked page instead of a transient loading snapshot.

The simulator never treats these preview changes as observed clicks,
never changes the original `transitions.json`, and never runs recorded
source scripts or sends requests upstream. Candidates with different URLs
or ambiguous source states are skipped. The mode is **not appropriate for
quantitative agent-security experiments** until each transition is
independently checked against recorded behavior. Do not count a preview
transition as a verified successful interaction.

If buttons remain unresponsive while the preview is enabled, check
`http://mock.test/__mock_capture/events`: missing click selectors and
server-dependent actions are separate limitations not repaired by this
feature.


## Action-to-settled-state recorder (new recordings only)

The original automatic recorder saved the first DOM update after a click
(about 650 ms of quiet) and cleared the click before delayed UI rendering
finished. This could strand later saved screens as `dom-change` with no
associated user action. It also selected `[tabindex]` layout ancestors as
clickable controls, sometimes recording generic selectors such as
`body > main` instead of the specific DIV/button clicked.

The new recorder does **not** automatically restore missing actions in old
bundles. Record a **new authorized, isolated test flow** with the existing
read-only command:

    .\record-site-windows.bat --app demo --url "http://127.0.0.1:8000/" --name settled-flow

The recording now:
- emits a browser action ID and keeps an independent global recorder action
  ID for each click, change and submit
- uses the clicked element, not a focus-only `[tabindex]` ancestor, when
  deriving the CSS selector (both target and chosen selectors are recorded,
  never field values)
- waits 1.75 seconds of DOM quiet before recording a changed result (up to
  10 seconds on endlessly updating pages)
- allows up to 3.5 seconds for a button with no DOM/URL change to complete
  before classifying it as `no-change`
- saves `interrupted` rather than inventing a transition when another
  action happens before the previous one settles
- records `blocked-write` rather than successful navigation for clicks
  that attempted forbidden POST/PUT/PATCH/DELETE and did not change the UI
- writes metadata-only `blocked-writes.json` and enriched
  `action-events.json` for auditing

Read `action-events.json` after recording and check the `outcome`,
`selector`, `target_selector`, `from` and `to` fields. The new
report also prints the number of actions in each outcome category. Never
interpret a `blocked-write`, `interrupted`, or `unfinished` action
as an observed navigation or proof that a purchase/login took place.

**Limits:** This change improves action attribution for observed UI
changes. It does not execute original JavaScript during offline replay,
does not recreate backend-driven purchase/login states from blocked writes,
and cannot infer where an action in an existing incomplete recording would
have gone. Use synthetic server responses in your own controlled fixture
when testing backend-dependent flows. Do not remove the read-only network
guard to force a result.

Offline regression suite:

    .venv\Scripts\python.exe -m unittest discover -s tests -p "test_action_settling.py" -v

## Real clicks vs JavaScript-generated clicks (capture fix)

A previously captured cart interaction appeared as an interrupted click
with a blocked POST, immediately followed by an unrelated successful click
on a login control. These logs **do not prove** whether a human clicked the
second control or the page's JavaScript dispatched a second event. It would
misrepresent the experiment to manually remap the cart button to login.

New authorized recordings now preserve `Event.isTrusted` as a boolean:
- user-initiated clicks are recorded as distinct initiating actions
- untrusted `HTMLElement.click()` events are captured as **derived events**,
  not a second human click that interrupts the first
- immediate native form-submit and change events following a click are
  likewise audited as follow-up events
- the resulting settled DOM transition is attributed to the initiating
  user click, with any blocked request separately marked
- genuine second human clicks still interrupt the prior pending action;
  script-only changes without an initiating user click do not magically
  create verified user navigation.

Read `action-events.json` for user actions and `derived-events.json` for
their possible follow-up events. The latter logs action kind, CSS selector,
origin state, reason and parent action ID, **never field contents or request
bodies**. Inspect `blocked-writes.json` for redacted write-block metadata.
`observed: true` on a transition with `blocked_write: true` means a
browser-visible UI change was observed, **not** that a blocked server
transaction completed.

This requires a new recording. Existing bundles are never changed. The
recorded original host remains offline-only at replay; do not use real
credentials or remove upstream blocking. For server-dependent flows,
exercise the logic against a fully controlled fixture with synthetic
responses rather than a live phishing-like origin.

## Text input focus and DOM preview

The opt-in `--preview-dom-settling` mode previously performed a timed
`location.replace` to a same-URL snapshot even on editable screens.
Clicking an email field immediately after a screen appeared could therefore
look like a reload and destroy focus. The generic click listener could also
consider a text input a descendant of a broad recorded click selector.

The local simulator now:
- never treats focusing or clicking an ordinary text field, textarea, or
  dropdown as a synthetic button click (actual `change` events remain separate)
- cancels unverified timed preview navigation once an editable field gains focus
- avoids timed preview when an editable *text* field exists in the page's main
  content; this prevents unintended login/form refreshes
- preserves the prior auto-preview behavior for a product/cart screen
  without a main-content text field, such as cart loading state S2 to S3

Unverified DOM previews remain distinct from actual observed click edges.
Neither typing nor focusing a form sends its contents to the local event
endpoint, and upstream requests remain denied. The existing recorded
bundle is unchanged, and a proxy restart is required to load new simulator JS.

## JavaScript visibility: source inspection vs execution

Agents **do not automatically read JavaScript source** simply because the
browser loads a script. Screenshot-only agents see its *rendered effect*.
Source-reading agents need an explicit browser/source inspection tool or
a page that presents the source as text. These are separate experiment
conditions.

The existing HAR replay still runs no captured original scripts. As an
explicit, **read-only research inspection** facility, it now offers:

- `https://<recorded-host>/__mock_capture/scripts`: browsable listing of
  JavaScript resources found in the saved read-only HAR
- `https://<recorded-host>/__mock_capture/scripts.json`: JSON manifest with
  hashes, filenames, byte counts and recorded/external classification
- `https://<recorded-host>/__mock_capture/source/<SHA256>`: one script as
  `text/plain` with `nosniff`, never as executable JavaScript

The listing is **not linked from the replayed original page**, so it does not
silently change the baseline page DOM or what an agent sees. To study whether
agents can inspect source, explicitly give them a source-reading browser
capability and access to that path as a separate test condition.

Archive protections: GET/HEAD only; content from embedded HAR, no
upstream fetching; duplicates collapsed by body hash; each script <=1 MiB,
up to 128 scripts and 16 MiB total; path names shown without URL query
strings. The console reports how many resources were skipped by limits.
External loaded JS is included if the HAR contains its response body.
Original inline scripts removed from saved HTML are **not reconstructed**;
missing/blocked JS bodies cannot be recovered automatically. A HAR may
contain proprietary/sensitive code: retain it in a restricted research
environment, not in a public report.

### Dynamic JavaScript execution, safely

A tiny benign working example lives in `gym/fixtures/js-demo/`. Unlike the
static replay, its `index.html` loads a first-party `app.js`, and buttons
update item details, the basket count and accessibility properties using
actual DOM event listeners. It is synthetic, makes **zero network calls**,
and has no authentication or data collection.

Start it from the repository root:

```powershell
.\.venv\Scripts\python.exe -m http.server 8000 --bind 127.0.0.1 --directory "gym/fixtures/js-demo"
```

Open `http://127.0.0.1:8000/` in a disposable local browser. Source is at
`/app.js`. This verifies agent behavior against working JavaScript
without executing a captured phishing-like page. Do not treat the demo or
source viewer as proof that the original recorded site is fully functional.

To rerun an **existing** offline recording with source inspection enabled
(no new recording required), update the repository and restart its proxy:

```powershell
git pull origin main
.\start-har-mock-windows.bat "<your recording folder>" --preview-dom-settling
```

This preserves the deny-upstream proxy and existing recorded transitions.

## Reviewed original-JavaScript replay (synthetic fixture only)

Original JS source is important to agents with Chrome debugging/source tools,
but a loaded JS resource is not proof the agent read its source. To separate
**original executable source** from static simulation, there is now one
explicitly trusted, first-party synthetic fixture mode.

Build an offline capture directly from packaged reviewed source (no remote URL
is fetched). On Windows, from the repository root:

```powershell
.\.venv\Scripts\python.exe .\gym\build_js_fixture_recording.py --output ".\recordings\js-demo-trusted"
.\start-har-mock-windows.bat ".\recordings\js-demo-trusted" --trusted-fixture-js
```

Open the dedicated proxy Chrome and navigate to **https://fixture.test/**.
Only the exact-byte, SHA-256-matching bundled `gym/fixtures/js-demo/app.js`
is provided as executable `text/javascript`, and it attaches native DOM
listeners to the synthetic product-selection/basket interface. The ordinary
offline replay simulator is **not** injected in this mode. JavaScript
modifications appear in the live DOM without stepping through snapshots.
The originally authored JS is available to source-capable agents through
DevTools/source inspection. CSS is still served from the captured HAR.

**Safety boundary:** `--trusted-fixture-js` is limited by code to the
synthetic `https://fixture.test/` origin and the exact source digest of
the reviewed bundled demo. Unknown/changed JS, inline scripts, captured
third-party scripts, original event-handler attributes and external-site
recordings remain inert. The proxy still denies upstream connections and
all non-synthetic writes. The mode does *not* clone or activate an
untrusted recorded site's login, payment, credential capture or backend.

This is the first implementation of a functional JavaScript replay
mechanism for an authorized fixture, **not** an automatic
original-JavaScript clone of recorded phishing-like sites. The ordinary
`--preview-dom-settling` mode remains unchanged. Use the fidelity
audit to report original-site differences rather than assuming parity.
