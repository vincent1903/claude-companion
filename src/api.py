from anthropic import Anthropic

from config import DEFAULT_MODEL, DEFAULT_MAX_TOKENS, DEFAULT_SYSTEM_PROMPT, DEFAULT_LANGUAGE

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


class ClaudeChat:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        language: str = DEFAULT_LANGUAGE,
    ):
        self.client = Anthropic(api_key=api_key)
        self.model = model
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.language = language
        self.messages: list[dict] = []

    def stream(self, user_message: str, on_chunk):
        self.messages.append({"role": "user", "content": user_message})
        full = []
        kwargs = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=self.messages,
        )
        system = _compose_system(self.system_prompt, self.language)
        if system:
            kwargs["system"] = system
        with self.client.messages.stream(**kwargs) as stream:
            for text in stream.text_stream:
                full.append(text)
                on_chunk(text)
        response = "".join(full)
        self.messages.append({"role": "assistant", "content": response})
        return response

    def reset(self):
        self.messages = []
