#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Cloudflare WARP in *proxy mode* for Debian/Ubuntu VPS.
#
# Why: YouTube aggressively blocks datacenter IPs ("Sign in to confirm
# you're not a bot"). With WARP, yt-dlp traffic exits through Cloudflare's
# network instead — no full-tunnel VPN (SSH stays untouched), just a local
# SOCKS5 proxy at 127.0.0.1:40000 for the bot to use.
#
# Usage:  sudo bash scripts/install_warp.sh
# Then point the bot at it (one of):
#   • .env:  PROXY=socks5://127.0.0.1:40000     (native / systemd run)
#   • Admin Mini App → Proxy → "Use WARP (local)" → Test → Apply
# Docs: https://developers.cloudflare.com/warp-client/get-started/linux/
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root:  sudo bash $0" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

echo "==> Adding Cloudflare's package repository"
curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg \
  | gpg --yes --dearmor --output /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
# shellcheck disable=SC1091
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $(. /etc/os-release && echo "$VERSION_CODENAME") main" \
  > /etc/apt/sources.list.d/cloudflare-client.list

echo "==> Installing cloudflare-warp"
apt-get update -qq
apt-get install -y -qq cloudflare-warp

echo "==> Starting the WARP daemon (proxy mode is set BEFORE connecting,"
echo "    so system routes/SSH are never hijacked)"
systemctl enable --now warp-svc
sleep 2

# Newer CLI verbs first, legacy ones as fallback (Cloudflare renamed a few).
warp-cli --accept-tos registration new 2>/dev/null \
  || warp-cli --accept-tos register 2>/dev/null \
  || true
warp-cli mode proxy 2>/dev/null || warp-cli set-mode proxy
warp-cli proxy port 40000 2>/dev/null || warp-cli set-proxy-port 40000
warp-cli connect
sleep 3

echo "==> Status:"
warp-cli status || true
echo "==> Verifying through the SOCKS5 proxy (expect warp=on or warp=plus):"
curl -fsS --proxy socks5h://127.0.0.1:40000 https://www.cloudflare.com/cdn-cgi/trace \
  | grep -E '^(ip|warp)=' || {
    echo "Verification failed — check 'warp-cli status' and 'journalctl -u warp-svc'." >&2
    exit 1
  }

cat <<'EOF'

✅ WARP proxy is live at socks5://127.0.0.1:40000

Point the bot at it:
  • .env:  PROXY=socks5://127.0.0.1:40000   then restart the bot, or
  • Admin Mini App → Proxy pool → "🌀 Use WARP (local)" → 🧪 Test → 💾 Apply

Docker instead? Use the bundled profile:  docker compose --profile warp up -d
EOF
