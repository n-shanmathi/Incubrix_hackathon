import json
import importlib.util
import re
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from .config import settings
from .models import Captions, JobRequest, JobResponse
from .pipeline import process_job, render_job
from .storage import JobStore

app = FastAPI(title=settings.app_name, version="0.1.0")
store = JobStore(settings.database_path)
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
ALLOWED_SUFFIXES = {".json", ".srt", ".mp4", ".jpg", ".jpeg"}
JOB_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


def executable_available(value: str) -> bool:
    candidate = Path(value)
    return candidate.is_file() if candidate.is_absolute() else shutil.which(value) is not None


def response_from_row(row) -> JobResponse:
    return JobResponse(**store.as_dict(row))


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    frontend_index = FRONTEND_DIST / "index.html"
    if frontend_index.is_file():
        return HTMLResponse(frontend_index.read_text(encoding="utf-8"))
    return """<!doctype html><html><head><meta charset="utf-8"><title>ScriptFlow AI</title>
    <style>body{font:16px system-ui;max-width:900px;margin:2rem auto;padding:0 1rem}
    textarea{width:100%;max-width:760px}label{display:block;margin:.7rem 0}
    button{padding:.6rem 1rem}#status{white-space:pre-wrap;background:#f4f4f4;padding:1rem}
    video{max-width:100%;margin-top:1rem}</style></head><body>
    <h1>ScriptFlow AI</h1><p>Generate a validated MP4 from a script or narration audio.</p>
    <form id="form"><label>Script<textarea id="script" rows="5">Saving money creates options. Small habits build a stronger future.</textarea></label>
    <label>Audio upload (optional)<input id="audio" type="file" accept=".mp3,.wav,.m4a"></label>
    <label>Style<input id="style" value="bright, modern, real-world footage"></label>
    <label>Avoid terms<input id="avoid" value=""></label>
    <label>Aspect ratios
    <select id="ratios" multiple><option selected>16:9</option><option>9:16</option><option>1:1</option></select></label>
    <label><input id="burn" type="checkbox"> Burn captions into video</label>
    <button>Render video</button></form><h2>Status</h2><div id="status">Waiting for a job.</div>
    <div id="links"></div><video id="preview" controls hidden></video>
    <script>
    const form=document.getElementById('form'), statusBox=document.getElementById('status');
    form.onsubmit=async event=>{event.preventDefault(); statusBox.textContent='Submitting...';
      const ratios=[...document.getElementById('ratios').selectedOptions].map(o=>o.value);
      const file=document.getElementById('audio').files[0]; let response;
      if(file){const data=new FormData();data.append('audio',file);data.append('aspect_ratios',JSON.stringify(ratios));
        data.append('style',document.getElementById('style').value);data.append('captions',JSON.stringify({burn_in:burn.checked,srt:true}));
        response=await fetch('/api/v1/broll/jobs/upload',{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:data});
      }else{response=await fetch('/api/v1/broll/jobs',{method:'POST',headers:{'content-type':'application/json','Idempotency-Key':crypto.randomUUID()},
        body:JSON.stringify({script:script.value,aspect_ratios:ratios,style:style.value,captions:{burn_in:burn.checked,srt:true},render:true})});}
      const created=await response.json(); if(!response.ok){statusBox.textContent=JSON.stringify(created,null,2);return}
      for(;;){const current=await fetch('/api/v1/jobs/'+created.job_id).then(r=>r.json());statusBox.textContent=JSON.stringify(current,null,2);
        if(current.status==='completed'){const result=await fetch('/api/v1/jobs/'+created.job_id+'/result').then(r=>r.json());
          links.innerHTML=Object.entries(result).map(([name,url])=>'<a href="'+url+'" download>'+name+'</a><br>').join('');
          const first=Object.entries(result).find(([name])=>name.includes(':'));if(first){preview.src=first[1];preview.hidden=false}break}
        if(current.status==='failed')break; await new Promise(resolve=>setTimeout(resolve,1000));}
    };
    </script></body></html>"""


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    return {"status": "ready"}


