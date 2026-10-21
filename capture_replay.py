"""Offline HAR + DOM snapshot renderer.

Static GET resources are served from the HAR; no recorded scripts execute.
Simulated form progression is handled by a tiny local-only script.
"""
import base64
import hashlib
import html
from html.parser import HTMLParser
import json
import mimetypes
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit, parse_qs
from navigation_analysis import extract_html_navigation, temporal_dom_candidates
from navigation_editor import NavigationEditor

ASSETS = "/__mock_capture/assets/"
SIMULATOR = "/__mock_capture/sim.js"
# Captured JS is inspectable as *text* only, never inserted as an executable
# script. This is an explicit research inspection channel, not a page feature.
SCRIPT_INDEX = "/__mock_capture/scripts"
SCRIPT_INDEX_JSON = "/__mock_capture/scripts.json"
SCRIPT_SOURCE = "/__mock_capture/source/"
TRUSTED_JS_ASSETS = "/__mock_capture/trusted-js/"
# The only executable captured JS is a byte-identical copy of an explicitly
# reviewed, shipped benign fixture script. A renamed phishing capture cannot
# opt in by providing its own manifest or moving to a .test hostname.
TRUSTED_FIXTURE_HOST = "fixture.test"
TRUSTED_FIXTURE_SCRIPT = "/app.js"
MAX_ASSET_BYTES = 12 * 1024 * 1024
MAX_SOURCE_BYTES = 1024 * 1024
MAX_SCRIPT_SOURCES = 128
MAX_TOTAL_SOURCE_BYTES = 16 * 1024 * 1024

def is_javascript_response(url, mime):
    """Recognize captured JavaScript, but never treat HTML error pages as JS."""
    content_type = mime.lower().split(";", 1)[0].strip()
    if any(blocked in content_type for blocked in ("html", "json", "xml")):
        return False
    return ("javascript" in content_type or "ecmascript" in content_type
            or (urlsplit(url).path.lower().endswith((".js", ".mjs"))
                and content_type in {"text/plain", "application/octet-stream", ""}))


