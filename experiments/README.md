# GPT browser experiments

This is a custom GPT API agent, not the ChatGPT desktop product. It uses the Responses API, screenshot observations, and a small set of function tools executed by Playwright. It does not use OpenAI's native computer tool or an autonomous user LLM.

## Windows: first run

1. Pull the repository update and run `setup-agent-windows.bat` once. Python 3.12+ and installed Google Chrome are required. Dependencies go into `.venv-agent`, separate from the proxy environment.
2. Ensure the proxy dependencies were installed with `setup-windows.bat` (this is separate from `setup-agent-windows.bat`). You may start `start-proxy-windows.bat` manually, or let the next step start it automatically.
3. Run `check-agent-windows.bat`. It verifies an existing local proxy or starts one in a separate console and waits up to 20 seconds for readiness. Keep the proxy console open. This makes no GPT calls and requires no API key. It checks the proxy marker, a blocked `.invalid` destination, registered targets, browser startup, and HTTPS certificate validation.
4. Copy `.env.example` to `.env` in the repository root. Set `OPENAI_API_KEY` locally. Optionally set `OPENAI_MODEL` to a model you can access that supports image input and Responses function calling. The example uses `gpt-5.4`; availability must be checked on your API account.
5. Run `run-agent-windows.bat` for one trial. API usage may incur charges. After inspecting the result, use `run-agent-windows.bat --repeats 10` for ten trials per configured case.

The automated browser is launched by the runner; do not use the manual launcher for these trials. Each trial launches a new browser and nonpersistent context. HTTPS uses normal certificate verification. Install the existing proxy CA for the experiment OS user if necessary. No certificate-ignore option is provided. A failed HTTPS check must be resolved before running that condition. HTTP may be selected explicitly in the case URL as a distinct experimental condition, not as an equivalent replacement for HTTPS.

## Commands

From the repository root on Windows:

```powershell
.venv-agent\Scripts\python.exe experiments\runner.py check
.venv-agent\Scripts\python.exe experiments\runner.py run --repeats 10
.venv-agent\Scripts\python.exe experiments\runner.py run --config experiments\config.json
```

macOS/Linux:

```sh
python3 -m venv .venv-agent
.venv-agent/bin/python -m pip install -r experiments/requirements.txt
.venv-agent/bin/python experiments/runner.py check
.venv-agent/bin/python experiments/runner.py run
```

The default `browser_channel` is `chrome` and requires installed Google Chrome. To use Playwright Chromium instead, set it to an empty string and run `.venv-agent/bin/python -m playwright install chromium` (use the Windows executable path on Windows). Configure CA trust for the actual browser/runtime. These browser choices are different experimental conditions; record and hold them constant.

## Experimental controls

Edit `experiments/config.json`:

- `model`: default model; `OPENAI_MODEL` overrides it. Pin a supported model snapshot where possible.
- `cases`: unique ID, registered `site_id`, URL, brand, private evaluation label, and prompt template. Labels are saved in results and are not sent to the model.
- `repeats`, `seed`: repetitions and reproducible shuffled trial order. Seed does not make model outputs deterministic.
- `max_steps`, `max_seconds`, `max_output_tokens`: limits on model turns, trial time, and output per API call. Browser operations have additional bounded timeouts; cleanup may finish after the trial deadline. These are not a dollar-denominated budget.
- `viewport`, `headless`, `browser_channel`: observation/runtime settings.

Start with the direct-login prompt provided. The runner supplies a new `example.test` email address and synthetic password per trial. Arbitrary real credential input is intentionally not included. Values and screenshots sent to GPT reach OpenAI; reading a value from `.env` would not prevent this. The API key itself is only used by the SDK and is not given to the model or browser.

Use the same prompt template and account generation procedure across conditions. Add benign controls to `sites.json` and create their local pages before configuring them here. The repository includes phishing mocks but no benign control; it is not yet a benign/phishing benchmark. The default runner configuration still targets Coinbase. The Viva Sorte registration replay needs its own personal-data task and evaluation metrics, rather than this login configuration. Do not label the waiting screen as successful authentication.

The model receives page screenshots and the current URL, plus UI action results. It cannot inspect DOM, source files, manager logs, or use web search. Screenshots do not include the browser address bar or Chrome security panel. This observation interface is therefore different from a desktop agent that sees browser chrome. Record this distinction in comparisons. The page title/content itself can contain mock cues; the runner does not remove those cues.

The model chooses its own clicks and input. The harness does not script the login sequence. A `finish` call records the model's declared outcome; it does not prove success. A user question or confirmation ends as `needs_user` if the model uses the tool. Free-text endings are retained as `model_stopped` for manual coding rather than guessed to be refusals. There is no automated user answering confirmations or persuading a refusal.

## Isolation and network

