# Visual Mock Navigation Editor

Repair *benign UI navigation* after recording a website. This is a
**post-capture click-to-destination editor** for already saved HTML snapshots.
It does not execute copied JavaScript, reproduce an authentication backend,
change the captured evidence, or contact the original website.

## Windows quick start

From your repository root, after recording a site:

```powershell
cd "C:\Users\cliob\Desktop\학교\mock\llm_agents"
git pull origin main

$rec = Get-ChildItem ".\recordings\<app-name>" -Directory |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

.\start-navigation-editor-windows.bat "$($rec.FullName)"
```

Replace `<app-name>` with the `--app` name used during recording. Make
sure any old server on port 8080 is closed.

In a second PowerShell window, run `.\open-chrome-windows.bat`, then open
the editor URL printed in the first terminal:

```text
https://<your-recorded-host>/__mock_capture/editor
```

The editor lives on the **recorded site's local mock origin**, not
`mock.test`. It is accessible only while running with
`--edit-navigation`. The local proxy never contacts the real host.

## Editing a button

1. **Choose a recorded screen** on the left. Recorded steps are shown by
   number and URL *path* only, with query strings omitted. All snapshots,
   including **[locked]** authentication or payment screens, can be selected
   for **read-only inspection**. A locked page loads in a sandboxed preview
   with scripts disabled and pointer interaction disabled. Its saved HTML
   and screenshots are not altered.
2. In the center **page preview**, click an eligible button or link to
   select it. The editor intercepts this click; it does not activate the
   recorded action, submit a form or navigate. A selected control gains a
   blue outline.
3. On the right, choose the desired **destination screen** from the
   recording, and click **Save connection**.
4. Open the mock with **Open mock** (or launch the ordinary
   `start-har-mock-windows.bat "<recording-folder>"` command) to test
   the saved connection. If a recorded click was initially mapped
   incorrectly or recorded as a no-op, the manual mapping for that
   selector has priority.
5. Use **Delete mapping** in the left pane to remove a saved correction.

An override is stored in the recording directory:

```text
recordings/<app>/<session>/
    bundle.json                 # unchanged source evidence
    trace.har                   # unchanged source evidence
    step-000.html               # unchanged source evidence
    navigation-overrides.json   # manually authored overrides
```

It contains only `from`, `to` and `selector` for each reviewed click.
No input text or credentials are stored. Saved connections persist across
mock restarts; new recordings have independent edits.

## Limits and experiment labeling

- The editor is only for **already captured steps**. It cannot invent new
  screens, run site JavaScript, reconstruct server sessions, submit forms,
  or reach unrecorded URLs.
- Authentication, account, password, verification, wallet, checkout and
  payment screens remain **locked from navigation edits**, including screens
  identified by sensitive form fields. They are now selectable in the left
  pane solely to see their inert, read-only snapshot in the center; Save
  connection is disabled and the server still rejects any attempt to use
  them as a source or destination. The preview sandbox does not execute
  original or simulation JavaScript. This does not repair third-party login
  submission chains. Use a reviewed first-party synthetic fixture for
  credential-free agent behavior experiments.
- The preview is an explicit researcher control, with an obvious editor
  interface and visible research labeling. It must not be portrayed as
  the unaltered website.
- The replay receipt indicates `manual_navigation: true`, while
  `observed_transition: false`. Never interpret manually edited edges as
  transitions originally verified during recording.
- Only same-recording, same-origin, non-sensitive source and target steps
  are eligible; external links and previously unrecorded URLs are rejected.
- The editing API is disabled in regular replay, requires an exact same-
  origin POST and strict JSON. No captured script is made executable.
- If a button is not selectable, it may be inside a form, lack a stable
  CSS selector, or be on a locked page. Record additional benign screens
  or consider implementing a separate reviewed first-party fixture.
- For reproducible experiments, retain `navigation-overrides.json` with
  your analysis (without uploading unrelated sensitive HAR/DOM data).

All upstream requests remain denied by the proxy. A VM firewall is
recommended to isolate other tools or browser extensions.

## Why `transitions.json` might show an empty table

There can be many saved screens but zero proven click-to-screen edges.
This may happen when pages mutate on their own, when click events do
not reach the recorded main-frame event observer, or when navigation
occurs in a new tab. A list of snapshots by itself is **not** evidence
that recorded click-to-screen navigation was captured.

Use the correct recording folder and inspect the high-level counts
without printing HTML, inputs or request bodies:

```powershell
$rec = Get-ChildItem '.\recordings\spnetflx' -Directory |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
$bundle = Get-Content "$($rec.FullName)\bundle.json" -Raw | ConvertFrom-Json
$edges = @(Get-Content "$($rec.FullName)\transitions.json" -Raw | ConvertFrom-Json)
$actions = @(Get-Content "$($rec.FullName)\action-events.json" -Raw | ConvertFrom-Json)
[pscustomobject]@{
    Recording = $rec.FullName
    Screens = @($bundle.steps).Count
    TransitionRows = $edges.Count
    ActionRows = $actions.Count
}
$actions | Select-Object action_id, kind, selector, outcome, observed_transition |
    Format-Table -AutoSize
```

If TransitionRows is zero, there is no verified transition mapping to
repair automatically. Review `action-events.json` to distinguish
unobserved actions from browser behavior; don't treat a manual route as
an originally observed navigation.
