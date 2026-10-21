# Display captured original JavaScript in Chrome DevTools Sources

**Purpose:** See *actual HAR-captured* JavaScript under **F12 → Sources →
Workspace** while testing the existing offline snapshot mock.

> Important: **Sources → Page** displays JavaScript actually loaded by the
> mock. In a normal recorded-page replay that is the common `sim.js`, not
> the captured original JS. The exported original JS files appear under
> **Workspace**, not under **Page**. They are inspectable but NOT executed.

## Export captured JavaScript on Windows

From the repository root, select your newest recording:

```powershell
cd "C:\Users\cliob\Desktop\학교\mock\llm_agents"
git pull origin main

$rec = Get-ChildItem ".\recordings\google" -Directory |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

.\export-devtools-js-windows.bat "$($rec.FullName)"
```

If your recording belongs to another `--app` name, replace
`recordings\google` with that app's folder.

The output is `$($rec.FullName)\_devtools_js\`.
Each original JavaScript response saved in the HAR is exported as a distinct
`archived_<basename>_<sha256>.js` (or `.mjs`) file. This folder also
contains `recorded-js-manifest.json` and `READ_ME_FIRST.txt`.
The exporter preserves the original response bytes exactly, without changing
scripts or injecting `sim.js`. Recorded JavaScript in the original HTML
remains disabled in the running mock.

## Open the source files inside DevTools

1. Run the normal recorded mock using
   `start-har-mock-windows.bat "<recording-folder>"`.
2. Start the dedicated Chrome with `open-chrome-windows.bat`.
3. In the mock page, press **F12 → Sources**.
4. Select **Workspace** in the left-hand navigator (sometimes called
   **Workspaces**). If not visible, use the **>>** overflow menu.
5. Choose **Add folder** / **Add folder to workspace**, select the printed
   `_devtools_js` folder, and grant local folder access when Chrome asks.
6. Click any `archived_*.js` file in the Workspace tree to inspect the
   original code. The manifest includes SHA-256, original URL *path*
   without its query, capture origin and saved byte length.

If Chrome's Workspace pane is missing, use the DevTools **Sources** file
navigator options to add a folder from the filesystem. An agent that only
observes webpage DOM/screenshots will not automatically have access to local
DevTools Workspace files. A desktop agent with DevTools interaction or explicit
filesystem permissions may read them.

You can also use the already available in-browser
`https://<recorded-host>/__mock_capture/scripts` listing and click the
source URLs. For a browser agent without Workspace access, this may be easier.

## Experimental interpretation

- Do **not** interpret these as JS scripts executed by the mock.
- Do **not** drag an exported JS file onto the Mock page, paste it in Console,
  or run it as a Snippet. Source files are solely for reading and analysis.
- The replay's actual runtime still uses `sim.js`, so compare the agent's
  archived-source reasoning separately from dynamic behavior observations.
- Captures may not contain every script: maximum 128 unique scripts, 1 MiB
  per script, 16 MiB total; dynamic requests omitted from the HAR are missing.
- Captured sources might include private code, embedded strings or tokens.
  Keep `recordings/` private. The generated folder lives inside ignored
  `recordings/` and is not part of git commits.
- Filename suffixes include a full SHA-256 digest to distinguish similarly
  named bundles. `recorded-js-manifest.json` lets you check hashes and
  trace file names to original recorded paths.
