# Maker Access Control UI

This folder packages the lightweight Maker Access Control interface that was previously embedded inside the main cardsystem codebase. It keeps the JSON-backed access provider, Quart UI, CLI helpers, fixtures, and tests together so it can be copied into its own Git repository when we're ready.

## Features

- Manage people, permissions, and assignments via a single-page UI powered by Quart.
- Pull the latest fallback export directly from your Drupal site using the built-in “Sync from Drupal” form.
- Dedicated `/permissions` page keeps badge definitions separate from everyday user/assignment triage.
- Simulator can call both card-serial and email-based access endpoints to mirror Drupal’s API.
- JSON-backed data store with hot reloads so local changes persist without Drupal.
- CLI helpers for scripting grants/revocations or debugging permissions.
- pytest suite (async) that covers the provider, API endpoints, and simulator flows.

## Getting Started

```bash
cd maker-access-control-ui
poetry install
poetry run pytest
./scripts/run-maker-access-control-ui.sh
```

The `run-maker-access-control-ui.sh` script seeds `.fixtures/maker-store.json` and `.fixtures/maker-reader-config.json` with demo data the first time it runs. It then launches the Quart app via `python -m maker_access_control_ui.ui.app`.

Environment variables:

- `CARDSYS_TEST_MODE=1` forces the JSON provider regardless of other config (set automatically by the script/tests).
- `CARDSYS_TEST_STORE`, `CARDSYS_TEST_USERS`, `CARDSYS_TEST_TOOLS`, `CARDSYS_TEST_ASSIGNMENTS` can point at custom JSON files.
- `READER_TO_TOOL_CONFIG_PATH` controls how reader devices map to permissions for the simulator endpoints.

### Running as the local access authority

The app can also run unattended as the building's local access authority: it keeps a
synced snapshot of Drupal's membership, answers badge decisions from it, and asks Drupal
only when the snapshot cannot answer honestly. See [`deploy/`](deploy/README.md) for the
systemd unit and a commented environment file.

- `MAKER_ACCESS_CONTROL_SYNC_ENABLED=1` starts a background loop that pulls the fallback
  export on an interval (`_SYNC_INTERVAL`, `_SYNC_JITTER`, `_SYNC_TIMEOUT`). Conditional
  requests mean an unchanged poll transfers nothing.
- `GET /health` reports store counts, sync age, failures, and proxy activity. It answers
  `200` while `ok`/`degraded` and **`503` when `stale`, `empty`, or `unknown`** — point an
  uptime monitor at it. A box that has quietly stopped syncing keeps answering from a
  frozen store, which fails *open* for revoked members.
- `POST /api/sync/run` runs one sync immediately (`{"force": true}` ignores the ETag).
- `MAKER_ACCESS_CONTROL_SYNC_MIN_USERS` / `_SYNC_MAX_SHRINK_RATIO` refuse an export that
  is implausibly small. A half-failed Drupal query still returns HTTP 200 with well-formed
  JSON, and installing it would silently revoke the membership.
- `MAKER_ACCESS_CONTROL_PROXY_ENABLED=1` forwards to Drupal on a miss — unknown member,
  unknown permission, or a denial on a store too old to believe. A *fresh* local deny is
  trusted, and any upstream failure leaves the local answer standing.

- `MAKER_ACCESS_CONTROL_LOG_FORWARD_ENABLED=1` forwards decisions the box made back to
  Drupal so `access_control_log` keeps being written. The queue is on disk and survives a
  power cut; retries are idempotent; `POST /api/log-forward/drain` flushes it by hand.
  Decisions the *proxy* handed upstream are deliberately not forwarded — Drupal already
  logged those as it answered.

A failed sync never narrows the store, and sync state is persisted beside it, so a
restarted box reports the true age of its data rather than waking up looking fresh.
- `MAKER_ACCESS_CONTROL_PERMISSION_ENDPOINT` lets the simulator target a custom permission URL. Use `{card_serial}`, `{card_id}`, `{uuid}`, `{permission}`, or `{permission_id}` placeholders (defaults to `/api/v0/serial/{card_serial}/permission/{permission_id}`).
- `MAKER_ACCESS_CONTROL_PERMISSION_ENDPOINT_EMAIL` overrides the email-based permission endpoint template (defaults to `/api/v0/email/{email}/permission/{permission_id}`).
- `MAKER_ACCESS_CONTROL_FALLBACK_URL` and `MAKER_ACCESS_CONTROL_FALLBACK_CODE` optionally prefill the “Sync from Drupal” form in the UI so admins can download the latest export with a single click.

## Syncing From Drupal

1. Configure the fallback export shared code inside Drupal (`Configuration → System → Access Control Logger Settings`).
2. Launch this UI (`./scripts/run-maker-access-control-ui.sh`) and open the page in your browser.
3. Visit `/sync` (link in the banner) and point the form at your Drupal host’s `/api/v0/access-control/fallback-store` endpoint, then enter the shared code.
4. Click **Download latest data** to fetch the JSON and load it into the local provider. Optionally tick “Remember download code” to store the code in browser-local storage for future imports.
5. The people/permissions/assignments tables refresh automatically once the download completes.

## Managing Permissions

Visit `/permissions` (linked from the banner) to add, rename, or remove badge definitions. Changes sync instantly to the JSON store and show up in the main admin view for assignment management.

## Simulator

Use the Simulator tab to exercise the same endpoints Drupal exposes. Select “Card serial” or “Email address” to build the correct URL automatically. If you set `MAKER_ACCESS_CONTROL_PERMISSION_ENDPOINT_EMAIL`, the form can hit the `/api/v0/email/{email}/permission/{permission_id}` endpoint without editing the JSON store or code.

## Repository Split

When ready to split this directory into its own repo:

1. `cp -R maker-access-control-ui <new-repo>` (or use `git subtree split` if you want history).
2. Re-run `poetry install` in the new location.
3. Update the `README`/`pyproject` metadata as desired.
4. Remove the directory from the parent project once the standalone repo is established.
