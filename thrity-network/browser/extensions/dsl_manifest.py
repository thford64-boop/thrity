#!/usr/bin/env python3
"""
Turns the raw AST from dsl_parser.parse() into a structured
ExtensionManifest that the loader and interpreter can work with
directly, instead of every consumer re-walking the same tree.
"""

KNOWN_PERMISSIONS = {
    "devtools",     # add/update developer-tool panels
    "page_info",    # read info about the current .thrity site (name, ip:port, https, timing)
    "network",      # http_get() to Thrity registries / resolved .thrity hosts only - never arbitrary URLs
    "storage",      # storage_get/storage_set, private per-extension JSON storage
    "page_scripts",  # inject a JS file from the extension's own folder into the page
    "ui",           # toolbar buttons, menu items, set_title()
}


class ManifestError(Exception):
    pass


class ExtensionManifest:
    def __init__(self, ext_dir):
        self.ext_dir = ext_dir          # folder this extension was loaded from
        self.name = None
        self.id = None
        self.version = "0.0"
        self.author = ""
        self.description = ""
        self.permissions = set()
        self.toolbar_buttons = []       # [{id, label, icon, on_click_expr}]
        self.menu_items = []            # [{id, label, on_click_expr}]
        self.panels = []                # [{id, title, on_open_stmts}]
        self.devtool_panels = []        # [{id, title, on_open_stmts}]
        self.settings = {}              # plain literal values
        self.handlers = {}              # event_name -> [stmts] (merged across multiple `on` blocks)
        self.actions = {}               # action_name -> [stmts]

    def has_permission(self, perm):
        return perm in self.permissions


def _literal(expr):
    """Evaluates a settings-block expr that must be a plain literal
    (settings are declared once, not computed) - keeps the settings
    block simple and side-effect free."""
    if expr["kind"] == "str":
        return expr["value"]
    if expr["kind"] == "num":
        return expr["value"]
    if expr["kind"] == "bool":
        return expr["value"]
    raise ManifestError("settings values must be plain strings, numbers, or booleans")


def build_manifest(ast, ext_dir):
    if ast["kind"] != "extension":
        raise ManifestError("top-level block must be `extension \"Name\" { ... }`")

    manifest = ExtensionManifest(ext_dir)
    manifest.name = ast["name"]

    for entry in ast["entries"]:
        kind = entry["kind"]

        if kind == "kv":
            key, value = entry["key"], entry["value"]
            literal = _literal(value) if value["kind"] in ("str", "num", "bool") else None
            if key == "id":
                manifest.id = literal
            elif key == "version":
                manifest.version = str(literal)
            elif key == "author":
                manifest.author = literal
            elif key == "description":
                manifest.description = literal
            # unknown top-level keys are ignored rather than fatal, so
            # future manifest fields don't break older extensions

        elif kind == "permissions":
            unknown = set(entry["names"]) - KNOWN_PERMISSIONS
            if unknown:
                raise ManifestError(f"unknown permission(s): {', '.join(sorted(unknown))}")
            manifest.permissions = set(entry["names"])

        elif kind == "settings":
            manifest.settings = {k: _literal(v) for k, v in entry["values"].items()}

        elif kind == "on":
            manifest.handlers.setdefault(entry["event"], []).extend(entry["body"])

        elif kind == "action":
            manifest.actions[entry["name"]] = entry["body"]

        elif kind == "block":
            btype, label, sub_entries = entry["type"], entry["label"], entry["entries"]
            kv = {e["key"]: e["value"] for e in sub_entries if e["kind"] == "kv"}

            if btype == "toolbar_button":
                manifest.toolbar_buttons.append({
                    "id": label,
                    "label": _literal(kv["label"]) if "label" in kv else label,
                    "icon": _literal(kv["icon"]) if "icon" in kv else None,
                    "on_click": kv.get("on_click"),
                })
            elif btype == "menu_item":
                manifest.menu_items.append({
                    "id": label,
                    "label": _literal(kv["label"]) if "label" in kv else label,
                    "on_click": kv.get("on_click"),
                })
            elif btype == "panel":
                manifest.panels.append({
                    "id": label,
                    "title": _literal(kv["title"]) if "title" in kv else label,
                    "on_open": kv.get("on_open"),
                })
            elif btype == "devtool_panel":
                manifest.devtool_panels.append({
                    "id": label,
                    "title": _literal(kv["title"]) if "title" in kv else label,
                    "on_open": kv.get("on_open"),
                })
            else:
                raise ManifestError(f"unknown block type: {btype}")

    if not manifest.id:
        raise ManifestError(f"extension \"{manifest.name}\" is missing required `id: \"...\"`")

    return manifest
