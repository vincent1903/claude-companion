from anthropic import Anthropic, APIStatusError, APIConnectionError

from config import DEFAULT_MODEL, DEFAULT_MAX_TOKENS, DEFAULT_SYSTEM_PROMPT, DEFAULT_LANGUAGE

try:
    from i18n import _
except ImportError:
    def _(s: str) -> str:
        return s

# Optional Home Assistant bonus (not in public git).
try:
    import homeassistant as _ha
except ImportError:
    _ha = None

# Per-language reply directives appended to the system prompt.
# "system" means: don't inject — let Claude infer from the user's message.
_LANGUAGE_DIRECTIVES = {
    "system": "",
    "fr": "Réponds toujours en français.",
    "en": "Always reply in English.",
    "de": "Antworte immer auf Deutsch.",
    "es": "Responde siempre en español.",
    "it": "Rispondi sempre in italiano.",
}


def _compose_system(system_prompt: str, language: str) -> str:
    directive = _LANGUAGE_DIRECTIVES.get(language, "")
    parts = [p for p in (system_prompt.strip() if system_prompt else "", directive) if p]
    return "\n\n".join(parts)


def _friendly_error(e: Exception) -> str:
    if isinstance(e, APIStatusError):
        etype = None
        body = getattr(e, "body", None)
        if isinstance(body, dict):
            etype = (body.get("error") or {}).get("type")
        if etype == "overloaded_error" or e.status_code == 529:
            return _("Claude is temporarily overloaded — try again in a few seconds.")
        if e.status_code == 429:
            return _("Rate limit reached — wait a moment before retrying.")
        return _("API error") + f" ({e.status_code})."
    if isinstance(e, APIConnectionError):
        return _("Could not reach the Claude API — check your connection.")
    return str(e)


def _block_to_dict(b) -> dict | None:
    """Convert an SDK content block back to a plain dict for re-sending."""
    t = getattr(b, "type", None)
    if t == "text":
        return {"type": "text", "text": b.text}
    if t == "tool_use":
        return {
            "type": "tool_use",
            "id": b.id,
            "name": b.name,
            "input": dict(b.input or {}),
        }
    return None


class ClaudeChat:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        language: str = DEFAULT_LANGUAGE,
    ):
        self.client = Anthropic(api_key=api_key, max_retries=5)
        self.model = model
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.language = language
        self.messages: list[dict] = []

    def stream(self, user_message: str, on_chunk):
        use_tools = False
        if _ha is not None:
            try:
                use_tools = _ha.is_enabled()
            except Exception:
                use_tools = False

        # Roll back to this length if the turn fails, so a partial tool chain
        # never leaves a dangling tool_use / tool_result in the history.
        snapshot = len(self.messages)
        self.messages.append({"role": "user", "content": user_message})

        full_text: list[str] = []
        first_turn = True

        try:
            while True:
                kwargs = dict(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    messages=self.messages,
                )
                system = _compose_system(self.system_prompt, self.language)
                if system:
                    kwargs["system"] = system
                if use_tools:
                    kwargs["tools"] = _ha.get_tools()

                with self.client.messages.stream(**kwargs) as stream:
                    if not first_turn:
                        on_chunk("\n\n")
                        full_text.append("\n\n")
                    for text in stream.text_stream:
                        full_text.append(text)
                        on_chunk(text)
                    final = stream.get_final_message()
                first_turn = False

                # Preserve full content blocks (tool_use + text) so the next turn
                # can reference the tool_use_id in its tool_result.
                blocks = [d for d in (_block_to_dict(b) for b in final.content) if d]
                self.messages.append({"role": "assistant", "content": blocks})

                if final.stop_reason != "tool_use":
                    break

                tool_results = []
                for block in final.content:
                    if getattr(block, "type", None) != "tool_use":
                        continue
                    result = _ha.dispatch(block.name, dict(block.input or {}))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
                self.messages.append({"role": "user", "content": tool_results})
        except Exception as e:
            self.messages = self.messages[:snapshot]
            raise RuntimeError(_friendly_error(e)) from e

        return "".join(full_text)

    def reset(self):
        self.messages = []
