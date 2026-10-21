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

ASSETS = "/__mock_capture/assets/"
SIMULATOR = "/__mock_capture/sim.js"
MAX_ASSET_BYTES = 12 * 1024 * 1024

SIM_JS = r"""
(() => {
  const config = document.currentScript.dataset;
  const step = Number(config.step || "0");
  let edges = [];
  try { edges = JSON.parse(config.transitions || "[]"); }
  catch (err) { console.error("Invalid recorded transition data", err); }
  let busy = false;

  function matches(el, edge) {
    if (!edge.selector || !el) return false;
    try { return !!el.closest(edge.selector); }
    catch (_) { return false; }
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
      if (edge && edge.outcome === "changed" && edge.to !== step && edge.to_path) {
        const url = new URL(edge.to_path, location.origin);
        url.searchParams.set("__mock_step", String(edge.to));
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
    // Capture every observed click target, including DIV/SPAN handlers.
    // Captured scripts and original external navigation remain disabled.
    const edge = edges.find(e => e.kind === "click" && matches(target, e));
    const form = target.closest("form");
    const submitEdge = form
      ? edges.find(e => e.kind === "submit" && matches(form, e))
      : null;
    const candidate = edge || submitEdge || null;
    const interactive = target.closest(
      "button, a, input[type=submit], input[type=button], [role=button], [onclick], [tabindex]"
    );
    if (!candidate && !interactive) return;
    if (interactive && (interactive.matches("a") || interactive.matches("button"))) {
      event.preventDefault();
    }
    if (!candidate) {
      console.debug("No recorded transition for clicked element. " +
                    "Inspect bundle.json transitions or recapture this action.");
    }
    record(candidate, "button_click", form || document);
  }, true);

  document.addEventListener("submit", event => {
    event.preventDefault();
    const edge = edges.find(e => e.kind === "submit" && matches(event.target, e));
    record(edge || null, "form_submit", event.target);
  }, true);

  document.addEventListener("change", event => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const edge = edges.find(e => e.kind === "change" && matches(target, e));
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

    def __init__(self, page_url, asset_urls):
        super().__init__(convert_charrefs=False)
        self.page_url = page_url
        self.asset_urls = asset_urls
        self.result = []
        self.blocked = []
        self.style_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if self.blocked:
            if tag in self.DROP:
                self.blocked.append(tag)
            return
        if tag in self.DROP:
            self.blocked.append(tag)
            return
        values = {k.lower(): v for k, v in attrs if k}
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
                "srcdoc", "ping", "autofocus"}:
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
        if tag == "style" and self.style_depth:
            self.style_depth -= 1
        self.result.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.blocked:
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
    def __init__(self, directory):
        self.directory = Path(directory).expanduser().resolve(strict=True)
        self.bundle = json.loads((self.directory / "bundle.json").read_text(encoding="utf-8"))
        self.start_url = self.bundle.get("startUrl", "")
        parsed = urlsplit(self.start_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Invalid startUrl in bundle")
        self.host = parsed.hostname.lower()
        self.steps = self.bundle.get("steps", [])
        self.transitions = self.bundle.get("transitions", [])
        if not self.steps:
            raise ValueError("No recorded HTML snapshots")
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
        for entry in har.get("log", {}).get("entries", []):
            req, response = entry.get("request") or {}, entry.get("response") or {}
            payload = response.get("content") or {}
            url, body = req.get("url", ""), payload.get("text")
            if req.get("method") not in {"GET", "HEAD"} or not isinstance(body, str):
                continue
            mime = str(payload.get("mimeType") or mimetypes.guess_type(urlsplit(url).path)[0]
                       or "application/octet-stream")
            # Never serve captured JavaScript, HTML, JSON, or SVG as replay assets.
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
        for index, step in enumerate(self.steps):
            filename = step.get("html") or ("step-" + str(index).zfill(3) + ".html")
            file = (self.directory / filename).resolve(strict=True)
            if not file.is_relative_to(self.directory):
                raise ValueError("Snapshot path escapes recording")
            source = step.get("url") or self.start_url
            parser = SnapshotSanitizer(source, self.urls)
            parser.feed(file.read_text(encoding="utf-8", errors="replace"))
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
            # Legacy manual recordings do not contain action-to-state edges.
            # They remain inspectable through __mock_step, but no longer advance
            # to an arbitrary next screen on unrelated button clicks.
            transitions_attr = html.escape(json.dumps(edges), quote=True)
            shim = (f'<script src="{SIMULATOR}" data-step="{index}" '
                    f'data-transitions="{transitions_attr}"></script>')
            page = "".join(parser.result)
            page = (page.replace("</body>", shim + "</body>", 1)
                    if "</body>" in page else page + shim)
            self.pages[index] = page.encode("utf-8")

    def respond(self, method, path, query=""):
        if method not in {"GET", "HEAD"}:
            return 405, b"Method not allowed", "text/plain"
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
        requested = parse_qs(query).get("__mock_step")
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
