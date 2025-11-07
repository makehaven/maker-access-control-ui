#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_STORE="${PROJECT_ROOT}/.fixtures/maker-store.json"
STORE_PATH="${CARDSYS_TEST_STORE:-${DEFAULT_STORE}}"
DEFAULT_CONFIG="${PROJECT_ROOT}/.fixtures/maker-reader-config.json"
CONFIG_PATH="${READER_TO_TOOL_CONFIG_PATH:-${DEFAULT_CONFIG}}"
RESET=0
PORT_OVERRIDE=""
ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reset)
      RESET=1
      shift
      ;;
    --port)
      if [[ -n "${2:-}" ]]; then
        PORT_OVERRIDE="$2"
        shift 2
      else
        echo "--port requires a value" >&2
        exit 1
      fi
      ;;
    *)
      ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ ! -x "$(command -v poetry || true)" ]]; then
  echo "Poetry is required. Install it and run 'poetry install --with dev --no-root' first." >&2
  exit 1
fi

if [[ ${RESET} -eq 1 ]]; then
  rm -f "${STORE_PATH}" "${CONFIG_PATH}"
fi

mkdir -p "$(dirname "${STORE_PATH}")"
mkdir -p "$(dirname "${CONFIG_PATH}")"

if [[ ! -f "${STORE_PATH}" ]]; then
  cat <<'STORE' > "${STORE_PATH}"
{
  "users": [
    {
      "id": "u.alice",
      "card_serial": "01020304",
      "first_name": "Alice",
      "last_name": "Anderson",
      "uuid": "11111111-1111-1111-1111-111111111111"
    },
    {
      "id": "u.bob",
      "card_serial": "A1B2C3D4",
      "first_name": "Bob",
      "last_name": "Baker",
      "uuid": "22222222-2222-2222-2222-222222222222"
    }
  ],
  "tools": [
    {
      "id": "t.tool_a",
      "name": "Tool A",
      "reader_device_id": "test_tool_a_reader",
      "activator_device_id": "test_tool_a_activator",
      "badge_name": "tool_a"
    },
    {
      "id": "t.tool_b",
      "name": "Tool B",
      "reader_device_id": "test_tool_b_reader",
      "activator_device_id": "test_tool_b_activator",
      "badge_name": "tool_b"
    },
    {
      "id": "t.door",
      "name": "Test Door",
      "reader_device_id": "test_door_reader",
      "activator_device_id": "test_door_activator",
      "badge_name": "door"
    }
  ],
  "assignments": [
    ["u.alice", "t.tool_a"],
    ["u.alice", "t.door"],
    ["u.bob", "t.tool_b"]
  ]
}
STORE
fi

if [[ ! -f "${CONFIG_PATH}" ]]; then
  cat <<'CFG' > "${CONFIG_PATH}"
{
  "readers": {
    "test_tool_a_reader": {
      "deviceName": "test_tool_a_reader",
      "associatedToolNames": ["t.tool_a"]
    },
    "test_tool_b_reader": {
      "deviceName": "test_tool_b_reader",
      "associatedToolNames": ["t.tool_b"]
    },
    "test_door_reader": {
      "deviceName": "test_door_reader",
      "associatedToolNames": ["t.door"]
    }
  },
  "tools": {
    "t.tool_a": {
      "badgeName": "tool_a",
      "deviceName": "test_tool_a_activator"
    },
    "t.tool_b": {
      "badgeName": "tool_b",
      "deviceName": "test_tool_b_activator"
    },
    "t.door": {
      "badgeName": "door",
      "deviceName": "test_door_activator"
    }
  }
}
CFG
fi

export CARDSYS_TEST_MODE=1
export CARDSYS_TEST_STORE="${STORE_PATH}"
export READER_TO_TOOL_CONFIG_PATH="${CONFIG_PATH}"
export PYTHONPATH="${PROJECT_ROOT}/src:${PYTHONPATH:-}"
unset CARDSYS_TEST_USERS CARDSYS_TEST_TOOLS CARDSYS_TEST_ASSIGNMENTS || true

choose_port() {
  python - <<'PY'
import os
import socket

preferred = int(os.environ.get("MAC_UI_PORT_OVERRIDE", os.environ.get("PORT", "8080")))
force = os.environ.get("MAC_UI_FORCE_PORT", "0") == "1"

def is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
        except OSError:
            return False
    return True

if force:
    print(preferred)
else:
    for candidate in range(preferred, preferred + 20):
        if is_free(candidate):
            print(candidate)
            break
    else:
        raise SystemExit("No free port in range %s-%s" % (preferred, preferred + 19))
PY
}

if [[ -n "${PORT_OVERRIDE}" ]]; then
  export MAC_UI_FORCE_PORT=1
  export MAC_UI_PORT_OVERRIDE="${PORT_OVERRIDE}"
else
  export MAC_UI_FORCE_PORT=0
  export MAC_UI_PORT_OVERRIDE="${PORT:-8080}"
fi

PORT_SELECTED="$(PORT="${MAC_UI_PORT_OVERRIDE}" choose_port)"
export PORT="${PORT_SELECTED}"
echo "Starting Maker Access Control UI on http://127.0.0.1:${PORT}"

exec poetry run hypercorn --bind "0.0.0.0:${PORT}" maker_access_control_ui.ui.app:app "${ARGS[@]}"
