from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]

class Settings(BaseSettings):
    app_name: str = "LIA Manuscript"
    data_dir: Path = ROOT / "data"
    max_upload_bytes: int = 15 * 1024 * 1024
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore")

settings = Settings()