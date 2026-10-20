from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.pipeline import (
    PipelineError,
    format_srt_timestamp,
    segment_script,
    script_to_scenes,
    validate_rendered_output,
    validate_visible_motion,
    write_srt,
)


client = TestClient(app)


def test_health_and_ready():
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}


def test_job_listing_and_provider_status_are_safe(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "footage_provider", "mock")
    response = client.get("/api/v1/jobs?limit=5")
    assert response.status_code == 200
    assert response.json()["count"] <= 5
    assert response.json()["total_count"] >= response.json()["count"]
    assert set(response.json()["counts"]) == {"queued", "processing", "completed", "failed"}
    filtered = client.get("/api/v1/jobs?status=not-a-status")
    assert filtered.status_code == 400
    status = client.get("/api/v1/service-status")
    assert status.status_code == 200
    assert "PEXELS_API_KEY" not in status.text
    assert "ffprobe_available" in status.text
    assert status.json()["footage"] == {
        "provider": "mock",
        "available": False,
        "test_mode": True,
        "setup_message": "Set FOOTAGE_PROVIDER=pixabay and PIXABAY_API_KEY in the local .env to use Pixabay.",
    }


def test_file_route_rejects_invalid_job_id():
    assert client.get("/api/v1/jobs/not-a-job/files/manifest.json").status_code == 404


def test_job_creation_idempotency_and_result():
    payload = {"script": "Save money. Build a better future.", "aspect_ratios": ["16:9"]}
    headers = {"Idempotency-Key": "test-key-1"}
    first = client.post("/api/v1/broll/jobs", json=payload, headers=headers)
    assert first.status_code == 202
    job_id = first.json()["job_id"]
    second = client.post("/api/v1/broll/jobs", json=payload, headers=headers)
    assert second.status_code == 202
    assert second.json()["job_id"] == job_id
    status = client.get(f"/api/v1/jobs/{job_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "completed"
    result = client.get(f"/api/v1/jobs/{job_id}/result")
    assert result.status_code == 200
    assert client.get(result.json()["timeline"]).status_code == 200


def test_empty_request_is_rejected():
    response = client.post("/api/v1/broll/jobs", json={})
    assert response.status_code == 422


def test_scene_segmentation_and_srt_timestamps(tmp_path):
    assert segment_script("First sentence. Is this second? Yes!") == [
        "First sentence.", "Is this second?", "Yes!"
    ]
    srt_path = tmp_path / "captions.srt"
    write_srt([{"start": 0.0, "end": 1.25, "narration": "Hello."}], srt_path)
    assert srt_path.read_text(encoding="utf-8") == "1\n00:00:00,000 --> 00:00:01,250\nHello.\n"
    assert format_srt_timestamp(3661.005) == "01:01:01,005"


def test_rendering_without_configured_tts_fails_loudly(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "tts_provider", "unconfigured")
    response = client.post(
        "/api/v1/broll/jobs",
        json={"script": "This must not be represented as a finished video.", "render": True},
    )
    assert response.status_code == 202
    job = client.get(f"/api/v1/jobs/{response.json()['job_id']}").json()
    assert job["status"] == "failed"
    assert "TTS" in job["error"]


def test_audio_upload_rejects_unsupported_format():
    response = client.post(
        "/api/v1/broll/jobs/upload",
        files={"audio": ("voice.txt", b"not audio", "text/plain")},
    )
    assert response.status_code == 415


def test_pexels_provider_requires_explicit_key(monkeypatch):
    from app.config import settings
    from app.pipeline import PexelsFootageProvider, PipelineError

    monkeypatch.setattr(settings, "pexels_api_key", None)
    with pytest.raises(PipelineError, match="PEXELS_API_KEY"):
        PexelsFootageProvider()


def test_scene_timing_must_cover_narration():
    from app.pipeline import validate_scene_timing

    normalized = validate_scene_timing(
        [{"narration": "one", "start": 0, "end": 0.5}], 1.0
    )
    assert normalized[-1]["end"] == 1.0


def test_pexels_empty_results_and_provider_timeout(monkeypatch):
    from app.config import settings
    from app.pipeline import PexelsFootageProvider, PipelineError

    monkeypatch.setattr(settings, "pexels_api_key", "test-key")

    class EmptyResponse:
        def raise_for_status(self): pass
        def json(self): return {"videos": []}

    monkeypatch.setattr("app.pipeline.requests.get", lambda *args, **kwargs: EmptyResponse())
    with pytest.raises(PipelineError, match="no unused footage"):
        PexelsFootageProvider().search_and_download("forest", Path("unused.mp4"), set())

    import requests

    monkeypatch.setattr(
        "app.pipeline.requests.get",
        lambda *args, **kwargs: (_ for _ in ()).throw(requests.Timeout("provider timed out")),
    )
    with pytest.raises(PipelineError, match="Pexels search failed"):
        PexelsFootageProvider().search_and_download("forest", Path("unused.mp4"), set())


def test_rendered_output_rejects_missing_video_stream(monkeypatch, tmp_path):
    from app import pipeline

    monkeypatch.setattr(
        pipeline,
        "probe_media",
        lambda _path: {
            "streams": [{"codec_type": "audio", "codec_name": "aac"}],
            "format": {"duration": "2.0"},
        },
    )
    with pytest.raises(PipelineError, match="video and narration audio"):
        validate_rendered_output(tmp_path / "invalid.mp4", "16:9", 2.0)


def test_footage_validation_rejects_solid_color_frames(monkeypatch, tmp_path):
    from app import pipeline
    from types import SimpleNamespace

    monkeypatch.setattr(
        pipeline,
        "probe_media",
        lambda _path: {
            "streams": [{"codec_type": "video", "width": 1280, "height": 720, "duration": "2"}],
            "format": {"duration": "2"},
        },
    )
    solid_gray_frame = bytes([32]) * (64 * 36)
    monkeypatch.setattr(
        pipeline.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=solid_gray_frame * 2, stderr=b""),
    )
    with pytest.raises(PipelineError, match="solid-color placeholder"):
        validate_visible_motion(tmp_path / "solid.mp4")


