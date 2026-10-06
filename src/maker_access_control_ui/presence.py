"""Lobby presence board, served from the box instead of Pantheon.

Every wall screen used to poll the website for "who just came in" -- the
lobby kiosk alone was ~6,200 requests a day, and Pantheon bills every one,
cached or not. The box already decides every door tap, so it knows who came in
before the website does. Screens on the LAN poll the box; the website is only
asked for what the box cannot see: member photos and guest check-ins, both of
which ride the fallback-export sync that already runs every few minutes.

The rules mirror Drupal's ``access_display`` module, so the board looks the
same whichever side serves it:

* one card per person; taps within ``DEBOUNCE_SECONDS`` of the last one bump a
  counter instead of starting a new visit (``PresenceUpdater::upsert``);
* service accounts (``presence_hidden`` in the export) never appear;
* only the last ``WINDOW_SECONDS`` are served;
* a host's card counts the guests checked in under them since they arrived.

Recording a tap is on the path that opens a door, so it never raises.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from urllib.parse import urljoin
from urllib.request import Request
from urllib.request import urlopen

from maker_access_control_ui.config import CONFIG

logger = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 300
WINDOW_SECONDS = 24 * 3600
GUEST_DOOR_LABEL = "Guest check-in"

_LOCK = threading.Lock()
_ENTRIES: Dict[str, Dict[str, Any]] = {}
_GUESTS: List[Dict[str, Any]] = []
_LOADED = False


# ----------------------------------------------------------------------
# Persistence (survives a restart; losing it only blanks the board)
# ----------------------------------------------------------------------
def _store_base() -> Optional[str]:
    return os.getenv("CARDSYS_TEST_STORE") or CONFIG.STORE_PATH or None


def state_path() -> Optional[Path]:
    base = _store_base()
    return Path(f"{base}.presence.json") if base else None


def photo_dir() -> Optional[Path]:
    base = _store_base()
    return Path(f"{base}.photos") if base else None


def _load() -> None:
    global _LOADED, _GUESTS
    if _LOADED:
        return
    _LOADED = True
    path = state_path()
    if not path or not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _ENTRIES.update({str(k): v for k, v in (data.get("entries") or {}).items()})
        _GUESTS = [g for g in (data.get("guests") or []) if isinstance(g, dict)]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read presence state from %s: %s", path, exc)


def _save() -> None:
    path = state_path()
    if not path:
        return
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(
            json.dumps({"entries": _ENTRIES, "guests": _GUESTS}), encoding="utf-8"
        )
        tmp.replace(path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not persist presence state to %s: %s", path, exc)


def reset() -> None:
    """Forget everything (tests)."""
    global _LOADED, _GUESTS
    with _LOCK:
        _ENTRIES.clear()
        _GUESTS = []
        _LOADED = True


# ----------------------------------------------------------------------
# Writes
# ----------------------------------------------------------------------
def _display_name(person: Dict[str, Any]) -> str:
    name = f"{person.get('first_name') or ''} {person.get('last_name') or ''}".strip()
    return name or "Member"


def record_grant(person: Dict[str, Any], door: str, now: Optional[float] = None) -> None:
    """Note that ``person`` was just let through ``door``. Never raises."""
    try:
        if not person or person.get("presence_hidden"):
            return
        person_id = str(person.get("uuid") or person.get("id") or "")
        if not person_id:
            return
        ts = int(now if now is not None else time.time())
        with _LOCK:
            _load()
            entry = _ENTRIES.get(person_id)
            if entry is None or ts - int(entry.get("last", 0)) > WINDOW_SECONDS:
                entry = {"first": ts, "count": 0, "door": door}
            same_visit = ts - int(entry.get("last", ts)) <= DEBOUNCE_SECONDS
            entry.update(
                {
                    "name": _display_name(person),
                    "photo": person.get("photo") or "",
                    "door": (entry.get("door") or door) if same_visit and entry["count"] else door,
                    "last": ts,
                    "count": (int(entry["count"]) + 1) if same_visit else 1,
                }
            )
            _ENTRIES[person_id] = entry
            _save()
    except Exception as exc:  # noqa: BLE001
        logger.error("Presence record failed: %s", exc)


def set_guest_checkins(checkins: Any) -> None:
    """Replace the guest list with the one the latest export carried."""
    global _GUESTS
    if not isinstance(checkins, list):
        return
    with _LOCK:
        _load()
        _GUESTS = [g for g in checkins if isinstance(g, dict) and g.get("id")]
        _save()


# ----------------------------------------------------------------------
# Reads
# ----------------------------------------------------------------------
def _photo_url(person_id: str, source: str) -> Optional[str]:
    return f"/display/photo/{person_id}" if source else None


def feed(after: int = 0, limit: int = 24, now: Optional[float] = None) -> Dict[str, Any]:
    """Recent presence in the shape the website's feed returns (oldest last-seen first)."""
    now_ts = int(now if now is not None else time.time())
    cutoff = now_ts - WINDOW_SECONDS
    limit = max(1, min(int(limit or 24), 200))
    with _LOCK:
        _load()
        for key in [k for k, v in _ENTRIES.items() if int(v.get("last", 0)) < cutoff]:
            del _ENTRIES[key]
        cards: Dict[str, Dict[str, Any]] = {
            key: dict(value) for key, value in _ENTRIES.items()
        }
        guests = list(_GUESTS)

    for guest in guests:
        ts = int(guest.get("checked_in") or 0)
        gid = str(guest["id"])
        if ts < cutoff:
            continue
        existing = cards.get(gid)
        if existing and int(existing.get("last", 0)) >= ts:
            continue
        cards[gid] = {
            "name": guest.get("name") or "Guest",
            "door": GUEST_DOOR_LABEL,
            "first": int(existing["first"]) if existing else ts,
            "last": ts,
            "count": 1,
            "photo": guest.get("photo") or "",
        }

    items = []
    for key, card in cards.items():
        last = int(card.get("last", 0))
        if last < cutoff or (after and last <= after):
            continue
        first = int(card.get("first", last))
        guest_count = sum(
            1
            for g in guests
            if g.get("host_id") == key and int(g.get("checked_in") or 0) >= first
        )
        items.append(
            {
                "uid": key,
                "name": card.get("name") or "Member",
                "door": card.get("door") or "",
                "first": first,
                "last": last,
                "count": int(card.get("count", 1)),
                "guest_count": guest_count,
                "photo": _photo_url(key, card.get("photo") or ""),
            }
        )
    items.sort(key=lambda it: it["last"], reverse=True)
    items = list(reversed(items[:limit]))
    return {"items": items, "now": now_ts}


