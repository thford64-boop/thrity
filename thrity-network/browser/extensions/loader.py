#!/usr/bin/env python3
"""
ExtensionManager - discovers installed extensions, parses them, and
wires their `on` handlers to the EventBus.

An extension is a folder containing `extension.thrity` (the manifest
+ logic) and optionally an `assets/` folder (page scripts, icons).
Installed extensions live in ~/.thrity/extensions/<name>/ - "install"
is just "put the folder there" (or a future `thrity-ext install`
command that unpacks a .zip into that location - see cli.py).

One broken extension must never take down the browser or other
extensions: every step here is wrapped so a bad manifest becomes a
line in self.errors, not a crash.
"""

import os

from . import dsl_parser, dsl_manifest, dsl_interpreter
from .api import ExtensionAPI
from .dsl_parser import DSLSyntaxError
from .dsl_manifest import ManifestError

EXTENSIONS_DIR = os.path.expanduser("~/.thrity/extensions")


class LoadedExtension:
    def __init__(self, manifest, api):
        self.manifest = manifest
        self.api = api


class ExtensionManager:
    def __init__(self, event_bus, host, extensions_dir=EXTENSIONS_DIR):
        self.event_bus = event_bus
        self.host = host
        self.extensions_dir = extensions_dir
        self.extensions = {}   # id -> LoadedExtension
        self.errors = []       # [(folder_name, message)]

    def load_all(self):
        os.makedirs(self.extensions_dir, exist_ok=True)
        for entry in sorted(os.listdir(self.extensions_dir)):
            folder = os.path.join(self.extensions_dir, entry)
            manifest_path = os.path.join(folder, "extension.thrity")
            if not os.path.isfile(manifest_path):
                continue
            self.load_one(folder, entry)

    def load_one(self, folder, folder_name):
        try:
            with open(os.path.join(folder, "extension.thrity")) as f:
                text = f.read()
            ast = dsl_parser.parse(text)
            manifest = dsl_manifest.build_manifest(ast, folder)
        except (DSLSyntaxError, ManifestError, OSError) as e:
            self.errors.append((folder_name, str(e)))
            return None

        if manifest.id in self.extensions:
            self.errors.append((folder_name, f"duplicate extension id '{manifest.id}'"))
            return None

        api = ExtensionAPI(manifest, self.host)
        loaded = LoadedExtension(manifest, api)
        self.extensions[manifest.id] = loaded
        self._register_handlers(loaded)
        return loaded

    def _register_handlers(self, loaded):
        manifest = loaded.manifest
        for event_name, stmts in manifest.handlers.items():
            def make_callback(stmts=stmts, manifest=manifest, api=loaded.api):
                def callback(event_data):
                    dsl_interpreter.run(stmts, manifest, api, event=event_data)
                return callback
            self.event_bus.on(event_name, make_callback())

    # -- UI wiring: the browser calls these when a toolbar button /
    #    menu item / panel is actually clicked or opened --
    def run_expr_as_statement(self, ext_id, expr):
        loaded = self.extensions.get(ext_id)
        if not loaded or expr is None:
            return
        try:
            dsl_interpreter.exec_statement(
                {"kind": "expr_stmt", "expr": expr},
                {"event": {}, "locals": {}, "depth": 0},
                loaded.api, loaded.manifest,
            )
        except Exception as e:
            self.host.log(ext_id, f"[error] {type(e).__name__}: {e}")

    def open_panel(self, ext_id, panel_id, kind="panel"):
        loaded = self.extensions.get(ext_id)
        if not loaded:
            return
        panels = loaded.manifest.devtool_panels if kind == "devtool_panel" else loaded.manifest.panels
        panel = next((p for p in panels if p["id"] == panel_id), None)
        if panel and panel["on_open"] is not None:
            self.run_expr_as_statement(ext_id, panel["on_open"])

    # -- introspection, used by the DevTools "Extensions" panel --
    def summary(self):
        rows = []
        for ext_id, loaded in self.extensions.items():
            m = loaded.manifest
            rows.append({
                "id": ext_id, "name": m.name, "version": m.version,
                "permissions": sorted(m.permissions),
                "events": sorted(m.handlers.keys()),
            })
        return rows
