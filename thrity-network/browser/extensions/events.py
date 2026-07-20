#!/usr/bin/env python3
"""
A minimal publish/subscribe event bus. 30web.py emits browser events
here (page_loaded, navigation, tab_created, tab_closed,
request_started, request_finished); the extension loader subscribes
each extension's `on <event> { ... }` handlers.

Deliberately not a general message bus - only the fixed event names
below are meaningful to the DSL and documented in EXTENSION_API.md.
"""

KNOWN_EVENTS = {
    "page_loaded",
    "navigation",
    "tab_created",
    "tab_closed",
    "request_started",
    "request_finished",
}


class EventBus:
    def __init__(self):
        self._subscribers = {name: [] for name in KNOWN_EVENTS}

    def on(self, event_name, callback):
        if event_name not in self._subscribers:
            # unknown event names from a manifest are handlers that
            # will just never fire - don't crash the whole extension
            # over a typo, but keep the list so debugging tools can
            # still show "no such event".
            self._subscribers[event_name] = []
        self._subscribers[event_name].append(callback)

    def emit(self, event_name, **data):
        for callback in self._subscribers.get(event_name, []):
            try:
                callback(data)
            except Exception as e:  # an extension bug should never take down the browser
                print(f"[extensions] error handling '{event_name}': {e}")
