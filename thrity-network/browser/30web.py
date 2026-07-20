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
    Resolved names are cached briefly and re-resolved automatically
    if a page fails to load, instead of getting stuck.
  - Tabs, but no saved history: every tab is its own fully isolated,
    ephemeral WebKit context - nothing (history, cookies, cache) is
    written to disk, and no tab can see another tab's cookies/login
    state either. Local storage/IndexedDB are ephemeral too (needed
    for a lot of real sites to work at all) rather than fully off.
  - Camera/mic/location access is asked per-site instead of being
    silently blocked outright, so sites that need it (with the
    person's OK) actually work.
  - Each tab has its OWN "Anonymize" toggle (routes that tab's
    traffic through Tor) - it's per-tab on purpose, since a shared
    on/off switch across every tab defeats the point: logging into
    something in a non-Tor tab while another tab is anonymized is a
    classic way real anonymity gets accidentally broken. Onion
    (.onion) addresses default to plain http:// (most onion services
    don't speak TLS at all - the onion address itself is already the
    cryptographic identity), self-signed/invalid certs on .onion are
    trusted the same trust-on-first-use way .thrity certs are, and a
    failed load on a Tor-anonymized tab is retried a couple of times
    automatically since a fresh circuit failing once ("Internal
    SOCKSv5 proxy server error") is common and usually transient.
  - A "Directory" button lists every site a configured registry knows
    about, as real clickable thrity:// links.
  - Built-in DevTools: WebKit's own Web Inspector (element inspector,
    CSS, JS console, network, storage) plus a Thrity DevTools window
    with resolver debugging, per-site timing, a security panel, and
    an extensions panel - see devtools.py.
  - A full extension system (see extensions/) that lets people add
    toolbar buttons, menus, devtool panels, and page scripts through
    a small sandboxed DSL - no Python execution, no filesystem/
    network access beyond what each extension explicitly declares
    and the person installed.