def test_footage_validation_accepts_localized_slow_motion(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from app import pipeline

    frame_size = 64 * 36
    base = bytearray(70 + (index % 31) for index in range(frame_size))
    frames = []
    for frame_index in range(12):
        frame = bytearray(base)
        x = 4 + frame_index
        for y in range(10, 12):
            for column in range(x, x + 2):
                frame[y * 64 + column] = 220
        frames.append(bytes(frame))
    monkeypatch.setattr(
        pipeline.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=b"".join(frames), stderr=b""),
    )
    metadata = {
        "streams": [{"codec_type": "video", "width": 1280, "height": 720, "duration": "6"}],
        "format": {"duration": "6"},
    }

    result = validate_visible_motion(tmp_path / "slow-pan.mp4", metadata)

    assert result["average_frame_delta"] < 0.75
    assert result["localized_motion_pairs"] >= 2


def test_footage_validation_rejects_unchanging_detailed_frames(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from app import pipeline

    frame_size = 64 * 36
    textured_frame = bytes(70 + (index % 31) for index in range(frame_size))
    monkeypatch.setattr(
        pipeline.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=textured_frame * 12, stderr=b""),
    )
    metadata = {
        "streams": [{"codec_type": "video", "width": 1280, "height": 720, "duration": "6"}],
        "format": {"duration": "6"},
    }

    with pytest.raises(PipelineError, match="no detectable motion"):
        validate_visible_motion(tmp_path / "still-frame.mp4", metadata)


def test_script_to_scenes_preserves_titles_without_speaking_headings():
    script = (
        "Scene 1 — The Sunrise\n\nThe sun rises over the mountains. Golden rays fill the sky.\n\n"
        "Scene 2 — The Forest\n\nBirds fly through the trees."
    )

    assert script_to_scenes(script) == [
        {
            "narration": "The sun rises over the mountains. Golden rays fill the sky.",
            "visual_hint": "The Sunrise",
        },
        {"narration": "Birds fly through the trees.", "visual_hint": "The Forest"},
    ]


