# Creating a Thrity Extension

A guide to writing, testing, and installing an extension — no Python
required, the extension system speaks its own small DSL. See
`DSL_REFERENCE.md` for the full language and `EXTENSION_API.md` for
every builtin function.

---

## 1. What an extension is

A folder:

```
my-extension/
├── extension.thrity     # required: metadata, permissions, UI, logic
└── assets/               # optional: page scripts (.js), icons
    └── my-script.js
```

That's it — no build step, no packaging format. "Installing" an
extension is copying its folder into `~/.thrity/extensions/`.

## 2. Start from a template

```
extension "My First Extension" {
    id: "my-first-extension"
    version: "1.0"
    author: "you"
    description: "says hello when a page loads"

    permissions {
        ui
    }

    on page_loaded {
        notify("Hello from my first extension! Loaded: " + event.url)
    }
}
```

Save that as `my-first-extension/extension.thrity`.

## 3. Validate it before installing

You don't need the browser open, or even WebKit2GTK installed, to
check an extension is well-formed:

```bash
cd browser
python3 -m extensions.cli validate ../my-first-extension
```

This parses the file, builds its manifest, and prints a summary
(permissions, toolbar buttons, panels, events handled). Any syntax
or manifest error shows up here with a message, not a stack trace.

## 4. Test it against a fake event

Before touching the real browser, fire a synthetic event at your
extension and watch what it does:

```bash
python3 -m extensions.cli fire ../my-first-extension page_loaded url=home.thrity load_ms=42
```

This runs your `on page_loaded` handler for real (permission checks
and all) against a `DummyHost` that just prints what would have
happened — notifications, panel updates, storage writes — instead of
touching a real browser window. This is what CI / automated testing
of an extension looks like; see "Testing instructions" below.

## 5. Install it for real

```bash
mkdir -p ~/.thrity/extensions
cp -r my-first-extension ~/.thrity/extensions/
```

Restart 30web (or just launch it) — extensions load once at startup.
If it failed to load, you'll see a toast notification naming which
extension and why; the browser still starts normally.

## 6. Add UI

A toolbar button that opens a devtool panel:

```
toolbar_button "open_it" {
    label: "My Panel"
    on_click: show_panel("my_panel")
}

devtool_panel "my_panel" {
    title: "My Panel"
    on_open: refresh()
}

action refresh {
    set_panel_text("my_panel", "Current site: " + thrity_info())
}
```

`show_panel` / `set_panel_text` need the `devtools` permission;
`thrity_info()` needs `page_info`.

## 7. Add a page script

Page scripts are ordinary JavaScript files in `assets/`, injected
into the current page the same way a website's own `<script>` tag
would run — same sandbox, no special access:

```
permissions {
    page_scripts
}

toolbar_button "count_words" {
    label: "Word Count"
    on_click: run_page_script("word-count.js")
}
```

```js
// assets/word-count.js
(function () {
    var words = document.body.innerText.trim().split(/\s+/);
    alert("About " + words.length + " words on this page.");
})();
```

`run_page_script` only ever loads a file from your extension's own
`assets/` folder — there's no way to point it at an arbitrary path.

## 8. Store data

```
permissions {
    storage
}

on page_loaded {
    storage_set("last_url", event.url)
    log("last seen: " + storage_get("last_url"))
}
```

Each extension gets one private JSON file
(`~/.thrity/extension-data/<id>.json`), capped at 256KB, that no
other extension can read or write.

## 9. Talk to the Thrity network

```
permissions {
    network
}

action check_registry {
    let reg = primary_registry()
    if reg != "" {
        let listing = http_get(reg + "/list")
        log("registry says: " + listing)
    }
}
```

`http_get` only allows requests to a configured registry or the
currently-resolved `.thrity` host for the tab — not arbitrary URLs.
See `EXTENSION_API.md` for why.

## 10. Look at the examples

`extensions-examples/` in the repo has three complete, working
extensions covering everything above:

- **thrity-developer-helper** — devtools panel + page timing
- **thrity-page-tools** — page scripts (link highlighter, word count)
- **thrity-network-monitor** — devtools panel + registry `http_get`

## Testing instructions (for CI or before sharing an extension)

```bash
cd browser
# 1. Every example still parses:
for ext in ../extensions-examples/*/; do
    python3 -m extensions.cli validate "$ext"
done

# 2. Run the built-in unit tests for the DSL itself:
python3 -m unittest discover -s extensions/tests -v
```

(See `docs/EXTENSION_API.md` for the full builtin list to write
`fire` tests against for your own extension's event handlers.)
