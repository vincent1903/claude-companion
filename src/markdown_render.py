"""Render Markdown into a Gtk.TextBuffer using Gtk.TextTag styles."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango

from markdown_it import MarkdownIt


_MD = MarkdownIt("commonmark", {"breaks": True, "html": False}).enable("strikethrough")


def ensure_tags(buf: Gtk.TextBuffer) -> None:
    """Create the Gtk.TextTags used by render_markdown (idempotent)."""
    table = buf.get_tag_table()

    def add(name, **props):
        if table.lookup(name) is None:
            buf.create_tag(name, **props)

    add("md_bold", weight=Pango.Weight.BOLD)
    add("md_italic", style=Pango.Style.ITALIC)
    add("md_strike", strikethrough=True)
    add("md_code", family="monospace", background="rgba(127,127,127,0.18)")
    add(
        "md_code_block",
        family="monospace",
        background="rgba(127,127,127,0.14)",
        left_margin=24,
        pixels_above_lines=4,
        pixels_below_lines=4,
        wrap_mode=Gtk.WrapMode.NONE,
    )
    add("md_h1", weight=Pango.Weight.BOLD, scale=1.5,
        pixels_above_lines=6, pixels_below_lines=4)
    add("md_h2", weight=Pango.Weight.BOLD, scale=1.3,
        pixels_above_lines=6, pixels_below_lines=4)
    add("md_h3", weight=Pango.Weight.BOLD, scale=1.15,
        pixels_above_lines=4, pixels_below_lines=2)
    add("md_link", foreground="#3584e4", underline=Pango.Underline.SINGLE)
    add("md_quote", style=Pango.Style.ITALIC,
        foreground="rgba(127,127,127,0.95)", left_margin=18)
    add("md_bullet", left_margin=18)


_HEADING_TAGS = {"h1": "md_h1", "h2": "md_h2", "h3": "md_h3",
                 "h4": "md_h3", "h5": "md_h3", "h6": "md_h3"}


def render_markdown(buf: Gtk.TextBuffer, text: str) -> None:
    """Append `text` (markdown) to `buf` with style tags applied."""
    ensure_tags(buf)
    tokens = _MD.parse(text)

    state = {
        "tag_stack": [],
        "list_stack": [],  # list of dicts {"ordered": bool, "index": int}
        "block_tag": None,  # active block-level tag (heading, code_block, quote)
        "first_block": True,
        "suppress_next_break": False,  # set right after list_item_open
    }

    def insert(s: str):
        end = buf.get_end_iter()
        tags = list(state["tag_stack"])
        if state["block_tag"]:
            tags.append(state["block_tag"])
        if tags:
            buf.insert_with_tags_by_name(end, s, *tags)
        else:
            buf.insert(end, s)

    def newline_if_needed():
        end = buf.get_end_iter()
        if buf.get_char_count() == 0:
            return
        end.backward_char()
        if end.get_char() != "\n":
            insert("\n")

    def block_break(double: bool = True):
        if state["first_block"]:
            state["first_block"] = False
            return
        if state["suppress_next_break"]:
            state["suppress_next_break"] = False
            return
        newline_if_needed()
        if double:
            insert("\n")

    def walk_inline(children):
        for tok in children:
            t = tok.type
            if t == "text":
                insert(tok.content)
            elif t == "softbreak":
                insert("\n")
            elif t == "hardbreak":
                insert("\n")
            elif t == "strong_open":
                state["tag_stack"].append("md_bold")
            elif t == "strong_close":
                state["tag_stack"].pop()
            elif t == "em_open":
                state["tag_stack"].append("md_italic")
            elif t == "em_close":
                state["tag_stack"].pop()
            elif t == "s_open":
                state["tag_stack"].append("md_strike")
            elif t == "s_close":
                state["tag_stack"].pop()
            elif t == "code_inline":
                state["tag_stack"].append("md_code")
                insert(tok.content)
                state["tag_stack"].pop()
            elif t == "link_open":
                state["tag_stack"].append("md_link")
            elif t == "link_close":
                state["tag_stack"].pop()
            elif t == "image":
                alt = tok.content or "image"
                insert(f"[{alt}]")
            else:
                # Unknown inline token — fall back to raw content if any
                if getattr(tok, "content", None):
                    insert(tok.content)

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        t = tok.type

        if t == "paragraph_open":
            block_break()
        elif t == "paragraph_close":
            pass

        elif t == "heading_open":
            block_break()
            state["block_tag"] = _HEADING_TAGS.get(tok.tag, "md_h3")
        elif t == "heading_close":
            state["block_tag"] = None

        elif t == "fence" or t == "code_block":
            block_break()
            state["block_tag"] = "md_code_block"
            insert(tok.content.rstrip("\n"))
            state["block_tag"] = None

        elif t == "blockquote_open":
            block_break()
            state["block_tag"] = "md_quote"
            state["suppress_next_break"] = True
        elif t == "blockquote_close":
            state["block_tag"] = None

        elif t == "bullet_list_open":
            if not state["list_stack"]:
                block_break()
            state["list_stack"].append({"ordered": False, "index": 0})
        elif t == "ordered_list_open":
            if not state["list_stack"]:
                block_break()
            start = int(tok.attrs.get("start", 1)) if tok.attrs else 1
            state["list_stack"].append({"ordered": True, "index": start - 1})
        elif t in ("bullet_list_close", "ordered_list_close"):
            state["list_stack"].pop()

        elif t == "list_item_open":
            block_break(double=False)
            if state["list_stack"]:
                lst = state["list_stack"][-1]
                if lst["ordered"]:
                    lst["index"] += 1
                    marker = f"{lst['index']}. "
                else:
                    marker = "• "
                indent = "  " * (len(state["list_stack"]) - 1)
                state["tag_stack"].append("md_bullet")
                insert(indent + marker)
                state["suppress_next_break"] = True
        elif t == "list_item_close":
            if state["tag_stack"] and state["tag_stack"][-1] == "md_bullet":
                state["tag_stack"].pop()

        elif t == "hr":
            block_break()
            insert("─" * 20)

        elif t == "inline":
            walk_inline(tok.children or [])

        i += 1
