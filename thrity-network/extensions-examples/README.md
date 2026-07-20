# Example Extensions

Three working extensions demonstrating the full extension system.
`setup.sh` copies these into `~/.thrity/extensions/` automatically if
you don't already have any extensions installed. To install manually:

```bash
cp -r extensions-examples/* ~/.thrity/extensions/
```

- **thrity-developer-helper** — a toolbar button + DevTools panel
  showing the current `.thrity` site's info and page load timing.
- **thrity-page-tools** — two page-utility buttons (external-link
  highlighter, word count) backed by real JavaScript page scripts.
- **thrity-network-monitor** — a DevTools panel showing resolver,
  registry, and host information, including a live `http_get()` call
  to your configured registry's `/list` endpoint.

Read `docs/EXTENSIONS.md` for how to write your own, and
`docs/DSL_REFERENCE.md` / `docs/EXTENSION_API.md` for the full
language and API.

Validate any of these without launching the browser:

```bash
cd browser
python3 -m extensions.cli validate ../extensions-examples/thrity-developer-helper
python3 -m extensions.cli fire ../extensions-examples/thrity-developer-helper page_loaded url=home.thrity load_ms=42
```
