# Functional Replay Mode: reviewed first-party sites

This is a functional, **site-specific JavaScript** runtime for approved
synthetic websites. It is separate from generic HAR/DOM snapshot replay.
No `sim.js` is injected. The browser receives each site's *own* checked-in
`app.js` at its normal `/app.js` path, and the site's browser JS can call
a deterministic local backend. The proxy never connects upstream.

This system does **not** turn an arbitrary saved phishing-page HAR into an
executable clone. Captured external JS remains read-only in the existing
recording tools. Only explicitly reviewed, packaged first-party sites use
functional execution. Never add actual credential collection, payment
submission, imported third-party scripts or a generic API request-body logger.

## One-command site-specific mock generation (approved sources)

`generate-site-mock-windows.bat` automatically packages the original
**reviewed first-party** site files, produces SHA-256 coverage in
`mock-manifest.json`, verifies all bytes before serving, and starts
Functional Replay without generic `sim.js` injection.

```powershell
# From repo root; close earlier proxies on port 8080 first.
.\generate-site-mock-windows.bat study-board
# Or use the separate approved site:
.\generate-site-mock-windows.bat js-demo
```

Start the dedicated Chrome profile in another terminal with
`.\open-chrome-windows.bat`. The builder writes only inside
`generated-functional/<site>/` and preserves each site's own `app.js`
**byte for byte**. For a two-command sequence:

```powershell
.\.venv\Scripts\python.exe -m gym.build_approved_mock --site study-board
.\start-functional-gym-windows.bat study-board --generated
```

The source files and local backend schemas still require human review,
explicit site registration and the in-repository `SITES` allowlist.
Arbitrary URLs, HAR records, captured phishing scripts or unreviewed
folders **cannot** be passed to this builder. This is automatic generation
for *already approved* site sources, not generic URL-to-functional-clone.

## Windows quick start

Install once (or use the existing .venv):

```powershell
cd "C:\Users\cliob\Desktop\학교\mock\llm_agents"
.\setup-windows.bat
```

Stop any server using port 8080 and exit any existing experiment Chrome.
Then choose **one** reviewed site:

```powershell
# Example A: synthetic basket, real app.js event listeners
.\start-functional-gym-windows.bat js-demo

# OR Example B: independent synthetic campus study-board JavaScript + local API
.\start-functional-gym-windows.bat study-board
```

Keep the server window open. In a separate PowerShell session, start the
experiment profile:

```powershell
.\open-chrome-windows.bat
```

In **this dedicated Chrome**, open:
- js-demo: `https://fixture.test/`
- study-board: `https://studyboard.test/`

The browser sees and may inspect the site's real `/app.js` in DevTools.
Scripts come verbatim from `gym/fixtures/<site>/app.js`; they are **not**
scripts copied from unrelated recorded websites.

The local collector provides:
- `http://mock.test/__gym/events`: synthetic metadata-only receipts
- `http://mock.test/__gym/status`: active site and the SHA-256 of each
  approved local source file

Restart the server to reset the synthetic activity counts and receipt events.
A different fixture requires stopping the existing server and launching the
other site. A successful API reply is a **local synthetic receipt**, not a
receipt from any external website.

## Functional behaviors

| Site | Native JS behavior | Local backend |
| --- | --- | --- |
| `js-demo` | Choose sample item, increment basket and update DOM/ARIA | POST `/__mock_capture/fixture-receipt` only for fixed `basket_add` event and numeric sequence |
| `study-board` | Fetch sample study circles, render buttons dynamically, join and update availability | GET `/api/slots`, POST `/api/join` with only a fixed slot ID |

The local server accepts no personal information, identifiers, email,
credentials, form bodies, or arbitrary event data. Unknown methods/routes
return 4xx and never contact the original network.

## Add another owned/authorized functional site

1. Review your own first-party HTML/CSS/JS and place them in
   `gym/fixtures/<new-site>/`. Keep external JS imports disabled.
2. Add a distinct `<site>.test` host and explicit static file list to the
   checked-in `SITES` registry in `gym/functional_sites.py`.
3. Write a **named, typed, allowlisted** synthetic API response branch there.
   Only allow benign identifiers and deterministic state. Do not accept
   arbitrary JSON or forward its contents to a logging server.
4. Extend `tests/test_functional_gym.py` with expected native JS bytes,
   API behavior, rejected unknown fields and isolated site state.
5. Audit the source and network denial before doing agent comparisons.

The registry is deliberately not a user-supplied `--url` or `--directory`
parameter; adding an arbitrary downloaded site would bypass code review.
Different sites can have different scripts and APIs without any shared
`sim.js` or fabricated browser navigation edges.

## Scope and important limitations

- Only two reviewed synthetic sites ship initially. It does **not**
  automatically build a full functional copy from a HAR capture.
- No dynamic third-party scripts, inline captured scripts, original phishing
  JS execution, real authentication, checkout or unknown server responses.
- This runner binds mitmproxy to loopback and denies upstream connections.
  An experiment **VM egress firewall** is needed for stronger isolation
  against tools/extensions using transports outside the proxy.
- The existing saved HAR/static replay and its analyzer remain untouched.
  Use them as reference evidence, not as proof of functional equivalence.
- Chrome extensions that need external model APIs may not operate when the
  dedicated proxy denies all upstream traffic; test your agent execution
  architecture separately and do not loosen the site-origin deny policy.
- Use `python -m unittest discover -s tests -p "test_*.py" -v` to run
  offline tests. Proxy integration and Chrome extension behavior still need
  to be checked on a dedicated local experiment VM.
