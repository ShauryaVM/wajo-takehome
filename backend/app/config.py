from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://steward:steward@localhost:5432/steward"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "dev-secret-change-me"
    fernet_key: str = ""

    demo_user_email: str = "you@local"
    demo_user_password: str = "steward"

    app_origin: str = "http://localhost:3000"
    api_origin: str = "http://localhost:8000"

    llm_provider: str = "openai"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    anthropic_model: str = "claude-sonnet-4-5"

    google_client_id: str = ""
    google_client_secret: str = ""
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""
    microsoft_tenant: str = "common"

    cookie_name: str = "steward_session"
    session_hours: int = 24 * 14


settings = Settings()
