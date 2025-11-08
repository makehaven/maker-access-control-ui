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
