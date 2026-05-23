from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    # Comma-separated list for UI dropdown (override via OPENAI_MODELS in .env)
    openai_models: str = (
        "gpt-4o-mini,gpt-4o,gpt-4-turbo,gpt-4,gpt-3.5-turbo,o1-mini,o3-mini"
    )
    data_dir: Path = BACKEND_ROOT / "data" / "sample"
    upload_dir: Path = BACKEND_ROOT / "data" / "uploads"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origin_list(self):
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def openai_model_list(self) -> list:
        models = [m.strip() for m in self.openai_models.split(",") if m.strip()]
        if self.openai_model and self.openai_model not in models:
            models.insert(0, self.openai_model)
        return models or [self.openai_model]


settings = Settings()


def is_openai_configured() -> bool:
    """True only when a real API key is set (not empty or .env.example placeholder)."""
    key = (settings.openai_api_key or "").strip()
    if not key:
        return False
    placeholders = ("sk-your", "your-key", "changeme", "xxx")
    lower = key.lower()
    return not any(lower.startswith(p) or p in lower for p in placeholders)
