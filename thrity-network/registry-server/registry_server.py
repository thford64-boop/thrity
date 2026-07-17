#!/usr/bin/env python3
"""
Thrity Network Registry Server
--------------------------------
This is the free, open-source "phone book" for the Thrity Network.
Anyone can run this. It keeps a list of:

    site name (must end in .thrity)  ->  ip:port of the machine hosting it

Sites REGISTER themselves here (POST /register).
Browsers (30web) LOOK sites up here (GET /lookup?name=...).

Storage is a single JSON file (registry.json) next to this script.
No database software needed. No paid hosting needed - this can run
on your own PC, a Raspberry Pi, or any free-tier server you like.

SECURITY NOTE (read this):
Each name is protected by a "secret" the owner chooses on first
registration. To update or delete that name later, you must supply
the same secret. This stops random people from hijacking a name
someone else already claimed. It is NOT strong security (no HTTPS
here by default) - good enough for a hobby network among people who
trust each other, not for anything sensitive.
"""

import json
import os
import time
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

REGISTRY_FILE = os.path.join(os.path.dirname(__file__), "registry.json")
PORT = 9090  # the door this registry server listens on

# How long a site can go without "checking in" before we consider it
# stale and drop it from lookups (in seconds). 24 hours here.
STALE_AFTER = 24 * 60 * 60


def load_registry():
    if not os.path.exists(REGISTRY_FILE):
        return {}
    with open(REGISTRY_FILE, "r") as f:
        return json.load(f)


def save_registry(data):
    with open(REGISTRY_FILE, "w") as f:
        json.dump(data, f, indent=2)


def hash_secret(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Keep logs simple and quiet instead of the default noisy format
        print("[registry] " + (fmt % args))

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        data = load_registry()

        if parsed.path == "/lookup":
            name = qs.get("name", [""])[0].lower().strip()
            entry = data.get(name)
            if not entry:
                self._send_json(404, {"error": "not found"})
                return
            if time.time() - entry["last_seen"] > STALE_AFTER:
                self._send_json(404, {"error": "stale, not found"})
                return
            self._send_json(200, {"name": name, "ip": entry["ip"], "port": entry["port"]})
            return

        if parsed.path == "/list":
            # A basic public directory of all live sites, handy for a
            # "browse the network" homepage in 30web.
            now = time.time()
            live = {
                name: {"ip": e["ip"], "port": e["port"]}
                for name, e in data.items()
                if now - e["last_seen"] <= STALE_AFTER
            }
            self._send_json(200, {"sites": live})
            return

        self._send_json(404, {"error": "unknown endpoint"})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/register":
            self._send_json(404, {"error": "unknown endpoint"})
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
            name = body["name"].lower().strip()
            ip = body["ip"].strip()
            port = int(body["port"])
            secret = body["secret"]
        except (KeyError, ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "bad request, need name, ip, port, secret"})
            return

        if not name.endswith(".thrity"):
            self._send_json(400, {"error": "name must end in .thrity"})
            return

        data = load_registry()
        existing = data.get(name)
        secret_hash = hash_secret(secret)

        if existing and existing["secret_hash"] != secret_hash:
            self._send_json(403, {"error": "name already claimed with a different secret"})
            return

        data[name] = {
            "ip": ip,
            "port": port,
            "secret_hash": secret_hash,
            "last_seen": time.time(),
        }
        save_registry(data)
        self._send_json(200, {"status": "registered", "name": name})


if __name__ == "__main__":
    print(f"Thrity Registry Server starting on port {PORT}")
    print(f"Registry file: {REGISTRY_FILE}")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()
