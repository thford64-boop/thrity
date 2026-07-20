#!/usr/bin/env python3
"""
Headless developer tool for extension authors: parses and validates
an extension.thrity file, prints its manifest summary, and can fire
a synthetic event at it, all without GTK/WebKit2 or a display -
useful for local editing and for CI.

Usage:
    python3 -m extensions.cli validate <extension-folder>
    python3 -m extensions.cli fire <extension-folder> <event_name> [key=value ...]

Examples:
    python3 -m extensions.cli validate ../extensions-examples/thrity-developer-helper
    python3 -m extensions.cli fire ../extensions-examples/thrity-developer-helper page_loaded url=home.thrity load_ms=42
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from extensions import dsl_parser, dsl_manifest, dsl_interpreter
from extensions.api import ExtensionAPI
from extensions.host import DummyHost


def load(folder):
    manifest_path = os.path.join(folder, "extension.thrity")
    with open(manifest_path) as f:
        text = f.read()
    ast = dsl_parser.parse(text)
    manifest = dsl_manifest.build_manifest(ast, folder)
    return manifest


def cmd_validate(folder):
    manifest = load(folder)
    print(f"OK: '{manifest.name}' (id={manifest.id}, version={manifest.version})")
    print(f"  author:      {manifest.author or '(none)'}")
    print(f"  permissions: {sorted(manifest.permissions) or '(none)'}")
    print(f"  toolbar_buttons: {[b['id'] for b in manifest.toolbar_buttons]}")
    print(f"  menu_items:      {[m['id'] for m in manifest.menu_items]}")
    print(f"  panels:          {[p['id'] for p in manifest.panels]}")
    print(f"  devtool_panels:  {[p['id'] for p in manifest.devtool_panels]}")
    print(f"  settings:        {manifest.settings}")
    print(f"  events handled:  {sorted(manifest.handlers.keys())}")
    print(f"  actions defined: {sorted(manifest.actions.keys())}")


def cmd_fire(folder, event_name, kv_pairs):
    manifest = load(folder)
    host = DummyHost()
    api = ExtensionAPI(manifest, host)
    event_data = {}
    for pair in kv_pairs:
        key, _, value = pair.partition("=")
        if value.isdigit():
            value = int(value)
        event_data[key] = value
    stmts = manifest.handlers.get(event_name, [])
    if not stmts:
        print(f"(no handler for '{event_name}' in this extension - nothing to run)")
        return
    dsl_interpreter.run(stmts, manifest, api, event=event_data)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    command, folder = sys.argv[1], sys.argv[2]
    if command == "validate":
        cmd_validate(folder)
    elif command == "fire":
        if len(sys.argv) < 4:
            print("usage: cli.py fire <folder> <event_name> [key=value ...]")
            raise SystemExit(1)
        cmd_fire(folder, sys.argv[3], sys.argv[4:])
    else:
        print(__doc__)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