SIM_JS = r"""
(() => {
  const config = document.currentScript.dataset;
  const step = Number(config.step || "0");
  let edges = [];
  try { edges = JSON.parse(config.transitions || "[]"); }
  catch (err) { console.error("Invalid recorded transition data", err); }
  let busy = false;
  // Focusing an editable field is never navigation. Recording input content
  // is deliberately unsupported by the offline mock.
  const EDITABLE_FIELD = "input:not([type=submit]):not([type=button]):" +
    "not([type=reset]):not([type=image]):not([type=checkbox]):" +
    "not([type=radio]), textarea, select, [contenteditable]:not([contenteditable=false])";
  const MAIN_TEXT_FIELD = "main input:not([type=hidden]):not([type=submit]):" +
    "not([type=button]):not([type=checkbox]):not([type=radio]), " +
    "main textarea, [role=main] input:not([type=hidden]), [role=main] textarea";
  let editingStarted = false;
  document.addEventListener("focusin", event => {
    if (event.target instanceof Element && event.target.closest(EDITABLE_FIELD))
      editingStarted = true;
  }, true);

  // Research-only preview: this DOM update was NOT attributed to any click.
  // An explicit local-only flag must enable this. The delay is a display
  // convenience, not timing reconstructed from the original site.
  const domSettleTo = config.domSettleTo === undefined
    ? null : Number(config.domSettleTo);
  if (domSettleTo !== null && Number.isSafeInteger(domSettleTo) &&
      domSettleTo !== step && domSettleTo > step) {
    window.setTimeout(() => {
      // DOM settling is not a verified click. Never replace an active form
      // just as the user focuses it, and don't silently refresh full
      // editable screens (e.g. a login screen with an input under main).
      if (editingStarted ||
          document.activeElement?.closest?.(EDITABLE_FIELD) ||
          document.querySelector(MAIN_TEXT_FIELD)) {
        console.info("[offline mock] Held unverified DOM settling on editable screen",
                     {from: step, to: domSettleTo});
        return;
      }
      console.info("[offline mock] Previewing unverified DOM settling",
                   {from: step, to: domSettleTo});
      const next = new URL(location.pathname, location.origin);
      next.searchParams.set("_step", String(domSettleTo));
      // Settling is not a user navigation. Avoid adding spurious entries to
      // browser history; Back should return to the previous clicked page.
      location.replace(next.pathname + next.search);
    }, 500);
  }

  // A recorded no-op on a broad ancestor (e.g. "body > main")
  // must not shadow a narrower successful click transition underneath it.
  // Always prefer the selector whose matched element is closest to the
  // actual click target, then the more specific selector, then a transition.
  function matchingAncestor(el, edge) {
    if (!edge.selector || !el) return null;
    try { return el.closest(edge.selector); }
    catch (_) { return null; }
  }

  function distanceToAncestor(el, ancestor) {
    let distance = 0;
    for (let current = el; current; current = current.parentElement) {
      if (current === ancestor) return distance;
      distance++;
    }
    return Number.MAX_SAFE_INTEGER;
  }

  function bestEdge(el, kind) {
    // Captured "no-change" on main/body/container was often just a generic
    // click during recording. Never apply it to *every descendant button*.
    // It is only valid when the user clicks that exact element/control.
    const clickedControl = el?.closest?.(
      "button, a, label, select, input[type=submit], input[type=button], " +
      "[role=button], [onclick], [tabindex]"
    ) || null;
    const candidates = edges.filter(e => e.kind === kind).map(edge => ({
      edge, ancestor: matchingAncestor(el, edge)
    })).filter(item => {
      if (!item.ancestor) return false;
      if (item.edge.outcome !== "no-change" && item.edge.to !== step)
        return true;
      return item.ancestor === el || item.ancestor === clickedControl;
    });
    candidates.sort((a, b) => {
      const distance = distanceToAncestor(el, a.ancestor)
                     - distanceToAncestor(el, b.ancestor);
      if (distance) return distance;
      // A saved manual mapping replaces the recorded guess for the same control.
      if (a.edge.manual_override !== b.edge.manual_override)
        return Number(b.edge.manual_override) - Number(a.edge.manual_override);
      const specificity = b.edge.selector.length - a.edge.selector.length;
      if (specificity) return specificity;
      return Number(b.edge.outcome === "changed")
           - Number(a.edge.outcome === "changed");
    });
    return candidates[0]?.edge || null;
  }

  function filledFieldTypes(scope) {
    const elements = [...(scope?.querySelectorAll?.("input, textarea, select") || [])];
    return [...new Set(elements.filter(el =>
      el.type !== "hidden" && String(el.value || "").trim().length > 0
    ).map(el =>
      ["password", "email", "tel", "number"].includes(el.type) ? el.type : "other"
    ))].slice(0, 6);
  }

  async function record(edge, kind, container) {
    if (busy) return;
    busy = true;
    const payload = {
      kind, step, to: edge ? edge.to : step,
      selector: edge?.selector || "",
      filled_types: filledFieldTypes(container),
      observed_transition: Boolean(edge?.observed)
    };
    try {
      const response = await fetch("/__mock_capture/event", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      });
      if (!response.ok) throw Error("Event recording failed");
      const result = await response.json();
      // The local proxy validates both real observed edges and unambiguous
      // same-origin HTML href hints before authorizing local navigation.
      if (edge && result.to === edge.to &&
          (result.observed || result.static_navigation || result.manual_navigation) &&
          (edge.outcome === "changed" || edge.outcome === "html-href" ||
           edge.outcome === "manual_navigation") &&
          edge.to !== step && edge.to_path) {
        const url = new URL(edge.to_path, location.origin);
        url.searchParams.set("_step", String(edge.to));
        location.assign(url.pathname + url.search);
      }
    } catch (error) { console.error("Offline mock event failed", error); }
    finally { busy = false; }
  }

  document.addEventListener("click", event => {
    const chain = event.composedPath?.() || [];
    const target = chain.find(el => el instanceof Element)
      || (event.target instanceof Element ? event.target : null);
    if (!target) return;
    // Input focus is not a button click. Ignore it even if an overly broad
    // captured selector matches an ancestor such as main or form.
    if (target.closest(EDITABLE_FIELD)) return;
    // Capture every observed click target, including DIV/SPAN handlers.
    // Captured scripts and original external navigation remain disabled.
    const edge = bestEdge(target, "click");
    const form = target.closest("form");
    const submitEdge = form
      ? bestEdge(form, "submit")
      : null;
    const candidate = edge || submitEdge || null;
    const interactive = target.closest(
      "button, a, input[type=submit], input[type=button], [role=button], [onclick], [tabindex]"
    );
    // Even when we reject a broad no-op match, log the attempted click
    // as unmatched so researchers can see why nothing navigated.
    const broadNoop = edges.some(e => e.kind === "click"
      && (e.outcome === "no-change" || e.to === step)
      && matchingAncestor(target, e));
    if (!candidate && !interactive && !broadNoop) return;
    if (interactive && (interactive.matches("a") || interactive.matches("button"))) {
      event.preventDefault();
    }
    if (!candidate) {
      console.warn("[offline mock] No matching observed transition",
                   {step, tag: target.tagName, id: target.id || "",
                    available: edges.filter(e => e.kind === "click").map(e => ({
                      selector: e.selector, to: e.to, outcome: e.outcome
                    }))});
    }
    record(candidate, "button_click", form || document);
  }, true);

  document.addEventListener("submit", event => {
    event.preventDefault();
    const edge = bestEdge(event.target, "submit");
    record(edge || null, "form_submit", event.target);
  }, true);

  document.addEventListener("change", event => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const edge = bestEdge(target, "change");
    if (edge) record(edge, "field_change", target.closest("form") || document);
  }, true);
})();
"""

