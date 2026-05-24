from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    DATABASE_URL: str = "postgresql+asyncpg://routeiq:routeiq_secret@localhost:5432/routeiq"
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    OSRM_URL: str = "http://localhost:5000"

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ALGORITHM: str = "HS256"

    SIM_EMAIL: str = "simulator@routeiq.local"
    SIM_PASSWORD: str = "sim-secret-2026"

    OPENWEATHER_API_KEY: str = ""


settings = Settings()
