import { act, cleanup, renderHook, waitFor } from "@testing-library/react"
import {
  focusManager,
  onlineManager,
  QueryClientProvider,
} from "@tanstack/react-query"
import type { PropsWithChildren } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { api, ApiError, isActiveJob, type Job } from "@/lib/api"
import { createQueryClient } from "@/lib/query-client"
import { useJobEvents } from "./use-job-events"
import { JOB_RECOVERY_INTERVAL, jobKeys, useJobs } from "./use-jobs"

class FakeEventSource extends EventTarget {
  static instances: FakeEventSource[] = []
  closed = false
  url: string

  constructor(url: string) {
    super()
    this.url = url
    FakeEventSource.instances.push(this)
  }

  close() {
    this.closed = true
  }

  emit(type: string, job?: Job) {
    this.dispatchEvent(
      job
        ? new MessageEvent(type, { data: JSON.stringify({ type, job }) })
        : new Event(type)
    )
  }
}

function job(overrides: Partial<Job> = {}): Job {
  return {
    jobId: "job_test",
    title: "Book",
    status: "running",
    stage: "transcribe",
    progress: 0.2,
    createdAt: "2026-09-26T09:00:00.000Z",
    updatedAt: "2026-09-26T09:00:01.000Z",
    error: null,
    source: null,
    book: null,
    ...overrides,
  }
}

const clients: ReturnType<typeof createQueryClient>[] = []

function mount(fixedJobId?: string) {
  const client = createQueryClient()
  client.setDefaultOptions({
    queries: {
      ...client.getDefaultOptions().queries,
      retry: false,
      gcTime: Infinity,
    },
  })
  clients.push(client)
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  const rendered = renderHook(
    () => {
      const jobs = useJobs()
      const activeId = jobs.data?.find(isActiveJob)?.jobId ?? null
      useJobEvents(fixedJobId ?? activeId)
      return jobs
    },
    { wrapper }
  )
  return { client, ...rendered }
}

function lastSource() {
  const source = FakeEventSource.instances.at(-1)
  if (!source) throw new Error("No event stream was opened")
  return source
}

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal("EventSource", FakeEventSource)
  vi.spyOn(api, "listJobs").mockResolvedValue([job()])
})

