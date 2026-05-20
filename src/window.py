#!/usr/bin/env python3
import argparse
import os
import sys
import threading
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"))
_LOG_PATH = _DATA_HOME / "claude-companion" / "window.log"
_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
_LOG = open(_LOG_PATH, "a", buffering=1)
def _log(msg):
    _LOG.write(f"[pid={os.getpid()}] {msg}\n")

_log(f"--- start argv={sys.argv} ---")
_log(f"DISPLAY={os.environ.get('DISPLAY')} WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY')} XDG_RUNTIME_DIR={os.environ.get('XDG_RUNTIME_DIR')}")

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gdk, Gio, Pango

import config as quick_config
import i18n
i18n.setup(quick_config.load().get("language", "system"))
from i18n import _

from api import ClaudeChat
from keyring import load_api_key, store_api_key
from markdown_render import ensure_tags, render_markdown

# Optional Home Assistant bonus (not in public git).
try:
    import homeassistant as _ha
except ImportError:
    _ha = None

APP_ID = "org.little_home.ClaudeCompanion"
APP_NAME = "Claude Companion"


def _theme_options():
    return [
        ("system", _("System")),
        ("light", _("Light")),
        ("dark", _("Dark")),
    ]


_THEME_MAP = {
    "system": Adw.ColorScheme.DEFAULT,
    "light": Adw.ColorScheme.FORCE_LIGHT,
    "dark": Adw.ColorScheme.FORCE_DARK,
}


def _model_label(model_id: str) -> str:
    labels = {
        "claude-haiku-4-5-20251001": _("Claude Haiku 4.5 (fast, economical)"),
        "claude-sonnet-4-6": _("Claude Sonnet 4.6 (balanced)"),
        "claude-opus-4-7": _("Claude Opus 4.7 (most powerful)"),
    }
    return labels.get(model_id, model_id)


def _language_label(lang_id: str) -> str:
    if lang_id == "system":
        return _("System")
    # Language proper names stay in their own language.
    return dict(quick_config.AVAILABLE_LANGUAGES).get(lang_id, lang_id)


def _apply_theme(theme: str) -> None:
    sm = Adw.StyleManager.get_default()
    sm.set_color_scheme(_THEME_MAP.get(theme, Adw.ColorScheme.DEFAULT))


def _index_by_id(items, target_id, fallback=0):
    for i, (item_id, _label) in enumerate(items):
        if item_id == target_id:
            return i
    return fallback


