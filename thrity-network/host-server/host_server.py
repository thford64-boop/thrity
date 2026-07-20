#!/usr/bin/env python3
"""
Thrity Network Host Server
----------------------------
Serves ONE .thrity website (a plain folder of HTML/CSS/images) and
keeps it registered with a Thrity registry server so browsers can
find it.

Deliberately static-file-only: no server-side scripting, no databases.
That's a security choice - it means there's no code for a visitor to
exploit, just files being served.

USAGE (plain HTTP, default):
    python3 host_server.py --name home.thrity --folder ../examples/home.thrity \
        --port 8080 --registry http://REGISTRY_IP:9090 --secret mysecretword

USAGE (HTTPS, self-signed - see the --https note below):
    python3 host_server.py --name home.thrity --folder ../examples/home.thrity \
        --port 8443 --https --registry http://REGISTRY_IP:9090 --secret mysecretword

--https note: real (CA-signed) certificates don't exist for made-up
TLDs like .thrity - no certificate authority will issue one, because
.thrity isn't part of real DNS. This generates a SELF-SIGNED
certificate instead (via openssl, cached in ~/.thrity/certs/ so it's
only generated once). That still gives real encryption on the wire,
just without a third party vouching for who you are - 30web trusts
these automatically for .thrity sites specifically (not for regular
HTTPS sites), the same trust-on-first-use model SSH uses for host keys.
"""

import argparse
import gzip
import http.server
import functools
import io
import json
import os
import re
import ssl
import subprocess
import threading
import time
import urllib.request
import socket

CERT_DIR = os.path.expanduser("~/.thrity/certs")

# Same validation the resolver/registry use - keeps a typo'd or
# malicious --name from ever reaching the registry at all.
NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*\.thrity$")

# File types worth gzip-compressing on the wire - text formats
# compress well; images/fonts are already compressed and skipped.
COMPRESSIBLE_TYPES = ("text/", "application/javascript", "application/json", "image/svg+xml")

# How long browsers may cache a file before re-checking, in seconds.
# Short-ish since these are hobby sites that might change often, but
# long enough to avoid re-fetching every asset on every click within
# one visit.
CACHE_SECONDS = 300

VERBOSE = False  # set by --verbose, logs method/path/status/timing for every request

# Shared, read-only-from-outside state the /thrity-info debug
# endpoint reports on - what DevTools' "Server timing" and "Security"
# panels actually query when you're looking at a .thrity site.
SERVER_STATE = {
    "name": None,
    "https": False,
    "started_at": None,
    "requests_served": 0,
}


def get_local_ip():
    """Best-effort guess at this machine's LAN IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def ensure_self_signed_cert(name):
    """Returns (certfile, keyfile), generating a self-signed cert for
    this site name the first time it's needed, reusing it after that."""
    os.makedirs(CERT_DIR, exist_ok=True)
    certfile = os.path.join(CERT_DIR, f"{name}.crt")
    keyfile = os.path.join(CERT_DIR, f"{name}.key")
    if os.path.exists(certfile) and os.path.exists(keyfile):
        return certfile, keyfile

    print(f"[host] Generating a self-signed certificate for {name} (first run only)...")
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", keyfile, "-out", certfile,
            "-days", "3650", "-nodes",
            "-subj", f"/CN={name}",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return certfile, keyfile


def register_with_registry(registry_url, name, ip, port, secret, https):
    payload = json.dumps({
        "name": name, "ip": ip, "port": port, "secret": secret, "https": https,
    }).encode()
    req = urllib.request.Request(
        f"{registry_url}/register",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read())
            print(f"[host] registered '{name}' -> {ip}:{port} ({result.get('status')})")
    except Exception as e:
        print(f"[host] WARNING: could not reach registry ({e}). Site is still served locally.")


def heartbeat_loop(registry_url, name, ip, port, secret, https, interval=600):
    while True:
        register_with_registry(registry_url, name, ip, port, secret, https)
        time.sleep(interval)


class FastSafeHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler, with these differences:
      - no auto-generated folder listing (visitors get a clean 404
        instead of a raw directory dump when there's no index.html)
      - gzip-compresses text responses when the browser supports it
        (nearly every browser does) - meaningfully faster over slow
        links, especially for anything Tor-anonymized
      - adds Cache-Control so repeat visits within one browsing
        session don't re-fetch unchanged files
      - a small /thrity-info JSON debug endpoint (name, https,
        uptime, requests served) that 30web's DevTools Security/
        Timing panels query directly, and structured per-request
        logging when --verbose is set
    """
    def log_message(self, fmt, *args):
        if VERBOSE:
            print(f"[host] {self.client_address[0]} " + (fmt % args))

    def list_directory(self, path):
        self.send_error(404, "File not found")
        return None

    def do_GET(self):
        if self.path == "/thrity-info":
            self._send_info()
            return
        super().do_GET()

    def _send_info(self):
        uptime = time.time() - SERVER_STATE["started_at"] if SERVER_STATE["started_at"] else 0
        body = json.dumps({
            "name": SERVER_STATE["name"],
            "https": SERVER_STATE["https"],
            "uptime_s": round(uptime, 1),
            "requests_served": SERVER_STATE["requests_served"],
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")  # this endpoint should never be stale
        self.end_headers()
        self.wfile.write(body)

    def send_head(self):
        start = time.time()
        path = self.translate_path(self.path)
        SERVER_STATE["requests_served"] += 1
        if os.path.isdir(path):
            result = super().send_head()
            if VERBOSE:
                print(f"[host] GET {self.path} -> dir ({(time.time() - start) * 1000:.1f}ms)")
            return result

        accepts_gzip = "gzip" in self.headers.get("Accept-Encoding", "")
        ctype = self.guess_type(path)
        should_gzip = accepts_gzip and ctype.startswith(COMPRESSIBLE_TYPES)

        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError:
            self.send_error(404, "File not found")
            if VERBOSE:
                print(f"[host] GET {self.path} -> 404 ({(time.time() - start) * 1000:.1f}ms)")
            return None

        if should_gzip:
            buf = io.BytesIO()
            with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as gz:
                gz.write(raw)
            body = buf.getvalue()
        else:
            body = raw

        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", f"public, max-age={CACHE_SECONDS}")
        if should_gzip:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        if VERBOSE:
            gz_note = " gzip" if should_gzip else ""
            print(f"[host] GET {self.path} -> 200{gz_note} ({(time.time() - start) * 1000:.1f}ms, {len(body)}b)")
        return io.BytesIO(body)


def main():
    parser = argparse.ArgumentParser(description="Host a .thrity site")
    parser.add_argument("--name", required=True, help="site name, e.g. home.thrity")
    parser.add_argument("--folder", required=True, help="folder of HTML files to serve")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--ip", default=None, help="public/LAN IP to advertise (auto-detected if omitted)")
    parser.add_argument("--registry", default=None, help="e.g. http://192.168.1.10:9090")
    parser.add_argument("--secret", default=None, help="secret word that owns this name in the registry")
    parser.add_argument("--https", action="store_true", help="serve over HTTPS with a self-signed cert")
    parser.add_argument("--verbose", action="store_true", help="log method/path/status/timing for every request")
    args = parser.parse_args()

    global VERBOSE
    VERBOSE = args.verbose

    name = args.name.lower().strip()
    if not NAME_RE.match(name):
        raise SystemExit("Site name must be a valid .thrity name (letters/digits/hyphens, e.g. home.thrity)")

    if not os.path.isdir(args.folder):
        raise SystemExit(f"--folder '{args.folder}' doesn't exist or isn't a directory")

    SERVER_STATE["name"] = name
    SERVER_STATE["https"] = args.https
    SERVER_STATE["started_at"] = time.time()

    ip = args.ip or get_local_ip()

    if args.registry:
        if not args.secret:
            raise SystemExit("--secret is required when using --registry")
        register_with_registry(args.registry, name, ip, args.port, args.secret, args.https)
        t = threading.Thread(
            target=heartbeat_loop,
            args=(args.registry, name, ip, args.port, args.secret, args.https),
            daemon=True,
        )
        t.start()

    handler = functools.partial(FastSafeHandler, directory=args.folder)
    server = http.server.ThreadingHTTPServer(("0.0.0.0", args.port), handler)

    scheme = "http"
    if args.https:
        certfile, keyfile = ensure_self_signed_cert(name)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=certfile, keyfile=keyfile)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        scheme = "https"

    print(f"[host] Serving '{name}' from {args.folder} on {scheme}://{ip}:{args.port}")
    if not args.registry:
        print(f"[host] Add this to ~/.thrity/hosts.json on any PC that should find it:")
        print(f'       "{name}": {{"ip": "{ip}", "port": {args.port}, "https": {str(args.https).lower()}}}')
    print("[host] Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[host] Stopped.")


if __name__ == "__main__":
    main()
