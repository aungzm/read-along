/**
 * The browser's view of the read-along API.
 *
 * Requests are relative to `/api`, which the dev server proxies to the FastAPI
 * service. Set `VITE_API_BASE_URL` to point at an absolute URL instead.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api"

export type Stage = "extract" | "transcribe" | "align" | "build" | "package"

export type JobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"

export const STAGES: Stage[] = [
  "extract",
  "transcribe",
  "align",
  "build",
  "package",
]

export const STAGE_LABELS: Record<Stage, string> = {
  extract: "Extract",
  transcribe: "Transcribe",
  align: "Align",
  build: "Build overlays",
  package: "Package",
}

export type Health = {
  ok: boolean
  version: string
}

export type Book = {
  title: string
  author: string | null
  language: string | null
  chapters: number
  identifier: string | null
}

export type SourceFiles = {
  epubName: string
  audioName: string
  epubBytes: number
  audioBytes: number
}

export type Job = {
  jobId: string
  title: string
  status: JobStatus
  stage: Stage | null
  progress: number
  createdAt: string
  updatedAt: string
  error: string | null
  source: SourceFiles | null
  book: Book | null
}

export type JobEvent = {
  type: "snapshot" | "progress" | "done"
  job: Job
}

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init)
  } catch {
    throw new ApiError("Cannot reach the read-along API.", 0)
  }

  if (!response.ok) {
    let detail: string | undefined
    try {
      const body = (await response.json()) as { detail?: unknown }
      detail = typeof body.detail === "string" ? body.detail : undefined
    } catch {
      detail = undefined
    }
    throw new ApiError(detail ?? `Request failed with ${response.status}`, response.status)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  health: () => request<Health>("/health"),

  listJobs: () => request<Job[]>("/jobs"),

  createJob: (files: { epub: File; audio: File }) => {
    const body = new FormData()
    body.append("epub", files.epub)
    body.append("audio", files.audio)
    // No content-type header: the browser sets the multipart boundary.
    return request<Job>("/jobs", { method: "POST", body })
  },

  cancelJob: (jobId: string) =>
    request<Job>(`/jobs/${jobId}/cancel`, { method: "POST" }),

  eventStreamUrl: (jobId: string) => `${API_BASE_URL}/jobs/${jobId}/events`,
  downloadUrl: (jobId: string) => `${API_BASE_URL}/jobs/${jobId}/download`,
}
