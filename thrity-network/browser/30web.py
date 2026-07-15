#!/usr/bin/env python3
"""
30web - a small, old-school-style browser.

Built on WebKit2GTK (the same lightweight engine behind GNOME Web /
Midori / Surf) so real clearnet pages render properly, without the
weight of a full Chromium/Electron bundle.

Adds exactly one custom behaviour on top of a normal browser:
if the address ends in .thrity, it's resolved through the Thrity
Network resolver instead of normal DNS, then loaded like any other
page.

No accounts. No telemetry. No new-tab news feed. No extensions
framework. Just: address bar, back, forward, reload, go.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "resolver"))
from thrity_resolver import resolve  # noqa: E402

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, WebKit2, Gdk, GLib  # noqa: E402

HOMEPAGE = "https://start.duckduckgo.com/"  # change to anything, or a local file


def normalize_url(text: str) -> str:
    text = text.strip()
    if not text:
        return HOMEPAGE

    # Split off any path/query so we can resolve just the hostname
    scheme_stripped = text
    for prefix in ("http://", "https://"):
        if scheme_stripped.startswith(prefix):
            scheme_stripped = scheme_stripped[len(prefix):]
            break

    host = scheme_stripped.split("/")[0].split(":")[0].lower()

    if host.endswith(".thrity"):
        result = resolve(host)
        if result is None:
            # Show a simple built-in "not found" page instead of crashing out
            return "data:text/html," + GLib.uri_escape_string(
                f"<h2>Thrity site not found</h2><p><b>{host}</b> is not registered "
                f"with any configured registry, and has no local override.</p>",
                None, False)
        ip, port = result
        rest = "/" + "/".join(scheme_stripped.split("/")[1:]) if "/" in scheme_stripped else "/"
        return f"http://{ip}:{port}{rest}"

    # Looks like a normal domain/URL
    if "." in text and " " not in text and not text.startswith(("http://", "https://")):
        return "https://" + text
    if text.startswith(("http://", "https://", "data:", "file://")):
        return text
    # Otherwise treat it as a search
    return "https://duckduckgo.com/html/?q=" + GLib.uri_escape_string(text, None, False)


class ThirtyWeb(Gtk.Window):
    def __init__(self):
        super().__init__(title="30web")
        self.set_default_size(1024, 700)

        self.webview = WebKit2.WebView()
        settings = self.webview.get_settings()
        settings.set_enable_developer_extras(False)
        settings.set_enable_page_cache(True)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        toolbar.set_margin_top(4)
        toolbar.set_margin_bottom(4)
        toolbar.set_margin_start(4)
        toolbar.set_margin_end(4)

        back_btn = Gtk.Button(label="<")
        back_btn.connect("clicked", lambda w: self.webview.go_back())
        fwd_btn = Gtk.Button(label=">")
        fwd_btn.connect("clicked", lambda w: self.webview.go_forward())
        reload_btn = Gtk.Button(label="Reload")
        reload_btn.connect("clicked", lambda w: self.webview.reload())
        home_btn = Gtk.Button(label="Home")
        home_btn.connect("clicked", lambda w: self.load(HOMEPAGE))

        self.address_bar = Gtk.Entry()
        self.address_bar.connect("activate", self.on_go)

        go_btn = Gtk.Button(label="Go")
        go_btn.connect("clicked", self.on_go)

        for w in (back_btn, fwd_btn, reload_btn, home_btn):
            toolbar.pack_start(w, False, False, 0)
        toolbar.pack_start(self.address_bar, True, True, 0)
        toolbar.pack_start(go_btn, False, False, 0)

        vbox.pack_start(toolbar, False, False, 0)
        vbox.pack_start(self.webview, True, True, 0)
        self.add(vbox)

        self.webview.connect("notify::uri", self.on_uri_changed)
        self.webview.connect("notify::title", self.on_title_changed)

        self.connect("destroy", Gtk.main_quit)
        self.load(HOMEPAGE)

    def load(self, text):
        target = normalize_url(text)
        self.webview.load_uri(target)

    def on_go(self, widget):
        self.load(self.address_bar.get_text())

    def on_uri_changed(self, webview, param):
        uri = webview.get_uri()
        if uri:
            self.address_bar.set_text(uri)

    def on_title_changed(self, webview, param):
        title = webview.get_title()
        self.set_title(f"{title} - 30web" if title else "30web")


if __name__ == "__main__":
    win = ThirtyWeb()
    win.show_all()
    Gtk.main()