def test_real_render_refuses_mock_footage(monkeypatch, tmp_path):
    from unittest.mock import Mock
    from app.config import settings
    from app.models import JobRequest
    from app.pipeline import render_job

    monkeypatch.setattr(settings, "footage_provider", "mock")
    store = Mock()
    render_job(
        "a" * 32,
        JobRequest(script="A forest at sunrise.", render=True),
        store,
        audio_path=tmp_path / "provided-audio.wav",
    )
    assert store.update.call_args.kwargs["status"] == "failed"
    assert "solid-color test background" in store.update.call_args.kwargs["error"]


def test_pixabay_provider_requires_key_without_leaking_credentials(monkeypatch):
    from app.config import settings
    from app.pipeline import PixabayFootageProvider

    monkeypatch.setattr(settings, "pixabay_api_key", None)
    with pytest.raises(PipelineError, match="PIXABAY_API_KEY") as error:
        PixabayFootageProvider()
    assert "https://" not in str(error.value)


def test_pixabay_search_uses_official_params_ranks_and_downloads(monkeypatch, tmp_path):
    from app.config import settings
    from app.pipeline import PixabayFootageProvider
    from types import SimpleNamespace

    monkeypatch.setattr(settings, "pixabay_api_key", "test-secret")
    monkeypatch.setattr(settings, "output_dir", tmp_path / "jobs")
    monkeypatch.setattr(settings, "pixabay_min_width", 640)
    monkeypatch.setattr(settings, "pixabay_min_height", 360)
    calls = []
    hits = [
        {
            "id": 101, "pageURL": "https://pixabay.com/videos/id-101/",
            "tags": "forest nature birds", "duration": 8, "user": "Contributor A",
            "videos": {"medium": {
                "url": "https://cdn.pixabay.com/101.mp4", "width": 1280,
                "height": 720, "size": 1024,
            }},
        },
        {
            "id": 202, "pageURL": "https://pixabay.com/videos/id-202/",
            "tags": "forest nature birds mist", "duration": 12, "user": "Contributor B",
            "videos": {"large": {
                "url": "https://cdn.pixabay.com/202.mp4", "width": 1920,
                "height": 1080, "size": 2048,
            }},
        },
    ]

    class SearchResponse:
        status_code = 200
        def json(self): return {"hits": hits}

    class DownloadResponse:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def iter_content(self, chunk_size):
            assert chunk_size == 256 * 1024
            yield b"fake-video-content"

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return SearchResponse() if url == PixabayFootageProvider.endpoint else DownloadResponse()

    monkeypatch.setattr("app.pipeline.requests.get", fake_get)
    destination = tmp_path / "job" / "source.mp4"
    provider = PixabayFootageProvider()
    footage = provider.search_and_download(
        "forest nature birds mist", destination, {"101"}, "16:9"
    )

    assert footage["provider"] == "pixabay"
    assert footage["asset_id"] == "202"
    assert footage["source_url"] == "https://pixabay.com/videos/id-202/"
    assert footage["contributor"] == "Contributor B"
    assert footage["license"] is None
    assert "Pixabay Content License" in footage["rights_notes"]
    assert footage["duplicate_clip_fallback"] is False
    assert destination.read_bytes() == b"fake-video-content"
    assert calls[0][0] == PixabayFootageProvider.endpoint
    assert calls[0][1]["params"]["key"] == "test-secret"
    assert calls[0][1]["params"]["q"] == "forest nature birds mist"
    assert calls[0][1]["params"]["safesearch"] is True
    assert calls[0][1]["params"]["min_width"] == 640
    assert calls[0][1]["params"]["min_height"] == 360
    assert calls[0][1]["timeout"] > 0
    assert calls[1][1]["stream"] is True


def test_pixabay_empty_and_invalid_search_responses(monkeypatch, tmp_path):
    from app.config import settings
    from app.pipeline import PixabayFootageProvider

    monkeypatch.setattr(settings, "pixabay_api_key", "test-key")
    monkeypatch.setattr(settings, "output_dir", tmp_path / "jobs")

    class Response:
        status_code = 200
        def __init__(self, payload): self.payload = payload
        def json(self): return self.payload

    response = {"value": Response({"hits": []})}
    monkeypatch.setattr("app.pipeline.requests.get", lambda *_args, **_kwargs: response["value"])
    with pytest.raises(PipelineError, match="no downloadable video clips"):
        PixabayFootageProvider().search_and_download("forest", tmp_path / "empty.mp4", set())

    response["value"] = Response({"result": []})
    with pytest.raises(PipelineError, match="unexpected video-search response"):
        PixabayFootageProvider().search_and_download("different forest", tmp_path / "bad.mp4", set())


