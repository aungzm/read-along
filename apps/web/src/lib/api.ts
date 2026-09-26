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

export function isActiveJob(job: Pick<Job, "status">): boolean {
  return job.status === "queued" || job.status === "running"
}

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

export type UploadOptions = {
  /** Called with a 0–1 fraction as the request body is sent to the API. */
  onProgress?: (fraction: number) => void
  signal?: AbortSignal
}

/** Turn a FastAPI error body (a string or a validation array) into a message. */
function detailFromBody(body: unknown): string | undefined {
  if (!body || typeof body !== "object" || !("detail" in body)) return undefined

  const detail = (body as { detail?: unknown }).detail
  if (typeof detail === "string") return detail

  if (Array.isArray(detail)) {
    const messages = detail.flatMap((item) => {
      if (item && typeof item === "object" && typeof (item as { msg?: unknown }).msg === "string") {
        return [(item as { msg: string }).msg]
      }
      return []
    })
    if (messages.length > 0) return messages.join("; ")
  }

  return undefined
}

function errorFromBody(status: number, body: unknown): ApiError {
  return new ApiError(detailFromBody(body) ?? `Request failed with ${status}`, status)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init)
  } catch {
    throw new ApiError("Cannot reach the read-along API.", 0)
  }

  if (!response.ok) {
    let body: unknown
    try {
      body = await response.json()
    } catch {
      body = undefined
    }
    throw errorFromBody(response.status, body)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

/**
 * Create a job from the two files, reporting upload progress.
 *
 * Uses `XMLHttpRequest` instead of `fetch` because only the former exposes the
 * request-body progress events a large audiobook needs. Aborts cleanly when the
 * caller's signal fires.
 */
function uploadJob(
  files: { epub: File; audio: File },
  { onProgress, signal }: UploadOptions = {},
): Promise<Job> {
  return new Promise<Job>((resolve, reject) => {
    const body = new FormData()
    body.append("epub", files.epub)
    body.append("audio", files.audio)

    const xhr = new XMLHttpRequest()
    xhr.open("POST", `${API_BASE_URL}/jobs`)

    const abort = () => xhr.abort()
    signal?.addEventListener("abort", abort, { once: true })
    const cleanup = () => signal?.removeEventListener("abort", abort)

    if (onProgress) {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress(event.loaded / event.total)
      }
    }

    xhr.onload = () => {
      cleanup()
      // The files are on the server now; remaining time is the extract stage.
      onProgress?.(1)
      let payload: unknown
      try {
        payload = JSON.parse(xhr.responseText)
      } catch {
        payload = undefined
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(payload as Job)
        return
      }
      reject(errorFromBody(xhr.status, payload))
    }

    xhr.onerror = () => {
      cleanup()
      reject(new ApiError("Cannot reach the read-along API.", 0))
    }

    xhr.onabort = () => {
      cleanup()
      reject(new ApiError("The upload was cancelled.", 0))
    }

    xhr.send(body)
  })
}

export const api = {
  health: () => request<Health>("/health"),

  listJobs: ({ signal }: { signal?: AbortSignal } = {}) =>
    request<Job[]>("/jobs", { signal }),

  createJob: (files: { epub: File; audio: File }, options?: UploadOptions) =>
    uploadJob(files, options),

  cancelJob: (jobId: string) =>
    request<Job>(`/jobs/${jobId}/cancel`, { method: "POST" }),

  eventStreamUrl: (jobId: string) => `${API_BASE_URL}/jobs/${jobId}/events`,
  downloadUrl: (jobId: string) => `${API_BASE_URL}/jobs/${jobId}/download`,
}
