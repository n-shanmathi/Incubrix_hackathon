# Runtime Validation Report

**Generated:** 2026-10-20  
**Target:** `E:\Incubrix`

## Summary

| Step | Status | Exit code | Details |
|---|---:|---:|---|
| Application startup | PASS | 0 | Uvicorn started on `127.0.0.1:8000`; `/health` returned HTTP 200 |
| Backend tests | PASS | 0 | `11 passed, 1 warning` with `python -m pytest -q` |
| Frontend build | PASS | 0 | `npm run build` ran TypeScript project checks and Vite production build |
| Browser script workflow | PASS | 0 | Create page submitted a job; job status completed; editor loaded the actual MP4 and two scene rows |
| Audio error workflow | PASS | 0 | Audio upload without transcript reached a failed job with actionable STT setup instructions |
| Real render | PASS | 0 | Job `5fdf423c1e0844f1841b3ec900431d1b` produced 9:16 MP4, SRT, timeline, and manifest |
| FFprobe validation | PASS | 0 | Output contains H.264 video and AAC audio at `720x1280`, 30 fps, 7.702630 seconds |
| Ten-input evaluation | PASS | 0 | Ten jobs completed with automated checks passed |

## Real Render Evidence

The browser-created smoke job used local `pyttsx3` narration and the explicitly
synthetic mock-footage provider. FFprobe reported:

- `9:16`: `720x1280`, H.264/AAC, `7.702630` seconds

The manifest records `tts=pyttsx3`, `stt=mock`, and `footage=mock`; the output is
not evidence of real stock-footage relevance or commercial-use clearance.

## Evaluation Evidence

`data/evaluation_results.csv` contains ten completed jobs and `automated_checks=passed`
for every input. `human_relevance_score` is blank for every row and must be filled
only by a reviewer.

## Capability Gaps

- Pexels was not live-tested because no `PEXELS_API_KEY` is configured locally.
- Genuine uploaded-audio transcription was not tested because `faster-whisper` is
  optional and is not installed. Uploaded audio therefore requires a timestamped
  transcript JSON field unless a real STT adapter is configured.
- Crossfade transitions, animated text, music, and scene replacement are not
  implemented. The editor preview is read-only and accurately says so.
- Browser verification covered the landing/create/job/editor/settings/dashboard
  pages and a real script submit. The audio upload UI was also submitted and
  verified to show the clear missing-STT error. No separate Playwright test suite
  was added.
- The FastAPI/Starlette test client emitted one dependency deprecation warning.

## Reproduction

```powershell
cd E:\Incubrix
& C:\Python313\python.exe -m pytest -q
& C:\Python313\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
cd E:\Incubrix\frontend
npm install
npm run dev
& C:\Python313\python.exe scripts\evaluate.py
```
