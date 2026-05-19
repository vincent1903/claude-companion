import gi
gi.require_version("Secret", "1")
from gi.repository import Secret

SCHEMA = Secret.Schema.new(
    "org.little_home.ClaudeCompanion.ApiKey",
    Secret.SchemaFlags.NONE,
    {"service": Secret.SchemaAttributeType.STRING},
)
ATTRS = {"service": "anthropic-api"}


def store_api_key(key: str) -> None:
    Secret.password_store_sync(
        SCHEMA, ATTRS, Secret.COLLECTION_DEFAULT,
        "Anthropic API key for QuickClaude", key, None,
    )


def load_api_key() -> str | None:
    return Secret.password_lookup_sync(SCHEMA, ATTRS, None)


def clear_api_key() -> None:
    Secret.password_clear_sync(SCHEMA, ATTRS, None)