def rewrite_css(value, base_url, asset_urls):
    def replace(match):
        original = match.group(2).strip()
        asset = asset_urls.get(urljoin(base_url, original))
        return "url('" + asset + "')" if asset else "url('')"
    result = re.sub(r"url\(\s*(['\"]?)([^)'\"\s]+)\1\s*\)", replace, value, flags=re.I)
    # Rewrite quoted @import files as well as url(...) references.
    result = re.sub(
        r"@import\s+(['\"])([^'\"]+)\1",
        lambda m: "@import url('" + asset_urls.get(urljoin(base_url, m.group(2)), "") + "')",
        result, flags=re.I,
    )
    return result


class SnapshotSanitizer(HTMLParser):
    DROP = {"script", "iframe", "object", "embed", "base", "noscript",
            "frame", "frameset", "foreignobject", "template"}

    def __init__(self, page_url, asset_urls, trusted_js_urls=None):
        super().__init__(convert_charrefs=False)
        self.page_url = page_url
        self.asset_urls = asset_urls
        self.trusted_js_urls = trusted_js_urls or {}
        self.trusted_script_open = False
        self.link_count = 0
        self.result = []
        self.blocked = []
        self.style_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if self.blocked:
            if tag in self.DROP:
                self.blocked.append(tag)
            return
        values = {k.lower(): v for k, v in attrs if k}
        if tag == "script":
            # Never activate inline scripts from captured pages. In the
            # explicitly generated synthetic fixture only, a reviewed
            # same-origin external script may be reinserted by content hash.
            src = values.get("src", "")
            allowed = self.trusted_js_urls.get(urljoin(self.page_url, src)) if src else None
            script_type = (values.get("type") or "text/javascript").lower()
            if allowed and script_type in {"text/javascript", "application/javascript"}:
                defer_attr = " defer" if "defer" in values else ""
                self.result.append(f'<script src="{html.escape(allowed, quote=True)}"{defer_attr}>')
                self.trusted_script_open = True
                return
        if tag in self.DROP:
            self.blocked.append(tag)
            return
        if tag == "meta" and values.get("http-equiv", "").lower() in {
            "refresh", "content-security-policy"}:
            return
        if tag == "link" and values.get("rel", "").lower() not in {
            "stylesheet", "icon", "shortcut icon"}:
            return
        out = []
        for key, value in attrs:
            if not key:
                continue
            low = key.lower()
            if low.startswith("on") or low in {
                "integrity", "nonce", "crossorigin", "formaction", "target",
                "srcdoc", "ping", "autofocus", "data-mock-link-index"}:
                continue
            value = value or ""
            if low in {"src", "href", "poster", "action", "xlink:href", "data"}:
                if tag in {"a", "form"}:
                    value = "#"
                else:
                    value = self.asset_urls.get(urljoin(self.page_url, value), "")
            elif low == "srcset":
                candidates = []
                for candidate in value.split(","):
                    parts = candidate.strip().split()
                    if not parts:
                        continue
                    asset = self.asset_urls.get(urljoin(self.page_url, parts[0]))
                    if asset:
                        candidates.append(" ".join([asset] + parts[1:]))
                value = ", ".join(candidates)
            elif low == "style":
                value = rewrite_css(value, self.page_url, self.asset_urls)
            elif tag == "input" and low == "value":
                value = ""  # No pre-filled captured credentials.
            out.append(f' {key}="{html.escape(value, quote=True)}"')
        if tag == "a":
            # Marker links the inert HTML back to its original anchor index.
            out.append(f' data-mock-link-index="{self.link_count}"')
            self.link_count += 1
        self.result.append(f"<{tag}{''.join(out)}>")
        if tag == "style":
            self.style_depth += 1

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.blocked:
            if tag == self.blocked[-1]:
                self.blocked.pop()
            return
        if tag == "script" and self.trusted_script_open:
            self.trusted_script_open = False
            self.result.append("</script>")
            return
        if tag == "style" and self.style_depth:
            self.style_depth -= 1
        self.result.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.blocked and not self.trusted_script_open:
            self.result.append(rewrite_css(data, self.page_url, self.asset_urls)
                               if self.style_depth else data)

    def handle_entityref(self, name):
        if not self.blocked:
            self.result.append("&" + name + ";")

    def handle_charref(self, name):
        if not self.blocked:
            self.result.append("&#" + name + ";")

    def handle_decl(self, decl):
        self.result.append("<!" + decl + ">")


