# ScriptFlow AI

ScriptFlow AI is a local FastAPI + React/Vite application for rendering narrated
script-to-video jobs and transcript-aligned voiceover jobs. It tracks jobs in SQLite,
generates local narration with pyttsx3, renders MP4/SRT/timeline/manifest outputs
with FFmpeg, and validates the output with FFprobe. Real Pixabay retrieval is
required for actual MP4 renders and uses a local API key; mock footage is
synthetic solid-color test media and is rejected by the real render path.

## Demo video

Watch the ScriptFlow AI demo video: **[View the demo](PASTE_DEMO_VIDEO_URL_HERE)**.
Replace the placeholder link with the published video URL when it is available.

## Run locally

```powershell
& C:\Python313\python.exe -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 or http://127.0.0.1:8000/docs.

## React studio

The React/Vite frontend is in `frontend/`. Run the backend and frontend in
separate PowerShell terminals:

```powershell
cd E:\Incubrix
& C:\Python313\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
cd E:\Incubrix\frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173. Vite proxies `/api` requests to the local FastAPI
server. Production frontend assets can be checked with `npm run build` from
`frontend/`; the API remains a separately launched service.

## Deploy a live demo on Render

The repository includes a Render Blueprint and Dockerfile for a single-service
deployment. The image builds the React studio, serves it with FastAPI, and
installs FFmpeg/FFprobe plus eSpeak NG for Linux narration. On Linux, narration
uses the `en-us` eSpeak NG voice directly to avoid pyttsx3/espeak voice lookup
failures. The initial configuration uses Pixabay for real footage; add the API
key as a private
environment variable in Render, never in this repository:

```text
FOOTAGE_PROVIDER=pixabay
PIXABAY_API_KEY=<set privately in the Render dashboard>
TTS_PROVIDER=pyttsx3
REAL_RENDERING=true
```

To deploy, connect the GitHub repository to Render and create a new Blueprint
from `render.yaml`. Set `PIXABAY_API_KEY` when prompted, then deploy and open
the generated `onrender.com` URL. The `/health` endpoint is used for the
service health check. Confirm Pixabay credentials and the service-status page
before recording a real-footage demo.

The Blueprint uses Render's free web-service plan. Its local SQLite database,
Pixabay cache, and generated media are **ephemeral**: they can be lost after a
restart, sleep, or redeploy, and the first request after sleep may be slow.
This is suitable for a temporary demo, not durable job storage. Render free
services also have limited compute and may not reliably complete long renders.
Use persistent storage and an appropriate paid instance if results must survive
restarts or the service must remain available throughout a review period.

## Media dependencies on Windows

