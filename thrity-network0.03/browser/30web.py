#!/usr/bin/env python3
"""
30web - a small, old-school-style browser.

Built on WebKit2GTK (the same lightweight engine behind GNOME Web /
Midori / Surf) so real clearnet pages render properly, without the
weight of a full Chromium/Electron bundle.

Custom behaviour on top of a normal browser:
  - .thrity addresses (typed in the address bar, OR clicked as a
    thrity://name.thrity/path link inside any page) are resolved
    through the Thrity Network resolver instead of normal DNS. The
    address bar always shows the .thrity name, never the real ip:port.
  - Tabs, but no saved history: every tab is its own fully isolated,
    ephemeral WebKit context - nothing (history, cookies, cache) is
    written to disk, and no tab can see another tab's cookies/login
    state either.
  - Each tab has its OWN "Anonymize" toggle (routes that tab's
    traffic through Tor) - it's per-tab on purpose, since a shared
    on/off switch across every tab defeats the point: logging into
    something in a non-Tor tab while another tab is anonymized is a
    classic way real anonymity gets accidentally broken.
  - A "Directory" button lists every site a configured registry knows
    about, as real clickable thrity:// links.

Still no accounts, no telemetry, no news feed, no extensions
framework.
"""

import sys
import os
import json
import html as htmllib
import urllib.request
from urllib.parse import urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "resolver"))
from thrity_resolver import resolve, CONFIG_FILE, load_json, ensure_config  # noqa: E402

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, WebKit2, Gdk, GLib  # noqa: E402

HOMEPAGE = "https://start.duckduckgo.com/"  # change to anything, or a local file
TOR_SOCKS_URI = "socks5://127.0.0.1:9050"   # Tor's default local SOCKS port

# Remembers which real ip:port a .thrity name resolved to, so the
# address bar can keep showing the .thrity name (hiding the IP/port)
# even as the person clicks around deeper into that site.
THRITY_HOSTS = {}  # "ip:port" -> "name.thrity"


def normalize_url(text: str) -> str:
    """Turns typed text, or a thrity://name/path link, into a real
    loadable URL. A bare 'name.thrity' or 'name.thrity/path' (no
    scheme) is also accepted, since that's what the address bar and
    thrity:// link-handling both pass in here."""
    text = text.strip()
    if not text:
        return HOMEPAGE

    scheme_stripped = text
    for prefix in ("thrity://", "http://", "https://"):
        if scheme_stripped.startswith(prefix):
            scheme_stripped = scheme_stripped[len(prefix):]
            break

    host = scheme_stripped.split("/")[0].split(":")[0].lower()

    if host.endswith(".thrity"):
        result = resolve(host)
        if result is None:
            return "data:text/html," + GLib.uri_escape_string(
                f"<h2>Thrity site not found</h2><p><b>{host}</b> is not registered "
                f"with any configured registry, and has no local override.</p>",
                None, False)
        ip, port, https = result
        netloc = f"{ip}:{port}"
        THRITY_HOSTS[netloc] = host
        rest = "/" + "/".join(scheme_stripped.split("/")[1:]) if "/" in scheme_stripped else "/"
        scheme = "https" if https else "http"
        return f"{scheme}://{netloc}{rest}"

    if text.startswith(("http://", "https://", "data:", "file://")):
        return text
    if "." in text and " " not in text:
        return "https://" + text
    return "https://duckduckgo.com/html/?q=" + GLib.uri_escape_string(text, None, False)


def harden_settings(settings: WebKit2.Settings):
    """Security/privacy hardening applied to every tab."""
    settings.set_enable_developer_extras(False)
    settings.set_enable_page_cache(False)
    settings.set_enable_media_stream(False)
    settings.set_enable_mediasource(False)
    settings.set_enable_webgl(True)
    settings.set_enable_dns_prefetching(False)
    settings.set_enable_html5_database(False)
    settings.set_enable_html5_local_storage(False)
    settings.set_enable_offline_web_application_cache(False)
    settings.set_javascript_can_open_windows_automatically(False)


def fetch_directory_html(registry_url):
    """Builds a small directory page listing every live site a
    registry knows about, as real clickable thrity:// links."""
    try:
        with urllib.request.urlopen(f"{registry_url}/list", timeout=5) as resp:
            data = json.loads(resp.read())
        sites = sorted(data.get("sites", {}).keys())
    except Exception as e:
        return f"<h2>Couldn't reach the registry</h2><p>{htmllib.escape(str(e))}</p>"

    if not sites:
        return "<h2>Thrity Directory</h2><p>No sites registered yet.</p>"

    items = "".join(
        f'<li><a href="thrity://{htmllib.escape(name)}">{htmllib.escape(name)}</a></li>'
        for name in sites
    )
    return f"<h2>Thrity Directory</h2><p>{len(sites)} site(s) known to this registry.</p><ul>{items}</ul>"


