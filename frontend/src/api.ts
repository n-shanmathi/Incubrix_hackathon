export type Job = {
  job_id: string; status: "queued" | "processing" | "completed" | "failed";
  progress: number; error: string | null; result: Record<string, string> | null;
  created_at: string; updated_at: string;
};

export type ServiceStatus = {
  api: string;
  tts: { provider: string; available: boolean };
  stt: { provider: string; available: boolean };
  footage: { provider: string; available: boolean; test_mode: boolean; setup_message: string };
  rendering: { available: boolean; ffmpeg_available: boolean; ffprobe_available: boolean; formats: string[] };
};

export type JobList = {
  jobs: Job[];
  count: number;
  total_count: number;
  counts: Record<Job["status"], number>;
};

const json = async (response: Response) => {
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail ?? "Request failed");
  return data;
};

export async function createJob(input: object): Promise<Job> {
  return json(await fetch("/api/v1/broll/jobs", {
    method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify(input)
  }));
}

export async function createAudioJob(file: File, options: {
  aspect_ratios: string[];
  style: string;
  avoid: string[];
  captions: { burn_in: boolean; srt: boolean };
  transcript?: string;
}): Promise<Job> {
  const form = new FormData();
  form.set("audio", file);
  form.set("aspect_ratios", JSON.stringify(options.aspect_ratios));
  form.set("style", options.style);
  form.set("avoid", JSON.stringify(options.avoid));
  form.set("captions", JSON.stringify(options.captions));
  if (options.transcript?.trim()) form.set("transcript", options.transcript);
  const response = await fetch("/api/v1/broll/jobs/upload", {
    method: "POST",
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: form
  });
  return json(response);
}

export async function getJob(id: string): Promise<Job> { return json(await fetch(`/api/v1/jobs/${id}`)); }
export async function getJobs(limit = 50, offset = 0): Promise<JobList> {
  return json(await fetch(`/api/v1/jobs?limit=${limit}&offset=${offset}`));
}
export async function getServiceStatus(): Promise<ServiceStatus> { return json(await fetch("/api/v1/service-status")); }
export async function getTimeline(url: string): Promise<{ scenes: Array<Record<string, unknown>> }> {
  return json(await fetch(url));
}
export const fileUrl = (path: string) => path;
