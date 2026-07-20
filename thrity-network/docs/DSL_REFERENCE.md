# Thrity Extension DSL — Reference

The whole language, in one file. If you've read three lines of a
`.thrity` extension already, you've seen most of the syntax there is.

---

## 1. File shape

Every extension is one file, `extension.thrity`, wrapped in a single
top-level block:

```
extension "My Extension" {
    id: "my-extension"
    version: "1.0"
    author: "you"
    description: "what it does"

    permissions { ... }
    settings { ... }

    toolbar_button "some_id" { ... }
    menu_item "some_id" { ... }
    panel "some_id" { ... }
    devtool_panel "some_id" { ... }

    on some_event { ... }
    action some_name { ... }
}
```

Blocks can appear in any order, any number of times (multiple `on
page_loaded { }` blocks are merged — both run). `#` starts a
line comment.

`id` is the only required field — it's how the extension is
identified for storage, logs, and permission errors, and must be
unique across all installed extensions.

## 2. `permissions`

A bare list of names, no colons:

```
permissions {
    devtools
    page_info
    network
    storage
    page_scripts
    ui
}
```

See `EXTENSION_API.md` for exactly what each one unlocks. Calling a
function that needs a permission you didn't declare doesn't crash
the browser — it logs a `[permission denied]` line and stops that
handler, nothing more.

## 3. `settings`

Plain key: literal pairs — strings, numbers, or `true`/`false`. No
expressions here; settings are declared once, not computed:

```
settings {
    show_timing: true
    refresh_interval: 30
    label_text: "Hello"
}
```

Read them from event handlers with `settings.show_timing`.

## 4. UI blocks

```
toolbar_button "helper_btn" {
    label: "Dev Helper"
    icon: "wrench"          # optional, currently a hint only
    on_click: show_panel("helper_panel")
}

menu_item "clear_data" {
    label: "Clear my data"
    on_click: storage_set("saved", "")
}

panel "helper_panel" {
    title: "Dev Helper"
    on_open: refresh()
}

devtool_panel "helper_panel" {
    title: "Dev Helper"
    on_open: refresh()
}
```

`on_click` / `on_open` take a single call expression — either a
builtin (`show_panel(...)`) or one of your own `action`s
(`refresh()`).

`panel` is a regular in-page panel; `devtool_panel` shows up as a tab
in the Thrity DevTools window instead. Both use the same shape.

## 5. `on <event> { ... }`

Runs a statement list whenever the named browser event fires. Known
event names: `page_loaded`, `navigation`, `tab_created`,
`tab_closed`, `request_started`, `request_finished`. Inside the
handler, `event.<field>` reads data about what happened — see
`EXTENSION_API.md` for which fields each event carries.

```
on page_loaded {
    log("loaded " + event.url + " in " + event.load_ms + "ms")
}
```

## 6. `action <name> { ... }`

A named, reusable statement list — call it from `on_click`, `on_open`,
an event handler, or another action:

```
action refresh {
    set_panel_text("helper_panel", thrity_info())
}
```

## 7. Statements

```
let x = expr            # local variable, scoped to this handler/action call
if expr { ... } else { ... }   # else is optional
<call expression>       # e.g. log("hi"), refresh(), notify("done")
```

There are no loops and no early return — handlers are meant to be
short reactions to an event, not general-purpose programs. If you
need something more complex, do it in a page script (JavaScript,
`page_scripts` permission) instead.

## 8. Expressions

```
"a string"
42
3.5
true / false
event.some_field
settings.some_key
a_local_variable
some_function(arg1, arg2)
left + right             # string concatenation if either side is a string, else numeric add
left == right
left != right
(expr)
```

That's the entire expression grammar — no `<`/`>`, no `&&`/`||`, no
arrays or objects. Keep logic in Python-side extension code (there
isn't any — that's the point) or just keep handlers simple.

## 9. Errors

- A syntax error (`DSLSyntaxError`) is raised when the extension is
  loaded, and prevents that one extension from loading — everything
  else still works.
- A runtime error (unknown function, undefined variable, permission
  denied) is caught per-handler-invocation and logged with `[error]`
  — it doesn't crash the browser or stop other extensions.

Validate a file before installing it:

```bash
python3 -m extensions.cli validate path/to/your-extension
python3 -m extensions.cli fire path/to/your-extension page_loaded url=example.thrity load_ms=42
```
