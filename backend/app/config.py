from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
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
    shared_data_dir: Path = Field(
        default=BACKEND_ROOT / "data" / "sample",
        validation_alias=AliasChoices("SHARED_DATA_DIR", "DATA_DIR"),
    )
    # local = read CSVs from shared_data_dir on disk; google_drive = sync folder via API
    data_source: str = "local"
    google_drive_folder_id: str = ""
    # Inline service-account JSON for Render (alternative: GOOGLE_APPLICATION_CREDENTIALS path)
    google_service_account_json: str = ""
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @model_validator(mode="after")
    def normalize_shared_data_dir(self) -> "Settings":
        """Resolve relative DATA_DIR/SHARED_DATA_DIR against the backend root."""
        p = self.shared_data_dir
        if not p.is_absolute():
            object.__setattr__(self, "shared_data_dir", (BACKEND_ROOT / p).resolve())
        return self

    @property
    def data_dir(self) -> Path:
        """Backward-compatible alias for shared_data_dir."""
        return self.shared_data_dir

    @property
    def uses_google_drive(self) -> bool:
        return self.data_source.strip().lower() == "google_drive"

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
