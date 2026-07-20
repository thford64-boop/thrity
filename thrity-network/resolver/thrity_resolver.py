#!/usr/bin/env python3
"""
Thrity Resolver
------------------
Given a name like "home.thrity", figures out which ip:port serves it.

Lookup order:
  1. In-memory cache of recent answers (see CACHE_TTL below) - makes
     clicking around a site you're already on instant, and means a
     registry hiccup mid-session doesn't re-break pages you already
     resolved.
  2. Local overrides file (~/.thrity/hosts.json) - like a personal
     /etc/hosts file. Great for LAN-only sites or testing without any
     registry server at all.
  3. Registry server(s) listed in ~/.thrity/config.json. All
     configured registries are queried AT THE SAME TIME (not one
     after another) and the fastest valid answer wins - this is what
     used to make sites "not work": a single slow or offline registry
     listed first would eat its whole timeout before the next one was
     even tried.

This file has no dependencies outside the Python standard library.
"""

import json
import os
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

CONFIG_DIR = os.path.expanduser("~/.thrity")
HOSTS_FILE = os.path.join(CONFIG_DIR, "hosts.json")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    # Add one or more registry servers here. All of them are queried
    # in parallel and the fastest valid answer wins.
    "registries": []
}

# A valid .thrity name: letters, digits, and hyphens, dot-separated
# labels, ending in .thrity. Rejects anything with slashes, spaces,
# or other characters that have no business in a hostname - this is
# what stops a malformed or hostile name from being used to do
# path-tricks against the local overrides file or getting echoed
# somewhere unsafe later on.
NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*\.thrity$")

# How long a resolved name is trusted before being looked up again.
# Short enough that a site moving to a new ip:port is picked up
# quickly, long enough that browsing around a site doesn't re-hit the
# network on every single click.
CACHE_TTL = 120  # seconds
_cache = {}  # name -> (ip, port, https, expires_at)

REGISTRY_TIMEOUT = 3  # seconds, per registry


def ensure_config():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(HOSTS_FILE):
        with open(HOSTS_FILE, "w") as f:
            json.dump({}, f, indent=2)
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)


def load_json(path):
    with open(path) as f:
        return json.load(f)


def is_valid_name(name: str) -> bool:
    return bool(NAME_RE.match(name))


def _query_registry(registry_url, name):
    url = f"{registry_url}/lookup?name={name}"
    with urllib.request.urlopen(url, timeout=REGISTRY_TIMEOUT) as resp:
        data = json.loads(resp.read())
        return data["ip"], data["port"], bool(data.get("https", False))


def resolve(name: str, use_cache: bool = True):
    """
    Returns (ip, port, https) for a .thrity name, or None if not found
    or the name is malformed. 'https' is True only if the host
    advertised itself as HTTPS-capable (self-signed cert - see
    host_server.py --https).
    """
    result, _trace = resolve_with_debug(name, use_cache=use_cache)
    return result


def resolve_with_debug(name: str, use_cache: bool = True):
    """
    Same as resolve(), but also returns a trace of every step tried
    and how long it took - this is what powers the DevTools
    "Resolver" panel and `thrity_resolver.py --debug`. Each trace
    entry is a dict: {"source", "result", "ms"}.
    """
    trace = []
    ensure_config()
    name = name.lower().strip()

    if not is_valid_name(name):
        trace.append({"source": "validate", "result": "invalid name", "ms": 0.0})
        return None, trace

    # 1. Cache
    if use_cache:
        t0 = time.time()
        cached = _cache.get(name)
        hit = cached and cached[3] > time.time()
        trace.append({"source": "cache", "result": "hit" if hit else "miss", "ms": (time.time() - t0) * 1000})
        if hit:
            return (cached[0], cached[1], cached[2]), trace

    # 2. Local overrides (personal hosts file) - always wins, never
    #    goes stale since it's already instant and local.
    t0 = time.time()
    hosts = load_json(HOSTS_FILE)
    if name in hosts:
        entry = hosts[name]
        trace.append({"source": "hosts.json", "result": f"{entry['ip']}:{entry['port']}", "ms": (time.time() - t0) * 1000})
        return (entry["ip"], entry["port"], bool(entry.get("https", False))), trace
    trace.append({"source": "hosts.json", "result": "not found", "ms": (time.time() - t0) * 1000})

    # 3. Ask every configured registry server AT ONCE, use whichever
    #    answers first instead of waiting on each in turn.
    config = load_json(CONFIG_FILE)
    registries = config.get("registries", [])
    if not registries:
        trace.append({"source": "registries", "result": "none configured", "ms": 0.0})
        return None, trace

    result = None
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max(1, len(registries))) as pool:
        futures = {pool.submit(_query_registry, r, name): r for r in registries}
        for future in as_completed(futures, timeout=REGISTRY_TIMEOUT + 1):
            registry_url = futures[future]
            try:
                result = future.result()
                trace.append({"source": registry_url, "result": f"{result[0]}:{result[1]}", "ms": (time.time() - t0) * 1000})
                break
            except Exception as e:
                trace.append({"source": registry_url, "result": f"failed: {e}", "ms": (time.time() - t0) * 1000})
                continue

    if result:
        _cache[name] = (result[0], result[1], result[2], time.time() + CACHE_TTL)
    else:
        trace.append({"source": "registries", "result": "no registry had this name", "ms": (time.time() - t0) * 1000})
    return result, trace


def forget(name: str):
    """Drops a name from the cache - used after a failed connection so
    the next attempt re-resolves instead of retrying a dead address
    for up to CACHE_TTL seconds."""
    _cache.pop(name.lower().strip(), None)


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if a != "--debug"]
    debug = "--debug" in sys.argv
    if len(args) != 1:
        print("Usage: python3 thrity_resolver.py [--debug] <name.thrity>")
        raise SystemExit(1)
    result, trace = resolve_with_debug(args[0])
    if debug:
        for step in trace:
            print(f"  [{step['source']}] {step['result']} ({step['ms']:.1f}ms)")
    print(result if result else "Not found")
