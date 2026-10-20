from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_validator

AspectRatio = Literal["16:9", "9:16", "1:1"]


class Captions(BaseModel):
    burn_in: bool = False
    srt: bool = True


class SceneInput(BaseModel):
    narration: str = Field(min_length=1, max_length=5000)
    visual_hint: str | None = Field(default=None, max_length=500)


class JobRequest(BaseModel):
    script: str | None = Field(default=None, max_length=50_000)
    audio_url: str | None = None
    scenes: list[SceneInput] | None = None
    voice: str = "en-IN-female"
    aspect_ratios: list[AspectRatio] = Field(default_factory=lambda: ["16:9"])
    style: str = Field(default="bright, modern, real-world footage", max_length=500)
    avoid: list[str] = Field(default_factory=list, max_length=50)
    captions: Captions = Field(default_factory=Captions)
    render: bool = False

    @model_validator(mode="after")
    def validate_input(self) -> "JobRequest":
        if not any((self.script and self.script.strip(), self.audio_url, self.scenes)):
            raise ValueError("Provide a non-empty script, audio_url, or scene list")
        if not self.aspect_ratios:
            raise ValueError("At least one aspect ratio is required")
        return self


class JobResponse(BaseModel):
    job_id: str
    status: Literal["queued", "processing", "completed", "failed"]
    progress: int = Field(ge=0, le=100)
    error: str | None = None
    result: dict[str, str] | None = None
    created_at: datetime
    updated_at: datetime


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