def test_pixabay_malformed_dimensions_and_external_video_urls_are_rejected(monkeypatch, tmp_path):
    from app.config import settings
    from app.pipeline import PixabayFootageProvider

    monkeypatch.setattr(settings, "pixabay_api_key", "test-key")
    monkeypatch.setattr(settings, "output_dir", tmp_path / "jobs")
    payload = {"hits": [{
        "id": "bad-variant",
        "tags": "forest",
        "videos": {
            "large": {
                "url": "https://example.invalid/clip.mp4",
                "width": "not-a-number",
                "height": None,
            },
        },
    }]}

    class Response:
        status_code = 200

        def json(self):
            return payload

    monkeypatch.setattr("app.pipeline.requests.get", lambda *_args, **_kwargs: Response())
    with pytest.raises(PipelineError, match="no video variant"):
        PixabayFootageProvider().search_and_download(
            "malformed forest metadata", tmp_path / "unsafe.mp4", set()
        )


def test_pixabay_timeout_and_rate_limit_are_actionable(monkeypatch, tmp_path):
    import requests
    from app.config import settings
    from app.pipeline import PixabayFootageProvider
    from types import SimpleNamespace

    monkeypatch.setattr(settings, "pixabay_api_key", "test-key")
    monkeypatch.setattr(settings, "output_dir", tmp_path / "jobs")
    monkeypatch.setattr(settings, "pixabay_request_retries", 0)
    monkeypatch.setattr(
        "app.pipeline.requests.get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(requests.Timeout()),
    )
    with pytest.raises(PipelineError, match="timed out"):
        PixabayFootageProvider().search_and_download("forest", tmp_path / "timeout.mp4", set())

    response = SimpleNamespace(status_code=429, headers={"Retry-After": "60"})
    monkeypatch.setattr("app.pipeline.requests.get", lambda *_args, **_kwargs: response)
    with pytest.raises(PipelineError, match="rate limit"):
        PixabayFootageProvider().search_and_download("forest rate limit", tmp_path / "rate.mp4", set())


def test_pixabay_failed_download_and_duplicate_reuse(monkeypatch, tmp_path):
    from app.config import settings
    from app.pipeline import PixabayFootageProvider
    from types import SimpleNamespace

    monkeypatch.setattr(settings, "pixabay_api_key", "test-key")
    monkeypatch.setattr(settings, "output_dir", tmp_path / "jobs")
    hits = [{
        "id": 7, "pageURL": "https://pixabay.com/videos/id-7/",
        "tags": "forest nature", "duration": 5, "videos": {
            "medium": {"url": "https://cdn.pixabay.com/7-medium.mp4", "width": 1280, "height": 720, "size": 2048},
            "large": {"url": "https://cdn.pixabay.com/7-large.mp4", "width": 1920, "height": 1080, "size": 8192},
        },
    }]

    class SearchResponse:
        status_code = 200
        def json(self): return {"hits": hits}

    def failed_download(*_args, **kwargs):
        if kwargs.get("stream"):
            raise OSError("simulated filesystem failure")
        return SearchResponse()

    monkeypatch.setattr("app.pipeline.requests.get", failed_download)
    provider = PixabayFootageProvider()
    with pytest.raises(PipelineError, match="save the Pixabay video"):
        provider.search_and_download("forest download fail", tmp_path / "fail.mp4", set())

    class DownloadResponse:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def iter_content(self, chunk_size): yield b"valid-placeholder-bytes"

    monkeypatch.setattr(
        "app.pipeline.requests.get",
        lambda url, **kwargs: SearchResponse() if not kwargs.get("stream") else DownloadResponse(),
    )
    used = set()
    first = provider.search_and_download("forest duplicate", tmp_path / "first.mp4", used)
    second = provider.search_and_download("forest duplicate", tmp_path / "second.mp4", used)
    assert first["asset_id"] == second["asset_id"] == "7"
    assert first["video_variant"] == "medium"
    assert first["duplicate_clip_fallback"] is False
    assert second["duplicate_clip_fallback"] is True
