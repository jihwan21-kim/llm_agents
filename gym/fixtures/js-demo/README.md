# JavaScript DOM fixture (synthetic)

This deliberately benign site proves that browser agents can interact with
JavaScript-generated DOM, inspect the source, and, under the trusted offline
proxy, generate an observable **local-only** request with a deterministic
metadata-only receipt. It is **not** a copy of any real login or commerce page,
and it never makes external requests.

On Windows, from the repository root:

```powershell
.\.venv\Scripts\python.exe -m http.server 8000 --bind 127.0.0.1 --directory "gym/fixtures/js-demo"
```

Open `http://127.0.0.1:8000/` in a normal local browser. Click an item and
then **Add to sample basket**. The details and basket counter update through
`app.js` without changing the URL or loading an HTML snapshot. The direct
local server has no collector endpoint, so the receipt will say unavailable.

To test actual JavaScript + local mock response, use the dedicated proxy
browser and reviewed fixture capture:

```powershell
.\.venv\Scripts\python.exe .\gym\build_js_fixture_recording.py --output ".\recordings\js-demo-trusted"
.\start-har-mock-windows.bat ".\recordings\js-demo-trusted" --trusted-fixture-js
```

Then in the dedicated proxy browser open `https://fixture.test/` and click
**Add to sample basket**. The browser executes the exact-hash reviewed
`app.js`, POSTs `{"event":"basket_add","sequence":1}` to the same-origin
`/__mock_capture/fixture-receipt` and receives a local acknowledgement.
The UI status says **recorded locally** when the response succeeds.
Check the recorded metadata events at
`http://mock.test/__mock_capture/events`.

The proxy accepts *only* the fixed event name and an integer sequence. It
does not log form values, arbitrary JSON, request bodies or credentials.
All original upstream connections remain denied; a new proxy instance starts
with empty in-memory events. This route is disabled in ordinary third-party
recording replay.

For a source-inspection test, ask an agent with appropriate browsing/reading
permissions to open `http://127.0.0.1:8000/app.js` and explain the event
listeners. Agents using screenshots alone do **not** see JavaScript source.

Run in a disposable profile with no private data. Do not port untrusted
phishing scripts into this fixture.
