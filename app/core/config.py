"""
config.py — Application Configuration
--------------------------------------
Loads all environment variables from .env using pydantic-settings.
Provides a single `settings` singleton used across the entire app.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── GitHub OAuth App Credentials ──────────────────────────────────────────
    GITHUB_CLIENT_ID: str
    GITHUB_CLIENT_SECRET: str

    # ── OAuth Callback URL ─────────────────────────────────────────────────────
    # Defaults to localhost for local dev; override in Render env vars
    CALLBACK_URL: str = "http://localhost:8000/auth/callback"

    # ── MongoDB ────────────────────────────────────────────────────────────────
    MONGO_URI: str

    # ── App Metadata ───────────────────────────────────────────────────────────
    APP_NAME: str = "GitHub OAuth Connector"
    APP_VERSION: str = "1.0.0"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # silently ignore unexpected env vars
    )


# Singleton — import this object everywhere instead of re-instantiating
settings = Settings()
