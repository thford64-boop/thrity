#!/bin/bash
# Thrity Network / 30web - one-time setup for Linux Mint
# Run with: bash setup.sh
set -e

echo "== Installing system packages (needs your password) =="
sudo apt update
sudo apt install -y python3 python3-pip python3-gi gir1.2-webkit2-4.1 \
    gir1.2-gtk-3.0 python3-gi-cairo glib-networking ca-certificates tor

echo "== Starting Tor (used by the browser's Anonymize button) =="
sudo systemctl enable --now tor

echo "== Setting up personal Thrity config folder (~/.thrity) =="
mkdir -p ~/.thrity
if [ ! -f ~/.thrity/hosts.json ]; then
  echo "{}" > ~/.thrity/hosts.json
fi
if [ ! -f ~/.thrity/config.json ]; then
  cat > ~/.thrity/config.json <<'EOF'
{
  "registries": []
}
EOF
fi

echo ""
echo "Setup complete."
echo ""
echo "Next steps:"
echo "  1. Test locally (no network needed):"
echo "     python3 host-server/host_server.py --name home.thrity \\"
echo "         --folder examples/home.thrity --port 8080"
echo "     Then in another terminal, add a local override so 30web finds it:"
echo "     echo '{\"home.thrity\": {\"ip\": \"127.0.0.1\", \"port\": 8080}}' > ~/.thrity/hosts.json"
echo "  2. Launch the browser:"
echo "     python3 browser/30web.py"
echo "  3. Type home.thrity into the address bar."
echo ""
echo "See docs/GUIDE.md for the full walkthrough, including running a"
echo "shared registry server so other people's PCs can find your site."