class CaptureReplay:
    def __init__(self, directory, preview_dom_settling=False, trusted_fixture_js=False,
                 agent_js_inspection=False):
        self.directory = Path(directory).expanduser().resolve(strict=True)
        self.bundle = json.loads((self.directory / "bundle.json").read_text(encoding="utf-8"))
        self.start_url = self.bundle.get("startUrl", "")
        parsed = urlsplit(self.start_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Invalid startUrl in bundle")
        self.host = parsed.hostname.lower()
        self.trusted_fixture_js = bool(trusted_fixture_js)
        # Source-visible experiment condition. Ordinary replay remains unchanged.
        self.agent_js_inspection = bool(agent_js_inspection)
        self.trusted_js_urls = {}
        self.trusted_js_sources = {}
        if self.trusted_fixture_js:
            if (parsed.scheme != "https" or parsed.netloc.lower() != TRUSTED_FIXTURE_HOST):
                raise ValueError("Executable original JS is available only for the packaged synthetic fixture.test")
            approved_source = (Path(__file__).resolve().parent /
                               "gym/fixtures/js-demo/app.js").read_bytes()
            self.approved_js_sha256 = hashlib.sha256(approved_source).hexdigest()
        self.steps = self.bundle.get("steps", [])
        self.transitions = self.bundle.get("transitions", [])
        if not self.steps:
            raise ValueError("No recorded HTML snapshots")
        # Saved click fixes are not changes to the recorded evidence. The
        # editor rejects sensitive authentication/payment states.
        self.navigation_editor = NavigationEditor(self.directory, self.bundle)
        self.manual_edges = list(self.navigation_editor.overrides)
        self.preview_dom_settling = bool(preview_dom_settling)
        # Only time-adjacent, same-URL, previously recorded DOM states.
        # Not verified user actions. The default remains strict replay.
        candidates = temporal_dom_candidates(self.steps, self.transitions)
        self.dom_settle_candidates = candidates
        self.preview_edges = {}
        if self.preview_dom_settling:
            for candidate in candidates:
                source, dest = candidate["from"], candidate["to"]
                if source not in self.preview_edges:
                    self.preview_edges[source] = dest
                else:
                    # Ambiguity: never choose arbitrary next UI state.
                    self.preview_edges[source] = None
            self.preview_edges = {s: t for s, t in self.preview_edges.items()
                                  if t is not None}
        # Loading scripts often generate many no-action snapshots before
        # the first user click. Start at the first verified actionable state
        # on the recorded entry path, rather than always at state zero.
        entry_path = parsed.path or "/"
        candidates = []
        for edge in self.transitions:
            state = edge.get("from")
            if (type(state) is not int or state < 0 or state >= len(self.steps)
                    or edge.get("kind") not in {"click", "submit", "change"}
                    or not edge.get("observed")):
                continue
            source = urlsplit(self.steps[state].get("url") or self.start_url)
            if source.hostname == self.host and (source.path or "/") == entry_path:
                candidates.append(state)
        self.initial_step = candidates[0] if candidates else 0
        har = json.loads((self.directory / "trace.har").read_text(encoding="utf-8"))
        self.assets, self.urls = {}, {}
        self.script_sources, self.script_index = {}, []
        self.script_sources_skipped = 0
        total_source_bytes = 0
        for entry in har.get("log", {}).get("entries", []):
            req, response = entry.get("request") or {}, entry.get("response") or {}
            payload = response.get("content") or {}
            url, body = req.get("url", ""), payload.get("text")
            if req.get("method") not in {"GET", "HEAD"} or not isinstance(body, str):
                continue
            mime = str(payload.get("mimeType") or mimetypes.guess_type(urlsplit(url).path)[0]
                       or "application/octet-stream")
            if is_javascript_response(url, mime):
                # Text-only source inspection, no browser execution. Limit total
                # RAM and drop duplicates. Avoid exporting URL queries/tokens.
                if len(body) > MAX_SOURCE_BYTES * 2:
                    self.script_sources_skipped += 1
                    continue
                try:
                    raw = (base64.b64decode(body, validate=True)
                           if payload.get("encoding") == "base64"
                           else body.encode("utf-8"))
                except (ValueError, UnicodeError):
                    self.script_sources_skipped += 1
                    continue
                digest = hashlib.sha256(raw).hexdigest()
                if digest in self.script_sources:
                    continue
                if (len(raw) > MAX_SOURCE_BYTES
                        or len(self.script_sources) >= MAX_SCRIPT_SOURCES
                        or total_source_bytes + len(raw) > MAX_TOTAL_SOURCE_BYTES):
                    self.script_sources_skipped += 1
                    continue
                src_path = urlsplit(url).path or "/"
                basename = (src_path.rsplit("/", 1)[-1] or "unnamed.js")[:100]
                entry_data = {
                    "id": digest, "name": basename,
                    "origin": ("recorded" if urlsplit(url).hostname == self.host
                               else "external"), "bytes": len(raw),
                    "source_url": SCRIPT_SOURCE + digest,
                    "path": src_path[:200],
                }
                self.script_sources[digest] = raw
                self.script_index.append(entry_data)
                total_source_bytes += len(raw)
                if (self.trusted_fixture_js and
                        urlsplit(url).scheme == "https" and
                        urlsplit(url).netloc.lower() == TRUSTED_FIXTURE_HOST and
                        urlsplit(url).path == TRUSTED_FIXTURE_SCRIPT and
                        not urlsplit(url).query and
                        digest == self.approved_js_sha256):
                    trusted_uri = TRUSTED_JS_ASSETS + digest
                    self.trusted_js_sources[digest] = raw
                    self.trusted_js_urls[url] = trusted_uri
                continue
            # Never execute captured JavaScript or serve active source files as
            # browser assets; original executable scripts remain removed.
            if any(s in mime.lower() for s in ("javascript", "html", "json", "svg", "xml")):
                continue
            try:
                raw = (base64.b64decode(body, validate=True)
                       if payload.get("encoding") == "base64"
                       else body.encode("utf-8"))
            except (ValueError, UnicodeError):
                continue
            if len(raw) > MAX_ASSET_BYTES:
                continue
            token = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
            self.assets[token] = (raw, mime, url)
            self.urls[url] = ASSETS + token

        # Re-map CSS url() references inside the recorded CSS bytes.
        for token, (body, mime, url) in list(self.assets.items()):
            if "css" in mime.lower():
                text = body.decode("utf-8", errors="replace")
                self.assets[token] = (rewrite_css(text, url, self.urls).encode(), mime, url)

        self.pages = {}
        self.inferred_edges = []
        # A path might have many DOM states (SPA, modal). Only infer an HTML
        # link's destination when a single matching recorded state exists.
        by_path = {}
        for i, st in enumerate(self.steps):
            parsed_step = urlsplit(st.get("url") or self.start_url)
            if parsed_step.scheme == parsed.scheme and parsed_step.netloc.lower() == parsed.netloc.lower():
                by_path.setdefault(parsed_step.path or "/", []).append(i)
        for index, step in enumerate(self.steps):
            filename = step.get("html") or ("step-" + str(index).zfill(3) + ".html")
            file = (self.directory / filename).resolve(strict=True)
            if not file.is_relative_to(self.directory):
                raise ValueError("Snapshot path escapes recording")
            source = step.get("url") or self.start_url
            raw_page = file.read_text(encoding="utf-8", errors="replace")
            parser = SnapshotSanitizer(source, self.urls, self.trusted_js_urls)
            parser.feed(raw_page)
            parser.close()
            edges = []
            for transition in self.transitions:
                if transition.get("from") != index:
                    continue
                destination = transition.get("to")
                if type(destination) is not int or destination >= len(self.steps) or destination < 0:
                    continue
                target_url = urlsplit(self.steps[destination].get("url") or self.start_url)
                # All navigation remains on the one captured origin.
                if target_url.hostname != self.host:
                    continue
                edges.append({
                    "kind": transition.get("kind"),
                    "selector": str(transition.get("selector", ""))[:256],
                    "observed": bool(transition.get("observed")),
                    "to": destination,
                    "to_path": target_url.path or "/",
                    "outcome": transition.get("outcome"),
                })
            for hint in extract_html_navigation(raw_page, source):
                if hint["kind"] != "anchor":
                    continue
                dests = by_path.get(hint["target_path"], [])
                if len(dests) != 1 or dests[0] == index:
                    continue
                # Explicitly distinguish inferred anchor navigation from
                # browser-observed clicks. Not usable to claim task success.
                proposed = {
                    "kind": "click", "selector": hint["selector"],
                    "observed": False, "to": dests[0],
                    "to_path": hint["target_path"],
                    "outcome": "html-href", "source": "html_href",
                }
                if not any(e["selector"] == proposed["selector"]
                           and e["kind"] == "click" for e in edges):
                    edges.append(proposed)
                    self.inferred_edges.append({"from": index, **proposed})
            for manual in self.manual_edges:
                if manual["from"] != index:
                    continue
                dest = manual["to"]
                edges.append({
                    "kind": "click", "selector": manual["selector"],
                    "observed": False, "manual_override": True,
                    "to": dest, "to_path": self.navigation_editor.states[dest]["path"],
                    "outcome": "manual_navigation",
                })
            # Legacy manual recordings do not contain action-to-state edges.
            # They remain inspectable through _step, but no longer advance
            # to an arbitrary next screen on unrelated button clicks.
            transitions_attr = html.escape(json.dumps(edges), quote=True)
            preview_to = self.preview_edges.get(index)
            preview_attr = (f' data-dom-settle-to="{preview_to}"'
                            if preview_to is not None else "")
            # Running reviewed fixture JavaScript and synthetic click-shim
            # navigation simultaneously would distort native JS behavior.
            shim = "" if self.trusted_fixture_js else (
                f'<script src="{SIMULATOR}" data-step="{index}" '
                f'data-transitions="{transitions_attr}"{preview_attr}></script>')
            page = "".join(parser.result)
            # Opt-in, visibly labeled research source access. No captured JS
            # executes; adding this link creates a DISTINCT study condition.
            # Never silently expose it in the normal fidelity baseline.
            source_link = (
                '<aside id="mock-research-source-link" role="note" '
                'style="position:fixed;bottom:12px;right:12px;z-index:2147483647;'
                'background:#fff;color:#111;border:2px solid #333;padding:8px;'
                'font:14px sans-serif">Research mode: '
                f'<a href="{SCRIPT_INDEX}">Inspect recorded JavaScript (read-only)</a>'
                '</aside>'
                if self.agent_js_inspection else ""
            )
            append = shim + source_link
            page = (page.replace("</body>", append + "</body>", 1)
                    if "</body>" in page else page + append)
            self.pages[index] = page.encode("utf-8")

    def respond(self, method, path, query=""):
        if method not in {"GET", "HEAD"}:
            return 405, b"Method not allowed", "text/plain"
        if path.startswith(TRUSTED_JS_ASSETS):
            digest = path[len(TRUSTED_JS_ASSETS):]
            source = self.trusted_js_sources.get(digest)
            if source is None:
                return 404, b"Unknown trusted script", "text/plain"
            return 200, source if method == "GET" else b"", "text/javascript; charset=utf-8"
        if path == SCRIPT_INDEX_JSON:
            public_data = {"execution": False, "source": "recorded_har",
                           "scripts": self.script_index,
                           "skipped_due_to_limits": self.script_sources_skipped}
            raw = json.dumps(public_data, ensure_ascii=False).encode("utf-8")
            return 200, raw if method == "GET" else b"", "application/json; charset=utf-8"
        if path == SCRIPT_INDEX:
            # No inline JS, external scripts, or live links. Explicit opt-in
            # inspection URL so baseline replay DOM is not contaminated.
            rows = "".join(
                '<li><a href="' + SCRIPT_SOURCE + item["id"] + '">' +
                html.escape(item["name"]) + "</a> (" +
                item["origin"] + ", " + str(item["bytes"]) + " bytes; path: <code>" +
                html.escape(item["path"]) + "</code>; sha256: <code>" +
                item["id"] + "</code>)</li>"
                for item in self.script_index
            )
            markup = (
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<title>Recorded JS, read-only</title></head><body>"
                "<h1>Recorded JavaScript (read-only, not executed)</h1>"
                "<p>Explicit research inspection only. Agents do not "
                "automatically see this source in screenshots or the page DOM.</p>"
                "<p>Original page scripts are deliberately not run here.</p>"
                "<ul>" + rows + "</ul></body></html>"
            )
            return 200, markup.encode() if method == "GET" else b"", "text/html; charset=utf-8"
        if path.startswith(SCRIPT_SOURCE):
            digest = path[len(SCRIPT_SOURCE):]
            source = self.script_sources.get(digest)
            if source is None:
                return 404, b"Unknown recorded JavaScript", "text/plain"
            # The proxy adds X-Content-Type-Options: nosniff. This is data,
            # never text/javascript, even if the content contains JS syntax.
            return 200, source if method == "GET" else b"", "text/plain; charset=utf-8"
        if path == SIMULATOR:
            return 200, SIM_JS.encode(), "text/javascript; charset=utf-8"
        if path.startswith(ASSETS):
            token = path[len(ASSETS):]
            if token in self.assets:
                body, mime, _ = self.assets[token]
                return 200, body if method == "GET" else b"", mime
            return 404, b"Not captured", "text/plain"
        # The displayed URL preserves the original recorded hostname and path.
        # The query selects an offline snapshot, never the real website.
        requested = parse_qs(query).get("_step")
        if requested is None:
            entry_path = urlsplit(self.start_url).path or "/"
            if path == entry_path:
                idx_raw = str(self.initial_step)
            else:
                default_idx = next(
                    (i for i, st in enumerate(self.steps)
                     if urlsplit(st.get("url") or self.start_url).hostname == self.host
                     and (urlsplit(st.get("url") or self.start_url).path or "/") == path),
                    0
                )
                idx_raw = str(default_idx)
        else:
            idx_raw = requested[0]
        if not idx_raw.isdecimal() or int(idx_raw) not in self.pages:
            return 404, b"Unknown snapshot", "text/plain"
        index = int(idx_raw)
        saved_url = urlsplit(self.steps[index].get("url") or self.start_url)
        if saved_url.hostname == self.host and path == (saved_url.path or "/"):
            body = self.pages[index]
            return 200, body if method == "GET" else b"", "text/html; charset=utf-8"
        return 404, b"Not captured", "text/plain"
