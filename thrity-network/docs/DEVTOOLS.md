# Thrity DevTools

30web has two separate developer-tools surfaces, on purpose — one
general-purpose (comes free from the browser engine), one
Thrity-specific (nothing else could provide it).

---

## 1. WebKit Inspector — click "Inspect"

WebKit2GTK ships a complete Web Inspector: element/HTML inspector,
CSS inspection, a JavaScript console, a full network waterfall, and
a storage/cookie viewer. Earlier versions of 30web had this turned
off (`enable_developer_extras = False`) as part of general hardening;
v0.05 turns it back on, since "developer tools" was an explicit goal
and reimplementing what WebKit already does well would be wasted
weight.

Open it with the **Inspect** toolbar button, or right-click any page
element and choose "Inspect Element" the same as any other
WebKit/Chromium-family browser.

This covers, from the original feature list:
- HTML element inspector
- CSS inspection
- JavaScript console
- Network monitor
- Storage/cookie viewer (for the current page's own storage)

## 2. Thrity DevTools — click "DevTools"

A second window with the parts specific to how Thrity actually
works, that WebKit's inspector has no way to know about:

### Resolver tab
The step-by-step trace of how the current tab's `.thrity` address
was resolved — cache hit/miss, `hosts.json` lookup, which registry
answered (or failed) and how long each step took in milliseconds.
Backed by `resolver/thrity_resolver.py`'s `resolve_with_debug()`.

### Timing tab
Full page load time for the current tab (navigation start to
`WebKit2.LoadEvent.FINISHED`).

### Security tab
- Current site and its resolved ip:port
- Whether this tab is Tor-anonymized
- The TLS trust model in effect (`.thrity`/`.onion` self-signed certs
  are trusted on first use; everything else uses WebKit's normal CA
  validation)
- Storage isolation model (ephemeral, per-tab, wiped on close)

### Storage tab
Whether local storage/IndexedDB/cookies are enabled for this tab and
their isolation guarantees — the actual key/value contents are in
WebKit's own Inspector (Storage tab there), since that's what already
implements a live, editable storage browser.

### Extensions tab
Every loaded extension: name, version, declared permissions, which
events it handles — plus any extensions that failed to load and why,
so a typo in one extension's `.thrity` file doesn't silently do
nothing.

### One tab per `devtool_panel`
Any installed extension that declares a `devtool_panel` block gets
its own tab here automatically (see `EXTENSIONS.md`) — this is the
"extension debugging tools" part of the feature list: extensions can
add their own inspection surface without touching browser code.

## Server-side debugging

Both servers also expose their own debug endpoints, queryable
directly (`curl`) or from an extension with `network` permission —
see `SERVER_API.md`:

- Host server: `GET /thrity-info` — name, https, uptime, requests served
- Registry server: `GET /status` — version, uptime, site counts, per-endpoint request totals

Run either with `--verbose` for full per-request timing in the
terminal.
