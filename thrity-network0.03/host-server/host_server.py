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
import http.server
import functools
import json
import os
import ssl
import subprocess
import threading
import time
import urllib.request
import socket

CERT_DIR = os.path.expanduser("~/.thrity/certs")


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


class NoListingHandler(http.server.SimpleHTTPRequestHandler):
    """Same as SimpleHTTPRequestHandler, but refuses to show an
    auto-generated file listing when a folder has no index.html -
    visitors get a clean 404 instead of a raw directory dump."""
    def list_directory(self, path):
        self.send_error(404, "File not found")
        return None


def main():
    parser = argparse.ArgumentParser(description="Host a .thrity site")
    parser.add_argument("--name", required=True, help="site name, e.g. home.thrity")
    parser.add_argument("--folder", required=True, help="folder of HTML files to serve")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--ip", default=None, help="public/LAN IP to advertise (auto-detected if omitted)")
    parser.add_argument("--registry", default=None, help="e.g. http://192.168.1.10:9090")
    parser.add_argument("--secret", default=None, help="secret word that owns this name in the registry")
    parser.add_argument("--https", action="store_true", help="serve over HTTPS with a self-signed cert")
    args = parser.parse_args()

    if not args.name.endswith(".thrity"):
        raise SystemExit("Site name must end in .thrity")

    ip = args.ip or get_local_ip()

    if args.registry:
        if not args.secret:
            raise SystemExit("--secret is required when using --registry")
        register_with_registry(args.registry, args.name, ip, args.port, args.secret, args.https)
        t = threading.Thread(
            target=heartbeat_loop,
            args=(args.registry, args.name, ip, args.port, args.secret, args.https),
            daemon=True,
        )
        t.start()

    handler = functools.partial(NoListingHandler, directory=args.folder)
    server = http.server.ThreadingHTTPServer(("0.0.0.0", args.port), handler)

    scheme = "http"
    if args.https:
        certfile, keyfile = ensure_self_signed_cert(args.name)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=certfile, keyfile=keyfile)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        scheme = "https"

    print(f"[host] Serving '{args.name}' from {args.folder} on {scheme}://{ip}:{args.port}")
    if not args.registry:
        print(f"[host] Add this to ~/.thrity/hosts.json on any PC that should find it:")
        print(f'       "{args.name}": {{"ip": "{ip}", "port": {args.port}, "https": {str(args.https).lower()}}}')
    print("[host] Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[host] Stopped.")


if __name__ == "__main__":
    main()
