"""Pydantic Settings: loads .env and provides typed configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

def _find_project_root() -> Path:
    """Find the project root by looking for config/ directory.

    Checks (in order):
    1. SENTI_ROOT env var (explicit override)
    2. Current working directory (covers `python -m senti` and Docker WORKDIR)
    3. Relative to source file (covers editable installs / development)
    """
    import os

    env_root = os.environ.get("SENTI_ROOT")
    if env_root:
        return Path(env_root)

    cwd = Path.cwd()
    if (cwd / "config").is_dir():
        return cwd

    source_root = Path(__file__).resolve().parent.parent.parent
    if (source_root / "config").is_dir():
        return source_root

    return cwd


PROJECT_ROOT = _find_project_root()
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    telegram_bot_token: str = ""
    allowed_telegram_user_ids: list[int] = []

    # LLM
    ollama_host: str = "http://localhost:11434"
    llm_model: str = "ollama_chat/llama3"
    openai_api_key: str = ""
    gemini_api_key: str = ""
    anthropic_api_key: str = ""

    # Brave Search
    brave_api_key: str = ""

    # Google Drive
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""

    # Gmail (OAuth2 — uses same client ID/secret as Google Drive)
    gmail_refresh_token: str = ""  # separate token with gmail.readonly + gmail.compose scopes
    gmail_label: str = "Senti"    # Gmail label Senti can read (nothing else)

    # Security / limits
    max_tool_rounds: int = 10
    max_result_chars: int = 4000
    conversation_window_size: int = 20
    llm_max_retries: int = 3

    # Memory
    session_idle_timeout_minutes: int = 30
    memory_context_tokens: int = 1500

    # File uploads
    upload_max_file_size_bytes: int = 10 * 1024 * 1024      # 10 MB
    upload_inline_threshold_bytes: int = 100 * 1024          # 100 KB
    upload_allowed_mime_prefixes: list[str] = [
        "text/", "application/json", "application/csv",
        "application/xml", "application/x-yaml",
    ]


    @field_validator("allowed_telegram_user_ids", mode="before")
    @classmethod
    def parse_user_ids(cls, v: str | list | int) -> list[int]:
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            if not v.strip():
                return []
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v

    @property
    def personality_path(self) -> Path:
        return CONFIG_DIR / "personality.md"

    @property
    def models_config_path(self) -> Path:
        return CONFIG_DIR / "models.yaml"

    @property
    def skills_config_path(self) -> Path:
        return CONFIG_DIR / "skills.yaml"

    @property
    def redaction_config_path(self) -> Path:
        return CONFIG_DIR / "redaction_patterns.yaml"

    @property
    def schedules_config_path(self) -> Path:
        return CONFIG_DIR / "schedules.yaml"

    @property
    def memories_dir(self) -> Path:
        return DATA_DIR / "memories"

    @property
    def db_path(self) -> Path:
        return DATA_DIR / "senti.db"

    @property
    def uploads_dir(self) -> Path:
        return DATA_DIR / "uploads"

    @property
    def log_dir(self) -> Path:
        return DATA_DIR / "logs"

    def sensitive_values(self) -> set[str]:
        """Return set of non-empty secret values for redaction."""
        fields = [
            self.telegram_bot_token,
            self.brave_api_key,
            self.google_client_id,
            self.google_client_secret,
            self.google_refresh_token,
            self.gmail_refresh_token,
            self.openai_api_key,
            self.gemini_api_key,
            self.anthropic_api_key,
        ]
        return {v for v in fields if v and len(v) > 4}


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
