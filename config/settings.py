from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ─────────────────────────────────────────────────
    DB_HOST: str
    DB_PORT: int = 5432
    DB_NAME: str
    DB_USER: str
    DB_PASSWORD: str
    DB_MIN_CONN: int = 2
    DB_MAX_CONN: int = 10

    # ── Authorize.net ─────────────────────────────────────────────
    AUTHORIZE_NET_API_LOGIN_ID: str
    AUTHORIZE_NET_TRANSACTION_KEY: str
    AUTHORIZE_NET_URL: str = "https://api.authorize.net/xml/v1/request.api"

    # ── Payment filtering ─────────────────────────────────────────
    # Comma-separated list of payment types to include in the report.
    # Example: "credit-card" or "credit-card,paypal,stripe"
    PAYMENT_TYPES: str = "credit-card"

    # ── App ───────────────────────────────────────────────────────
    APP_ENV: str = "production"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # ── Authorize.net concurrency ─────────────────────────────────
    # Max parallel threads for Authorize.net transaction lookups.
    AUTHORIZE_MAX_WORKERS: int = 5


# Singleton — imported everywhere
settings = Settings()