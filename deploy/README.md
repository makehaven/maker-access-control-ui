# Deploying the box

The box is the **local access authority**: it answers badge decisions from a
snapshot of Drupal's membership, and asks Drupal only when the snapshot cannot
answer honestly. It is designed so that the network being down degrades speed
and freshness, never availability.

## Rebuild after losing the box (the short path)

Everything that is not in this repo is backed up nightly, encrypted, to the
private repo `makehaven/infra-backups` (host `accessbox`; passphrase in the
password manager, not in the repo). On a fresh Debian 12 VM, as root:

```bash
git clone https://github.com/makehaven/infra-backups && cd infra-backups
gpg -d hosts/accessbox/accessbox.tar.gz.gpg | tar -xz        # → ./accessbox
curl -fsSL https://raw.githubusercontent.com/makehaven/maker-access-control-ui/main/deploy/install.sh \
  | bash -s -- "$PWD/accessbox"
```

`install.sh` restores the env (download + ingest codes), the Apache site and
staff password, the Cloudflare tunnel token (UniFi Access API for the website),
the unsent log-forward queue, and the `makehaven` crontab that runs **live
CiviCRM's scheduled jobs** (Terminus must then be logged in as that user). The
member store rebuilds itself from the website within one sync interval. If the
new VM gets a different address, repoint cardsystem's three `.env` URLs; until
then its fallback asks the website directly, so doors keep working.

## One-time setup on the Proxmox LXC (manual equivalent of install.sh)

```bash
adduser --system --group --home /opt/maker-access-control maker
git clone https://github.com/makehaven/maker-access-control-ui /opt/maker-access-control
cd /opt/maker-access-control
python3 -m venv .venv && .venv/bin/pip install -e .

install -d -m 0750 -o maker -g maker /etc/maker-access-control
install -m 0600 -o maker -g maker deploy/maker-access-control.env.example \
        /etc/maker-access-control/maker-access-control.env
$EDITOR /etc/maker-access-control/maker-access-control.env   # set the download code

install -m 0644 deploy/maker-access-control.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now maker-access-control
```

## Verify before trusting it with anything

```bash
curl -s http://<box>:8080/health | python3 -m json.tool
```

Expect `"status": "ok"`, a non-zero `store.users`, and `sync.age_seconds` below
the sync interval. Then watch `sync.total_successes` climb across several polls
while `sync.last_change_at` holds still — that is the conditional-request path
working, and it is what makes a short interval affordable.

## Before the box answers door taps

Set the **ingest code** in Drupal at `/admin/config/system/access-control-api-logger`
("Shared log ingest code") and put the same value in `LOG_FORWARD_CODE`. Make it
different from the download code.

Then confirm decisions are getting back:

```bash
curl -s http://<box>:8080/health | python3 -c \
  'import json,sys; print(json.load(sys.stdin)["log_forward"])'
```

`queue_depth` should sit at or near zero and `forwarded` should climb. A depth that
only grows means Drupal is refusing or unreachable — the decisions are safe on disk,
but every report built on the access log is going stale until it drains.

Read `last_error` before guessing why. Two cases seen in practice:

- `HTTP 403` — the codes differ. Fix `LOG_FORWARD_CODE` or the Drupal setting.
- `JSONDecodeError` — Drupal answered something other than JSON. On Pantheon this
  is what an **unset ingest code** looks like: Drupal returns 503, and Pantheon's
  edge swaps any origin 503 for the site's front page as HTML 200. Set the code in
  Drupal; the queue drains on the next interval.

## Two things that must be true

**LAN-only.** The `/user/login` endpoint is a handshake shim that accepts any
credentials, because the clients that call it are on the same wire and the box
has no user model of its own. The box must not be reachable from the internet.
Bind it to the LAN interface and keep it behind the firewall.

**`/health` must be monitored.** A box that has quietly stopped syncing keeps
answering from a frozen store. That fails *open* for revoked members and is the
single most dangerous failure in the design — it is invisible from the door,
from the readers, and from Drupal. `/health` returns 503 once the store is
stale, empty, or of unestablished age; alert on that.

## Rolling back

Stop the service and repoint the clients at Drupal. The one thing worth doing first
is letting the log-forward queue drain (`POST /api/log-forward/drain`, or just watch
`queue_depth` reach zero) — those queued decisions are the only record of taps the
box answered, and nothing else holds them.
