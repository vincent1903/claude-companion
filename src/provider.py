#!/usr/bin/env python3
"""GNOME Shell SearchProvider2 D-Bus service that opens a QuickClaude window.

Works both in a Flatpak sandbox (uses /app/bin/claude-companion) and in dev
mode (uses the local venv next to this file).
"""
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

import gi
from gi.repository import GLib, Gio

import config as quick_config
import i18n
i18n.setup(quick_config.load().get("language", "system"))
from i18n import _

_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"))
_PLOG_PATH = _DATA_HOME / "claude-companion" / "provider.log"
_PLOG_PATH.parent.mkdir(parents=True, exist_ok=True)
_PLOG = open(_PLOG_PATH, "a", buffering=1)
def _plog(msg):
    _PLOG.write(f"{time.strftime('%H:%M:%S')} [pid={os.getpid()}] {msg}\n")

_plog(f"=== provider START argv={sys.argv} ===")

BUS_NAME = "org.little_home.ClaudeCompanion.SearchProvider"
OBJECT_PATH = "/org/little_home/ClaudeCompanion/SearchProvider"
RESULT_PREFIX = "ask:"


def _result_id_for(terms: list[str]) -> str:
    # GNOME Shell caches GetResultMetas by (provider, result_id), so we embed
    # the current query in the id to force a metas refresh on every keystroke.
    return RESULT_PREFIX + " ".join(terms)


def _resolve_window_cmd() -> list[str]:
    """Return the argv to spawn the chat window."""
    override = os.environ.get("CLAUDE_QUICK_WINDOW_CMD")
    if override:
        return override.split()
    if Path("/.flatpak-info").exists():
        # Inside the Flatpak sandbox.
        return ["/app/bin/claude-companion"]
    # Dev mode: use the local venv next to this file.
    base = Path(__file__).parent
    return [str(base / "venv" / "bin" / "python"), str(base / "window.py")]


INTERFACE_XML = """
<node>
  <interface name="org.gnome.Shell.SearchProvider2">
    <method name="GetInitialResultSet">
      <arg type="as" name="terms" direction="in"/>
      <arg type="as" name="results" direction="out"/>
    </method>
    <method name="GetSubsearchResultSet">
      <arg type="as" name="previous_results" direction="in"/>
      <arg type="as" name="terms" direction="in"/>
      <arg type="as" name="results" direction="out"/>
    </method>
    <method name="GetResultMetas">
      <arg type="as" name="identifiers" direction="in"/>
      <arg type="aa{sv}" name="metas" direction="out"/>
    </method>
    <method name="ActivateResult">
      <arg type="s" name="identifier" direction="in"/>
      <arg type="as" name="terms" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="LaunchSearch">
      <arg type="as" name="terms" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
  </interface>
</node>
"""


class Provider:
    def __init__(self):
        self.last_terms: list[str] = []
        node = Gio.DBusNodeInfo.new_for_xml(INTERFACE_XML)
        self.iface = node.interfaces[0]
        self.window_cmd = _resolve_window_cmd()
        _plog(f"window_cmd = {self.window_cmd}")
        self.idle_timeout_id = None
        self._schedule_idle_quit()

    def run(self):
        _plog("run() called")
        self.loop = GLib.MainLoop()
        Gio.bus_own_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameOwnerFlags.NONE,
            self._on_bus_acquired,
            self._on_name_acquired,
            self._on_name_lost,
        )
        _plog("entering loop")
        try:
            self.loop.run()
            _plog("loop exited normally")
        except Exception:
            _plog("loop crashed:\n" + traceback.format_exc())
            sys.exit(2)

    def _on_bus_acquired(self, conn, _name):
        _plog(f"bus_acquired {_name}")
        try:
            conn.register_object(OBJECT_PATH, self.iface, self._dispatch, None, None)
            _plog("register_object OK")
        except Exception:
            _plog("register_object failed:\n" + traceback.format_exc())

    def _on_name_acquired(self, _conn, _name):
        _plog(f"name_acquired {_name}")

    def _on_name_lost(self, _conn, _name):
        _plog(f"name_lost {_name} — exiting 1")
        sys.exit(1)

    def _dispatch(self, _conn, _sender, _path, _iface, method, params, invocation):
        self._touch_idle()
        try:
            if method == "GetInitialResultSet":
                terms = params.unpack()[0]
                self.last_terms = list(terms)
                results = [_result_id_for(self.last_terms)] if terms else []
                invocation.return_value(GLib.Variant("(as)", (results,)))
            elif method == "GetSubsearchResultSet":
                terms = params.unpack()[1]
                self.last_terms = list(terms)
                results = [_result_id_for(self.last_terms)] if terms else []
                invocation.return_value(GLib.Variant("(as)", (results,)))
            elif method == "GetResultMetas":
                ids = params.unpack()[0]
                metas = []
                for rid in ids:
                    if rid.startswith(RESULT_PREFIX):
                        query = rid[len(RESULT_PREFIX):]
                        display = query if len(query) <= 80 else query[:77] + "…"
                        metas.append({
                            "id": GLib.Variant("s", rid),
                            "name": GLib.Variant("s", _("Ask Claude") + f" : {display}"),
                            "description": GLib.Variant("s", _("Open a chat window with Claude")),
                            "gicon": GLib.Variant("s", "system-search-symbolic"),
                        })
                invocation.return_value(GLib.Variant("(aa{sv})", (metas,)))
            elif method == "ActivateResult":
                terms = params.unpack()[1]
                self._launch(" ".join(terms))
                invocation.return_value(None)
            elif method == "LaunchSearch":
                terms = params.unpack()[0]
                self._launch(" ".join(terms))
                invocation.return_value(None)
            else:
                invocation.return_dbus_error(
                    "org.gnome.Shell.SearchProvider2.Error.NoSuchMethod",
                    f"Unknown method {method}",
                )
        except Exception as e:
            invocation.return_dbus_error(
                "org.little_home.ClaudeCompanion.Error",
                f"{type(e).__name__}: {e}",
            )

    def _launch(self, prompt: str):
        log = _DATA_HOME / "claude-companion" / "launch.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        argv = list(self.window_cmd) + ["--prompt", prompt]
        try:
            proc = subprocess.Popen(
                argv,
                stdout=open(log, "ab"),
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            with open(log, "ab") as f:
                f.write(f"[launched pid={proc.pid} argv={argv!r}]\n".encode())
        except Exception as e:
            with open(log, "ab") as f:
                f.write(f"[launch error {type(e).__name__}: {e}]\n".encode())

    def _schedule_idle_quit(self):
        if self.idle_timeout_id:
            GLib.source_remove(self.idle_timeout_id)
        self.idle_timeout_id = GLib.timeout_add_seconds(300, self._quit_idle)

    def _touch_idle(self):
        self._schedule_idle_quit()

    def _quit_idle(self):
        self.loop.quit()
        return False


if __name__ == "__main__":
    Provider().run()
