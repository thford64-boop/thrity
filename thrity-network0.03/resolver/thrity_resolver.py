#!/usr/bin/env python3
"""
Thrity Resolver
------------------
Given a name like "home.thrity", figures out which ip:port serves it.

Lookup order:
  1. Local overrides file (~/.thrity/hosts.json) - like a personal
     /etc/hosts file. Great for LAN-only sites or testing without any
     registry server at all.
  2. Registry server(s) listed in ~/.thrity/config.json.

This file has no dependencies outside the Python standard library.
"""

import json
import os
import urllib.request

CONFIG_DIR = os.path.expanduser("~/.thrity")
HOSTS_FILE = os.path.join(CONFIG_DIR, "hosts.json")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    # Add one or more registry servers here. The first one that answers
    # is used. Anyone running registry_server.py can be added.
    "registries": []
}


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


def resolve(name: str):
    """
    Returns (ip, port, https) for a .thrity name, or None if not found.
    'https' is True only if the host advertised itself as HTTPS-capable
    (self-signed cert - see host_server.py --https).
    """
    ensure_config()
    name = name.lower().strip()
    if not name.endswith(".thrity"):
        return None

    # 1. Local overrides (personal hosts file)
    hosts = load_json(HOSTS_FILE)
    if name in hosts:
        entry = hosts[name]
        return entry["ip"], entry["port"], bool(entry.get("https", False))

    # 2. Ask each configured registry server until one answers
    config = load_json(CONFIG_FILE)
    for registry_url in config.get("registries", []):
        try:
            url = f"{registry_url}/lookup?name={name}"
            with urllib.request.urlopen(url, timeout=3) as resp:
                data = json.loads(resp.read())
                return data["ip"], data["port"], bool(data.get("https", False))
        except Exception:
            continue  # try the next registry

    return None


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python3 thrity_resolver.py <name.thrity>")
        raise SystemExit(1)
    result = resolve(sys.argv[1])
    print(result if result else "Not found")