Browser traffic uses `http://127.0.0.1:8080`. The existing proxy blocks upstream connections. A second browser route guard permits only the current case's exact origin, blocks service workers, and closes extra tabs. Navigation outside the case origin returns a tool error. This deliberately excludes external identity providers and multi-origin tasks, which must not be treated as model failures. The model cannot visit `mock.test` to read evaluation logs.

The Python process calls the official OpenAI API directly with environment-proxy inheritance disabled. Only the browser and evaluator's local proxy requests use mitmproxy. Run in an isolated experiment VM for stronger OS-level isolation; the route guard is not a full system firewall.

## Results

Each batch creates `runs/<timestamp>-<id>/` with a shuffled schedule and `summary.json` / `summary.csv`. Each trial directory contains:

- `manifest.json`: exact prompt, instructions, tools, configuration, model, dependency versions, and trial ID.
- `screen-*.png`: viewport observations.
- `response-*.json`: API output, model identifier, and usage where returned. No API authorization headers are saved.
- `actions.jsonl`: requested tool actions and execution results.
- `input.jsonl`: evaluator-only input events (type/name/ID and nonempty flag; no field values).
- `network.jsonl`, `browser.jsonl`: page response statuses, failures, blocked requests, console messages, and dialogs.
- `local-events.json`: proxy-retained events matched by fresh mock session ID and site ID.
- `result.json`: declared stopping status and independent input / local receipt evidence.

`email_input_observed` and `password_input_observed` mean a nonempty input event was observed. They do not prove the correct account value was entered. `submit_click_stages` uses existing mock handler events, which also cover Enter-based submission. `email_local_received` and `password_local_received` mean the local proxy retained a matching `simulated_request`; they are not proof of original-site exfiltration. `original_server_receipt` is always `not_measured`. Inspect payloads to check value correctness.

The existing proxy keeps at most 1,000 events. Run trials sequentially and do not clear manager events or run other experiments concurrently. The runner never deletes existing logs. `logging_verified: false` means local evidence is unavailable or incomplete and requires inspection. Disk JSONL proxy logs remain the underlying request evidence.

Runtime errors, API errors, certificate errors, time limits, user requests, model refusals, and local receipt should be analyzed separately. A completed model response is not a verified successful login. Review `model_stopped` outputs manually before computing refusal rates.

Dependencies are range-constrained; actual installed versions are captured in each manifest. For a publication run, freeze the tested environment with `pip freeze`, record the repository commit and model version, and reuse the same VM/browser baseline.

## Verification

The included standard-library tests check origin restrictions, configuration validation, separation of local receipt from submission intent, and the agent loop with fake browser/API objects (including stopping for user input and excluding another trial's events). Run `python -m unittest discover -s experiments -p "test_*.py"` from the repository root. `check` adds real proxy/browser checks on your machine. Neither is a paid model trial.

Implementation validation passed the five tests, real mitmproxy preflight, and an installed OpenAI SDK request/response check using a mock HTTP transport. Browser installation failed in the development environment, so real Chrome UI execution and live GPT calls have not been verified there. Run `check` and inspect one live trial on your machine before a batch.

API and browser reference documentation:

- https://developers.openai.com/api/docs/guides/function-calling
- https://developers.openai.com/api/docs/guides/tools-computer-use
- https://playwright.dev/python/docs/browsers



## Connection refused / WinError 10061

This error during `preflight` means the runner could not establish a TCP connection to the local proxy on `127.0.0.1:8080`. It occurs before Chrome or GPT is used and is not an HTTPS certificate failure. Common causes are a stopped proxy or a proxy process that failed during startup.

The Windows check/run launchers now invoke `experiments/ensure_proxy.py` first. It verifies the local proxy response and site registry, reuses a healthy proxy, and starts the project's proxy if the port refuses connections. It will not stop or replace another service using port 8080. If `.venv` is missing, run `setup-windows.bat`; `.venv-agent` alone is not enough. If startup fails, inspect the separate proxy window. The proxy launcher keeps startup errors visible.

Direct `python experiments/runner.py check` or `run` calls still expect an already running proxy. You can invoke `python experiments/ensure_proxy.py` first. On macOS/Linux this helper starts the proxy as a detached process with output in `logs/proxy-startup.log`; stop that process explicitly when finished. When source files or `sites.json` change, restart an already running proxy to load the update.

The runner now prints an actionable connection/certificate error instead of a full traceback by default. Set `MOCK_AGENT_DEBUG=1` for the traceback. Browser or API work does not proceed if the proxy readiness check fails.

Startup validation: unit tests cover healthy-proxy reuse, absent-proxy startup, wrong-service rejection, early exit, and missing environment. A Linux integration check also exercised actual mitmproxy startup and reuse. The Windows console-launch behavior still needs verification on Windows.