class QuickWindow(Adw.ApplicationWindow):
    def __init__(self, app, initial_prompt: str = ""):
        super().__init__(application=app, title=APP_NAME)
        self.set_default_size(760, 560)
        self.streaming = False

        api_key = load_api_key()
        if not api_key:
            self._build_key_prompt(initial_prompt)
            return

        self.cfg = quick_config.load()
        self.chat = ClaudeChat(
            api_key=api_key,
            model=self.cfg["model"],
            system_prompt=self.cfg["system_prompt"],
            max_tokens=self.cfg["max_tokens"],
            language=self.cfg["language"],
        )
        self._build_chat_ui()

        if initial_prompt:
            self.entry.set_text(initial_prompt)
            GLib.idle_add(self.on_send, None)

    # -- UI when no API key is stored ------------------------------------
    def _build_key_prompt(self, initial_prompt: str):
        self._pending_prompt = initial_prompt
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())

        clamp = Adw.Clamp(maximum_size=480)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=24, margin_bottom=24, margin_start=24, margin_end=24)
        title = Gtk.Label(label=_("Anthropic API key required"))
        title.add_css_class("title-2")
        title.set_xalign(0)
        sub = Gtk.Label(label=_("Paste your sk-ant-… key and confirm. Stored in the GNOME keyring."))
        sub.set_wrap(True)
        sub.set_xalign(0)
        sub.add_css_class("dim-label")
        entry = Gtk.PasswordEntry()
        entry.set_show_peek_icon(True)
        save = Gtk.Button(label=_("Save"))
        save.add_css_class("suggested-action")

        def on_save(_):
            key = entry.get_text().strip()
            if not key.startswith("sk-ant-"):
                sub.set_text(_("Invalid key (must start with sk-ant-)."))
                sub.remove_css_class("dim-label")
                sub.add_css_class("error")
                return
            store_api_key(key)
            self.cfg = quick_config.load()
            self.chat = ClaudeChat(
                api_key=key,
                model=self.cfg["model"],
                system_prompt=self.cfg["system_prompt"],
                max_tokens=self.cfg["max_tokens"],
                language=self.cfg["language"],
            )
            self._swap_to_chat(self._pending_prompt)

        save.connect("clicked", on_save)
        entry.connect("activate", on_save)

        box.append(title); box.append(sub); box.append(entry); box.append(save)
        clamp.set_child(box)
        toolbar.set_content(clamp)
        self.set_content(toolbar)

    def _swap_to_chat(self, initial_prompt: str):
        self._build_chat_ui()
        if initial_prompt:
            self.entry.set_text(initial_prompt)
            GLib.idle_add(self.on_send, None)

    # -- Chat UI ---------------------------------------------------------
    def _build_chat_ui(self):
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()

        reset_btn = Gtk.Button.new_from_icon_name("edit-clear-all-symbolic")
        reset_btn.set_tooltip_text(_("New conversation"))
        reset_btn.connect("clicked", self.on_reset)
        header.pack_start(reset_btn)

        prefs_btn = Gtk.Button.new_from_icon_name("emblem-system-symbolic")
        prefs_btn.set_tooltip_text(_("Preferences"))
        prefs_btn.connect("clicked", self.on_open_prefs)
        header.pack_end(prefs_btn)

        toolbar.add_top_bar(header)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll = scroll

        self.textview = Gtk.TextView()
        self.textview.set_editable(False)
        self.textview.set_cursor_visible(False)
        self.textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.textview.set_top_margin(12)
        self.textview.set_bottom_margin(12)
        self.textview.set_left_margin(14)
        self.textview.set_right_margin(14)
        buf = self.textview.get_buffer()
        buf.create_tag("user", weight=Pango.Weight.BOLD)
        buf.create_tag("assistant_label", weight=Pango.Weight.BOLD,
                       foreground="#c97b46")
        buf.create_tag("error", foreground="#cc3030", style=Pango.Style.ITALIC)
        ensure_tags(buf)
        self.response_start_mark = None
        scroll.set_child(self.textview)
        vbox.append(scroll)

        entry_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                            margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
        self.entry = Gtk.Entry()
        self.entry.set_hexpand(True)
        self.entry.set_placeholder_text(_("Ask anything…"))
        self.entry.connect("activate", self.on_send)
        entry_row.append(self.entry)

        self.send_btn = Gtk.Button.new_from_icon_name("document-send-symbolic")
        self.send_btn.add_css_class("suggested-action")
        self.send_btn.connect("clicked", self.on_send)
        entry_row.append(self.send_btn)
        vbox.append(entry_row)

        toolbar.set_content(vbox)
        self.set_content(toolbar)

        close_action = Gio.SimpleAction.new("close", None)
        close_action.connect("activate", lambda *_: self.close())
        self.add_action(close_action)
        app = self.get_application()
        if app is not None:
            app.set_accels_for_action("win.close", ["Escape"])

        def _grab_focus():
            self.entry.grab_focus()
            return False
        GLib.idle_add(_grab_focus)

    def _append(self, text: str, *tags: str):
        buf = self.textview.get_buffer()
        end = buf.get_end_iter()
        if tags:
            buf.insert_with_tags_by_name(end, text, *tags)
        else:
            buf.insert(end, text)
        adj = self.scroll.get_vadjustment()
        adj.set_value(adj.get_upper())

    def on_send(self, _btn):
        if self.streaming:
            return
        text = self.entry.get_text().strip()
        if not text:
            return
        self.entry.set_text("")

        buf = self.textview.get_buffer()
        if buf.get_char_count() > 0:
            self._append("\n\n")
        self._append(_("You") + " : ", "user")
        self._append(text + "\n\n")
        self._append("Claude : ", "assistant_label")
        self.response_start_mark = buf.create_mark(
            None, buf.get_end_iter(), left_gravity=True
        )

        self.streaming = True
        self.send_btn.set_sensitive(False)

        def worker():
            try:
                self.chat.stream(text, lambda c: GLib.idle_add(self._append, c))
            except Exception as e:
                msg = "\n[" + _("error") + f": {e}]"
                GLib.idle_add(self._append, msg, "error")
            finally:
                GLib.idle_add(self._on_stream_done)

        threading.Thread(target=worker, daemon=True).start()

    def _on_stream_done(self):
        self._render_response_markdown()
        self.streaming = False
        self.send_btn.set_sensitive(True)
        self.entry.grab_focus()
        return False

    def _render_response_markdown(self):
        mark = self.response_start_mark
        if mark is None:
            return
        buf = self.textview.get_buffer()
        start = buf.get_iter_at_mark(mark)
        end = buf.get_end_iter()
        raw = buf.get_text(start, end, True)
        if not raw.strip():
            return
        buf.delete(start, end)
        render_markdown(buf, raw)
        buf.delete_mark(mark)
        self.response_start_mark = None
        adj = self.scroll.get_vadjustment()
        adj.set_value(adj.get_upper())

    def on_reset(self, _btn):
        if self.streaming:
            return
        self.chat.reset()
        self.textview.get_buffer().set_text("")

    # -- Preferences -----------------------------------------------------
    def on_open_prefs(self, _btn):
        dlg = Adw.PreferencesDialog()
        dlg.set_title(_("Preferences"))

        page = Adw.PreferencesPage()

        # --- Appearance & language ------------------------------------
        ui_group = Adw.PreferencesGroup(title=_("Appearance and language"))

        theme_options = _theme_options()
        theme_row = Adw.ComboRow()
        theme_row.set_title(_("Theme"))
        theme_model = Gtk.StringList.new([label for _id, label in theme_options])
        theme_row.set_model(theme_model)
        theme_row.set_selected(_index_by_id(theme_options, self.cfg.get("theme", "system")))

        def on_theme_changed(row, _pspec):
            _apply_theme(theme_options[row.get_selected()][0])

        theme_row.connect("notify::selected", on_theme_changed)
        ui_group.add(theme_row)

        lang_items = [(lid, _language_label(lid)) for lid, _label in quick_config.AVAILABLE_LANGUAGES]
        lang_row = Adw.ComboRow()
        lang_row.set_title(_("Language"))
        lang_row.set_subtitle(_("Interface and Claude reply language (restart required for UI)"))
        lang_model = Gtk.StringList.new([label for _id, label in lang_items])
        lang_row.set_model(lang_model)
        lang_row.set_selected(_index_by_id(lang_items, self.cfg.get("language", "system")))
        ui_group.add(lang_row)

        page.add(ui_group)

        # --- System prompt --------------------------------------------
        prompt_group = Adw.PreferencesGroup(
            title=_("System instructions"),
            description=_("Sent with every message as permanent context."),
        )
        prompt_view = Gtk.TextView()
        prompt_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        prompt_view.set_top_margin(8); prompt_view.set_bottom_margin(8)
        prompt_view.set_left_margin(8); prompt_view.set_right_margin(8)
        prompt_view.get_buffer().set_text(self.cfg.get("system_prompt", ""))
        prompt_scroll = Gtk.ScrolledWindow()
        prompt_scroll.set_min_content_height(120)
        prompt_scroll.set_child(prompt_view)
        prompt_scroll.add_css_class("card")
        prompt_group.add(prompt_scroll)
        page.add(prompt_group)

        # --- Model ----------------------------------------------------
        model_group = Adw.PreferencesGroup(title=_("Model"))

        model_items = [(mid, _model_label(mid)) for mid, _label in quick_config.AVAILABLE_MODELS]
        model_row = Adw.ComboRow()
        model_row.set_title(_("Claude model"))
        model_model = Gtk.StringList.new([label for _id, label in model_items])
        model_row.set_model(model_model)
        model_row.set_selected(_index_by_id(model_items, self.cfg.get("model")))
        model_group.add(model_row)

        tokens_row = Adw.SpinRow.new_with_range(256, 16384, 256)
        tokens_row.set_title(_("Max tokens per response"))
        tokens_row.set_value(self.cfg.get("max_tokens", 4096))
        model_group.add(tokens_row)
        page.add(model_group)

        # --- Home Assistant (bonus, untracked) ------------------------
        if _ha is not None:
            page.add(_ha.build_prefs_group())

        dlg.add(page)

        def on_close(_dlg):
            buf = prompt_view.get_buffer()
            new_prompt = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True).strip()
            new_model = model_items[model_row.get_selected()][0]
            new_tokens = int(tokens_row.get_value())
            new_theme = theme_options[theme_row.get_selected()][0]
            new_lang = lang_items[lang_row.get_selected()][0]

            self.cfg["system_prompt"] = new_prompt
            self.cfg["model"] = new_model
            self.cfg["max_tokens"] = new_tokens
            self.cfg["theme"] = new_theme
            self.cfg["language"] = new_lang
            quick_config.save(self.cfg)

            self.chat.system_prompt = new_prompt
            self.chat.model = new_model
            self.chat.max_tokens = new_tokens
            self.chat.language = new_lang

            i18n.setup(new_lang)  # New dynamic strings will use the new language
            _apply_theme(new_theme)

        dlg.connect("closed", on_close)
        dlg.present(self)


class QuickApp(Adw.Application):
    def __init__(self, prompt: str = ""):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.prompt = prompt

    def do_activate(self):
        _log("do_activate")
        cfg = quick_config.load()
        _apply_theme(cfg.get("theme", "system"))
        win = QuickWindow(self, initial_prompt=self.prompt)
        win.present()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="")
    args = parser.parse_args()
    app = QuickApp(prompt=args.prompt)
    try:
        rc = app.run([])
    except Exception:
        _log("exception in app.run():\n" + traceback.format_exc())
        rc = 1
    sys.exit(rc)


if __name__ == "__main__":
    main()