"""

import sys
import os
import json
import time
import html as htmllib
import urllib.request
from urllib.parse import urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "resolver"))
from thrity_resolver import (  # noqa: E402
    resolve, resolve_with_debug, forget, is_valid_name,
    CONFIG_FILE, load_json, ensure_config,
)

sys.path.insert(0, os.path.dirname(__file__))
from extensions.loader import ExtensionManager  # noqa: E402
from extensions.events import EventBus  # noqa: E402
from extensions.host import Host  # noqa: E402
from devtools import DevToolsWindow  # noqa: E402

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, WebKit2, Gdk, GLib  # noqa: E402

HOMEPAGE = "https://start.duckduckgo.com/"  # change to anything, or a local file
TOR_SOCKS_URI = "socks5://127.0.0.1:9050"   # Tor's default local SOCKS port
TOR_RETRY_ATTEMPTS = 2       # extra attempts after the first failure, Tor-anonymized tabs only
TOR_RETRY_DELAY_MS = 2500    # gives Tor a moment to build a fresh circuit before retrying

# A recent, ordinary desktop user-agent. WebKit2GTK's default UA
# string identifies itself in a way that some sites' browser-sniffing
# treats as "unsupported" and blocks outright, even though the engine
# renders the page fine - this is the single biggest cause of pages
# that "just don't work". Spoofing a mainstream UA fixes most of that.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)

# Remembers which real ip:port a .thrity name resolved to, so the
# address bar can keep showing the .thrity name (hiding the IP/port)
# even as the person clicks around deeper into that site.
THRITY_HOSTS = {}  # "ip:port" -> "name.thrity"


def error_page(title, message):
    return "data:text/html," + GLib.uri_escape_string(
        f"<h2>{htmllib.escape(title)}</h2><p>{htmllib.escape(message)}</p>", None, False)


def normalize_url(text: str, fresh: bool = False, debug_sink=None) -> str:
    """Turns typed text, or a thrity://name/path link, into a real
    loadable URL. A bare 'name.thrity' or 'name.thrity/path' (no
    scheme) is also accepted, since that's what the address bar and
    thrity:// link-handling both pass in here. 'fresh' skips the
    resolver cache - used on retry after a failed load. `debug_sink`,
    if given, is a list that the resolver's step-by-step trace gets
    appended to, for the DevTools Resolver panel."""
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
        if not is_valid_name(host):
            return error_page("Invalid Thrity address",
                               f"'{host}' isn't a valid .thrity name.")
        result, trace = resolve_with_debug(host, use_cache=not fresh)
        if debug_sink is not None:
            debug_sink[:] = trace
        if result is None:
            return error_page(
                "Thrity site not found",
                f"{host} is not registered with any configured registry, "
                "and has no local override.")
        ip, port, https = result
        netloc = f"{ip}:{port}"
        THRITY_HOSTS[netloc] = host
        rest = "/" + "/".join(scheme_stripped.split("/")[1:]) if "/" in scheme_stripped else "/"
        scheme = "https" if https else "http"
        return f"{scheme}://{netloc}{rest}"

    if text.startswith(("http://", "https://", "data:", "file://")):
        return text
    if host.endswith(".onion") and "." in text and " " not in text:
        # Most onion services only ever serve plain HTTP - the onion
        # address is already the cryptographic identity, so there's
        # no CA-signed cert to get anyway. Defaulting to https:// (like
        # we do for clearnet) just makes an otherwise-working site look
        # broken with a TLS/connection error. If a site really does
        # speak HTTPS, typing https:// explicitly still works fine.
        return "http://" + text
    if "." in text and " " not in text:
        return "https://" + text
    return "https://duckduckgo.com/html/?q=" + GLib.uri_escape_string(text, None, False)


def harden_settings(settings: WebKit2.Settings):
    """Security/privacy hardening applied to every tab, balanced
    against real sites actually working."""
    settings.set_enable_developer_extras(True)    # powers WebKit's built-in DevTools (see devtools.py docstring)
    settings.set_enable_page_cache(True)           # faster back/forward, no disk write (ephemeral context)
    settings.set_enable_media_stream(True)         # asked per-site via permission-request, not blanket-blocked
    settings.set_enable_mediasource(True)          # most video sites (streaming, embeds) need this to play at all
    settings.set_enable_webgl(True)
    settings.set_enable_dns_prefetching(False)
    settings.set_enable_html5_database(True)       # ephemeral context still wipes this on tab close
    settings.set_enable_html5_local_storage(True)  # same - lots of ordinary sites are broken without this
    settings.set_enable_offline_web_application_cache(False)
    settings.set_javascript_can_open_windows_automatically(False)
    settings.set_user_agent(USER_AGENT)


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


# Errors from Tor that usually mean "this circuit failed, try again",
# not "this site is genuinely unreachable" - matched loosely against
# WebKit's GError message text.
TRANSIENT_TOR_ERRORS = ("socks", "proxy", "circuit", "timed out", "timeout")


def looks_transient_tor_error(error) -> bool:
    text = str(error).lower()
    return any(marker in text for marker in TRANSIENT_TOR_ERRORS)


class Tab:
    """Holds everything specific to one tab: its own isolated context
    (so cookies/logins never leak between tabs), its own Tor state,
    and the bits DevTools/extensions need to describe this tab."""
    def __init__(self):
        self.data_manager = WebKit2.WebsiteDataManager.new_ephemeral()
        self.context = WebKit2.WebContext.new_with_website_data_manager(self.data_manager)
        self.user_content_manager = WebKit2.UserContentManager()
        self.webview = WebKit2.WebView(
            web_context=self.context,
            user_content_manager=self.user_content_manager,
            is_ephemeral=True,
        )
        harden_settings(self.webview.get_settings())
        self.tor_enabled = False
        self.retried_uri = None       # tracks a load we've already retried once, so we don't loop
        self.tor_retry_count = 0
        self.resolver_trace = []      # last .thrity resolve, for DevTools
        self.load_started_at = None
        self.last_load_ms = None
        self.title_suffix = None      # set by extensions via set_title()


class BrowserHost(Host):
    """Implements extensions/host.py's interface against a real
    ThirtyWeb window - this is the only bridge extension code has
    into the actual browser, and every method here does only the one
    thing its name says."""
    def __init__(self, app):
        self.app = app

    def log(self, ext_id, message):
        print(f"[ext:{ext_id}] {message}")

    def notify(self, ext_id, message):
        self.app.show_toast(f"{ext_id}: {message}")

    def set_title_suffix(self, ext_id, suffix):
        tab = self.app.tabs.get(self.app.current_webview())
        if tab:
            tab.title_suffix = suffix
            self.app.on_title_changed(self.app.current_webview(), None)

    def show_panel(self, ext_id, panel_id):
        self.app.open_devtools()
        self.app.devtools.show_extension_panel(ext_id, panel_id)

    def set_panel_text(self, ext_id, panel_id, text):
        self.app.devtools.set_extension_panel_text(ext_id, panel_id, text)

    def get_thrity_info(self):
        webview = self.app.current_webview()
        tab = self.app.tabs.get(webview)
        uri = webview.get_uri() if webview else None
        netloc = urlsplit(uri).netloc if uri else ""
        name = THRITY_HOSTS.get(netloc, netloc or "(no page loaded)")
        return {
            "site": name,
            "ip_port": netloc or "(none)",
            "load_ms": round(tab.last_load_ms, 1) if tab and tab.last_load_ms else "(unknown)",
            "tor": tab.tor_enabled if tab else False,
        }

    def inject_page_script(self, ext_id, script_path):
        webview = self.app.current_webview()
        tab = self.app.tabs.get(webview)
        if not tab:
            return
        with open(script_path) as f:
            source = f.read()
        script = WebKit2.UserScript(
            source,
            WebKit2.UserContentInjectedFrames.ALL_FRAMES,
            WebKit2.UserScriptInjectionTime.END,
            None, None,
        )
        tab.user_content_manager.add_script(script)

    def is_allowed_thrity_url(self, url):
        netloc = urlsplit(url).netloc
        if netloc in THRITY_HOSTS:
            return True
        ensure_config()
        registries = load_json(CONFIG_FILE).get("registries", [])
        return any(urlsplit(r).netloc == netloc for r in registries)

    def get_registries(self):
        ensure_config()
        return load_json(CONFIG_FILE).get("registries", [])


class ThirtyWeb(Gtk.Window):
    def __init__(self):
        super().__init__(title="30web")
        self.set_default_size(1024, 700)
        self.tabs = {}  # webview -> Tab
        self._syncing_tab = False

        self.event_bus = EventBus()
        self.host = BrowserHost(self)
        self.extension_manager = ExtensionManager(self.event_bus, self.host)
        self.extension_manager.load_all()

        self.devtools = DevToolsWindow(self)

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
        devtools_btn = Gtk.Button(label="DevTools")
        devtools_btn.connect("clicked", lambda w: self.open_devtools())
        inspector_btn = Gtk.Button(label="Inspect")
        inspector_btn.connect("clicked", self.on_open_inspector)

        self.address_bar = Gtk.Entry()
        self.address_bar.connect("activate", self.on_go)
        go_btn = Gtk.Button(label="Go")
        go_btn.connect("clicked", self.on_go)

        self.tor_btn = Gtk.ToggleButton(label="Anonymize: Off")
        self.tor_btn.connect("toggled", self.on_tor_toggled)

        for w in (back_btn, fwd_btn, reload_btn, home_btn, new_tab_btn, dir_btn,
                  devtools_btn, inspector_btn):
            toolbar.pack_start(w, False, False, 0)
        toolbar.pack_start(self.address_bar, True, True, 0)
        toolbar.pack_start(go_btn, False, False, 0)
        toolbar.pack_start(self.tor_btn, False, False, 0)

        self._add_extension_toolbar_buttons(toolbar)

        # ---- toast (for extension notify() and permission prompts) ----
        self.toast_label = Gtk.Label()
        self.toast_revealer = Gtk.Revealer()
        self.toast_revealer.add(self.toast_label)
        self.toast_revealer.set_reveal_child(False)

        # ---- tabs ----
        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.connect("switch-page", self.on_switch_tab)

        vbox.pack_start(toolbar, False, False, 0)
        vbox.pack_start(self.toast_revealer, False, False, 0)
        vbox.pack_start(self.notebook, True, True, 0)
        self.add(vbox)

        self.connect("destroy", Gtk.main_quit)
        self.add_tab(HOMEPAGE)

        if self.extension_manager.errors:
            names = ", ".join(f[0] for f in self.extension_manager.errors)
            self.show_toast(f"{len(self.extension_manager.errors)} extension(s) failed to load: {names}")

    def _add_extension_toolbar_buttons(self, toolbar):
        for ext_id, loaded in self.extension_manager.extensions.items():
            for button in loaded.manifest.toolbar_buttons:
                btn = Gtk.Button(label=button["label"])
                btn.connect(
                    "clicked",
                    lambda w, eid=ext_id, expr=button["on_click"]: self.extension_manager.run_expr_as_statement(eid, expr),
                )
                toolbar.pack_start(btn, False, False, 0)

    def show_toast(self, message):
        self.toast_label.set_text(message)
        self.toast_revealer.set_reveal_child(True)
        GLib.timeout_add(4000, lambda: (self.toast_revealer.set_reveal_child(False), False)[1])

    # -- tab management --
    def add_tab(self, url):
        tab = Tab()
        webview = tab.webview
        self.tabs[webview] = tab

        webview.connect("notify::uri", self.on_uri_changed)
        webview.connect("notify::title", self.on_title_changed)
        webview.connect("load-failed-with-tls-errors", self.on_tls_error)
        webview.connect("load-failed", self.on_load_failed)
        webview.connect("load-changed", self.on_load_changed)
        webview.connect("decide-policy", self.on_decide_policy)
        webview.connect("permission-request", self.on_permission_request)
        webview.connect("resource-load-started", self.on_resource_load_started)

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

        debug_sink = tab.resolver_trace
        webview.load_uri(normalize_url(url, debug_sink=debug_sink))

        self.event_bus.emit("tab_created", url=url)
        return webview

    def close_tab(self, webview):
        page_index = self.notebook.page_num(webview)
        if page_index == -1:
            return
        uri = webview.get_uri()
        if self.notebook.get_n_pages() == 1:
            Gtk.main_quit()
            return
        self.notebook.remove_page(page_index)
        self.tabs.pop(webview, None)
        self.event_bus.emit("tab_closed", url=uri or "")

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
        tab = self.tabs.get(webview)
        suffix = f" [{tab.title_suffix}]" if tab and tab.title_suffix else ""
        self.set_title(f"{title}{suffix} - 30web" if title else "30web")

    # -- navigation --
    def load(self, text):
        tab = self.tabs.get(self.current_webview())
        debug_sink = tab.resolver_trace if tab else None
        target = normalize_url(text, debug_sink=debug_sink)
        self.current_webview().load_uri(target)

    def on_go(self, widget):
        self.event_bus.emit("navigation", url=self.address_bar.get_text())
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

    def on_load_changed(self, webview, load_event):
        tab = self.tabs.get(webview)
        if not tab:
            return
        if load_event == WebKit2.LoadEvent.STARTED:
            tab.load_started_at = time.time()
        elif load_event == WebKit2.LoadEvent.FINISHED:
            if tab.load_started_at is not None:
                tab.last_load_ms = (time.time() - tab.load_started_at) * 1000
                tab.load_started_at = None
            tab.tor_retry_count = 0  # a clean finish resets the retry counter
            self.event_bus.emit(
                "page_loaded",
                url=self.display_uri(webview.get_uri() or ""),
                load_ms=round(tab.last_load_ms, 1) if tab.last_load_ms else 0,
            )

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
            tab = self.tabs.get(webview)
            debug_sink = tab.resolver_trace if tab else None
            self.event_bus.emit("navigation", url=uri)
            webview.load_uri(normalize_url(uri, debug_sink=debug_sink))
            return True
        return False

    def on_resource_load_started(self, webview, resource, request):
        uri = request.get_uri()
        self.event_bus.emit("request_started", url=uri)
        resource.connect("finished", lambda r: self.event_bus.emit("request_finished", url=uri))

    def on_permission_request(self, webview, request):
        """Camera/mic/location/etc: ask instead of silently denying,
        so sites that legitimately need it (video calls, maps) work
        when the person says yes - still denied by default if they
        don't respond to the dialog."""
        origin = webview.get_uri() or "this site"
        kind = type(request).__name__.replace("WebKit2.", "")
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f"Allow {kind} for\n{self.display_uri(origin)}?",
        )
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            request.allow()
        else:
            request.deny()
        return True

    def on_tls_error(self, webview, failing_uri, certificate, errors):
        netloc = urlsplit(failing_uri).netloc
        host = netloc.split(":")[0]
        tab = self.tabs.get(webview)
        is_thrity_host = netloc in THRITY_HOSTS
        is_onion = host.endswith(".onion")
        if is_thrity_host or (is_onion and tab and tab.tor_enabled):
            # Self-signed/invalid cert from a .thrity host we reached
            # via our own resolver, or from a .onion service reached
            # over Tor - in both cases the ADDRESS itself (not a CA)
            # is what authenticates the destination, the same
            # trust-on-first-use model SSH uses for host keys. A
            # random clearnet site with a bad cert still gets
            # WebKit's normal warning page below.
            self.tabs[webview].context.allow_tls_certificate_for_host(certificate, host)
            webview.load_uri(failing_uri)
            return True
        return False  # not a .thrity/.onion host: let WebKit show its normal cert-error page

    def on_load_failed(self, webview, load_event, failing_uri, error):
        """Two independent reasons a load can fail and deserve a
        retry instead of just giving up:
          1. A .thrity page whose cached ip:port went stale (site
             moved, registry heartbeat lagged) - re-resolve fresh.
          2. Any page on a Tor-anonymized tab, where "Internal SOCKSv5
             proxy server error" and similar circuit failures are
             common and often gone on the very next attempt."""
        tab = self.tabs.get(webview)
        netloc = urlsplit(failing_uri).netloc
        thrity_name = THRITY_HOSTS.get(netloc)

        if thrity_name and not (tab and tab.retried_uri == failing_uri):
            forget(thrity_name)
            if tab:
                tab.retried_uri = failing_uri
            debug_sink = tab.resolver_trace if tab else None
            webview.load_uri(normalize_url(thrity_name, fresh=True, debug_sink=debug_sink))
            return True

        if tab and tab.tor_enabled and looks_transient_tor_error(error) \
                and tab.tor_retry_count < TOR_RETRY_ATTEMPTS:
            tab.tor_retry_count += 1
            GLib.timeout_add(TOR_RETRY_DELAY_MS, lambda: (webview.load_uri(failing_uri), False)[1])
            return True

        if tab:
            tab.retried_uri = None
            tab.tor_retry_count = 0
        return False  # genuinely failed - let WebKit show its normal error page

    # -- Tor / anonymize (per tab) --
    def on_tor_toggled(self, button):
        if self._syncing_tab:
            return  # this toggle came from switching tabs, not a user click
        webview = self.current_webview()
        tab = self.tabs[webview]
        tab.tor_enabled = button.get_active()
        tab.tor_retry_count = 0
        if tab.tor_enabled:
            # ignore_hosts=[] explicitly (not None) so every request
            # for this tab, .onion or otherwise, actually goes
            # through Tor - an empty exclusion list, not "no proxy
            # config for anything".
            settings = WebKit2.NetworkProxySettings.new(TOR_SOCKS_URI, [])
            tab.context.set_network_proxy_settings(WebKit2.NetworkProxyMode.CUSTOM, settings)
            button.set_label("Anonymize: On (Tor)")
        else:
            tab.context.set_network_proxy_settings(WebKit2.NetworkProxyMode.DEFAULT, None)
            button.set_label("Anonymize: Off")
        self.on_title_changed(webview, None)  # refresh the [Tor] tab-label prefix
        webview.reload()

    # -- directory --
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

    # -- DevTools --
    def on_open_inspector(self, widget):
        """Opens WebKit's own built-in Web Inspector for the current
        tab - HTML element inspector, CSS, JS console, network
        waterfall, and storage/cookie viewer, all provided by WebKit2GTK
        itself now that developer extras are enabled (see
        harden_settings)."""
        webview = self.current_webview()
        inspector = webview.get_inspector()
        inspector.show()

    def open_devtools(self):
        webview = self.current_webview()
        tab = self.tabs.get(webview)
        if not tab:
            return
        self.devtools.ensure_extension_panels(self.extension_manager)
        self.devtools.refresh_resolver(tab.resolver_trace)
        self.devtools.refresh_timing(
            {"last full page load": tab.last_load_ms} if tab.last_load_ms else {})
        security_info = {
            **self.host.get_thrity_info(),
            "tls_trust": "trust-on-first-use (.thrity / .onion only)",
            "storage": "ephemeral, per-tab, wiped on close",
        }
        self.devtools.refresh_security(security_info)
        self.devtools.refresh_storage({
            "html5_local_storage": "on (ephemeral)",
            "html5_database": "on (ephemeral)",
            "cookies": "isolated to this tab, wiped on close",
        })
        self.devtools.refresh_extensions(self.extension_manager)
        for ext_id, loaded in self.extension_manager.extensions.items():
            for panel in loaded.manifest.devtool_panels:
                self.extension_manager.open_panel(ext_id, panel["id"], kind="devtool_panel")
        self.devtools.show_all()
        self.devtools.present()


if __name__ == "__main__":
    win = ThirtyWeb()
    win.show_all()
    Gtk.main()
