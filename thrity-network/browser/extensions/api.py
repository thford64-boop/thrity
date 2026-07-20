#!/usr/bin/env python3
"""
ExtensionAPI - the only surface extension code can call into.

Every method here either does something harmless unconditionally
(log, notify) or checks the extension's declared permission first
via `_require`. There is deliberately no generic "do anything"
escape hatch:

  - storage_get/storage_set only ever touch ONE JSON file per
    extension, under ~/.thrity/extension-data/<id>.json - an
    extension can't request another extension's file or any
    arbitrary path, because the path is built here, not passed in.
  - http_get only allows requests to registry servers already
    configured in ~/.thrity/config.json, or to the ip:port a
    .thrity name most recently resolved to in THIS browser session -
    never an arbitrary URL. This makes "network" permission mean
    "talk to the Thrity network", not "make requests anywhere",
    which is what stops it being used for data exfiltration to a
    random third party.
  - run_page_script only loads a file that lives inside the
    extension's own folder (path-traversal checked) and hands it to
    WebKit as a page-world user script - it never executes as
    Python, it runs as ordinary sandboxed page JavaScript, same as
    any script a website could include itself.
"""

import json
import os
import urllib.request

EXT_DATA_DIR = os.path.expanduser("~/.thrity/extension-data")
STORAGE_MAX_BYTES = 256 * 1024  # keep a single extension's storage file small on purpose


class PermissionError_(Exception):
    pass


class ExtensionAPI:
    def __init__(self, manifest, host):
        """`host` is the object providing real browser behaviour -
        see browser/extensions/host.py for the interface, and
        DummyHost in that file for a headless stand-in used by tests
        and the CLI validator."""
        self.manifest = manifest
        self.host = host

    def _require(self, permission):
        if not self.manifest.has_permission(permission):
            raise PermissionError_(
                f"extension '{self.manifest.id}' used a '{permission}' feature "
                f"without declaring `permissions {{ {permission} }}`")

    # -- always allowed: harmless, and essential for debugging --
    def log(self, message):
        self.host.log(self.manifest.id, str(message))

    def notify(self, message):
        self.host.notify(self.manifest.id, str(message))

    # -- ui permission --
    def set_title(self, suffix):
        self._require("ui")
        self.host.set_title_suffix(self.manifest.id, str(suffix))

    # -- devtools permission --
    def show_panel(self, panel_id):
        self._require("devtools")
        self.host.show_panel(self.manifest.id, str(panel_id))

    def set_panel_text(self, panel_id, text):
        self._require("devtools")
        self.host.set_panel_text(self.manifest.id, str(panel_id), str(text))

    # -- page_info permission --
    def thrity_info(self):
        self._require("page_info")
        info = self.host.get_thrity_info()
        return ", ".join(f"{k}={v}" for k, v in info.items())

    # -- page_scripts permission --
    def run_page_script(self, filename):
        self._require("page_scripts")
        safe_name = os.path.basename(str(filename))  # strips any '../' component entirely
        script_path = os.path.join(self.manifest.ext_dir, "assets", safe_name)
        if not os.path.isfile(script_path):
            raise FileNotFoundError(f"page script not found: assets/{safe_name}")
        self.host.inject_page_script(self.manifest.id, script_path)

    # -- network permission (Thrity network only, never arbitrary URLs) --
    def list_registries(self):
        self._require("network")
        return ", ".join(self.host.get_registries()) or "(none configured)"

    def primary_registry(self):
        self._require("network")
        registries = self.host.get_registries()
        return registries[0] if registries else ""

    def http_get(self, url):
        self._require("network")
        if not self.host.is_allowed_thrity_url(url):
            raise PermissionError_(
                "network permission only allows requests to configured registries "
                "or the currently-resolved .thrity host, not arbitrary URLs")
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.read(4096).decode("utf-8", errors="replace")

    # -- storage permission (private, capped, JSON-only) --
    def storage_get(self, key):
        self._require("storage")
        data = self._load_storage()
        return data.get(str(key))

    def storage_set(self, key, value):
        self._require("storage")
        data = self._load_storage()
        data[str(key)] = value
        self._save_storage(data)

    def _storage_path(self):
        os.makedirs(EXT_DATA_DIR, exist_ok=True)
        return os.path.join(EXT_DATA_DIR, f"{self.manifest.id}.json")

    def _load_storage(self):
        path = self._storage_path()
        if not os.path.exists(path):
            return {}
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_storage(self, data):
        encoded = json.dumps(data)
        if len(encoded.encode()) > STORAGE_MAX_BYTES:
            raise ValueError(f"extension storage limit exceeded ({STORAGE_MAX_BYTES} bytes)")
        with open(self._storage_path(), "w") as f:
            f.write(encoded)