@app.get("/api/v1/jobs")
def list_jobs(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    if status not in {None, "queued", "processing", "completed", "failed"}:
        raise HTTPException(status_code=400, detail="Unsupported job status.")
    rows = store.list(status, limit, offset)
    counts = store.counts()
    total_count = sum(counts.values()) if status is None else counts[status]
    return {
        "jobs": [store.as_dict(row) for row in rows],
        "count": len(rows),
        "total_count": total_count,
        "counts": counts,
    }


@app.get("/api/v1/service-status")
def service_status() -> dict[str, object]:
    has_pyttsx3 = importlib.util.find_spec("pyttsx3") is not None
    has_whisper = importlib.util.find_spec("faster_whisper") is not None
    ffmpeg_available = executable_available(settings.ffmpeg_path)
    ffprobe_available = executable_available(settings.ffprobe_path)
    return {
        "api": "available",
        "tts": {
            "provider": settings.tts_provider,
            "available": settings.tts_provider == "pyttsx3" and has_pyttsx3,
        },
        "stt": {
            "provider": settings.stt_provider,
            "available": settings.stt_provider == "faster-whisper" and has_whisper,
        },
        "footage": {
            "provider": settings.footage_provider,
            "available": (
                settings.footage_provider == "pixabay" and bool(settings.pixabay_api_key)
            ) or (
                settings.footage_provider == "pexels" and bool(settings.pexels_api_key)
            ),
            "test_mode": settings.footage_provider == "mock",
            "setup_message": (
                "Set FOOTAGE_PROVIDER=pixabay and PIXABAY_API_KEY in the local .env, then restart the backend."
                if settings.footage_provider == "pixabay" and not settings.pixabay_api_key
                else "Pixabay is ready for video search."
                if settings.footage_provider == "pixabay" and settings.pixabay_api_key
                else "Set FOOTAGE_PROVIDER=pixabay and PIXABAY_API_KEY in the local .env to use Pixabay."
                if settings.footage_provider == "mock"
                else "Check the configured footage provider credentials."
            ),
        },
        "rendering": {
            "available": ffmpeg_available and ffprobe_available,
            "ffmpeg_available": ffmpeg_available,
            "ffprobe_available": ffprobe_available,
            "formats": ["mp4", "srt", "json"],
        },
    }


@app.post("/api/v1/broll/jobs", response_model=JobResponse, status_code=202)
def create_job(
    request: JobRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JobResponse:
    if idempotency_key:
        existing = store.get_by_idempotency_key(idempotency_key)
        if existing:
            return response_from_row(existing)
    job_id = uuid4().hex
    if not store.create(job_id, request.model_dump(), idempotency_key):
        existing = store.get_by_idempotency_key(idempotency_key or "")
        if existing:
            return response_from_row(existing)
        raise HTTPException(status_code=409, detail="Could not create job")
    background_tasks.add_task(process_job, job_id, request, store)
    return response_from_row(store.get(job_id))


@app.post("/api/v1/broll/jobs/upload", response_model=JobResponse, status_code=202)
async def create_audio_job(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    aspect_ratios: str = Form('["16:9"]'),
    style: str = Form("bright, modern, real-world footage"),
    avoid: str = Form("[]"),
    captions: str = Form('{"burn_in":false,"srt":true}'),
    transcript: str | None = Form(None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JobResponse:
    suffix = Path(audio.filename or "").suffix.lower()
    if suffix not in {".mp3", ".wav", ".m4a"}:
        raise HTTPException(status_code=415, detail="Audio must be MP3, WAV, or M4A.")
    try:
        request = JobRequest(
            audio_url="uploaded",
            aspect_ratios=json.loads(aspect_ratios),
            style=style,
            avoid=json.loads(avoid),
            captions=Captions.model_validate(json.loads(captions)),
            render=True,
        )
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid multipart options: {exc}") from exc
    try:
        parsed_transcript = json.loads(transcript) if transcript else None
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid transcript JSON: {exc}") from exc
    if parsed_transcript is not None and (
        not isinstance(parsed_transcript, list)
        or any(not isinstance(scene, dict) for scene in parsed_transcript)
    ):
        raise HTTPException(status_code=422, detail="Transcript must be a JSON array of scene objects.")
    if idempotency_key:
        existing = store.get_by_idempotency_key(idempotency_key)
        if existing:
            return response_from_row(existing)
    job_id = uuid4().hex
    job_dir = settings.output_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    destination = job_dir / f"input{suffix}"
    size = 0
    with destination.open("wb") as output:
        while chunk := await audio.read(1024 * 256):
            size += len(chunk)
            if size > settings.max_upload_bytes:
                destination.unlink(missing_ok=True)
                job_dir.rmdir()
                raise HTTPException(status_code=413, detail="Uploaded audio exceeds the size limit.")
            output.write(chunk)
    if not store.create(job_id, request.model_dump(), idempotency_key):
        destination.unlink(missing_ok=True)
        job_dir.rmdir()
        existing = store.get_by_idempotency_key(idempotency_key or "")
        if existing:
            return response_from_row(existing)
        raise HTTPException(status_code=409, detail="Could not create job")
    background_tasks.add_task(render_job, job_id, request, store, destination, parsed_transcript)
    return response_from_row(store.get(job_id))


@app.get("/api/v1/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str) -> JobResponse:
    if not JOB_ID_PATTERN.fullmatch(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    row = store.get(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    return response_from_row(row)


@app.get("/api/v1/jobs/{job_id}/result")
def get_result(job_id: str) -> dict:
    if not JOB_ID_PATTERN.fullmatch(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    row = store.get(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    if row["status"] != "completed":
        raise HTTPException(status_code=409, detail="Job is not complete")
    return json.loads(row["result_json"])


@app.get("/api/v1/jobs/{job_id}/files/{filename}")
def get_file(job_id: str, filename: str):
    if (not JOB_ID_PATTERN.fullmatch(job_id)
            or Path(filename).name != filename
            or Path(filename).suffix.lower() not in ALLOWED_SUFFIXES):
        raise HTTPException(status_code=404, detail="File not found")
    path = settings.output_dir / job_id / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)


@app.get("/{asset_path:path}", include_in_schema=False)
def frontend_route(asset_path: str):
    if asset_path == "api" or asset_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    frontend_root = FRONTEND_DIST.resolve()
    asset = (frontend_root / asset_path).resolve()
    if frontend_root not in asset.parents:
        raise HTTPException(status_code=404, detail="Not found")
    if asset.is_file():
        return FileResponse(asset)
    frontend_index = frontend_root / "index.html"
    if frontend_index.is_file():
        return FileResponse(frontend_index)
    raise HTTPException(status_code=404, detail="Not found")
