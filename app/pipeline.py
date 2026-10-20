import json
import hashlib
import re
import shutil
import subprocess
import time
import wave
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import uuid4

import requests

from .config import settings
from .models import JobRequest
from .storage import JobStore


class PipelineError(RuntimeError):
    """An actionable error raised while building a video job."""


def validate_scene_timing(scenes: list[dict[str, Any]], duration: float) -> list[dict[str, Any]]:
    if not scenes:
        raise PipelineError("Transcription or scene descriptions produced no scenes.")
    normalized: list[dict[str, Any]] = []
    cursor = 0.0
    for index, scene in enumerate(scenes, 1):
        narration = str(scene.get("narration", "")).strip()
        if not narration:
            raise PipelineError(f"Scene {index} has no narration text.")
        try:
            start = float(scene.get("start", cursor))
            end = float(scene["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PipelineError(f"Scene {index} has invalid timestamps.") from exc
        if start < cursor - 0.05 or end <= start:
            raise PipelineError(f"Scene {index} timestamps overlap or are not increasing.")
        start = cursor
        normalized.append({
            "narration": narration,
            "visual_hint": scene.get("visual_hint"),
            "start": max(0.0, start),
            "end": min(duration, end),
        })
        cursor = end
    if cursor < duration - 0.05:
        normalized[-1]["end"] = duration
    if normalized[-1]["end"] < duration - 0.05:
        raise PipelineError("Scene timing does not cover the complete narration.")
    return normalized


def segment_script(script: str) -> list[str]:
    """Split prose at sentence boundaries while preserving useful fallback text."""
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", script.replace("\n", " ")) if part.strip()]
    return parts or [script.strip()]


def script_to_scenes(script: str) -> list[dict[str, str | None]]:
    """Preserve explicitly titled scene blocks; otherwise use sentence-level scenes."""
    heading_pattern = re.compile(r"^\s*Scene\s+\d+\s*[-–—:]\s*(.+?)\s*$", re.IGNORECASE)
    sections: list[tuple[str | None, list[str]]] = []
    current_title: str | None = None
    current_lines: list[str] = []
    found_heading = False

    for line in script.splitlines():
        match = heading_pattern.match(line)
        if match:
            found_heading = True
            if any(part.strip() for part in current_lines):
                sections.append((current_title, current_lines))
            current_title = match.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if any(part.strip() for part in current_lines):
        sections.append((current_title, current_lines))

    if not found_heading:
        return [{"narration": text, "visual_hint": None} for text in segment_script(script)]

    scenes: list[dict[str, str | None]] = []
    for title, lines in sections:
        narration = " ".join(segment_script(" ".join(lines)))
        if narration:
            scenes.append({"narration": narration, "visual_hint": title})
    return scenes


def format_srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds_value, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds_value:02d},{millis:03d}"


def write_srt(scenes: list[dict[str, Any]], path: Path) -> None:
    entries = []
    for index, scene in enumerate(scenes, 1):
        entries.append(
            f"{index}\n{format_srt_timestamp(scene['start'])} --> "
            f"{format_srt_timestamp(scene['end'])}\n{scene['narration']}\n"
        )
    path.write_text("\n".join(entries), encoding="utf-8")


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        raise PipelineError(
            f"FFmpeg executable was not found at {command[0]!r}. "
            "Install FFmpeg and set FFMPEG_PATH in .env."
        ) from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "unknown FFmpeg error").strip()[-1000:]
        raise PipelineError(f"FFmpeg command failed: {detail}") from exc


def _ffmpeg_executable() -> str:
    if settings.ffmpeg_path != "ffmpeg":
        return settings.ffmpeg_path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return settings.ffmpeg_path


