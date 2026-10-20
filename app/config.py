from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ScriptFlow AI"
    database_path: Path = Path("data/scriptflow.sqlite3")
    output_dir: Path = Path("data/jobs")
    max_upload_bytes: int = 50 * 1024 * 1024
    max_audio_seconds: int = 15 * 60
    mock_processing_delay_seconds: float = 0.05
    footage_provider: str = "mock"
    pexels_api_key: str | None = None
    pixabay_api_key: str | None = None
    pixabay_min_width: int = 1280
    pixabay_min_height: int = 720
    pixabay_safe_search: bool = True
    pixabay_search_cache_seconds: int = 86400
    pixabay_request_retries: int = 1
    tts_provider: str = "mock"
    tts_api_key: str | None = None
    stt_provider: str = "mock"
    stt_model: str = "base"
    stt_device: str = "cpu"
    stt_compute_type: str = "int8"
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    footage_download_timeout_seconds: int = 30
    max_media_download_bytes: int = 100 * 1024 * 1024
    real_rendering: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")


settings = Settings()
