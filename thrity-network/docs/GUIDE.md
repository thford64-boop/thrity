# Thrity Network + 30web — Full Guide

A completely free, self-hosted mini-internet with its own `.thrity`
addresses, and a lightweight browser (30web) to view it — plus the
regular clearnet.

---

## 1. Why these tools

- **Python 3** — already on Linux Mint, huge standard library, no
  build step, easy to read as a beginner. Used for the resolver, the
  registry server, and the site host server.
- **WebKit2GTK** — the rendering engine (turns HTML/CSS into pixels)
  used by GNOME Web, Midori, and Surf. Free, open source, and far
  lighter than bundling Chromium (what Electron-based "lightweight"
  browsers actually do under the hood). This is what makes 30web an
  *actual* small browser rather than a 200MB Electron app pretending
  to be one.
- **GTK 3** — the toolkit for 30web's window, buttons, and address
  bar. Comes standard on Mint (Cinnamon is built on it).
- **Plain JSON files** — the "phone book" storage. No database
  server to install, back up, or misconfigure.

Nothing here costs money, and nothing requires an account with any
company.

---

## 2. Folder structure

```
thrity-network/
├── setup.sh                  # installs everything, run once
├── resolver/
│   └── thrity_resolver.py    # looks up .thrity names -> ip:port
├── registry-server/
│   └── registry_server.py    # the shared "phone book" server (optional to run)
├── host-server/
│   └── host_server.py        # serves one .thrity website's files
├── browser/
│   └── 30web.py              # the browser itself
├── examples/
│   └── home.thrity/
│       └── index.html        # a starter website to try out
└── docs/
    └── GUIDE.md               # this file
```

Your personal settings live outside this folder, at `~/.thrity/`:
- `~/.thrity/hosts.json` — your personal overrides (like a private
  `/etc/hosts` file, but for `.thrity` names). Anything you put here
  is checked *before* any registry server, so it always wins.
- `~/.thrity/config.json` — list of registry servers 30web should
  ask when a name isn't in your local overrides.

---

## 3. Install (Linux Mint)

Open a terminal in the `thrity-network` folder and run:

```bash
bash setup.sh
```

This does three things:
1. Installs Python and WebKit2GTK via `apt` (Mint's package manager —
   `sudo apt install` downloads free, open-source packages from
   Mint's software repositories, same as the Software Manager app
   but from the terminal).
2. Creates `~/.thrity/` with empty config files.
3. Prints the next steps.

If you'd rather type the install command yourself, this is what it
runs:

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-gi gir1.2-webkit2-4.1 gir1.2-gtk-3.0 python3-gi-cairo
```

(`sudo` runs the command as an administrator, needed to install
software; `apt update` refreshes Mint's list of available packages;
`apt install` fetches and installs the named ones.)

---

## 4. First test: everything on one PC

This proves the whole pipeline works before involving any other
computer or the internet.

**Terminal 1 — host the example site:**
```bash
cd thrity-network
python3 host-server/host_server.py --name home.thrity --folder examples/home.thrity --port 8080
```
This starts a tiny web server (`http.server` under the hood) that
hands out the files in `examples/home.thrity/` to anyone who asks on
port 8080. Leave this running.

**Terminal 2 — tell your resolver where it is:**
Since you don't have a registry server yet, just add a manual entry:
```bash
echo '{"home.thrity": {"ip": "127.0.0.1", "port": 8080}}' > ~/.thrity/hosts.json
```
`127.0.0.1` is the special "this same computer" address (called
*localhost*).

**Terminal 2 (still) — launch the browser:**
```bash
python3 browser/30web.py
```
Type `home.thrity` in the address bar and press Enter. 30web sees the
`.thrity` ending, looks it up in `~/.thrity/hosts.json`, finds
`127.0.0.1:8080`, and loads the page from your host server. Type
`wikipedia.org` in the same bar and it'll load normally over the real
internet — both work side by side.

---

## 5. Hosting your own `.thrity` site (Option 1: from your own PC)

1. Make a folder for your site, e.g. `~/thrity-sites/myname.thrity/`,
   and put an `index.html` in it (copy `examples/home.thrity/` as a
   starting point).
2. Run the host server pointed at it:
   ```bash
   python3 host-server/host_server.py --name myname.thrity \
       --folder ~/thrity-sites/myname.thrity --port 8081
   ```
3. If you're only sharing on your home network (LAN), that's it —
   anyone on your Wi-Fi can add an entry to their own
   `~/.thrity/hosts.json` pointing at your PC's LAN IP (find it with
   `hostname -I`) and port.
4. To be reachable over the *internet* (not just your LAN), see the
   registry server + port forwarding steps below.

Keep the terminal running the host server open the whole time your
site should be reachable — closing it takes the site offline, same
as unplugging a server.

---

## 6. Running a shared Registry Server (so multiple people can find each other)

One person (could be you) runs:
```bash
python3 registry-server/registry_server.py
```
This listens on port `9090` and keeps `registry-server/registry.json`
— the shared phone book. It needs to be reachable by everyone who
wants to use it:

- **On a LAN**: everyone just uses your LAN IP, e.g.
  `http://192.168.1.10:9090`.
- **Over the internet**: you'll need port forwarding (see Security
  section) so port 9090 on your router points at this PC, or run it
  on a free-tier cloud VM if you'd rather not expose your home
  network at all (still $0, e.g. Oracle Cloud's free tier — outside
  the scope of this guide, but the script runs unmodified anywhere
  Python 3 is available).

