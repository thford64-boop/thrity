#!/usr/bin/env python3
"""
The interface ExtensionAPI calls into. 30web.py implements a real
one (BrowserHost, wired to GTK/WebKit); this file also provides
DummyHost, a headless stand-in that makes it possible to load-test
and validate extensions from the command line without a display or
WebKit2GTK installed at all - see extensions/cli.py.
"""


class Host:
    """Interface only - subclass and implement every method."""

    def log(self, ext_id, message):
        raise NotImplementedError

    def notify(self, ext_id, message):
        raise NotImplementedError

    def set_title_suffix(self, ext_id, suffix):
        raise NotImplementedError

    def show_panel(self, ext_id, panel_id):
        raise NotImplementedError

    def set_panel_text(self, ext_id, panel_id, text):
        raise NotImplementedError

    def get_thrity_info(self):
        """Returns a plain dict describing the current tab's .thrity
        site (or clearnet site) - name, ip/port, https, resolve_ms."""
        raise NotImplementedError

    def inject_page_script(self, ext_id, script_path):
        raise NotImplementedError

    def is_allowed_thrity_url(self, url):
        raise NotImplementedError

    def get_registries(self):
        """Returns a list of configured registry URL strings."""
        raise NotImplementedError


class DummyHost(Host):
    """Records everything instead of touching a real browser. Used by
    `python3 -m extensions.cli validate <folder>` and by anyone
    writing/testing an extension before installing it for real."""

    def __init__(self):
        self.log_lines = []
        self.notifications = []
        self.title_suffix = None
        self.panel_events = []
        self.injected_scripts = []

    def log(self, ext_id, message):
        line = f"[{ext_id}] {message}"
        self.log_lines.append(line)
        print(line)

    def notify(self, ext_id, message):
        self.notifications.append((ext_id, message))
        print(f"[{ext_id}] NOTIFY: {message}")

    def set_title_suffix(self, ext_id, suffix):
        self.title_suffix = suffix
        print(f"[{ext_id}] title suffix -> {suffix!r}")

    def show_panel(self, ext_id, panel_id):
        self.panel_events.append(("show", panel_id))
        print(f"[{ext_id}] show_panel({panel_id!r})")

    def set_panel_text(self, ext_id, panel_id, text):
        self.panel_events.append(("set_text", panel_id, text))
        print(f"[{ext_id}] set_panel_text({panel_id!r}, {text!r})")

    def get_thrity_info(self):
        return {"site": "example.thrity", "ip": "127.0.0.1", "port": 8080,
                "https": False, "resolve_ms": 0}

    def inject_page_script(self, ext_id, script_path):
        self.injected_scripts.append(script_path)
        print(f"[{ext_id}] would inject page script: {script_path}")

    def is_allowed_thrity_url(self, url):
        return False  # the dummy host has no real registries/hosts to allow

    def get_registries(self):
        return ["http://192.168.1.10:9090"]  # fake, for offline testing/validation only