def probe_media(path: Path) -> dict[str, Any]:
    """Probe media with FFprobe; fail rather than claiming unvalidated output."""
    try:
        result = subprocess.run(
            [settings.ffprobe_path, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise PipelineError(
            "FFprobe is required to validate rendered media. "
            "Install FFmpeg (which includes FFprobe) and set FFPROBE_PATH in .env."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise PipelineError(f"FFprobe rejected media: {(exc.stderr or '').strip()[-500:]}") from exc
    return json.loads(result.stdout)


def validate_visible_motion(path: Path, metadata: dict[str, Any] | None = None) -> dict[str, float | int]:
    """Reject corrupt, blank, or static video before treating it as usable footage."""
    metadata = metadata or probe_media(path)
    video = next(
        (stream for stream in metadata.get("streams", []) if stream.get("codec_type") == "video"),
        None,
    )
    if video is None or int(video.get("width") or 0) <= 0 or int(video.get("height") or 0) <= 0:
        raise PipelineError(f"Footage {path.name} does not contain a valid video stream.")
    try:
        duration = float(video.get("duration") or metadata.get("format", {}).get("duration") or 0)
    except (TypeError, ValueError) as exc:
        raise PipelineError(f"Footage {path.name} has an invalid duration.") from exc
    if duration <= 0:
        raise PipelineError(f"Footage {path.name} has no usable video duration.")

    try:
        decoded = subprocess.run(
            [
                _ffmpeg_executable(), "-v", "error", "-i", str(path),
                "-vf", "fps=2,scale=64:36:force_original_aspect_ratio=decrease,"
                       "pad=64:36:(ow-iw)/2:(oh-ih)/2,format=gray",
                "-frames:v", "12", "-an", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
            ],
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise PipelineError("FFmpeg is required to decode and validate footage frames.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode(errors="replace").strip()[-500:]
        raise PipelineError(f"Could not decode footage {path.name}: {detail}") from exc

    frame_size = 64 * 36
    frame_count = len(decoded.stdout) // frame_size
    if frame_count < 2 or len(decoded.stdout) % frame_size:
        raise PipelineError(f"Footage {path.name} did not decode into complete video frames.")

    frames = [
        decoded.stdout[index * frame_size:(index + 1) * frame_size]
        for index in range(frame_count)
    ]
    means: list[float] = []
    deviations: list[float] = []
    for frame in frames:
        mean = sum(frame) / frame_size
        means.append(mean)
        deviations.append((sum((pixel - mean) ** 2 for pixel in frame) / frame_size) ** 0.5)
    frame_deltas = [
        [abs(current - previous) for current, previous in zip(left, right)]
        for left, right in zip(frames, frames[1:])
    ]
    average_delta = sum(sum(delta) / frame_size for delta in frame_deltas) / len(frame_deltas)
    localized_motion_pairs = sum(
        sum(pixel_delta > 10 for pixel_delta in delta) / frame_size >= 0.001
        for delta in frame_deltas
    )
    localized_motion_fraction = localized_motion_pairs / len(frame_deltas)
    if max(means) < 8 or max(deviations) < 4:
        raise PipelineError(f"Footage {path.name} is visually blank or a solid-color placeholder.")
    minimum_localized_pairs = max(2, int(len(frame_deltas) * 0.25))
    if average_delta < 0.75 and localized_motion_pairs < minimum_localized_pairs:
        raise PipelineError(f"Footage {path.name} has no detectable motion; moving video footage is required.")
    return {
        "sampled_frames": frame_count,
        "average_luma": round(sum(means) / frame_count, 2),
        "minimum_frame_contrast": round(min(deviations), 2),
        "average_frame_delta": round(average_delta, 2),
        "localized_motion_pairs": localized_motion_pairs,
        "localized_motion_fraction": round(localized_motion_fraction, 4),
    }


def validate_rendered_output(path: Path, ratio: str, expected_duration: float) -> dict[str, Any]:
    dimensions = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1080, 1080)}
    if ratio not in dimensions:
        raise PipelineError(f"Unsupported aspect ratio: {ratio}")
    metadata = probe_media(path)
    streams = metadata.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if video is None or audio is None:
        raise PipelineError(f"Rendered output {path.name} must contain video and narration audio.")
    width, height = dimensions[ratio]
    if (video.get("width"), video.get("height")) != (width, height):
        raise PipelineError(
            f"Rendered output {path.name} has {video.get('width')}x{video.get('height')}; "
            f"expected {width}x{height}."
        )
    if video.get("codec_name") != "h264":
        raise PipelineError(f"Rendered output {path.name} is not H.264.")
    if video.get("pix_fmt") != "yuv420p":
        raise PipelineError(f"Rendered output {path.name} is not yuv420p.")
    frame_rate = video.get("r_frame_rate", "")
    if frame_rate not in {"30/1", "30/1.0"}:
        raise PipelineError(f"Rendered output {path.name} is not 30 fps (reported {frame_rate}).")
    duration = float(metadata.get("format", {}).get("duration", 0))
    if abs(duration - expected_duration) > 0.75:
        raise PipelineError(
            f"Rendered output {path.name} duration {duration:.2f}s differs from "
            f"narration duration {expected_duration:.2f}s."
        )
    metadata["visual_validation"] = validate_visible_motion(path, metadata)
    return metadata


def audio_duration(path: Path) -> float:
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as audio:
                return audio.getnframes() / audio.getframerate()
        except (wave.Error, EOFError) as exc:
            raise PipelineError("The uploaded WAV file is corrupted or unreadable.") from exc
    metadata = probe_media(path)
    try:
        return float(metadata["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PipelineError("The audio duration could not be determined.") from exc


class TTSProvider(Protocol):
    def synthesize(self, text: str, destination: Path) -> None: ...


class LocalTTS:
    def synthesize(self, text: str, destination: Path) -> None:
        try:
            import pyttsx3
        except ImportError as exc:
            raise PipelineError(
                "TTS_PROVIDER=pyttsx3 requires pyttsx3. Install it with "
                "'pip install pyttsx3', or configure an external TTS adapter."
            ) from exc
        engine = pyttsx3.init()
        engine.save_to_file(text, str(destination))
        engine.runAndWait()
        if not destination.is_file() or destination.stat().st_size == 0:
            raise PipelineError("The local TTS provider did not produce an audio file.")


class MockFootageProvider:
    """Creates clearly-labelled synthetic media for tests only."""

    def create_clip(self, destination: Path, duration: float, _label: str) -> dict[str, Any]:
        _run([
            _ffmpeg_executable(), "-y", "-f", "lavfi", "-i",
            f"color=c=0x16324f:s=1280x720:r=30:d={duration:.3f}",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(destination),
        ])
        return {
            "provider": "mock",
            "asset_id": f"synthetic-{uuid4().hex[:12]}",
            "source_url": None,
            "license": "Synthetic test media; not stock footage.",
            "attribution": None,
            "is_synthetic": True,
            "relevance_method": "deterministic mock asset",
            "selection_reason": f"Used only because FOOTAGE_PROVIDER=mock for query { _label!r}.",
        }


class PexelsFootageProvider:
    def __init__(self) -> None:
        if not settings.pexels_api_key:
            raise PipelineError("FOOTAGE_PROVIDER=pexels requires PEXELS_API_KEY.")

    def search_and_download(
        self, query: str, destination: Path, used_ids: set[str]
    ) -> dict[str, Any]:
        try:
            response = requests.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": settings.pexels_api_key},
                params={"query": query, "per_page": 15, "orientation": "landscape"},
                timeout=settings.footage_download_timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise PipelineError(f"Pexels search failed: {exc}") from exc
        videos = response.json().get("videos", [])
        candidates = [item for item in videos if str(item.get("id")) not in used_ids]
        if not candidates:
            raise PipelineError(f"Pexels returned no unused footage for query: {query!r}")
        terms = {term.lower() for term in re.findall(r"[a-z0-9]+", query) if len(term) > 2}
        def relevance(video: dict[str, Any]) -> tuple[int, int]:
            haystack = " ".join(str(video.get(key, "")) for key in ("url", "image", "user"))
            score = sum(term in haystack.lower() for term in terms)
            return score, int(video.get("duration") or 0)
        selected = max(candidates, key=relevance)
        files = [item for item in selected.get("video_files", []) if item.get("link")]
        files.sort(key=lambda item: abs((item.get("width") or 1280) - 1280))
        if not files:
            raise PipelineError(f"Pexels result {selected.get('id')} has no downloadable video.")
        source_url = files[0]["link"]
        try:
            with requests.get(source_url, stream=True, timeout=settings.footage_download_timeout_seconds) as download:
                download.raise_for_status()
                size = 0
                with destination.open("wb") as output:
                    for chunk in download.iter_content(chunk_size=1024 * 256):
                        size += len(chunk)
                        if size > settings.max_media_download_bytes:
                            raise PipelineError("Downloaded footage exceeds the configured size limit.")
                        output.write(chunk)
        except requests.RequestException as exc:
            raise PipelineError(f"Pexels footage download failed: {exc}") from exc
        used_ids.add(str(selected.get("id")))
        return {
            "provider": "pexels",
            "asset_id": str(selected.get("id")),
            "source_url": selected.get("url"),
            "license": "See https://www.pexels.com/license/; verify current terms before release.",
            "attribution": selected.get("user", {}).get("name"),
            "is_synthetic": False,
            "relevance_method": "Token overlap against official API result metadata, then duration tie-break",
            "relevance_score": relevance(selected)[0],
            "selection_reason": f"Highest deterministic token-overlap score for query {query!r}.",
        }


class PixabayFootageProvider:
    """Pixabay video search with a 24-hour response cache and bounded API retries."""

    endpoint = "https://pixabay.com/api/videos/"

    def __init__(self) -> None:
        if not settings.pixabay_api_key:
            raise PipelineError(
                "Pixabay video search is not configured. Add PIXABAY_API_KEY to the local .env "
                "and set FOOTAGE_PROVIDER=pixabay, then restart the backend."
            )
        self.cache_dir = settings.output_dir.parent / "pixabay-cache"

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {
            token.casefold()
            for token in re.findall(r"[a-zA-Z0-9]+", text)
            if len(token) > 2
        }

    @staticmethod
    def _nonnegative_int(value: Any) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError):
            return 0
        return parsed if parsed >= 0 else 0

    def _search(self, query: str) -> list[dict[str, Any]]:
        normalized_query = " ".join(query.split())[:100]
        if not normalized_query:
            raise PipelineError("Pixabay search needs a non-empty scene description.")
        cache_key = hashlib.sha256(
            f"{normalized_query.casefold()}|{settings.pixabay_min_width}|"
            f"{settings.pixabay_min_height}|{settings.pixabay_safe_search}".encode("utf-8")
        ).hexdigest()
        cache_path = self.cache_dir / f"{cache_key}.json"
        if cache_path.is_file():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                cache_lifetime = max(86400, settings.pixabay_search_cache_seconds)
                if time.time() - float(cached["cached_at"]) < cache_lifetime:
                    hits = cached.get("hits")
                    if isinstance(hits, list):
                        return [hit for hit in hits if isinstance(hit, dict)]
            except (OSError, ValueError, KeyError, TypeError):
                cache_path.unlink(missing_ok=True)

        params: dict[str, str | int | bool] = {
            "key": settings.pixabay_api_key or "",
            "q": normalized_query,
            "per_page": 20,
            "safesearch": settings.pixabay_safe_search,
            "order": "popular",
            "min_width": settings.pixabay_min_width,
            "min_height": settings.pixabay_min_height,
        }
        retries = max(0, min(settings.pixabay_request_retries, 2))
        for attempt in range(retries + 1):
            try:
                response = requests.get(
                    self.endpoint,
                    params=params,
                    timeout=settings.footage_download_timeout_seconds,
                )
            except requests.Timeout as exc:
                if attempt < retries:
                    time.sleep(min(0.5 * (attempt + 1), 1.0))
                    continue
                raise PipelineError("Pixabay video search timed out; retry the job later.") from exc
            except requests.RequestException as exc:
                if attempt < retries:
                    time.sleep(min(0.5 * (attempt + 1), 1.0))
                    continue
                raise PipelineError("Pixabay video search failed due to a network error.") from exc

            if response.status_code == 429:
                if attempt < retries:
                    retry_after = response.headers.get("Retry-After", "")
                    try:
                        delay = float(retry_after)
                    except (TypeError, ValueError):
                        delay = 1.0
                    if delay <= 1.0:
                        time.sleep(max(0.0, delay))
                        continue
                raise PipelineError(
                    "Pixabay rate limit reached (HTTP 429). Wait before submitting another render."
                )
            if response.status_code in {401, 403}:
                raise PipelineError(
                    "Pixabay rejected the API key (HTTP "
                    f"{response.status_code}). Check PIXABAY_API_KEY in the local .env."
                )
            if response.status_code >= 500 and attempt < retries:
                time.sleep(min(0.5 * (attempt + 1), 1.0))
                continue
            if response.status_code >= 400:
                raise PipelineError(f"Pixabay video search returned HTTP {response.status_code}.")
            try:
                payload = response.json()
            except (ValueError, json.JSONDecodeError) as exc:
                raise PipelineError("Pixabay returned invalid JSON for the video search.") from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("hits"), list):
                raise PipelineError("Pixabay returned an unexpected video-search response.")
            hits = [hit for hit in payload["hits"] if isinstance(hit, dict)]
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps({"cached_at": time.time(), "hits": hits}),
                encoding="utf-8",
            )
            return hits
        raise PipelineError("Pixabay video search failed after its limited retries.")

    def _rank(
        self, video: dict[str, Any], query: str, aspect_ratio: str
    ) -> tuple[float, int, int, float]:
        tokens = self._tokens(query)
        searchable = self._tokens(str(video.get("tags", "")))
        relevance = len(tokens & searchable) / max(1, len(tokens))
        variants = video.get("videos")
        if not isinstance(variants, dict):
            variants = {}
        best_resolution = 0
        aspect_match = 0.0
        for variant in variants.values():
            if not isinstance(variant, dict):
                continue
            width = self._nonnegative_int(variant.get("width"))
            height = self._nonnegative_int(variant.get("height"))
            if width >= settings.pixabay_min_width and height >= settings.pixabay_min_height:
                best_resolution = max(best_resolution, width * height)
                target = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0}.get(aspect_ratio)
                if target is not None and height:
                    similarity = min(width / height, height / width) / min(target, 1 / target)
                    aspect_match = max(aspect_match, min(1.0, similarity))
        duration = self._nonnegative_int(video.get("duration"))
        return relevance, best_resolution, duration, aspect_match

    def search_and_download(
        self,
        query: str,
        destination: Path,
        used_ids: set[str],
        aspect_ratio: str = "16:9",
    ) -> dict[str, Any]:
        hits = self._search(query)
        candidates = [
            item for item in hits
            if item.get("id") is not None
            and isinstance(item.get("videos"), dict)
            and item["videos"]
        ]
        if not candidates:
            raise PipelineError(
                f"Pixabay returned no downloadable video clips for scene: {query!r}. "
                "Try a shorter scene description or use a local video library."
            )
        unused = [item for item in candidates if str(item["id"]) not in used_ids]
        pool = unused or candidates
        selected = max(pool, key=lambda item: self._rank(item, query, aspect_ratio))
        score = self._rank(selected, query, aspect_ratio)
        video_variants = selected["videos"]
        variants = [
            (name, item) for name, item in video_variants.items()
            if isinstance(item, dict)
            and isinstance(item.get("url"), str)
            and urlparse(item["url"]).scheme == "https"
            and urlparse(item["url"]).hostname is not None
            and urlparse(item["url"]).hostname.endswith(".pixabay.com")
            and self._nonnegative_int(item.get("width")) >= settings.pixabay_min_width
            and self._nonnegative_int(item.get("height")) >= settings.pixabay_min_height
        ]
        if not variants:
            raise PipelineError(
                f"Pixabay clip {selected['id']} has no video variant at the configured "
                f"minimum resolution ({settings.pixabay_min_width}x{settings.pixabay_min_height})."
            )
        variant_name, variant = min(
            variants,
            key=lambda pair: (
                self._nonnegative_int(pair[1].get("width"))
                * self._nonnegative_int(pair[1].get("height")),
                self._nonnegative_int(pair[1].get("size"))
                or settings.max_media_download_bytes + 1,
            ),
        )
        clip_id = str(selected["id"])
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cached_clip = self.cache_dir / f"{clip_id}-{variant_name}.mp4"
        if not cached_clip.is_file():
            retries = max(0, min(settings.pixabay_request_retries, 2))
            for attempt in range(retries + 1):
                try:
                    with requests.get(
                        variant["url"],
                        stream=True,
                        timeout=settings.footage_download_timeout_seconds,
                    ) as download:
                        if download.status_code >= 400:
                            if download.status_code >= 500 and attempt < retries:
                                continue
                            raise PipelineError(
                                f"Pixabay video download returned HTTP {download.status_code}."
                            )
                        size = 0
                        with cached_clip.open("wb") as output:
                            for chunk in download.iter_content(chunk_size=256 * 1024):
                                if not chunk:
                                    continue
                                size += len(chunk)
                                if size > settings.max_media_download_bytes:
                                    raise PipelineError(
                                        "Pixabay video exceeds the configured download-size limit."
                                    )
                                output.write(chunk)
                    break
                except requests.Timeout as exc:
                    cached_clip.unlink(missing_ok=True)
                    if attempt < retries:
                        time.sleep(min(0.5 * (attempt + 1), 1.0))
                        continue
                    raise PipelineError("Pixabay video download timed out; retry the job later.") from exc
                except requests.RequestException as exc:
                    cached_clip.unlink(missing_ok=True)
                    if attempt < retries:
                        time.sleep(min(0.5 * (attempt + 1), 1.0))
                        continue
                    raise PipelineError("Pixabay video download failed due to a network error.") from exc
                except OSError as exc:
                    cached_clip.unlink(missing_ok=True)
                    raise PipelineError("Could not save the Pixabay video to the local media cache.") from exc
                except PipelineError:
                    cached_clip.unlink(missing_ok=True)
                    raise
            if not cached_clip.is_file() or cached_clip.stat().st_size == 0:
                cached_clip.unlink(missing_ok=True)
                raise PipelineError("Pixabay returned an empty video download.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(cached_clip, destination)
        except OSError as exc:
            raise PipelineError("Could not copy the Pixabay video into the isolated job directory.") from exc
        used_ids.add(clip_id)
        duplicate_fallback = not unused
        return {
            "provider": "pixabay",
            "asset_id": clip_id,
            "source_url": selected.get("pageURL"),
            "download_url": variant["url"],
            "contributor": selected.get("user"),
            "attribution": (
                f"Video by {selected.get('user')} on Pixabay"
                if selected.get("user") else "Pixabay video; contributor name not provided by API"
            ),
            "license": None,
            "rights_notes": (
                "Pixabay Content License; review current terms and this asset page before use. "
                "No additional rights are asserted by this manifest."
            ),
            "license_url": "https://pixabay.com/service/license/",
            "is_synthetic": False,
            "duration_seconds": selected.get("duration"),
            "width": variant.get("width"),
            "height": variant.get("height"),
            "video_variant": variant_name,
            "relevance_method": (
                "Scene-tag token overlap, then resolution, duration, and aspect-ratio suitability"
            ),
            "relevance_score": round(score[0], 4),
            "selection_reason": (
                f"Ranked for query {query!r}; matched {score[0]:.0%} of query tokens, "
                f"selected {variant.get('width')}x{variant.get('height')} {variant_name} variant."
            ),
            "duplicate_clip_fallback": duplicate_fallback,
        }


def transcribe_audio(path: Path) -> list[dict[str, Any]]:
    if settings.stt_provider != "faster-whisper":
        raise PipelineError(
            "Uploaded audio requires transcription. Set STT_PROVIDER=faster-whisper, "
            "install faster-whisper, and configure STT_MODEL, or submit timestamped transcript JSON."
        )
    try:
        WhisperModel = import_module("faster_whisper").WhisperModel
    except ImportError as exc:
        raise PipelineError(
            "STT_PROVIDER=faster-whisper is configured but faster-whisper is not installed. "
            "Install it with 'pip install faster-whisper' or submit timestamped transcript JSON."
        ) from exc
    try:
        model = WhisperModel(settings.stt_model, device=settings.stt_device, compute_type=settings.stt_compute_type)
        segments, _ = model.transcribe(str(path), word_timestamps=False)
        result = [
            {"narration": segment.text.strip(), "start": float(segment.start), "end": float(segment.end)}
            for segment in segments if segment.text.strip()
        ]
    except Exception as exc:
        raise PipelineError(f"Speech-to-text transcription failed: {exc}") from exc
    if not result:
        raise PipelineError("Speech-to-text returned no narration; the audio may be silent.")
    return result


def _render_aspect(
    clip_paths: list[Path], audio_path: Path, output_path: Path, ratio: str,
    srt_path: Path | None, duration: float,
) -> None:
    dimensions = {"16:9": "1280:720", "9:16": "720:1280", "1:1": "1080:1080"}
    if ratio not in dimensions:
        raise PipelineError(f"Unsupported aspect ratio: {ratio}")
    width, height = (int(value) for value in dimensions[ratio].split(":"))
    concat_file = output_path.parent / f"{output_path.stem}-concat.txt"
    concat_file.write_text(
        "".join(f"file '{path.resolve().as_posix()}'\n" for path in clip_paths),
        encoding="utf-8",
    )
    filters = [
        f"scale={dimensions[ratio]}:force_original_aspect_ratio=increase",
        f"crop={dimensions[ratio]}",
        "setsar=1",
        "eq=contrast=1.04:saturation=1.05",
        f"zoompan=z='min(zoom+0.00012,1.04)':x='iw/2-(iw/zoom/2)':"
        f"y='ih/2-(ih/zoom/2)':d=1:s={width}x{height}:fps=30",
        "fade=t=in:st=0:d=0.2",
        f"fade=t=out:st={max(0.0, duration - 0.2):.3f}:d=0.2",
    ]
    if srt_path:
        subtitle_path = srt_path.as_posix().replace(":", r"\:")
        filters.append(f"subtitles={subtitle_path}")
    _run([
        _ffmpeg_executable(), "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-i", str(audio_path), "-vf", ",".join(filters), "-map", "0:v:0", "-map", "1:a:0",
        "-shortest", "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-movflags", "+faststart", str(output_path),
    ])
    concat_file.unlink(missing_ok=True)


def _normalize_clip(source: Path, destination: Path, duration: float) -> None:
    """Normalize provider media before concat demuxing to avoid codec mismatches."""
    _run([
        _ffmpeg_executable(), "-y", "-stream_loop", "-1", "-i", str(source), "-t", f"{duration:.3f}",
        "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,"
        "pad=1280:720:(ow-iw)/2:(oh-ih)/2,eq=contrast=1.04:saturation=1.05,"
        "fps=30,format=yuv420p",
        "-r", "30", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(destination),
    ])


def render_job(
    job_id: str,
    request: JobRequest,
    store: JobStore,
    audio_path: Path | None = None,
    transcript: list[dict[str, Any]] | None = None,
) -> None:
    job_dir = settings.output_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    started_at = time.perf_counter()
    try:
        if not request.render:
            raise PipelineError("Rendering is disabled. Set render=true to run the real pipeline.")
        if audio_path is None and settings.tts_provider != "pyttsx3":
            raise PipelineError(
                "No configured script TTS provider. Set TTS_PROVIDER=pyttsx3 and install "
                "pyttsx3, or upload narration audio."
            )
        if settings.footage_provider not in {"pixabay", "pexels"}:
            raise PipelineError(
                "Real video rendering is blocked because FOOTAGE_PROVIDER is not set to 'pixabay' or 'pexels'. "
                "The mock provider creates a solid-color test background, not moving footage. "
                "Set FOOTAGE_PROVIDER=pixabay and PIXABAY_API_KEY in the local .env; no MP4 was produced."
            )
        if settings.footage_provider == "pixabay" and not settings.pixabay_api_key:
            raise PipelineError(
                "Real video rendering requires PIXABAY_API_KEY in the local .env. "
                "No MP4 was produced."
            )
        if settings.footage_provider == "pexels" and not settings.pexels_api_key:
            raise PipelineError(
                "Real video rendering requires PEXELS_API_KEY in the local .env. "
                "No MP4 was produced."
            )
        store.update(job_id, status="processing", progress=5)
        uploaded_audio = audio_path is not None
        if audio_path is None:
            audio_path = job_dir / "narration.wav"
            narration_text = " ".join(
                str(scene["narration"]) for scene in script_to_scenes(request.script or "")
            )
            LocalTTS().synthesize(narration_text, audio_path)
        duration = audio_duration(audio_path)
        if duration <= 0 or duration > settings.max_audio_seconds:
            raise PipelineError(f"Audio duration must be greater than 0 and no more than {settings.max_audio_seconds}s.")
        if transcript:
            scene_data = validate_scene_timing(transcript, duration)
        elif uploaded_audio:
            scene_data = validate_scene_timing(transcribe_audio(audio_path), duration)
        elif request.scenes:
            span = duration / len(request.scenes)
            scene_data = [
                {"narration": item.narration, "visual_hint": item.visual_hint, "start": i * span, "end": (i + 1) * span}
                for i, item in enumerate(request.scenes)
            ]
        else:
            script_scenes = script_to_scenes(request.script or "")
            span = duration / len(script_scenes)
            scene_data = [
                {
                    "narration": str(scene["narration"]),
                    "visual_hint": scene["visual_hint"],
                    "start": i * span,
                    "end": (i + 1) * span,
                }
                for i, scene in enumerate(script_scenes)
            ]
        scene_data = validate_scene_timing(scene_data, duration)
        store.update(job_id, progress=20)
        provider: PexelsFootageProvider | PixabayFootageProvider | MockFootageProvider
        if settings.footage_provider == "pixabay":
            provider = PixabayFootageProvider()
        elif settings.footage_provider == "pexels":
            provider = PexelsFootageProvider()
        else:
            provider = MockFootageProvider()
        used_ids: set[str] = set()
        clip_paths: list[Path] = []
        timeline: list[dict[str, Any]] = []
        for index, scene in enumerate(scene_data, 1):
            avoid_terms = {term.casefold() for term in request.avoid}
            scene_terms = " ".join(
                part for part in (scene.get("visual_hint"), scene["narration"]) if part
            ).split()
            filtered_scene = " ".join(term for term in scene_terms if term.casefold() not in avoid_terms)
            query = f"{request.style} {filtered_scene}".strip()
            source_path = job_dir / f"source-{index:03d}.mp4"
            clip_path = job_dir / f"clip-{index:03d}.mp4"
            if isinstance(provider, PixabayFootageProvider):
                footage = provider.search_and_download(
                    query, source_path, used_ids, request.aspect_ratios[0]
                )
            else:
                footage = provider.search_and_download(query, source_path, used_ids)
            source_metadata = probe_media(source_path)
            footage["validated_media"] = validate_visible_motion(source_path, source_metadata)
            _normalize_clip(source_path, clip_path, scene["end"] - scene["start"])
            clip_paths.append(clip_path)
            timeline.append({
                "scene_id": f"scene-{index:03d}", "narration": scene["narration"],
                "start": scene["start"], "end": scene["end"],
                "visual_search_query": query, "visual_hint": scene.get("visual_hint"),
                "selected_footage": footage,
            })
        store.update(job_id, progress=55)
        timeline_path = job_dir / "timeline.json"
        timeline_path.write_text(json.dumps({"scenes": timeline}, indent=2), encoding="utf-8")
        srt_path = job_dir / "captions.srt"
        if request.captions.srt or request.captions.burn_in:
            write_srt(timeline, srt_path)
        outputs: dict[str, str] = {}
        output_metadata: dict[str, dict[str, Any]] = {}
        for ratio in request.aspect_ratios:
            output = job_dir / f"scriptflow-{ratio.replace(':', 'x')}.mp4"
            _render_aspect(
                clip_paths, audio_path, output, ratio,
                srt_path if request.captions.burn_in else None, duration,
            )
            outputs[ratio] = f"/api/v1/jobs/{job_id}/files/{output.name}"
            output_metadata[ratio] = validate_rendered_output(output, ratio, duration)
        first_output = job_dir / f"scriptflow-{request.aspect_ratios[0].replace(':', 'x')}.mp4"
        poster = job_dir / "poster.jpg"
        _run([
            _ffmpeg_executable(), "-y", "-ss", "0.25", "-i", str(first_output),
            "-frames:v", "1", "-q:v", "2", str(poster),
        ])
        manifest = {
            "application": "ScriptFlow AI", "pipeline_version": "0.2.0",
            "providers": {"tts": settings.tts_provider, "stt": settings.stt_provider, "footage": settings.footage_provider},
            "model_settings": {"stt_model": settings.stt_model if settings.stt_provider == "faster-whisper" else None},
            "render_settings": {
                "style": request.style,
                "avoid_terms": request.avoid,
                "captions": request.captions.model_dump(),
                "frame_rate": 30,
                "video_codec": "h264",
                "audio_codec": "aac",
            },
            "requested_aspect_ratios": request.aspect_ratios, "input_duration_seconds": duration,
            "processing_time_seconds": round(time.perf_counter() - started_at, 3),
            "outputs": {
                ratio: {
                    "duration_seconds": float(metadata.get("format", {}).get("duration", 0)),
                    "video_codec": next((s.get("codec_name") for s in metadata.get("streams", [])
                                         if s.get("codec_type") == "video"), None),
                    "audio_codec": next((s.get("codec_name") for s in metadata.get("streams", [])
                                         if s.get("codec_type") == "audio"), None),
                    "width": next((s.get("width") for s in metadata.get("streams", [])
                                   if s.get("codec_type") == "video"), None),
                    "height": next((s.get("height") for s in metadata.get("streams", [])
                                    if s.get("codec_type") == "video"), None),
                    "frame_rate": next((s.get("r_frame_rate") for s in metadata.get("streams", [])
                                        if s.get("codec_type") == "video"), None),
                    "pixel_format": next((s.get("pix_fmt") for s in metadata.get("streams", [])
                                          if s.get("codec_type") == "video"), None),
                    "visual_validation": metadata["visual_validation"],
                }
                for ratio, metadata in output_metadata.items()
            },
            "media_rights": "Verify provider terms and attribution before release.",
            "scene_count": len(timeline),
        }
        (job_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        outputs.update({
            "poster": f"/api/v1/jobs/{job_id}/files/{poster.name}",
            "srt": f"/api/v1/jobs/{job_id}/files/captions.srt",
            "timeline": f"/api/v1/jobs/{job_id}/files/timeline.json",
            "manifest": f"/api/v1/jobs/{job_id}/files/manifest.json",
        })
        store.update(job_id, status="completed", progress=100, result=outputs)
    except Exception as exc:
        for output in job_dir.glob("scriptflow-*.mp4"):
            output.unlink(missing_ok=True)
        store.update(job_id, status="failed", progress=100, error=str(exc))


def process_job(job_id: str, request: JobRequest, store: JobStore) -> None:
    if request.render:
        render_job(job_id, request, store)
        return
    job_dir = settings.output_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    try:
        store.update(job_id, status="processing", progress=10)
        texts = [(item.narration, item.visual_hint) for item in request.scenes] if request.scenes else [
            (str(scene["narration"]), scene["visual_hint"])
            for scene in script_to_scenes(request.script or "")
        ]
        timeline = [{
            "scene_id": f"scene-{index:03d}", "narration": narration,
            "start": (index - 1) * 3.0, "end": index * 3.0,
            "visual_search_query": hint or narration, "visual_hint": hint,
            "selected_footage": {"provider": "mock", "asset_id": f"synthetic-{uuid4().hex[:12]}",
                                 "is_synthetic": True, "rights": "Synthetic test media; not stock footage."},
        } for index, (narration, hint) in enumerate(texts, 1)]
        (job_dir / "timeline.json").write_text(json.dumps({"scenes": timeline}, indent=2), encoding="utf-8")
        (job_dir / "manifest.json").write_text(json.dumps({
            "application": "ScriptFlow AI", "pipeline_version": "0.2.0",
            "providers": {"tts": settings.tts_provider, "footage": settings.footage_provider},
            "requested_aspect_ratios": request.aspect_ratios,
            "warnings": ["Preview metadata only; set render=true for actual media rendering."],
        }, indent=2), encoding="utf-8")
        time.sleep(settings.mock_processing_delay_seconds)
        store.update(job_id, status="completed", progress=100, result={
            "timeline": f"/api/v1/jobs/{job_id}/files/timeline.json",
            "manifest": f"/api/v1/jobs/{job_id}/files/manifest.json",
        })
    except Exception as exc:
        store.update(job_id, status="failed", progress=100, error=str(exc))
