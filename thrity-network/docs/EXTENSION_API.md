# Thrity Extension API Reference

Every function callable from a `.thrity` extension's `on`/`action`
blocks, what permission it needs, and every event's fields. This is
the complete surface — there is nothing else reachable from
extension code (see `dsl_interpreter.py`'s docstring for why that's
a hard guarantee, not just a convention).

---

## Functions

### Always allowed (no permission needed)

| Function | Description |
|---|---|
| `log(message)` | Writes a line to the browser's console/log, prefixed with the extension id. First stop for debugging. |
| `notify(message)` | Shows a short-lived toast in the browser window. |

### `ui`

| Function | Description |
|---|---|
| `set_title(suffix)` | Appends `[suffix]` to the current tab's window title. |

Also unlocks declaring `toolbar_button` and `menu_item` blocks.

### `devtools`

| Function | Description |
|---|---|
| `show_panel(panel_id)` | Opens the Thrity DevTools window and switches to this extension's panel. |
| `set_panel_text(panel_id, text)` | Replaces the panel's contents with plain text. |

Also unlocks declaring `panel` and `devtool_panel` blocks.

### `page_info`

| Function | Description |
|---|---|
| `thrity_info()` | Returns a string describing the current tab: site name, ip:port, last load time, whether Tor-anonymized. |

### `page_scripts`

| Function | Description |
|---|---|
| `run_page_script(filename)` | Injects `assets/<filename>` (from your own extension folder only — `../` is stripped) into the current page as ordinary JavaScript. Same sandbox as any script the site itself could include. |

### `network`

| Function | Description |
|---|---|
| `http_get(url)` | GETs a URL and returns up to 4KB of the response body as text. **Only** allowed if `url`'s host is a configured registry or the .thrity host the current tab most recently resolved — any other host raises a permission error, even with this permission declared. |
| `list_registries()` | Returns a comma-separated string of every registry in `~/.thrity/config.json`. |
| `primary_registry()` | Returns the first configured registry URL, or `""` if none. |

### `storage`

| Function | Description |
|---|---|
| `storage_get(key)` | Reads a value from this extension's private storage. Returns nothing (empty) if unset. |
| `storage_set(key, value)` | Writes a value. Backed by one JSON file per extension at `~/.thrity/extension-data/<id>.json`, capped at 256KB. No other extension can read or write it. |

---

## Events

Fire with `on <name> { ... }`; fields are read as `event.<field>`.

| Event | Fields | Fires when |
|---|---|---|
| `page_loaded` | `url`, `load_ms` | A page finishes loading in any tab. |
| `navigation` | `url` | The person navigates (address bar Enter, or a link click that resolves a `.thrity` name). |
| `tab_created` | `url` | A new tab is opened. |
| `tab_closed` | `url` | A tab is closed. |
| `request_started` | `url` | Any sub-resource (image, script, stylesheet, XHR) starts loading. |
| `request_finished` | `url` | That sub-resource finishes loading. |

Handlers for `request_started`/`request_finished` fire very often on
media-heavy pages — keep them cheap (a `log()` call, not a network
request).

---

## Permission summary

| Permission | Unlocks |
|---|---|
| `ui` | `set_title`, `toolbar_button`, `menu_item` |
| `devtools` | `show_panel`, `set_panel_text`, `panel`, `devtool_panel` |
| `page_info` | `thrity_info()` |
| `page_scripts` | `run_page_script()` |
| `network` | `http_get()`, `list_registries()`, `primary_registry()` — Thrity network only, never arbitrary URLs |
| `storage` | `storage_get()`, `storage_set()` — private, capped, JSON only |

An extension only ever sees the permissions it declared; there's no
way to request "everything," by design.

---

## Testing against this API without a browser

```bash
cd browser
python3 -m extensions.cli fire path/to/extension page_loaded url=home.thrity load_ms=42
```

uses `extensions/host.py`'s `DummyHost`, which implements every
method above by printing what it would have done — safe to run
anywhere, no display or WebKit2GTK required.
