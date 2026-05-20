"""Home Assistant integration (BONUS — not in public git).

Self-contained module: owns its config file, its keyring schema, the HA REST
client, the Anthropic tool definitions, and the preferences UI panel.

Public API used by api.py / window.py:
- is_enabled() -> bool
- get_tools() -> list[dict]  (Anthropic tool schemas)
- dispatch(name, input_dict) -> str  (tool result as JSON-encoded string)
- build_prefs_group(on_changed) -> Adw.PreferencesGroup
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import gi
gi.require_version("Secret", "1")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Secret, Gtk, Adw

try:
    from i18n import _
except ImportError:
    def _(s: str) -> str:
        return s


# ---------------------------------------------------------------- config & secret

_CFG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "claude-companion"
_CFG_PATH = _CFG_DIR / "ha.json"

DEFAULT_URL = "http://homeassistant.local:8123"

_SCHEMA = Secret.Schema.new(
    "org.little_home.ClaudeCompanion.HomeAssistantToken",
    Secret.SchemaFlags.NONE,
    {"service": Secret.SchemaAttributeType.STRING},
)
_ATTRS = {"service": "homeassistant"}


def _load_cfg() -> dict:
    if not _CFG_PATH.exists():
        return {"enabled": False, "url": DEFAULT_URL}
    try:
        data = json.loads(_CFG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {"enabled": False, "url": DEFAULT_URL}
    return {
        "enabled": bool(data.get("enabled", False)),
        "url": data.get("url") or DEFAULT_URL,
    }


def _save_cfg(cfg: dict) -> None:
    _CFG_DIR.mkdir(parents=True, exist_ok=True)
    _CFG_PATH.write_text(json.dumps({
        "enabled": bool(cfg.get("enabled")),
        "url": cfg.get("url") or DEFAULT_URL,
    }, indent=2))


def _load_token() -> str | None:
    return Secret.password_lookup_sync(_SCHEMA, _ATTRS, None)


def _store_token(token: str) -> None:
    Secret.password_store_sync(
        _SCHEMA, _ATTRS, Secret.COLLECTION_DEFAULT,
        "Home Assistant long-lived access token", token, None,
    )


def _clear_token() -> None:
    Secret.password_clear_sync(_SCHEMA, _ATTRS, None)


def is_enabled() -> bool:
    cfg = _load_cfg()
    return cfg["enabled"] and bool(cfg["url"]) and bool(_load_token())


# ---------------------------------------------------------------- REST client

class HAError(Exception):
    pass


def _request(method: str, path: str, body: dict | None = None) -> object:
    cfg = _load_cfg()
    token = _load_token()
    if not token:
        raise HAError("No Home Assistant token configured")
    url = cfg["url"].rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode()
            if not raw:
                return None
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        raise HAError(f"HTTP {e.code}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise HAError(f"Network error: {e.reason}") from e


def _list_states() -> list[dict]:
    states = _request("GET", "/api/states")
    return states if isinstance(states, list) else []


def _get_state(entity_id: str) -> dict:
    state = _request("GET", f"/api/states/{urllib.parse.quote(entity_id)}")
    return state if isinstance(state, dict) else {}


def _call_service(domain: str, service: str, payload: dict) -> object:
    return _request("POST", f"/api/services/{domain}/{service}", payload)


# ---------------------------------------------------------------- Tool schemas

_TOOLS = [
    {
        "name": "ha_list_entities",
        "description": (
            "List Home Assistant entities. Strongly prefer passing a domain "
            "filter (e.g. 'light', 'switch', 'cover', 'climate', 'sensor', "
            "'scene', 'media_player') — listing all entities can return "
            "hundreds. Without filter, only entity_ids (no attributes) are "
            "returned. With filter, full state + attributes are returned."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Filter to a single HA domain. Strongly recommended.",
                },
            },
        },
    },
    {
        "name": "ha_get_state",
        "description": (
            "Get the current state and attributes of a single Home Assistant "
            "entity by its entity_id (e.g. 'light.kitchen', "
            "'cover.bedroom_shutter', 'climate.living_room')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The entity_id to query.",
                },
            },
            "required": ["entity_id"],
        },
    },
    {
        "name": "ha_call_service",
        "description": (
            "Call a Home Assistant service to perform an action. Common "
            "examples: light.turn_on, light.turn_off (data: {brightness_pct, "
            "color_name}), cover.close_cover, cover.open_cover, "
            "cover.set_cover_position (data: {position 0-100}), switch.toggle, "
            "scene.turn_on, climate.set_temperature (data: {temperature}), "
            "media_player.media_play / media_pause."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Service domain."},
                "service": {"type": "string", "description": "Service name."},
                "entity_id": {
                    "type": "string",
                    "description": "Target entity_id (omit if service has no target).",
                },
                "data": {
                    "type": "object",
                    "description": "Extra service data (brightness, position, temperature…).",
                },
            },
            "required": ["domain", "service"],
        },
    },
]


def get_tools() -> list[dict]:
    return _TOOLS


def dispatch(name: str, args: dict) -> str:
    """Run a tool call and return a JSON-encoded string result.

    Errors are returned as a JSON dict {"error": "..."} so the model can
    recover instead of the whole chain aborting.
    """
    try:
        if name == "ha_list_entities":
            domain = (args or {}).get("domain")
            states = _list_states()
            if domain:
                filtered = [
                    {
                        "entity_id": s["entity_id"],
                        "state": s.get("state"),
                        "attributes": s.get("attributes", {}),
                    }
                    for s in states
                    if s["entity_id"].startswith(f"{domain}.")
                ]
                return json.dumps(filtered, ensure_ascii=False)
            # No filter → only entity_ids to keep tokens manageable
            return json.dumps(sorted(s["entity_id"] for s in states))

        if name == "ha_get_state":
            entity_id = (args or {}).get("entity_id")
            if not entity_id:
                return json.dumps({"error": "entity_id is required"})
            return json.dumps(_get_state(entity_id), ensure_ascii=False)

        if name == "ha_call_service":
            domain = (args or {}).get("domain")
            service = (args or {}).get("service")
            if not domain or not service:
                return json.dumps({"error": "domain and service are required"})
            payload = dict((args or {}).get("data") or {})
            entity_id = (args or {}).get("entity_id")
            if entity_id:
                payload["entity_id"] = entity_id
            result = _call_service(domain, service, payload)
            return json.dumps({"ok": True, "result": result}, ensure_ascii=False)

        return json.dumps({"error": f"unknown tool {name}"})
    except HAError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:  # noqa: BLE001
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


# ---------------------------------------------------------------- Prefs UI

def build_prefs_group() -> Adw.PreferencesGroup:
    """Return a PreferencesGroup that owns its own save logic (no callback needed).

    The group writes to ha.json + keyring as the user edits the fields.
    """
    cfg = _load_cfg()
    token = _load_token() or ""

    group = Adw.PreferencesGroup(
        title=_("Home Assistant"),
        description=_("Let Claude control your Home Assistant (lights, covers, switches…)."),
    )

    enable_row = Adw.SwitchRow()
    enable_row.set_title(_("Enable Home Assistant tools"))
    enable_row.set_subtitle(_("Claude can list entities and call services when this is on."))
    enable_row.set_active(cfg["enabled"])

    url_row = Adw.EntryRow()
    url_row.set_title(_("Home Assistant URL"))
    url_row.set_text(cfg["url"])

    token_row = Adw.PasswordEntryRow()
    token_row.set_title(_("Long-lived access token"))
    token_row.set_text(token)

    def _persist(*_a):
        new_cfg = {
            "enabled": enable_row.get_active(),
            "url": url_row.get_text().strip() or DEFAULT_URL,
        }
        _save_cfg(new_cfg)
        new_token = token_row.get_text().strip()
        if new_token:
            _store_token(new_token)
        elif not new_token and _load_token():
            _clear_token()

    enable_row.connect("notify::active", _persist)
    url_row.connect("changed", _persist)
    token_row.connect("changed", _persist)

    group.add(enable_row)
    group.add(url_row)
    group.add(token_row)
    return group
