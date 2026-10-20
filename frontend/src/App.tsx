import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Link, NavLink, Route, Routes, useNavigate, useParams, useSearchParams
} from "react-router-dom";
import {
  Film, FolderOpen, Gauge, LayoutTemplate, Play, Settings, Sparkles, Upload, WandSparkles
} from "lucide-react";
import {
  createAudioJob, createJob, fileUrl, getJob, getJobs, getServiceStatus, getTimeline, Job, ServiceStatus
} from "./api";

const templates = [
  { name: "Cinematic travel", description: "Wide landscapes, measured pacing, cinematic tone.", style: "travel", ratio: "16:9" },
  { name: "Nature documentary", description: "A calm documentary treatment for nature stories.", style: "nature", ratio: "16:9" },
  { name: "Educational explainer", description: "Clear narration and balanced educational visuals.", style: "educational", ratio: "16:9" },
  { name: "Business story", description: "Clean, confident framing for business narratives.", style: "business", ratio: "16:9" },
  { name: "Social media reel", description: "Portrait-first settings for short social videos.", style: "social media", ratio: "9:16" },
  { name: "Motivational video", description: "Narration-led scenes for an uplifting message.", style: "cinematic", ratio: "9:16" },
  { name: "Product showcase", description: "A simple product-oriented visual direction.", style: "business", ratio: "1:1" },
  { name: "News-style explainer", description: "A direct, minimal style for informative scripts.", style: "minimal", ratio: "16:9" }
];

function Shell({ children }: { children: ReactNode }) {
  return <div className="app-shell">
    <aside>
      <Link className="brand" to="/"><span className="brand-mark"><Sparkles size={18}/></span>ScriptFlow <em>AI</em></Link>
      <nav aria-label="Main navigation">
        <NavLink to="/" end><Sparkles size={17}/>Home</NavLink>
        <NavLink to="/dashboard"><Gauge size={17}/>Dashboard</NavLink>
        <NavLink to="/create"><WandSparkles size={17}/>Create video</NavLink>
        <NavLink to="/projects"><FolderOpen size={17}/>My projects</NavLink>
        <NavLink to="/templates"><LayoutTemplate size={17}/>Templates</NavLink>
        <a href="/#features"><Film size={17}/>Features</a>
        <NavLink to="/settings"><Settings size={17}/>Settings</NavLink>
      </nav>
      <div className="side-note"><span className="dot"/> Local app</div>
    </aside>
    <main>{children}</main>
  </div>;
}

function Home() {
  const featureTitles = ["Scene matching", "Local narration", "Caption-ready", "Three ratios"];
  const featureDescriptions = [
    "Use each scene's narration as a visual search query and record the selection rationale.",
    "Generate narration locally with pyttsx3 when configured.",
    "Export synchronized SRT subtitles and optional burn-in.",
    "Render 16:9, 9:16, and 1:1 outputs separately."
  ];
  return <Shell>
    <section className="hero">
      <div>
        <p className="eyebrow">SCRIPT TO STORY · VOICEOVER TO B-ROLL</p>
        <h1>Turn your script into a <span>cinematic cut.</span></h1>
        <p className="lede">Create narration-led videos with timed scenes, captions, and downloadable production metadata.</p>
        <div className="actions">
          <Link className="button primary" to="/create"><WandSparkles size={17}/>Create your first video</Link>
          <Link className="button ghost" to="/templates">Explore templates</Link>
        </div>
      </div>
      <div className="hero-preview">
        <div className="preview-top"><span>WORKSPACE PREVIEW · SAMPLE</span><span className="pill">16:9</span></div>
        <div className="preview-art"><Play size={34}/><div><strong>Your story, in motion.</strong><small>Illustrative workspace preview, not generated footage.</small></div></div>
        <div className="wave" aria-hidden="true">{Array.from({length: 34}, (_, i) => <i key={i} style={{height: `${20 + (i * 17) % 50}%`}}/>)}</div>
      </div>
    </section>
    <section className="feature-grid" id="features">{featureTitles.map((title, i) => <article className="feature" key={title}>
      <span className="feature-icon">{[<Sparkles key="spark"/>,<Gauge key="gauge"/>,<Film key="film"/>,<LayoutTemplate key="layout"/>][i]}</span>
      <h3>{title}</h3><p>{featureDescriptions[i]}</p>
    </article>)}</section>
    <section className="workflow"><p className="eyebrow">THREE STEPS</p><div>
      <article><b>01</b><h3>Write or upload</h3><p>Start with script text or voiceover with a timestamped transcript.</p></article>
      <article><b>02</b><h3>Choose your frame</h3><p>Pick an output ratio and a visual style the renderer supports.</p></article>
      <article><b>03</b><h3>Render and review</h3><p>Track the actual job, preview the MP4, and download project files.</p></article>
    </div></section>
    <footer><span>ScriptFlow AI · Local video workflow</span><Link to="/settings">Provider status</Link></footer>
  </Shell>;
}

