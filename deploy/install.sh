#!/usr/bin/env bash
# Build (or rebuild) the access box on a fresh Debian 12 VM, as root.
#
#   install.sh                      # fresh box: fill in the env afterwards
#   install.sh /path/to/accessbox   # restore from a decrypted infra-backups
#                                   # bundle (makehaven/infra-backups, host
#                                   # "accessbox"): env, Apache password,
#                                   # tunnel token, crontab, unsent log queue
#
# Idempotent: safe to re-run on a working box (it updates the code and
# re-applies config; it never overwrites an existing env or password file
# unless a backup directory is given).
#
# Production today: Proxmox VM 110 "website-clone", 192.168.23.33.
set -euo pipefail

BACKUP="${1:-}"
APP=/opt/maker-access-control
REPO=https://github.com/makehaven/maker-access-control-ui
ETC=/etc/maker-access-control

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
if [ -n "$BACKUP" ] && [ ! -f "$BACKUP/etc/maker-access-control/maker-access-control.env" ]; then
  echo "$BACKUP does not look like a decrypted accessbox bundle" >&2
  exit 1
fi

echo "== packages"
apt-get update -q
apt-get install -y -q git python3-venv apache2 curl

echo "== app user and code"
id maker >/dev/null 2>&1 || adduser --system --group --home "$APP" maker
if [ -d "$APP/.git" ]; then
  git -c safe.directory="$APP" -C "$APP" pull -q --ff-only
else
  git clone -q "$REPO" "$APP.tmp" && cp -a "$APP.tmp/." "$APP/" && rm -r "$APP.tmp"
fi
chown -R maker:maker "$APP"
sudo -u maker python3 -m venv "$APP/.venv"
sudo -u maker "$APP/.venv/bin/pip" install -q -e "$APP"

echo "== config"
install -d -m 0750 -o maker -g maker "$ETC"
if [ -n "$BACKUP" ]; then
  install -m 0600 -o maker -g maker "$BACKUP/etc/maker-access-control/maker-access-control.env" "$ETC/"
  [ -f "$BACKUP/etc/maker-access-control/reader-config.json" ] && \
    install -m 0640 -o maker -g maker "$BACKUP/etc/maker-access-control/reader-config.json" "$ETC/"
elif [ ! -f "$ETC/maker-access-control.env" ]; then
  install -m 0600 -o maker -g maker "$APP/deploy/maker-access-control.env.example" "$ETC/maker-access-control.env"
  echo "!! Fill in $ETC/maker-access-control.env (download code, ingest code) before trusting the box."
fi

echo "== service"
install -m 0644 "$APP/deploy/maker-access-control.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable -q maker-access-control
if [ -n "$BACKUP" ] && [ -f "$BACKUP/var/maker-store.json.logqueue.jsonl" ]; then
  # Unsent decisions from the old box: the only record of those taps.
  install -d -m 0750 -o maker -g maker /var/lib/maker-access-control
  install -m 0640 -o maker -g maker "$BACKUP/var/maker-store.json.logqueue.jsonl" /var/lib/maker-access-control/
fi
systemctl restart maker-access-control

echo "== Apache (LAN front door; /api/v0, /user/login and /health open, the rest behind staff password)"
a2enmod -q proxy proxy_http headers auth_basic >/dev/null
install -m 0644 "$APP/deploy/apache-access-box.conf" /etc/apache2/sites-available/access-box.conf
if [ -n "$BACKUP" ] && [ -f "$BACKUP/etc/apache2/access-box.htpasswd" ]; then
  install -m 0640 -o root -g www-data "$BACKUP/etc/apache2/access-box.htpasswd" /etc/apache2/
elif [ ! -f /etc/apache2/access-box.htpasswd ]; then
  echo "!! Create the staff password: htpasswd -c /etc/apache2/access-box.htpasswd staff"
fi
a2dissite -q 000-default >/dev/null 2>&1 || true
a2ensite -q access-box >/dev/null
systemctl reload apache2

echo "== Cloudflare tunnel (UniFi Access API for the website: unifi-api.makehaven.org)"
if [ -n "$BACKUP" ] && [ -f "$BACKUP/etc/cloudflared/token" ]; then
  if ! command -v cloudflared >/dev/null; then
    curl -fsSL -o /tmp/cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
    apt-get install -y -q /tmp/cloudflared.deb
  fi
  install -d -m 0700 /etc/cloudflared
  install -m 0600 "$BACKUP/etc/cloudflared/token" /etc/cloudflared/token
  install -m 0644 "$BACKUP/etc/systemd/cloudflared.service" /etc/systemd/system/cloudflared.service
  systemctl daemon-reload
  systemctl enable -q --now cloudflared
else
  echo "!! No tunnel restored. Reissue a token for tunnel 'unifi-access-12445' in the Cloudflare dashboard if needed."
fi

echo "== live CiviCRM cron (runs on this VM; see docs/ops/ACCESS_BOX.md in makehaven-website)"
if [ -n "$BACKUP" ] && [ -s "$BACKUP/crontab/makehaven" ]; then
  id makehaven >/dev/null 2>&1 || adduser --gecos "" --disabled-password makehaven
  crontab -u makehaven "$BACKUP/crontab/makehaven"
  echo "!! The crontab calls /usr/local/bin/terminus as makehaven: install Terminus and"
  echo "   'terminus auth:login --machine-token=...' as makehaven, or CiviCRM's scheduled"
  echo "   jobs on live stop running."
fi

echo "== check"
sleep 3
curl -fsS http://127.0.0.1:8080/health | head -c 300; echo
echo "Done. Store fills from the website within one sync interval (3 min)."
