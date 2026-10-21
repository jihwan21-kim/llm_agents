# Explicit site permission and capability registry

The checked-in file **`gym/site_access_policy.json`** stores exact hostnames and
the actions that this local experiment runner accepts for them. It is a
**capability policy**, *not* independent proof that an outside organization
granted permission to copy or activate their authentication JavaScript*.

## Current policy

| Host | Capture, static mock, inspect saved HAR JS | Execute original JS in mock |
| --- | --- | --- |
| `google.com` | Yes | **No** |
| `www.google.com` | Yes | **No** |
| `accounts.google.com` | Yes | **No** |
| `fixture.test` | Yes | Yes, packaged synthetic JS only |
| `studyboard.test` | Yes | Yes, packaged synthetic JS only |

The Google hostnames are included because they are useful **recording and
source-inspection targets**. `owner_permission_verified: false` explicitly
states that site-owner authorization has NOT been established here.
This repository cannot declare Google's actual authorization merely by
adding its domain to JSON.

### Check a host

```powershell
cd "C:\Users\cliob\Desktop\학교\mock\llm_agents"
.\.venv\Scripts\python.exe -m gym.site_access_policy --url "https://accounts.google.com/" --mode source_inspection
.\.venv\Scripts\python.exe -m gym.site_access_policy --url "https://accounts.google.com/" --mode native_js
```

The first command prints `ALLOWED` (read-only inspection); the second
prints `DENIED` and exits with code 2. Running
`--url "https://fixture.test/" --mode native_js --fixture-id js-demo`
works for the checked-in fixture.

### Launch only registered static replay hosts

First record a test page as usual. Then select the newest recording:

```powershell
$rec = Get-ChildItem ".\recordings\google" -Directory |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
.\start-policy-har-mock-windows.bat "$($rec.FullName)"
```

The launcher checks the saved `bundle.json` start URL against the exact-host
registry **before** starting the regular offline HAR mock with visible,
read-only original-JS source inspection. It does NOT load captured JavaScript
as active scripts in `Sources > Page`.

Chrome DevTools original-HAR source reading remains available via the
`__mock_capture/scripts` page, or F12 `Sources > Workspace` with
`export-devtools-js-windows.bat`. Source execution is not enabled.

### Create a functional native-JS mock of a reviewed fixture

```powershell
.\generate-site-mock-windows.bat js-demo
# or
.\generate-site-mock-windows.bat study-board
```

The generated local first-party JS is genuinely loaded and runs under
`Sources > Page`, with `sim.js` absent and upstream network disabled.
The separately checked-in `SITES` registry, explicit `.test` domain
restriction, and verified fixture assets remain required. Adding a public
domain, changing a policy flag, or relabeling a HAR recording cannot promote
unknown third-party JavaScript into native execution.

### Adding another legitimate owned test website

Review the source and authorization *outside* the policy file, create a
first-party synthetic/test fixture under `gym/fixtures/`, use a dedicated
`.test` hostname, add an explicit matching `SITES` registry record, then
register the site in `gym/site_access_policy.json` with
`source_kind: reviewed_synthetic_fixture` and `native_js`. Test that
script URLs return the reviewed JS bytes, unknown endpoints are refused,
untrusted raw request bodies are neither stored nor forwarded, and no
upstream requests occur.

For external real-world sites, listing them as capture/inspection targets
does not authorize credential-oriented executable clone creation. Do not
equate saved source, a visible script listing, and an actually executing
browser runtime.
