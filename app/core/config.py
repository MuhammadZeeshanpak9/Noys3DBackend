from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"  # Ignore extra fields in .env
    )

    supabase_url: str = "https://vwizhzbdnpraxfhaokpu.supabase.co"
    supabase_anon_key: str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ3aXpoemJkbnByYXhmaGFva3B1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUyODE0NDQsImV4cCI6MjA5MDg1NzQ0NH0.Ix1Xtam4MW8IKmqVZGX4EwWtsc2oj_aPLewagVLxDFM"

    jwt_secret_key: str = "noys-3d-prints-secret-key-change-in-production-2024"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 10080

    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""

    tripo_api_key: str = ""

    supabase_service_key: str = ""

    resend_api_key: str = ""
    admin_email: str = "orders@noys3dprints.co.uk"
    frontend_url: str = "https://noys-3d-print.vercel.app"

    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = ["*"]


@lru_cache()
def get_settings() -> Settings:
    return Settings()
