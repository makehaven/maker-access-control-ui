# Maker Access Control UI

This folder packages the lightweight Maker Access Control interface that was previously embedded inside the main cardsystem codebase. It keeps the JSON-backed access provider, Quart UI, CLI helpers, fixtures, and tests together so it can be copied into its own Git repository when we're ready.

## Features

- Manage people, permissions, and assignments via a single-page UI powered by Quart.
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

## Repository Split

When ready to split this directory into its own repo:

1. `cp -R maker-access-control-ui <new-repo>` (or use `git subtree split` if you want history).
2. Re-run `poetry install` in the new location.
3. Update the `README`/`pyproject` metadata as desired.
4. Remove the directory from the parent project once the standalone repo is established.