`ffmpeg` and `ffprobe` must be from the same official FFmpeg build. The simplest
safe option is to install a current build from
[gyan.dev](https://www.gyan.dev/ffmpeg/builds/) or use Windows package manager:

```powershell
winget install --id Gyan.FFmpeg.Shared -e
```

Close and reopen PowerShell, then verify:

```powershell
ffmpeg -version
ffprobe -version
```

If they are not on `PATH`, set absolute paths in `.env`:

```text
FFMPEG_PATH=C:\ffmpeg\bin\ffmpeg.exe
FFPROBE_PATH=C:\ffmpeg\bin\ffprobe.exe
```

Absolute paths are also supported when the installation directory contains
spaces. The current WinGet per-user installation can be discovered with:

```powershell
Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Filter ffprobe.exe -Recurse
```

The project has a Python-managed FFmpeg fallback through `imageio-ffmpeg`, but
that fallback does not include FFprobe and therefore cannot pass final-output
validation. It is not enough for an assessment-ready render.

## API example

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/broll/jobs `
  -H "Content-Type: application/json" -H "Idempotency-Key: demo-1" `
  -d '{"script":"Save money. Build a better future.","aspect_ratios":["16:9"]}'
```

The response contains a `job_id`. Query `/api/v1/jobs/{job_id}` and then
`/api/v1/jobs/{job_id}/result`.

For uploaded narration:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/broll/jobs/upload `
  -H "Idempotency-Key: audio-demo-1" `
  -F "audio=@C:\path\to\narration.wav" `
  -F 'aspect_ratios=["16:9","9:16"]' `
  -F 'captions={"burn_in":true,"srt":true}'
```

The upload endpoint accepts MP3, WAV, and M4A. A real transcription provider is
not bundled; pass a timestamped `transcript` JSON payload for local deterministic
testing, or add an STT adapter before using unannotated uploads.

## Real moving footage setup

Real MP4 rendering requires Pixabay footage. Copy `.env.example` to `.env` if
needed, then configure the following values locally (never put the key in the
frontend or commit it):

```text
FOOTAGE_PROVIDER=pixabay
PIXABAY_API_KEY=your_pixabay_api_key
```

Restart the backend after changing `.env`. Pixabay API video search is cached
locally for at least 24 hours and uses a bounded number of retries. Search results are
ranked deterministically using scene-tag token overlap, then resolution,
duration, and aspect-ratio suitability. Downloaded clips are kept in a local
cache and copied into each isolated job directory. A render fails with an
actionable error when the provider/key is unavailable, a search has no usable
clips, or the footage fails media validation; there is no silent mock fallback.
The manifest preserves the source page, contributor data when supplied, and a
link to Pixabay's current terms. It does not assert an unverified specific
licence grant; verify Pixabay's current terms and the asset page before
redistribution or commercial use.

## Known limitations

The real rendering path includes SRT generation, aspect-ratio encoding, provider
adapters, duplicate prevention, and FFprobe validation. The final video must
decode into visible, moving frames. Script rendering requires
`TTS_PROVIDER=pyttsx3` and the local `pyttsx3` package. Pixabay rendering requires
`FOOTAGE_PROVIDER=pixabay` and `PIXABAY_API_KEY`; the provider uses the official
Pixabay video endpoint and records the result URL and available attribution.
No synthetic asset is represented as real stock footage or as having
commercial-use rights. Live Pixabay search and rendering require a configured
key; mocked tests do not establish that live API access is working.

The studio UI supports landing, dashboard, create, project library, templates,
job status, settings, and read-only editor preview routes. Real renders include
a slow zoom/pan, a restrained contrast/saturation grade, short opening/closing
fades, and synchronized captions. Crossfades between scenes, music mixing,
animated word highlighting, scene replacement, and editing/regenerating scenes
are not implemented.

Uploaded audio requires either a timestamped `transcript` multipart field or a
real transcription configuration:

```text
STT_PROVIDER=faster-whisper
STT_MODEL=base
STT_DEVICE=cpu
STT_COMPUTE_TYPE=int8
```

Install the optional adapter only when local model downloads and disk space are
available:

```powershell
& C:\Python313\python.exe -m pip install faster-whisper
```

Without it, an uploaded audio job fails clearly instead of being treated as
already transcribed.

## Tests

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
```

Run the ten-input automated evaluation after starting the API:

```powershell
& C:\Python313\python.exe scripts\evaluate.py
```

This writes `data/evaluation_results.csv`. Automated status is recorded, but the
`human_relevance_score` column is intentionally blank until a reviewer rates each
video.

### Visual render smoke check

Submit the original short script from the Create page, wait for the job to
complete, and open the editor preview. Confirm that the poster and playback show
moving footage throughout, captions track the narration, and the output is not
labelled mock. Then inspect the same output with FFprobe. Use a job created with a configured
Pixabay key; mock mode is deliberately not a real-footage demonstration.
Scripts may use headings such as `Scene 1 — The Sunrise` on a line by itself;
these are treated as scene visual hints, not spoken narration. Footage checks
allow localized movement (such as birds crossing an otherwise slowly changing
sunrise) while still rejecting blank and unchanged-frame clips.
Inspect the generated video at multiple timestamps to ensure it contains
moving footage rather than only relying on a completed job status:

```powershell
ffprobe -v error -show_entries format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,pix_fmt,duration -of json E:\Incubrix\data\jobs\<job-id>\scriptflow-16x9.mp4
```

For visual frame inspection, extract frames at multiple points and open the PNGs:

```powershell
ffmpeg -y -ss 0.5 -i E:\Incubrix\data\jobs\<job-id>\scriptflow-16x9.mp4 -frames:v 1 $env:TEMP\scriptflow-frame-1.png
ffmpeg -y -ss 2.5 -i E:\Incubrix\data\jobs\<job-id>\scriptflow-16x9.mp4 -frames:v 1 $env:TEMP\scriptflow-frame-2.png
ffmpeg -y -ss 5 -i E:\Incubrix\data\jobs\<job-id>\scriptflow-16x9.mp4 -frames:v 1 $env:TEMP\scriptflow-frame-3.png
```

Do not count a completed job or an MP4 file alone as evidence of a successful
visual render. If Pixabay credentials are not configured, the expected behavior
is an explicit failed job and no MP4.
