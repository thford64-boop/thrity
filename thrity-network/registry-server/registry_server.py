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

USAGE (plain HTTP, default):
    python3 registry_server.py

USAGE (HTTPS, self-signed):
    python3 registry_server.py --https
    (30web/host_server don't verify this cert against a CA - there
    isn't one for a made-up TLD - but it still encrypts the --secret
    on the wire, instead of sending it in plain text as before.)

SECURITY NOTE (read this):
Each name is protected by a "secret" the owner chooses on first
registration. To update or delete that name later, you must supply
the same secret. This stops random people from hijacking a name
someone else already claimed. It is NOT strong security - good
enough for a hobby network among people who trust each other, not
for anything sensitive. Run with --https to at least keep the
secret from being visible to anyone else on the same network.
"""

import argparse
import json
import os
import ssl
import subprocess
import time
import hashlib
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

REGISTRY_FILE = os.path.join(os.path.dirname(__file__), "registry.json")
CERT_DIR = os.path.expanduser("~/.thrity/certs")
PORT = 9090  # the door this registry server listens on

# Must match the resolver's/host server's validation, so a name that
# passes here is guaranteed safe to hand back to a browser later.
NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*\.thrity$")

# How long a site can go without "checking in" before we consider it
# stale and drop it from lookups (in seconds). 24 hours here.
STALE_AFTER = 24 * 60 * 60

# Basic anti-abuse: cap how many registrations one IP can make per
# hour, so a script can't rapid-fire claim every name it can think of.
RATE_LIMIT_WINDOW = 60 * 60
RATE_LIMIT_MAX = 20
_registration_log = {}  # ip -> [timestamps]

# Separate, looser limit on lookups - legitimate browsing does a
# lookup per site visited, but this stops the /lookup endpoint being
# hammered as a denial-of-service vector or used to scrape the whole
# namespace by brute-forcing names quickly.
LOOKUP_LIMIT_WINDOW = 60
LOOKUP_LIMIT_MAX = 120
_lookup_log = {}  # ip -> [timestamps]

# Guards both the registry file and the two rate-limit logs above,
# since ThreadingHTTPServer handles requests concurrently - without
# this, two registrations landing at the same instant could silently
# clobber each other on the read-modify-write to registry.json.
_lock = threading.Lock()


def check_rate_limit(log, ip, window, max_count):
    with _lock:
        now = time.time()
        timestamps = log.setdefault(ip, [])
        timestamps[:] = [t for t in timestamps if now - t < window]
        if len(timestamps) >= max_count:
            return False
        timestamps.append(now)
        return True


def load_registry():
    if not os.path.exists(REGISTRY_FILE):
        return {}
    with open(REGISTRY_FILE, "r") as f:
        return json.load(f)


def save_registry(data):
    tmp = REGISTRY_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, REGISTRY_FILE)  # atomic on POSIX - no half-written file if we crash mid-write


def hash_secret(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def ensure_self_signed_cert():
    os.makedirs(CERT_DIR, exist_ok=True)
    certfile = os.path.join(CERT_DIR, "registry.crt")
    keyfile = os.path.join(CERT_DIR, "registry.key")
    if os.path.exists(certfile) and os.path.exists(keyfile):
        return certfile, keyfile
    print("[registry] Generating a self-signed certificate (first run only)...")
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", keyfile, "-out", certfile,
            "-days", "3650", "-nodes", "-subj", "/CN=thrity-registry",
        ],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return certfile, keyfile


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

        if parsed.path == "/lookup":
            if not check_rate_limit(_lookup_log, self.client_address[0],
                                     LOOKUP_LIMIT_WINDOW, LOOKUP_LIMIT_MAX):
                self._send_json(429, {"error": "rate limit exceeded, try again shortly"})
                return
            name = qs.get("name", [""])[0].lower().strip()
            if not NAME_RE.match(name):
                self._send_json(400, {"error": "invalid name"})
                return
            data = load_registry()
            entry = data.get(name)
            if not entry:
                self._send_json(404, {"error": "not found"})
                return
            if time.time() - entry["last_seen"] > STALE_AFTER:
                self._send_json(404, {"error": "stale, not found"})
                return
            self._send_json(200, {
                "name": name, "ip": entry["ip"], "port": entry["port"],
                "https": entry.get("https", False),
            })
            return

        if parsed.path == "/list":
            # A basic public directory of all live sites, handy for a
            # "browse the network" homepage in 30web.
            data = load_registry()
            now = time.time()
            live = {
                name: {"ip": e["ip"], "port": e["port"], "https": e.get("https", False)}
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

        if not check_rate_limit(_registration_log, self.client_address[0],
                                 RATE_LIMIT_WINDOW, RATE_LIMIT_MAX):
            self._send_json(429, {"error": "rate limit exceeded, try again later"})
            return

        length = int(self.headers.get("Content-Length", 0))
        if length > 4096:  # a registration payload is tiny - reject anything absurd up front
            self._send_json(400, {"error": "request too large"})
            return
        try:
            body = json.loads(self.rfile.read(length))
            name = body["name"].lower().strip()
            ip = body["ip"].strip()
            port = int(body["port"])
            secret = body["secret"]
            https = bool(body.get("https", False))
        except (KeyError, ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "bad request, need name, ip, port, secret"})
            return

        if not NAME_RE.match(name):
            self._send_json(400, {"error": "invalid name"})
            return
        if not (0 < port < 65536):
            self._send_json(400, {"error": "invalid port"})
            return
        if not secret:
            self._send_json(400, {"error": "secret must not be empty"})
            return

        with _lock:
            data = load_registry()
            existing = data.get(name)
            secret_hash = hash_secret(secret)

            if existing and existing["secret_hash"] != secret_hash:
                self._send_json(403, {"error": "name already claimed with a different secret"})
                return

            data[name] = {
                "ip": ip,
                "port": port,
                "https": https,
                "secret_hash": secret_hash,
                "last_seen": time.time(),
            }
            save_registry(data)
        self._send_json(200, {"status": "registered", "name": name})


def main():
    parser = argparse.ArgumentParser(description="Thrity Network registry server")
    parser.add_argument("--https", action="store_true",
                         help="serve over HTTPS with a self-signed cert (encrypts secrets in transit)")
    args = parser.parse_args()

    print(f"Thrity Registry Server starting on port {PORT}")
    print(f"Registry file: {REGISTRY_FILE}")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)

    if args.https:
        certfile, keyfile = ensure_self_signed_cert()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=certfile, keyfile=keyfile)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        print("[registry] Serving over HTTPS (self-signed)")

    server.serve_forever()


if __name__ == "__main__":
    main()