**Everyone who wants to use this registry** adds it to their own
`~/.thrity/config.json`:
```json
{
  "registries": ["http://192.168.1.10:9090"]
}
```
You can list more than one registry - 30web now queries all of them
at the same time and uses whichever answers first, instead of trying
them one at a time, so one slow or offline registry no longer stalls
every lookup.

Run the registry with `--https` (self-signed, same trust-on-first-use
model as `.thrity` sites) to stop your `--secret` from being sent in
plain text on the wire:
```bash
python3 registry-server/registry_server.py --https
```
then use `https://` in the registry URL everywhere above.

**Hosting a site through the registry** (instead of manual
`hosts.json` entries):
```bash
python3 host-server/host_server.py --name myname.thrity \
    --folder ~/thrity-sites/myname.thrity --port 8081 \
    --registry http://192.168.1.10:9090 --secret "some password only I know"
```
The `--secret` is yours — remember it. It's the only thing stopping
someone else from later "stealing" `myname.thrity` by re-registering
it with a different IP. The host server automatically re-registers
every 10 minutes (a "heartbeat"), so the registry knows your site is
still alive, and drops it from lookups if you go offline for a day.

---

## 7. Letting other people host on the Thrity Network (Option 2)

Anyone who wants to host their own site does exactly what you did:

1. Install the same prerequisites (`bash setup.sh`, or the manual
   `apt install` line in section 3).
2. Copy (or clone, if you put this on GitHub) the `thrity-network`
   folder.
3. Add your registry server's address to their
   `~/.thrity/config.json`.
4. Run `host_server.py` pointed at their own site folder, with a
   `--name` ending in `.thrity` and their own `--secret`.
5. Run `browser/30web.py` to browse the network, exactly as you do.

That's the entire onboarding process — no accounts, no payments, no
central authority approving names (first-come-first-served per
registry, protected by each owner's secret).

---

## 8. Testing across multiple computers

1. Put both PCs on the same Wi-Fi/LAN for the first test — simplest,
   no router configuration needed.
2. On PC A, run the registry server and note its LAN IP
   (`hostname -I`).
3. On PC B, add that IP to `~/.thrity/config.json` and host a site
   with `--registry http://<PC A's IP>:9090`.
4. On PC A, launch 30web and type PC B's site name — it should
   resolve through the registry and load PC B's page.
5. Once that works, the same commands work over the real internet,
   provided the registry server's port is reachable from outside
   (port forwarding, see below) — nothing else about the code
   changes.

---

## 9. Growing beyond one registry server (future direction)

Right now, one registry server is a single point of failure — if it
goes down, name lookups fail (already-known local `hosts.json`
entries still work). Natural next steps, roughly in order of
difficulty:

1. **Multiple independent registries**: list several in
   `config.json`; 30web already tries each in order until one
   answers.
2. **Mirroring**: periodically have registries fetch each other's
   `/list` and merge entries, so any one of them going down doesn't
   lose the whole directory.
3. **Full peer-to-peer (DHT)**: replace the central registry with a
   distributed hash table, the same technique BitTorrent uses to find
   peers without a central server. This is a legitimate long-term
   goal but a significant undertaking — worth it only once you have
   an active community of hosts to justify it.

---

## 10. Security — read before exposing anything to the internet

- **The host server only serves static files** (HTML/CSS/images) —
  no server-side code execution by design. Don't add PHP/CGI/etc.
  without understanding the risk: any bug in server-side code can be
  used to attack the host machine.
- **Only forward the port you mean to.** Port forwarding on your
  router (usually under "NAT" or "Port Forwarding" in its admin page,
  reached via a browser at an address like `192.168.1.1`) exposes
  *that one port* on *that one PC* to the whole internet. Don't
  forward more ports than you're actively using, and turn forwarding
  off when you're not hosting.
- **Use a firewall.** Linux Mint includes `ufw` (Uncomplicated
  Firewall). Enable it and only allow the ports you're using:
  ```bash
  sudo ufw enable
  sudo ufw allow 8080/tcp   # your host server's port
  sudo ufw allow 9090/tcp   # only if you're running a registry server
  ```
- **Don't run any of this as root.** Run it as your normal user —
  none of these scripts need administrator privileges to serve files
  or make network requests.
- **Treat your `--secret` like a password.** Anyone who has it can
  overwrite where your site name points.
- **Registry traffic is plain HTTP by default**, meaning your
  `--secret` isn't encrypted in transit unless you start the registry
  with `--https` (see above). Either way this is still fine for a
  hobby network of static pages among people who trust each other,
  not appropriate for anything sensitive (passwords, personal data,
  payments). Don't build anything like that on top of this without
  adding real encryption first.
- **Local storage/IndexedDB are on again as of v0.04** (they were
  fully off before, which is what broke a lot of ordinary sites).
  They're still wiped the moment a tab closes, same as everything
  else in an ephemeral tab - nothing is ever written to disk.
- **Camera/mic/location are asked per-site** instead of blocked
  outright - a permission dialog pops up the first time a site
  requests one, and denying it is always safe.
- **Registry server abuse**: the current design lets anyone register
  any unclaimed name. If this becomes a real shared network, consider
  adding basic rate-limiting or a simple invite/allowlist system
  before opening it up publicly.

---

## 11. Everything is free, permanently

- Python, GTK, WebKit2GTK: free and open source (no license fees,
  ever).
- `.thrity` names: not real domains, so there's no registrar to pay —
  they only mean something to Thrity resolvers.
- Hosting: your own electricity, that's it. No hosting company, no
  subscription.
- Registry server: same — runs on hardware you or a friend already
  owns.

The only unavoidable non-free things are (a) your existing internet
connection and (b) the electricity to run a PC — everything above
that layer is $0.
