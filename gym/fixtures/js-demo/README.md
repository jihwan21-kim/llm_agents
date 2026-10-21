# JavaScript DOM fixture (synthetic)

This deliberately benign site proves that browser agents can interact with
JavaScript-generated DOM and optionally inspect the JavaScript source. It is
**not** a copy of any real login or commerce page and makes no network calls.

On Windows, from the repository root:

```powershell
.\.venv\Scripts\python.exe -m http.server 8000 --bind 127.0.0.1 --directory "gym/fixtures/js-demo"
```

Open `http://127.0.0.1:8000/` in a normal local browser. Click an item and
then **Add to sample basket**. The details and basket counter update through
`app.js` without changing the URL or loading an HTML snapshot.

For a source-inspection test, ask an agent with appropriate browsing/reading
permissions to open `http://127.0.0.1:8000/app.js` and explain the event
listeners. Agents using screenshots alone do **not** see JavaScript source.

Run in a disposable profile with no private data. Do not port untrusted
phishing scripts into this fixture.
