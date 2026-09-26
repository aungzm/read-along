import { useQueryClient } from "@tanstack/react-query"
import { useEffect } from "react"

import { api, isActiveJob, type Job, type JobEvent } from "@/lib/api"
import { jobKeys } from "./use-jobs"

/**
 * Follow one job's server-sent event stream and fold each event into the cached
 * job list. Only a job that is still running needs a stream open.
 */
export function useJobEvents(jobId: string | null) {
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!jobId) return undefined

    const source = new EventSource(api.eventStreamUrl(jobId))
    let disposed = false

    const reconcile = () => {
      if (disposed) return
      // Keep an existing reconciliation request instead of restarting it for
      // each connection error. useJobs also polls if SSE cannot reconnect.
      void queryClient.invalidateQueries(
        { queryKey: jobKeys.list, exact: true },
        { cancelRefetch: false }
      )
    }

    const onMessage = (event: MessageEvent<string>) => {
      if (disposed) return
      let decoded: JobEvent
      try {
        decoded = JSON.parse(event.data) as JobEvent
        if (
          !decoded ||
          !["snapshot", "progress", "done"].includes(decoded.type) ||
          !decoded.job ||
          decoded.job.jobId !== jobId ||
          !["queued", "running", "succeeded", "failed", "cancelled"].includes(
            decoded.job.status
          ) ||
          !Number.isFinite(decoded.job.progress) ||
          decoded.job.progress < 0 ||
          decoded.job.progress > 1 ||
          !Number.isFinite(Date.parse(decoded.job.updatedAt))
        ) {
          reconcile()
          return
        }
      } catch {
        reconcile()
        return
      }
      const { job } = decoded
      const cached = queryClient.getQueryData<Job[]>(jobKeys.list)
      const current = cached?.find((candidate) => candidate.jobId === jobId)
      if (!current) {
        // An authoritative list may already have removed this job after a
        // restart. Never recreate it from a delayed message on the old stream.
        reconcile()
        return
      }
      if (
        Date.parse(job.updatedAt) < Date.parse(current.updatedAt) ||
        (!isActiveJob(current) && isActiveJob(job)) ||
        (isActiveJob(current) &&
          isActiveJob(job) &&
          job.progress < current.progress)
      ) {
        return
      }

      // A GET started before this event could otherwise overwrite newer SSE
      // state when it resolves. The query function consumes the abort signal.
      void queryClient.cancelQueries(
        { queryKey: jobKeys.list, exact: true },
        { revert: false }
      )
      queryClient.setQueryData<Job[]>(jobKeys.list, (jobs) =>
        jobs?.map((candidate) =>
          candidate.jobId === job.jobId ? job : candidate
        )
      )

      if (!isActiveJob(job)) {
        source.close()
        reconcile()
      }
    }

    source.addEventListener("snapshot", onMessage)
    source.addEventListener("progress", onMessage)
    source.addEventListener("done", onMessage)
    source.addEventListener("open", reconcile)
    source.addEventListener("error", reconcile)

    return () => {
      disposed = true
      source.removeEventListener("snapshot", onMessage)
      source.removeEventListener("progress", onMessage)
      source.removeEventListener("done", onMessage)
      source.removeEventListener("open", reconcile)
      source.removeEventListener("error", reconcile)
      source.close()
    }
  }, [jobId, queryClient])
}
