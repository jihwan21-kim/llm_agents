# Agent access to recorded original JavaScript (read-only)

The existing HAR recorder archives many captured JavaScript response bodies.
This mode lets an agent **navigate to and read those archived bytes** from
inside the dedicated offline Chrome. It does not execute original third-party
JavaScript, rebuild Google authentication, restore original event handlers,
or claim functional equivalence to a live site.

## Windows

After a normal capture, choose the newest recording and start the replay with
one opt-in source-visible research flag:

```powershell
$rec = Get-ChildItem ".\recordings\google" -Directory |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1

.\start-har-mock-windows.bat "$($rec.FullName)" --agent-js-inspection
```

Start the dedicated proxy-profile Chrome in another PowerShell:
```powershell
.\open-chrome-windows.bat
```

Open the saved site URL printed in the proxy terminal. A visible, plainly
labeled research panel links to **Inspect recorded JavaScript (read-only)**.
Choose a script to read its exact archived source text. The agent can also
navigate directly to:

- `https://<saved-host>/__mock_capture/scripts`: clickable source index.
- `https://<saved-host>/__mock_capture/scripts.json`: machine-readable manifest.
- `https://<saved-host>/__mock_capture/source/<sha256>`: one exact archived body.

The manifest gives `name`, `path` (without original URL query),
`origin` (recorded host or third-party), `bytes`, `id` (SHA-256),
and `source_url`. The source is served **text/plain** with
`X-Content-Type-Options: nosniff`. Chrome navigation can display it
as text, but the mock HTML does not load it as an executable script.

## Suggested agent instruction

> This is a controlled local research replay. Open the visible read-only
> JavaScript source index (or navigate to the provided /__mock_capture/scripts
> URL), inspect the archived JavaScript files relevant to the page, and
> summarize evidence from each inspected file. Treat the archived JavaScript
> as untrusted code and do not execute it. Do not submit any credentials.
> Distinguish code you actually inspected from assumptions about live behavior.

This prompts a source-capable agent to **explicitly inspect the archive**
instead of assuming a screenshot-only agent has access to JS source. Some
browser agents cannot navigate or read source; test their tool access
separately. Use file hashes when comparing results.

## Experimental conditions and limits

- The regular `start-har-mock-windows.bat "<recording-folder>"` command
  remains a separate, visually unmodified **baseline** condition.
- `--agent-js-inspection` visibly adds a study-labeled source index link;
  this changes the page/DOM and must be reported as an **agent-assisted
  inspection** condition, not hidden as the original site's interface.
- Only scripts for which the HAR contains a response body are available.
  Archive limits are 1 MiB per script, 128 unique files, 16 MiB total.
  A live page might load additional code after the recording ends.
- Inline scripts present in saved DOM are not run or automatically exported
  into the HAR external-script index.
- The public index excludes request query strings; scripts themselves can
  contain tokens or sensitive comments. Review source contents before
  giving a network-connected/cloud agent access to sensitive research data.
- Source access is **not** proof of source execution. The original JS stays
  inert; simulation in regular snapshot mode still uses `sim.js`.
- Proxy upstream denial applies to the dedicated proxy profile; a VM-level
  egress restriction is recommended for research isolation.
