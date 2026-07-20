#!/usr/bin/env python3
"""
Thrity DevTools window
-------------------------
30web already turns on WebKit2's own Web Inspector (HTML/CSS
inspector, JS console, network waterfall, storage/cookie viewer -
all of that comes free from WebKit2GTK itself, right-click ->
Inspect Element, or the "Inspector" toolbar button). Reimplementing
those from scratch would be a lot of code for something WebKit
already does well, and would work against "keep it lightweight".

What THIS file adds is the Thrity-specific stuff the built-in
inspector has no way to know about:
  - Resolver debug: how a .thrity name was resolved (cache / local
    hosts.json / which registry answered) and how long each step took
  - Server timing: connect/response time to the current .thrity
    host, and to each configured registry
  - Security panel: whether the current tab is Tor-anonymized,
    whether the current .thrity host's TLS cert is trusted-on-first-
    use, and whether local storage for this tab is ephemeral
  - Extensions panel: every loaded extension, its permissions, which
    events it handles, and its most recent log lines / errors - the
    "extension debugging tools" from the feature list
  - A tab per extension-registered devtool_panel (see extensions/)
"""

import time
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk


class DevToolsWindow(Gtk.Window):
    def __init__(self, app):
        super().__init__(title="Thrity DevTools")
        self.app = app  # the ThirtyWeb window, for reading current-tab state
        self.set_default_size(560, 480)

        self.notebook = Gtk.Notebook()
        self.add(self.notebook)

        self.resolver_view = self._make_text_tab("Resolver")
        self.timing_view = self._make_text_tab("Timing")
        self.security_view = self._make_text_tab("Security")
        self.storage_view = self._make_text_tab("Storage")
        self.extensions_view = self._make_text_tab("Extensions")

        # one tab per extension-defined devtool_panel, created lazily
        # the first time DevTools opens so newly-installed extensions
        # show up without restarting the window
        self.ext_panel_views = {}  # (ext_id, panel_id) -> Gtk.TextBuffer

        self.connect("delete-event", lambda w, e: (self.hide(), True)[1])

    def _make_text_tab(self, title):
        scroller = Gtk.ScrolledWindow()
        textview = Gtk.TextView()
        textview.set_editable(False)
        textview.set_monospace(True)
        textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        scroller.add(textview)
        self.notebook.append_page(scroller, Gtk.Label(label=title))
        return textview.get_buffer()

    def ensure_extension_panels(self, extension_manager):
        for ext_id, loaded in extension_manager.extensions.items():
            for panel in loaded.manifest.devtool_panels:
                key = (ext_id, panel["id"])
                if key in self.ext_panel_views:
                    continue
                buf = self._make_text_tab(f"{panel['title']} ({loaded.manifest.name})")
                self.ext_panel_views[key] = buf

    def set_extension_panel_text(self, ext_id, panel_id, text):
        buf = self.ext_panel_views.get((ext_id, panel_id))
        if buf:
            buf.set_text(text)

    def show_extension_panel(self, ext_id, panel_id):
        buf = self.ext_panel_views.get((ext_id, panel_id))
        if not buf:
            return
        for i in range(self.notebook.get_n_pages()):
            page = self.notebook.get_nth_page(i)
            child = page.get_child()
            if hasattr(child, "get_buffer") and child.get_buffer() is buf:
                self.notebook.set_current_page(i)
                break
        self.present()

    # -- refresh methods, called right before the window is shown --
    def refresh_resolver(self, debug_trace):
        lines = ["Resolver trace for the current tab's last .thrity lookup:", ""]
        if not debug_trace:
            lines.append("(current tab isn't on a .thrity site)")
        else:
            for step in debug_trace:
                lines.append(f"  [{step['source']:10s}] {step['result']}  ({step['ms']:.1f}ms)")
        self.resolver_view.set_text("\n".join(lines))

    def refresh_timing(self, timing):
        lines = ["Page load timing (current tab):", ""]
        if not timing:
            lines.append("(no timing recorded yet - reload the page)")
        else:
            for label, ms in timing.items():
                lines.append(f"  {label:20s} {ms:.1f}ms")
        self.timing_view.set_text("\n".join(lines))

    def refresh_security(self, info):
        lines = ["Security information (current tab):", ""]
        for key, value in info.items():
            lines.append(f"  {key:20s} {value}")
        self.security_view.set_text("\n".join(lines))

    def refresh_storage(self, info):
        lines = ["Storage (current tab, ephemeral - wiped on tab close):", ""]
        for key, value in info.items():
            lines.append(f"  {key:20s} {value}")
        self.storage_view.set_text("\n".join(lines))

    def refresh_extensions(self, extension_manager):
        lines = ["Loaded extensions:", ""]
        for row in extension_manager.summary():
            lines.append(f"  {row['name']} (id={row['id']}, v{row['version']})")
            lines.append(f"    permissions: {row['permissions']}")
            lines.append(f"    handles:     {row['events']}")
            lines.append("")
        if extension_manager.errors:
            lines.append("Failed to load:")
            for folder, err in extension_manager.errors:
                lines.append(f"  {folder}: {err}")
        self.extensions_view.set_text("\n".join(lines))
