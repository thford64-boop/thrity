#!/usr/bin/env python3
"""
Unit tests for the Thrity Extension DSL: parser, manifest builder,
and interpreter (including permission enforcement). Run with:

    python3 -m unittest discover -s extensions/tests -v

from inside browser/, or as part of a CI job.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from extensions import dsl_parser, dsl_manifest, dsl_interpreter
from extensions.dsl_parser import DSLSyntaxError
from extensions.dsl_manifest import ManifestError
from extensions.api import ExtensionAPI, PermissionError_
from extensions.host import DummyHost


def build(source, ext_dir="/tmp/test-ext"):
    ast = dsl_parser.parse(source)
    return dsl_manifest.build_manifest(ast, ext_dir)


class TestParser(unittest.TestCase):
    def test_minimal_extension_parses(self):
        m = build('extension "X" { id: "x" }')
        self.assertEqual(m.id, "x")
        self.assertEqual(m.name, "X")

    def test_missing_id_is_rejected(self):
        with self.assertRaises(ManifestError):
            build('extension "X" { version: "1.0" }')

    def test_unknown_permission_is_rejected(self):
        with self.assertRaises(ManifestError):
            build('extension "X" { id: "x" permissions { time_travel } }')

    def test_syntax_error_on_missing_brace(self):
        with self.assertRaises(DSLSyntaxError):
            dsl_parser.parse('extension "X" { id: "x"')

    def test_toolbar_button_and_devtool_panel(self):
        m = build('''
            extension "X" {
                id: "x"
                permissions { devtools }
                toolbar_button "btn" {
                    label: "Click me"
                    on_click: show_panel("p")
                }
                devtool_panel "p" {
                    title: "Panel"
                }
            }
        ''')
        self.assertEqual(len(m.toolbar_buttons), 1)
        self.assertEqual(m.toolbar_buttons[0]["label"], "Click me")
        self.assertEqual(m.toolbar_buttons[0]["on_click"]["kind"], "call")
        self.assertEqual(len(m.devtool_panels), 1)

    def test_settings_are_literals(self):
        m = build('extension "X" { id: "x" settings { a: true b: 5 c: "hi" } }')
        self.assertEqual(m.settings, {"a": True, "b": 5, "c": "hi"})

    def test_multiple_on_blocks_for_same_event_merge(self):
        m = build('''
            extension "X" { id: "x"
                on page_loaded { log("one") }
                on page_loaded { log("two") }
            }
        ''')
        self.assertEqual(len(m.handlers["page_loaded"]), 2)


class TestInterpreter(unittest.TestCase):
    def run_handler(self, source, event=None):
        m = build(source)
        host = DummyHost()
        api = ExtensionAPI(m, host)
        dsl_interpreter.run(m.handlers.get("page_loaded", []), m, api, event=event or {})
        return host

    def test_log_and_notify_always_allowed(self):
        host = self.run_handler('''
            extension "X" { id: "x" permissions { }
                on page_loaded { log("hi") notify("there") }
            }
        ''')
        self.assertIn("[x] hi", host.log_lines)
        self.assertEqual(host.notifications, [("x", "there")])

    def test_permission_denied_is_caught_not_raised(self):
        host = self.run_handler('''
            extension "X" { id: "x" permissions { }
                on page_loaded { http_get("http://example.com") }
            }
        ''')
        self.assertTrue(any("PermissionError" in line for line in host.log_lines))

    def test_permission_granted_allows_call(self):
        # DummyHost.is_allowed_thrity_url always returns False, so this
        # still gets denied at the network-scope check, but must NOT be
        # denied at the permission-declaration check - i.e. a different
        # error message than the undeclared-permission case above.
        host = self.run_handler('''
            extension "X" { id: "x" permissions { network }
                on page_loaded { http_get("http://example.com") }
            }
        ''')
        self.assertTrue(any("only allows requests to configured registries" in line
                             for line in host.log_lines))

    def test_if_else_and_field_access(self):
        host = self.run_handler('''
            extension "X" { id: "x" permissions { }
                settings { flag: true }
                on page_loaded {
                    if settings.flag {
                        notify("yes")
                    } else {
                        notify("no")
                    }
                }
            }
        ''', event={"url": "home.thrity"})
        self.assertEqual(host.notifications, [("x", "yes")])

    def test_string_concatenation_with_number(self):
        host = self.run_handler('''
            extension "X" { id: "x" permissions { }
                on page_loaded { notify("loaded in " + event.load_ms + "ms") }
            }
        ''', event={"load_ms": 42})
        self.assertEqual(host.notifications, [("x", "loaded in 42ms")])

    def test_action_call_from_handler(self):
        host = self.run_handler('''
            extension "X" { id: "x" permissions { }
                action say_hi { notify("hi from action") }
                on page_loaded { say_hi() }
            }
        ''')
        self.assertEqual(host.notifications, [("x", "hi from action")])

    def test_storage_requires_permission(self):
        host = self.run_handler('''
            extension "X" { id: "x" permissions { }
                on page_loaded { storage_set("k", "v") }
            }
        ''')
        self.assertTrue(any("PermissionError" in line for line in host.log_lines))

    def test_storage_roundtrip_with_permission(self):
        m = build('''
            extension "X" { id: "x-storage-test" permissions { storage }
                action save { storage_set("k", "v1") }
                action load { let v = storage_get("k") log("got: " + v) }
            }
        ''')
        host = DummyHost()
        api = ExtensionAPI(m, host)
        dsl_interpreter.run(m.actions["save"], m, api)
        dsl_interpreter.run(m.actions["load"], m, api)
        self.assertIn("[x-storage-test] got: v1", host.log_lines)
        # cleanup so repeated test runs don't accumulate files
        api._storage_path() and os.path.exists(api._storage_path()) and os.remove(api._storage_path())

    def test_unknown_function_is_a_caught_runtime_error(self):
        host = self.run_handler('''
            extension "X" { id: "x" permissions { }
                on page_loaded { this_function_does_not_exist() }
            }
        ''')
        self.assertTrue(any("unknown function" in line for line in host.log_lines))


if __name__ == "__main__":
    unittest.main()