def photo_source(person_id: str) -> str:
    """The export's root-relative photo path for a card on the board, or ''."""
    with _LOCK:
        _load()
        entry = _ENTRIES.get(person_id)
        if entry and entry.get("photo"):
            return str(entry["photo"])
        for guest in _GUESTS:
            if str(guest.get("id")) == person_id and guest.get("photo"):
                return str(guest["photo"])
    return ""


# ----------------------------------------------------------------------
# Photos: fetched from the website once per photo version, then served locally
# ----------------------------------------------------------------------
def cached_photo(source: str, timeout: float = 10.0) -> Optional[Tuple[bytes, str]]:
    """Return ``(bytes, content_type)`` for a photo path, downloading it once.

    The cache key is the full path, ``itok`` included, so a member who changes
    their photo gets a new file rather than a stale one.
    """
    if not source:
        return None
    directory = photo_dir()
    key = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if directory:
        body_path = directory / key
        type_path = directory / f"{key}.type"
        if body_path.exists():
            try:
                content_type = type_path.read_text().strip() if type_path.exists() else "image/jpeg"
                return body_path.read_bytes(), content_type
            except OSError:
                pass
    url = urljoin(CONFIG.FALLBACK_SOURCE_URL or "", source)
    try:
        with urlopen(Request(url, headers={"Accept": "image/*"}), timeout=timeout) as response:
            body = response.read()
            content_type = response.headers.get("Content-Type", "image/jpeg")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Photo fetch failed for %s: %s", source, exc)
        return None
    if not content_type.startswith("image/"):
        return None
    if directory:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            (directory / key).write_bytes(body)
            (directory / f"{key}.type").write_text(content_type)
        except OSError as exc:
            logger.warning("Could not cache photo %s: %s", source, exc)
    return body, content_type
