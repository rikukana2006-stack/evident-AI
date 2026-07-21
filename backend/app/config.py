from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Evident AI Fukkei Match API"
    database_url: str = "sqlite:///./data/evident_ai.db"
    allowed_origins: list[str] = ["http://localhost:3002"]
    storage_dir: Path = Path("storage")
    ocr_work_dir: Path = Path("storage/ocr_work")
    vision_ocr_provider: str = "stub"
    openai_api_key: str | None = None
    openai_vision_model: str = "gpt-4.1-mini"
    vision_ocr_max_images: int = 30
    paddle_ocr_lang: str = "japan"
    paddle_ocr_version: str = "PP-OCRv3"
    paddle_cache_dir: Path | None = None

    model_config = SettingsConfigDict(env_file=".env", env_prefix="EVIDENT_")


settings = Settings()