function Create() {
  const navigate = useNavigate();
  const [search] = useSearchParams();
  const [mode, setMode] = useState<"script" | "audio">("script");
  const [script, setScript] = useState("Every morning, one small habit can change the direction of your day. Take a breath, step outside, and make space for a better idea.");
  const [ratios, setRatios] = useState<string[]>([search.get("ratio") || "16:9"]);
  const [style, setStyle] = useState(search.get("style") || "cinematic");
  const [burn, setBurn] = useState(true);
  const [avoidText, setAvoidText] = useState("");
  const [audio, setAudio] = useState<File | null>(null);
  const [transcript, setTranscript] = useState("");
  const [audioPreview, setAudioPreview] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [serviceStatus, setServiceStatus] = useState<ServiceStatus | null>(null);
  const realFootageReady = serviceStatus?.footage.available === true;
  const words = script.trim().split(/\s+/).filter(Boolean).length;
  useEffect(() => { getServiceStatus().then(setServiceStatus).catch(e => setError(e instanceof Error ? e.message : "Could not check rendering services")); }, []);
  useEffect(() => {
    if (!audio) { setAudioPreview(""); return; }
    const url = URL.createObjectURL(audio);
    setAudioPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [audio]);

  async function submit() {
    setError("");
    setBusy(true);
    try {
      const job = mode === "audio" && audio
        ? await createAudioJob(audio, {
          aspect_ratios: ratios, style, avoid: avoidText.split(",").map(term => term.trim()).filter(Boolean),
          captions: { burn_in: burn, srt: true }, transcript
        })
        : await createJob({
          script, aspect_ratios: ratios, style,
          avoid: avoidText.split(",").map(term => term.trim()).filter(Boolean),
          captions: { burn_in: burn, srt: true }, render: true
        });
      navigate(`/jobs/${job.job_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not submit job");
    } finally {
      setBusy(false);
    }
  }

  function toggleRatio(ratio: string) {
    setRatios(current => current.includes(ratio)
      ? (current.length > 1 ? current.filter(value => value !== ratio) : current)
      : [...current, ratio]);
  }

  return <Shell>
    <div className="page-head"><div><p className="eyebrow">CREATE STUDIO</p><h2>Build your next video</h2><p>Configure a supported output, then follow the real render job.</p></div><span className={`status-badge ${serviceStatus?.rendering.available && serviceStatus.footage.available ? "" : "failed"}`}><span className="dot"/>{serviceStatus ? (!serviceStatus.rendering.available ? "FFmpeg/FFprobe unavailable" : serviceStatus.footage.available ? "Real footage ready" : "Footage not configured") : "Checking services…"}</span></div>
    {serviceStatus && (!serviceStatus.rendering.available || (mode === "script" && !serviceStatus.tts.available)) && <div className="notice"><Settings size={18}/><span>{!serviceStatus.rendering.available ? "FFmpeg and FFprobe must be available to render output." : "The selected TTS provider is unavailable; configure pyttsx3 in the backend environment."}</span></div>}
    {serviceStatus && !realFootageReady && <div className="notice" role="alert"><Settings size={18}/><span>{serviceStatus.footage.test_mode ? "Test footage mode is active and cannot produce real B-roll. " : ""}{serviceStatus.footage.setup_message}</span></div>}
    <div className="mode-tabs" role="tablist" aria-label="Video input mode">
      <button role="tab" aria-selected={mode === "script"} className={mode === "script" ? "active" : ""} onClick={() => setMode("script")}>Script to video</button>
      <button role="tab" aria-selected={mode === "audio"} className={mode === "audio" ? "active" : ""} onClick={() => setMode("audio")}>Voiceover to video</button>
    </div>
    <div className="studio-grid">
      <section className="panel">
        <div className="panel-title"><span>01</span><h3>{mode === "script" ? "Story input" : "Voiceover input"}</h3></div>
        {mode === "script" ? <>
          <label htmlFor="script-input">Script<textarea id="script-input" value={script} onChange={e => setScript(e.target.value)} rows={10}/></label>
          <div className="word-count">{words} words · roughly {Math.max(1, Math.round(words / 2.5))} sec narration</div>
        </> : <>
          <label className="upload-box" htmlFor="audio-input"><Upload size={23}/><span>{audio ? audio.name : "Choose an audio file"}</span><small>MP3, WAV, M4A · up to 50 MB</small><input id="audio-input" type="file" accept=".mp3,.wav,.m4a,audio/mpeg,audio/wav,audio/mp4" onChange={e => setAudio(e.target.files?.[0] ?? null)}/></label>
          {audio && <>
            <audio controls src={audioPreview} className="audio-control"/>
            <p className="word-count">{(audio.size / 1024 / 1024).toFixed(2)} MB · Real transcription is required unless you provide transcript segments.</p>
            <label htmlFor="transcript-input">Timestamped transcript JSON (or configure STT)<textarea id="transcript-input" rows={5} value={transcript} onChange={e => setTranscript(e.target.value)} placeholder={'[{"narration":"Hello","start":0,"end":2.4}]'}/></label>
          </>}
        </>}
        <label htmlFor="style-input">Visual style<select id="style-input" value={style} onChange={e => setStyle(e.target.value)}>{["cinematic","documentary","travel","educational","business","social media","nature","minimal"].map(x => <option key={x}>{x}</option>)}</select></label>
        <label htmlFor="avoid-input">Avoid terms (comma-separated)<input id="avoid-input" value={avoidText} onChange={e => setAvoidText(e.target.value)} placeholder="e.g. night, indoors"/></label>
      </section>
      <section className="panel">
        <div className="panel-title"><span>02</span><h3>Output settings</h3></div>
        <div className="editor-preview"><div className="grid-lines"/><Play size={38}/><small>Preview is generated after job submission</small></div>
        <div className="settings-row"><div><label>Aspect ratio</label><div className="segmented">{["16:9","9:16","1:1"].map(r => <button aria-pressed={ratios.includes(r)} className={ratios.includes(r) ? "selected" : ""} onClick={() => toggleRatio(r)} key={r}>{r}</button>)}</div></div><label className="check"><input type="checkbox" checked={burn} onChange={e => setBurn(e.target.checked)}/>Burn captions into video</label></div>
        <p className="word-count">MP4 · H.264 · 30 fps when rendered. Scene transitions and background music are not currently supported.</p>
        {error && <div role="alert" className="error">{error}</div>}
        <button className="button primary generate" disabled={busy || !serviceStatus?.rendering.available || (mode === "script" && !serviceStatus.tts.available) || (mode === "script" ? !script.trim() : !audio)} onClick={submit}>{busy ? "Submitting…" : <><WandSparkles size={17}/>Generate video</>}</button>
      </section>
    </div>
  </Shell>;
}

function useJob(jobId: string) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await getJob(jobId);
        if (!live) return;
        setJob(next);
        if (next.status !== "completed" && next.status !== "failed") timer = window.setTimeout(poll, 1200);
      } catch (e) {
        if (live) setError(e instanceof Error ? e.message : "Could not load job");
      }
    };
    void poll();
    return () => { live = false; if (timer) window.clearTimeout(timer); };
  }, [jobId]);
  return { job, error };
}

function JobPage() {
  const { jobId = "" } = useParams();
  const { job, error } = useJob(jobId);
  if (!job) return <Shell><div className="loading">{error || "Loading job…"}</div></Shell>;
  return <Shell>
    <div className="page-head"><div><p className="eyebrow">RENDER STATUS</p><h2>{job.status === "completed" ? "Your video is ready" : job.status === "failed" ? "Render needs attention" : "Rendering your story"}</h2><p className="mono">{job.job_id}</p></div><span className={`status-badge ${job.status}`}><span className="dot"/>{job.status} · {job.progress}%</span></div>
    <section className="panel job-panel"><p className="word-count">Progress reported by the job service</p><div className="progress"><span style={{width: `${job.progress}%`}}/></div>
      {job.error && <div role="alert" className="error">{job.error}</div>}
      {job.result && <div className="result-grid">{Object.entries(job.result).map(([name, url]) => <a className="result-card" href={fileUrl(url)} key={name} target="_blank" rel="noreferrer"><Film size={20}/><span>{name}</span><small>Open download</small></a>)}</div>}
      {job.status === "completed" && job.result && <Link className="button ghost editor-link" to={`/editor/${job.job_id}`}>Open editor preview</Link>}
      {job.status === "failed" && <Link className="button ghost editor-link" to="/create">Create a new job</Link>}
    </section>
  </Shell>;
}

function Editor() {
  const { jobId = "" } = useParams();
  const { job, error } = useJob(jobId);
  const [timeline, setTimeline] = useState<Array<Record<string, unknown>>>([]);
  const [ratio, setRatio] = useState("");
  const [videoState, setVideoState] = useState<"loading" | "ready" | "error">("loading");
  const ratios = Object.keys(job?.result ?? {}).filter(key => ["16:9","9:16","1:1"].includes(key));
  useEffect(() => {
    if (job?.status === "completed" && job.result?.timeline) {
      getTimeline(job.result.timeline).then(data => setTimeline(data.scenes)).catch(() => setTimeline([]));
    }
  }, [job]);
  useEffect(() => { if (ratios.length && !ratios.includes(ratio)) setRatio(ratios[0]); }, [ratios, ratio]);
  const selectedVideo = ratio ? job?.result?.[ratio] : undefined;
  const poster = job?.result?.poster;
  useEffect(() => { if (selectedVideo) setVideoState("loading"); }, [selectedVideo]);

  return <Shell>
    <div className="page-head"><div><p className="eyebrow">EDITOR PREVIEW</p><h2>{job?.status === "completed" ? "Review your render" : "Waiting for render"}</h2><p className="mono">{jobId}</p></div>{job?.status === "completed" && <Link className="button ghost" to={`/jobs/${jobId}`}>Job details</Link>}</div>
    {error && <div role="alert" className="error">{error}</div>}
    {job?.status === "completed" && job.result ? <div className="editor-layout">
      <section className="panel"><div className="editor-toolbar"><strong>Preview</strong><select aria-label="Output aspect ratio" value={ratio} onChange={e => setRatio(e.target.value)}>{ratios.map(r => <option key={r}>{r}</option>)}</select></div>
        {selectedVideo && <><video className="video-player" controls preload="metadata" poster={poster ? fileUrl(poster) : undefined} src={fileUrl(selectedVideo)} onLoadStart={() => setVideoState("loading")} onLoadedData={() => setVideoState("ready")} onError={() => setVideoState("error")}/>{videoState === "loading" && <p role="status" className="word-count">Loading the completed MP4…</p>}{videoState === "error" && <div role="alert" className="error">The completed video could not be loaded. Try the download link or check the backend file endpoint.</div>}</>}
        <div className="result-grid">{Object.entries(job.result).filter(([name]) => name !== "poster").map(([name,url]) => <a className="result-card" href={fileUrl(url)} key={name} target="_blank" rel="noreferrer">{name}<small>Download output</small></a>)}</div>
        <p className="word-count">Scene replacement is not available in this renderer; the timeline is read-only.</p>
      </section>
      <aside className="timeline-panel"><h3>Scene timeline</h3>{timeline.length ? timeline.map((scene,i) => {
        const footage = scene.selected_footage as Record<string, unknown> | undefined;
        const sourceUrl = typeof footage?.source_url === "string" ? footage.source_url : null;
        return <article className="scene-card" key={String(scene.scene_id ?? i)}><strong>Scene {i+1}</strong><p>{String(scene.narration ?? "")}</p><small>{Number(scene.start ?? 0).toFixed(2)}s — {Number(scene.end ?? 0).toFixed(2)}s</small><small>Source: {String(footage?.provider ?? "not recorded")}</small>{sourceUrl && <a href={sourceUrl} target="_blank" rel="noreferrer">View source</a>}</article>;
      }) : <p className="word-count">Timeline metadata has not loaded yet.</p>}</aside>
    </div> : <section className="panel"><div className="progress"><span style={{width: `${job?.progress ?? 0}%`}}/></div><p>{job?.status ?? "Loading"} · {job?.progress ?? 0}%</p>{job?.error && <div role="alert" className="error">{job.error}</div>}</section>}
  </Shell>;
}

function Projects() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [status, setStatus] = useState("all");
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [loadingMore, setLoadingMore] = useState(false);
  useEffect(() => {
    getJobs(24,0).then(x => { setJobs(x.jobs); setTotalCount(x.total_count); })
      .catch(e => setError(e instanceof Error ? e.message : "Could not load jobs"));
  }, []);
  const filtered = useMemo(() => jobs.filter(j => (status === "all" || j.status === status) && j.job_id.toLowerCase().includes(query.toLowerCase())), [jobs,status,query]);
  async function loadMore() {
    setLoadingMore(true);
    try {
      const next = await getJobs(24,jobs.length);
      setJobs(current => [...current,...next.jobs]);
      setTotalCount(next.total_count);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load more projects");
    } finally {
      setLoadingMore(false);
    }
  }
  return <Shell>
    <div className="page-head"><div><p className="eyebrow">LIBRARY</p><h2>My projects</h2><p>Actual jobs from the local SQLite store.</p></div><Link className="button primary" to="/create">New video</Link></div>
    <div className="project-filters"><input aria-label="Search projects" placeholder="Search job ID…" value={query} onChange={e => setQuery(e.target.value)}/><select aria-label="Filter status" value={status} onChange={e => setStatus(e.target.value)}><option value="all">All statuses</option>{["queued","processing","completed","failed"].map(s => <option key={s}>{s}</option>)}</select></div>
    {error && <div role="alert" className="error">{error}</div>}
    {filtered.length === 0 ? <div className="empty"><FolderOpen size={28}/><h3>{jobs.length ? "No matching projects" : "No projects yet"}</h3><p>{jobs.length ? "Change the search or status filter." : "Generate your first video to see it here."}</p></div> : <div className="project-grid">{filtered.map(job => <Link className="project-card" to={job.status === "completed" ? `/editor/${job.job_id}` : `/jobs/${job.job_id}`} key={job.job_id}><div className="thumb"><Film size={24}/><span>{job.status === "completed" ? "READY" : `${job.progress}%`}</span></div><strong>{job.job_id.slice(0,12)}…</strong><small>{job.status} · {new Date(job.created_at).toLocaleString()}</small></Link>)}</div>}
    {jobs.length < totalCount && <button className="button ghost load-more" onClick={loadMore} disabled={loadingMore}>{loadingMore ? "Loading…" : `Load more (${jobs.length} of ${totalCount})`}</button>}
  </Shell>;
}

function Templates() {
  return <Shell><div className="page-head"><div><p className="eyebrow">START FASTER</p><h2>Templates</h2><p>Presets only set options supported by the current pipeline.</p></div></div>
    <div className="template-grid">{templates.map(item => <article className="template-card" key={item.name}><div className={`template-art ${item.style}`}><Film size={25}/><span>{item.ratio} · STYLE PRESET</span></div><h3>{item.name}</h3><p>{item.description}</p><Link className="button ghost small" to={`/create?style=${encodeURIComponent(item.style)}&ratio=${encodeURIComponent(item.ratio)}`}>Use template</Link></article>)}</div>
  </Shell>;
}

function Dashboard() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [counts, setCounts] = useState<Record<Job["status"], number>>({ queued: 0, processing: 0, completed: 0, failed: 0 });
  const [error, setError] = useState("");
  useEffect(() => { getJobs().then(x => { setJobs(x.jobs); setTotalCount(x.total_count); setCounts(x.counts); }).catch(e => setError(e instanceof Error ? e.message : "Could not load jobs")); }, []);
  return <Shell><div className="page-head"><div><p className="eyebrow">WORKSPACE</p><h2>Good to see you.</h2><p>Keep the story moving with verifiable local renders.</p></div><Link className="button primary" to="/create">Create new video</Link></div>
    <div className="stats"><div><small>Total projects</small><strong>{totalCount}</strong></div><div><small>Completed</small><strong>{counts.completed}</strong></div><div><small>Processing</small><strong>{counts.processing}</strong></div></div>
    <section className="panel"><div className="panel-title"><h3>Recent projects</h3><Link to="/projects">View all</Link></div>{error && <div role="alert" className="error">{error}</div>}{jobs.length === 0 ? <div className="empty"><p>No projects yet. Create one to see it here.</p></div> : jobs.slice(0,5).map(j => <Link className="recent-row" to={`/jobs/${j.job_id}`} key={j.job_id}><span className="mini-thumb"><Film size={16}/></span><span><strong>{j.job_id.slice(0,16)}…</strong><small>{new Date(j.created_at).toLocaleString()}</small></span><span className={`status-text ${j.status}`}>{j.status}</span></Link>)}</section>
  </Shell>;
}

function SettingsPage() {
  const [status,setStatus] = useState<Record<string,unknown> | null>(null);
  const [error,setError] = useState("");
  useEffect(() => { getServiceStatus().then(setStatus).catch(e => setError(e instanceof Error ? e.message : "Could not load status")); }, []);
  return <Shell><div className="page-head"><div><p className="eyebrow">SYSTEM</p><h2>Settings & provider status</h2><p>Secrets and local installation paths are not returned by this status API.</p></div></div>
    {error && <div role="alert" className="error">{error}</div>}
    <section className="service-grid">{status && Object.entries(status).map(([key,value]) => <div className="service-card" key={key}><div><strong>{key}</strong><small>{typeof value === "object" && value ? JSON.stringify(value) : String(value)}</small></div><span className="dot"/></div>)}</section>
    <div className="notice"><Upload size={18}/><span>Pixabay status: {status && typeof status.footage === "object" && status.footage ? String((status.footage as Record<string, unknown>).available ? "connected" : "not configured") : "checking"}. Set <code>FOOTAGE_PROVIDER=pixabay</code> and <code>PIXABAY_API_KEY</code> in the backend .env. Uploaded audio without a timestamped transcript requires the optional faster-whisper adapter.</span></div>
  </Shell>;
}

export default function App() {
  return <Routes>
    <Route path="/" element={<Home/>}/><Route path="/dashboard" element={<Dashboard/>}/>
    <Route path="/create" element={<Create/>}/><Route path="/jobs/:jobId" element={<JobPage/>}/>
    <Route path="/editor/:jobId" element={<Editor/>}/><Route path="/projects" element={<Projects/>}/>
    <Route path="/templates" element={<Templates/>}/><Route path="/settings" element={<SettingsPage/>}/>
    <Route path="*" element={<Home/>}/>
  </Routes>;
}
