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

USAGE:
    python3 host_server.py --name home.thrity --folder ../examples/home.thrity \
        --port 8080 --registry http://REGISTRY_IP:9090 --secret mysecretword

If you don't have a registry server yet, you can still run this to
test locally - just skip --registry and open http://localhost:8080
directly in your browser.
"""

import argparse
import http.server
import functools
import json
import threading
import time
import urllib.request
import socket


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


def register_with_registry(registry_url, name, ip, port, secret):
    payload = json.dumps({"name": name, "ip": ip, "port": port, "secret": secret}).encode()
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


def heartbeat_loop(registry_url, name, ip, port, secret, interval=600):
    while True:
        register_with_registry(registry_url, name, ip, port, secret)
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="Host a .thrity site")
    parser.add_argument("--name", required=True, help="site name, e.g. home.thrity")
    parser.add_argument("--folder", required=True, help="folder of HTML files to serve")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--ip", default=None, help="public/LAN IP to advertise (auto-detected if omitted)")
    parser.add_argument("--registry", default=None, help="e.g. http://192.168.1.10:9090")
    parser.add_argument("--secret", default=None, help="secret word that owns this name in the registry")
    args = parser.parse_args()

    if not args.name.endswith(".thrity"):
        raise SystemExit("Site name must end in .thrity")

    ip = args.ip or get_local_ip()

    if args.registry:
        if not args.secret:
            raise SystemExit("--secret is required when using --registry")
        register_with_registry(args.registry, args.name, ip, args.port, args.secret)
        t = threading.Thread(
            target=heartbeat_loop,
            args=(args.registry, args.name, ip, args.port, args.secret),
            daemon=True,
        )
        t.start()

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=args.folder)
    server = http.server.ThreadingHTTPServer(("0.0.0.0", args.port), handler)
    print(f"[host] Serving '{args.name}' from {args.folder} on http://{ip}:{args.port}")
    print("[host] Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[host] Stopped.")


if __name__ == "__main__":
    main()