afterEach(() => {
  cleanup()
  for (const client of clients.splice(0)) client.clear()
  focusManager.setFocused(undefined)
  onlineManager.setOnline(true)
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe("live job recovery", () => {
  it.each(["succeeded", "failed", "cancelled"] as const)(
    "closes a terminal %s snapshot without waiting for done",
    async (status) => {
      const { result } = mount()
      await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
      const source = lastSource()
      const terminal = job({
        status,
        stage: null,
        progress: 1,
        updatedAt: "2026-09-26T09:01:00Z",
      })
      vi.mocked(api.listJobs).mockResolvedValue([terminal])
      act(() => source.emit("snapshot", terminal))
      await waitFor(() => expect(result.current.data?.[0].status).toBe(status))
      expect(source.closed).toBe(true)
    }
  )

  it("accepts terminal progress even when the done event is lost", async () => {
    const { result } = mount()
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    const terminal = job({
      status: "succeeded",
      stage: null,
      progress: 1,
      updatedAt: "2026-09-26T09:01:00Z",
    })
    vi.mocked(api.listJobs).mockResolvedValue([terminal])
    const source = lastSource()
    act(() => source.emit("progress", terminal))
    await waitFor(() =>
      expect(result.current.data?.[0].status).toBe("succeeded")
    )
    expect(source.closed).toBe(true)
  })

  it("removes stale running work when a restarted API returns an empty list", async () => {
    const { result } = mount()
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    const source = lastSource()
    vi.mocked(api.listJobs).mockResolvedValue([])
    act(() => source.emit("error"))
    await waitFor(() => expect(result.current.data).toEqual([]))
    expect(result.current.data?.some(isActiveJob)).toBe(false)
    expect(source.closed).toBe(true)
  })

  it("reconciles state on stream reconnect even while the cache is fresh", async () => {
    const { result } = mount()
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    vi.mocked(api.listJobs).mockResolvedValue([job({ progress: 0.6 })])
    act(() => lastSource().emit("open"))
    await waitFor(() => expect(result.current.data?.[0].progress).toBe(0.6))
    expect(api.listJobs).toHaveBeenCalledTimes(2)
  })

  it("does not overwrite newer events with an older in-flight GET", async () => {
    const { client, result } = mount()
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    let resolve: (jobs: Job[]) => void = () => {
      throw new Error("Not initialized")
    }
    const pending = new Promise<Job[]>((finish) => {
      resolve = finish
    })
    vi.mocked(api.listJobs).mockReturnValueOnce(pending)
    act(() => {
      void client.invalidateQueries({ queryKey: jobKeys.list })
    })
    await waitFor(() => expect(api.listJobs).toHaveBeenCalledTimes(2))
    const signal = vi.mocked(api.listJobs).mock.calls[1][0]?.signal
    act(() =>
      lastSource().emit(
        "progress",
        job({ progress: 0.8, updatedAt: "2026-09-26T09:01:00Z" })
      )
    )
    expect(signal?.aborted).toBe(true)
    await act(async () => {
      resolve([job()])
      await pending
    })
    await waitFor(() => expect(result.current.data?.[0].progress).toBe(0.8))
  })

  it("ignores delayed events that regress progress", async () => {
    vi.mocked(api.listJobs).mockResolvedValue([job({ progress: 0.8 })])
    const { result } = mount()
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    act(() => lastSource().emit("progress", job({ progress: 0.2 })))
    expect(result.current.data?.[0].progress).toBe(0.8)
  })

  it("ignores older timestamps even when they contain higher progress", async () => {
    vi.mocked(api.listJobs).mockResolvedValue([
      job({ progress: 0.6, updatedAt: "2026-09-26T09:01:00Z" }),
    ])
    const { result } = mount()
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    act(() => lastSource().emit("progress", job({ progress: 0.8 })))
    expect(result.current.data?.[0].progress).toBe(0.6)
  })

  it("does not recreate a job removed by authoritative reconciliation", async () => {
    const { client } = mount("job_test")
    await waitFor(() =>
      expect(client.getQueryData(jobKeys.list)).toEqual([job()])
    )
    vi.mocked(api.listJobs).mockResolvedValue([])
    act(() => client.setQueryData(jobKeys.list, []))
    act(() => lastSource().emit("progress", job({ progress: 0.8 })))
    await waitFor(() => expect(api.listJobs).toHaveBeenCalledTimes(2))
    expect(client.getQueryData(jobKeys.list)).toEqual([])
  })

  it("does not regress a cached terminal job to running", async () => {
    const { client } = mount("job_test")
    await waitFor(() =>
      expect(client.getQueryData(jobKeys.list)).toEqual([job()])
    )
    const terminal = job({ status: "succeeded", progress: 1, stage: null })
    act(() => client.setQueryData(jobKeys.list, [terminal]))
    act(() =>
      lastSource().emit("progress", job({ updatedAt: "2026-09-26T09:01:00Z" }))
    )
    expect(client.getQueryData(jobKeys.list)).toEqual([terminal])
  })

  it.each([
    "not JSON",
    "null",
    JSON.stringify({ type: "progress", job: { jobId: "job_test" } }),
    JSON.stringify({ type: "progress", job: job({ jobId: "other" }) }),
    JSON.stringify({ type: "progress", job: job({ progress: Number.NaN }) }),
    JSON.stringify({ type: "progress", job: job({ updatedAt: "invalid" }) }),
  ])(
    "recovers malformed stream message %s through the authoritative list",
    async (data) => {
      mount()
      await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
      act(() =>
        lastSource().dispatchEvent(new MessageEvent("progress", { data }))
      )
      await waitFor(() => expect(api.listJobs).toHaveBeenCalledTimes(2))
    }
  )

  it("coalesces repeated stream errors into one reconciliation request", async () => {
    const { result } = mount()
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    let resolve: (jobs: Job[]) => void = () => {
      throw new Error("Not initialized")
    }
    const pending = new Promise<Job[]>((finish) => {
      resolve = finish
    })
    vi.mocked(api.listJobs).mockReturnValueOnce(pending)
    act(() => {
      lastSource().emit("error")
      lastSource().emit("error")
    })
    await waitFor(() => expect(api.listJobs).toHaveBeenCalledTimes(2))
    await act(async () => {
      resolve([])
      await pending
    })
    await waitFor(() => expect(result.current.data).toEqual([]))
    expect(lastSource().closed).toBe(true)
  })

  it("removes listeners so late messages cannot modify the cache after unmount", async () => {
    const { client, unmount } = mount()
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1))
    const source = lastSource()
    unmount()
    source.emit("progress", job({ progress: 0.8 }))
    source.emit("error")
    expect(client.getQueryData(jobKeys.list)).toEqual([job()])
    expect(api.listJobs).toHaveBeenCalledTimes(1)
    expect(source.closed).toBe(true)
  })

  it("refetches on window focus and network reconnect even with fresh idle data", async () => {
    vi.mocked(api.listJobs).mockResolvedValue([])
    mount()
    await waitFor(() => expect(api.listJobs).toHaveBeenCalledTimes(1))
    act(() => {
      focusManager.setFocused(false)
      focusManager.setFocused(true)
    })
    await waitFor(() => expect(api.listJobs).toHaveBeenCalledTimes(2))
    act(() => {
      onlineManager.setOnline(false)
      onlineManager.setOnline(true)
    })
    await waitFor(() => expect(api.listJobs).toHaveBeenCalledTimes(3))
  })

  it("polls missed completion without SSE and stops polling once idle", async () => {
    vi.useFakeTimers()
    const { result } = mount()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    const terminal = job({ status: "succeeded", stage: null, progress: 1 })
    vi.mocked(api.listJobs).mockResolvedValue([terminal])
    await act(async () => {
      await vi.advanceTimersByTimeAsync(JOB_RECOVERY_INTERVAL + 1)
    })
    expect(result.current.data?.[0].status).toBe("succeeded")
    expect(lastSource().closed).toBe(true)
    const calls = vi.mocked(api.listJobs).mock.calls.length
    await act(async () => {
      await vi.advanceTimersByTimeAsync(JOB_RECOVERY_INTERVAL * 3)
    })
    expect(api.listJobs).toHaveBeenCalledTimes(calls)
  })

  it("retains cached work during an outage, then recovers through polling", async () => {
    vi.useFakeTimers()
    const { result } = mount()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(result.current.isError).toBe(false)
    vi.mocked(api.listJobs).mockRejectedValueOnce(new ApiError("Offline", 0))
    act(() => lastSource().emit("error"))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(result.current.data?.[0].status).toBe("running")
    expect(result.current.isError).toBe(true)
    vi.mocked(api.listJobs).mockResolvedValue([])
    await act(async () => {
      await vi.advanceTimersByTimeAsync(JOB_RECOVERY_INTERVAL + 1)
    })
    expect(result.current.data).toEqual([])
    expect(lastSource().closed).toBe(true)
  })

  it("retries an initial list failure even without a cached active job", async () => {
    vi.useFakeTimers()
    vi.mocked(api.listJobs).mockRejectedValueOnce(new ApiError("Offline", 0))
    const { result } = mount()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(result.current.data).toBeUndefined()
    vi.mocked(api.listJobs).mockResolvedValue([])
    await act(async () => {
      await vi.advanceTimersByTimeAsync(JOB_RECOVERY_INTERVAL + 1)
    })
    expect(result.current.data).toEqual([])
    expect(FakeEventSource.instances).toHaveLength(0)
  })
})
