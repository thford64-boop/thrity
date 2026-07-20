# Thrity Server API Reference

Every HTTP endpoint the host server and registry server expose, for
anyone writing tooling (an extension, a script, a status dashboard)
against them.

---

## Host server (`host-server/host_server.py`)

One process serves one `.thrity` site (a static folder). Endpoints:

### `GET /<any file path>`
Serves the requested file from the folder passed to `--folder`.
gzip-compressed when the client sends `Accept-Encoding: gzip` and the
content type is text-like; `Cache-Control: public, max-age=300`.
Folder listings are disabled — a missing `index.html` in a
subdirectory returns a plain 404, never a raw file listing.

### `GET /thrity-info`
```json
{
  "name": "home.thrity",
  "https": false,
  "uptime_s": 143.2,
  "requests_served": 17
}
```
`Cache-Control: no-store` — always live. This is what 30web's
DevTools Security/Timing panels query, and what a `network`-permission
extension can `http_get()` for the currently-resolved `.thrity` host.

### Flags
- `--verbose` — logs `METHOD path -> status (Nms, Nb)` for every request to stdout.
- `--https` — self-signed cert, trust-on-first-use (see the script's docstring).

---

## Registry server (`registry-server/registry_server.py`)

The shared "phone book". Endpoints:

### `GET /lookup?name=<name>.thrity`
```json
{"name": "home.thrity", "ip": "203.0.113.5", "port": 8080, "https": false}
```
404 `{"error": "not found"}` if unregistered or stale (unseen for
>24h). 400 if `name` isn't a valid `.thrity` name. 429 if the
calling IP has made more than 120 lookups in the last 60 seconds.

### `GET /list`
```json
{"sites": {"home.thrity": {"ip": "...", "port": 8080, "https": false}, "...": {...}}}
```
Every currently-live (non-stale) registered site. Powers 30web's
"Directory" button.

### `GET /status`
```json
{
  "version": "0.05",
  "uptime_s": 5821.3,
  "sites_total": 12,
  "sites_live": 9,
  "requests": {"lookup": 340, "register": 15, "list": 4, "status": 2}
}
```
Debug/health endpoint — what a `network`-permission extension, or
just `curl`, checks before relying on a registry. Always live,
never cached.

### `POST /register`
Request body:
```json
{"name": "home.thrity", "ip": "203.0.113.5", "port": 8080, "secret": "...", "https": false}
```
- 200 `{"status": "registered", "name": "..."}` on success.
- 400 for a malformed body, invalid name, or invalid port.
- 403 if the name is already claimed under a different secret.
- 429 if the calling IP has registered more than 20 names in the
  last hour.
- Request bodies over 4KB are rejected outright (a registration is a
  handful of small fields; anything bigger is almost certainly
  abuse, not a real registration).

Registry writes are atomic (`os.replace`) and protected by a lock, so
concurrent registrations from different hosts can't corrupt
`registry.json`.

### Flags
- `--verbose` — logs `METHOD path -> status (Nms)` for every request to stdout.
- `--https` — self-signed cert; encrypts `secret` in transit (still not CA-validated — see the script's docstring for why that's expected for a made-up TLD).

---

## Using these from an extension

```
permissions { network }

action check_registry_health {
    let reg = primary_registry()
    if reg != "" {
        let status = http_get(reg + "/status")
        log("registry status: " + status)
    }
}
```

`http_get` enforces the same restriction either way: only configured
registries or the tab's currently-resolved `.thrity` host, regardless
of which of the endpoints above you're calling.