class Tab:
    """Holds everything specific to one tab: its own isolated context
    (so cookies/logins never leak between tabs) and its own Tor state."""
    def __init__(self):
        self.data_manager = WebKit2.WebsiteDataManager.new_ephemeral()
        self.context = WebKit2.WebContext.new_with_website_data_manager(self.data_manager)
        self.webview = WebKit2.WebView(web_context=self.context, is_ephemeral=True)
        harden_settings(self.webview.get_settings())
        self.tor_enabled = False


class ThirtyWeb(Gtk.Window):
    def __init__(self):
        super().__init__(title="30web")
        self.set_default_size(1024, 700)
        self.tabs = {}  # webview -> Tab
        self._syncing_tab = False

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # ---- toolbar ----
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        toolbar.set_margin_top(4)
        toolbar.set_margin_bottom(4)
        toolbar.set_margin_start(4)
        toolbar.set_margin_end(4)

        back_btn = Gtk.Button(label="<")
        back_btn.connect("clicked", lambda w: self.current_webview().go_back())
        fwd_btn = Gtk.Button(label=">")
        fwd_btn.connect("clicked", lambda w: self.current_webview().go_forward())
        reload_btn = Gtk.Button(label="Reload")
        reload_btn.connect("clicked", lambda w: self.current_webview().reload())
        home_btn = Gtk.Button(label="Home")
        home_btn.connect("clicked", lambda w: self.load(HOMEPAGE))
        new_tab_btn = Gtk.Button(label="+")
        new_tab_btn.connect("clicked", lambda w: self.add_tab(HOMEPAGE))
        dir_btn = Gtk.Button(label="Directory")
        dir_btn.connect("clicked", self.on_directory)

        self.address_bar = Gtk.Entry()
        self.address_bar.connect("activate", self.on_go)
        go_btn = Gtk.Button(label="Go")
        go_btn.connect("clicked", self.on_go)

        self.tor_btn = Gtk.ToggleButton(label="Anonymize: Off")
        self.tor_btn.connect("toggled", self.on_tor_toggled)

        for w in (back_btn, fwd_btn, reload_btn, home_btn, new_tab_btn, dir_btn):
            toolbar.pack_start(w, False, False, 0)
        toolbar.pack_start(self.address_bar, True, True, 0)
        toolbar.pack_start(go_btn, False, False, 0)
        toolbar.pack_start(self.tor_btn, False, False, 0)

        # ---- tabs ----
        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.connect("switch-page", self.on_switch_tab)

        vbox.pack_start(toolbar, False, False, 0)
        vbox.pack_start(self.notebook, True, True, 0)
        self.add(vbox)

        self.connect("destroy", Gtk.main_quit)
        self.add_tab(HOMEPAGE)

    # ---- tab management ----
    def add_tab(self, url):
        tab = Tab()
        webview = tab.webview
        self.tabs[webview] = tab

        webview.connect("notify::uri", self.on_uri_changed)
        webview.connect("notify::title", self.on_title_changed)
        webview.connect("load-failed-with-tls-errors", self.on_tls_error)
        webview.connect("decide-policy", self.on_decide_policy)

        label_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        label = Gtk.Label(label="New Tab")
        close_btn = Gtk.Button(label="x")
        close_btn.set_relief(Gtk.ReliefStyle.NONE)
        label_box.pack_start(label, True, True, 0)
        label_box.pack_start(close_btn, False, False, 0)
        label_box.show_all()

        page_index = self.notebook.append_page(webview, label_box)
        self.notebook.set_tab_reorderable(webview, True)
        close_btn.connect("clicked", lambda w: self.close_tab(webview))

        self.notebook.show_all()
        self.notebook.set_current_page(page_index)
        webview.load_uri(normalize_url(url))
        return webview

    def close_tab(self, webview):
        page_index = self.notebook.page_num(webview)
        if page_index == -1:
            return
        if self.notebook.get_n_pages() == 1:
            Gtk.main_quit()
            return
        self.notebook.remove_page(page_index)
        self.tabs.pop(webview, None)

    def current_webview(self):
        index = self.notebook.get_current_page()
        return self.notebook.get_nth_page(index)

    def on_switch_tab(self, notebook, page, page_num):
        webview = notebook.get_nth_page(page_num)
        uri = webview.get_uri()
        self.address_bar.set_text(self.display_uri(uri) if uri else "")
        self._update_title(webview)

        # Sync the toolbar's Tor toggle to THIS tab's own state, without
        # re-triggering a reload via the toggle handler.
        self._syncing_tab = True
        tab = self.tabs.get(webview)
        enabled = tab.tor_enabled if tab else False
        self.tor_btn.set_active(enabled)
        self.tor_btn.set_label("Anonymize: On (Tor)" if enabled else "Anonymize: Off")
        self._syncing_tab = False

    def _update_title(self, webview):
        if webview is not self.current_webview():
            return
        title = webview.get_title()
        self.set_title(f"{title} - 30web" if title else "30web")

    # ---- navigation ----
    def load(self, text):
        target = normalize_url(text)
        self.current_webview().load_uri(target)

    def on_go(self, widget):
        self.load(self.address_bar.get_text())

    def display_uri(self, uri):
        parts = urlsplit(uri)
        thrity_name = THRITY_HOSTS.get(parts.netloc)
        if thrity_name:
            display = thrity_name + parts.path
            if parts.query:
                display += "?" + parts.query
            return display
        return uri

    def on_uri_changed(self, webview, param):
        if webview is not self.current_webview():
            return  # ignore background tabs
        uri = webview.get_uri()
        if uri:
            self.address_bar.set_text(self.display_uri(uri))

    def on_title_changed(self, webview, param):
        self._update_title(webview)
        page_index = self.notebook.page_num(webview)
        if page_index != -1:
            label_box = self.notebook.get_tab_label(webview)
            if label_box:
                label = label_box.get_children()[0]
                title = webview.get_title() or "New Tab"
                tab = self.tabs.get(webview)
                prefix = "[Tor] " if (tab and tab.tor_enabled) else ""
                label.set_text((prefix + title)[:22])

    def on_decide_policy(self, webview, decision, decision_type):
        """Intercepts any navigation - typed, clicked link, redirect,
        form submit - whose target is a thrity:// link, so .thrity
        sites can link to EACH OTHER, not just be reachable one at a
        time from the address bar."""
        if decision_type != WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            return False
        uri = decision.get_request().get_uri()
        if urlsplit(uri).scheme == "thrity":
            decision.ignore()
            webview.load_uri(normalize_url(uri))
            return True
        return False

    def on_tls_error(self, webview, failing_uri, certificate, errors):
        netloc = urlsplit(failing_uri).netloc
        if netloc in THRITY_HOSTS:
            # Self-signed cert from a .thrity host we reached via our
            # own resolver, not a random clearnet site - trust it
            # (same model as SSH trusting a host key on first
            # connect) and retry the load.
            host = netloc.split(":")[0]
            self.tabs[webview].context.allow_tls_certificate_for_host(certificate, host)
            webview.load_uri(failing_uri)
            return True
        return False  # not a .thrity host: let WebKit show its normal cert-error page

    # ---- Tor / anonymize (per tab) ----
    def on_tor_toggled(self, button):
        if self._syncing_tab:
            return  # this toggle came from switching tabs, not a user click
        webview = self.current_webview()
        tab = self.tabs[webview]
        tab.tor_enabled = button.get_active()
        if tab.tor_enabled:
            settings = WebKit2.NetworkProxySettings.new(TOR_SOCKS_URI, None)
            tab.context.set_network_proxy_settings(WebKit2.NetworkProxyMode.CUSTOM, settings)
            button.set_label("Anonymize: On (Tor)")
        else:
            tab.context.set_network_proxy_settings(WebKit2.NetworkProxyMode.DEFAULT, None)
            button.set_label("Anonymize: Off")
        self.on_title_changed(webview, None)  # refresh the [Tor] tab-label prefix
        webview.reload()

    # ---- directory ----
    def on_directory(self, widget):
        ensure_config()
        config = load_json(CONFIG_FILE)
        registries = config.get("registries", [])
        if not registries:
            body = "<h2>No registries configured</h2><p>Add one to ~/.thrity/config.json to browse the network.</p>"
        else:
            body = fetch_directory_html(registries[0])
        html_doc = f"<html><body style='font-family:sans-serif;padding:20px;'>{body}</body></html>"
        self.current_webview().load_uri("data:text/html," + GLib.uri_escape_string(html_doc, None, False))


if __name__ == "__main__":
    win = ThirtyWeb()
    win.show_all()
    Gtk.main()
