from pydantic_settings import BaseSettings
from typing import List, Optional


class Settings(BaseSettings):
    app_name: str = "guangya-resource-bot"
    debug: bool = False
    secret_key: str = "dev-secret-key"

    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/guangya"
    redis_url: str = "redis://redis:6379/0"

    admin_username: str = "admin"
    admin_password: str = "admin123"

    guangya_api_base: str = "https://api.guangyapan.com"
    guangya_account_base: str = "https://account.guangyapan.com"

    worker_max_concurrent: int = 2
    worker_poll_interval: int = 10
    worker_max_retries: int = 3
    worker_task_timeout: int = 300

    api_key_salt: str = "change-this-salt"
    jwt_expire_minutes: int = 1440
    cors_origins: List[str] = ["http://localhost:5173"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
