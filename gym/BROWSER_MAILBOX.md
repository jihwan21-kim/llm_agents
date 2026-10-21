# Browser-only inbox entrypoint for offline experiments

This adds a first web page for browser agents, **not** an email application,
SMTP server, Gmail account, browser extension or operating-system inbox. It is
an ordinary website served inside your dedicated Chrome via the existing
deny-upstream MITM proxy.

**Initial Chrome page:** `https://inbox.cedarpostmail.net/`

This hostname is a **virtual laboratory mapping only**. No ownership, domain
registration, mail hosting or permission to use a third-party's public domain
is implied. Only the dedicated proxy Chrome should open it; the proxy
must be stopped before using that profile for normal browsing. A locally
trusted CA is required to avoid browser certificate warnings on HTTPS.
If certificate trust is not configured, do not disable certificate checks
to hide errors: install/check the dedicated MITM root CA.

## HTTPS "Not secure" / "주의 요함" in Chrome

The launch URL must start with **https://**, not http://. Start the
mock proxy in a PowerShell window *before* checking HTTPS:

```powershell
.\start-proxy-windows.bat
```

In a second PowerShell run:

```powershell
.\check-mock-https-windows.bat
```

This compares the **specific CA actually used by this repository** at
`mitm-ca/mitmproxy-ca-cert.cer` with the Windows trusted-root store and
verifies a TLS handshake for `inbox.cedarpostmail.net` over 127.0.0.1:8080.
The default mitmproxy CA in `%USERPROFILE%\.mitmproxy` is usually **not
the same certificate**, so installing the wrong one does not fix this
project's Chrome profile.

If the check prints `Project CA in Windows trusted root store: NO`,
run the separately confirmed helper:

```powershell
.\trust-project-ca-windows.bat
```

Review the CA path, subject and fingerprint, then type **TRUST** only if
this is your isolated experiment VM or Windows user. It imports only the
public root certificate for `CurrentUser\Root` and never installs the
private key. A trusted mitmproxy CA is powerful enough to sign certificates
for other hostnames, so **remove the project CA when finished**.

Restart **all** Chrome windows belonging to the dedicated experiment
profile, then start the proxy and Chrome again:

```powershell
.\open-chrome-windows.bat
```

If the check succeeds but Chrome still says `주의 요함`, open Chrome F12
→ **Security**, inspect the displayed problem, and check the precise
address and certificate issuer for that tab. A browser warning might instead
indicate HTTP navigation or an unsafe subresource, not a missing CA.
Do not disable certificate verification or click through a Chrome
certificate warning to mask an experiment failure.

## Normal Windows flow

```powershell
cd "C:\Users\cliob\Desktop\학교\mock\llm_agents"
git pull origin main
.\start-proxy-windows.bat
```

In a new PowerShell window:

```powershell
.\open-chrome-windows.bat
```

Chrome opens the browser inbox rather than the research manager. The inbox
contains ordinary-looking message cards, searchable subjects, a sidebar and
message details. **No researcher UI, task labels, JSON logs or study
classification are rendered on the agent's inbox page.** Clicking an email
selects it; clicking **View details** follows a browser navigation to an
already registered local mock target.

Use the Chrome/desktop-agent connection you already use to drive that
dedicated browser. The page itself does not connect to an AI provider.
Extensions that require network calls may not work with the deny-upstream
proxy; use an externally controlled Chrome tool if that limitation applies.

**Researcher dashboard** remains unchanged at
`http://mock.test/` inside the same proxy browser.
Mail click metadata is also available at:

```text
http://mock.test/__mock/mail-events
```

Use `.\open-chrome-windows.bat --manager` to start Chrome on the old manager
instead. When Chrome is already running with the experiment profile, navigate
directly to that URL rather than launching another profile instance.

## Available mock destinations

- In `start-proxy-windows.bat` mode, the inbox contains entries for the four
  sites already registered in `sites.json`.
- With `start-har-mock-windows.bat "<recording-folder>"`, it also includes
  the *single active* recorded origin as one extra message. This is useful for
  a separately recorded benign counterpart. Use a separate recording for
  other target origins; this mode does not serve all recordings simultaneously.
- With `start-functional-gym-windows.bat <site>`, it links only to the
  currently loaded reviewed synthetic fixture. Legacy sites are not served
  in that runtime.

The inbox does not add new external navigation capabilities: each redirect
is generated from a server-side route that is already loaded in this proxy
process. Unknown message IDs, input submissions, and unregistered hosts
are blocked. Existing saved pages remain simulations, and the new inbox
does not make captured third-party JS or authentication APIs executable.

## Research events and controls

Opening an email causes a first-party read-only GET to
`/read/<message_id>`; following the link goes to
`/open/<message_id>`, which responds with an HTTP redirect to the
registered mock origin. The proxy logs only message IDs, event kind, time,
local-only status, and target *hostname* on a link click. It records no
email text, browser cookies, user credentials, request bodies or URL queries
in **mailbox event logs**.

These events can be inspected and cleared in the old researcher dashboard.
If your existing legacy site mocks accept entered field values, never use
real accounts, passwords, API keys, cards or personal data in those
experimental pages. The proxy's older mock-site submission telemetry
is separate from the clean inbox telemetry.

A synthetic mailbox cannot reproduce Gmail reputation signals, actual
sender verification, or externally delivered email provenance. Do not
present its incoming messages as genuine received mail. Use the same
initial inbox with fixed messages and browser resets across repeated
model comparisons.
