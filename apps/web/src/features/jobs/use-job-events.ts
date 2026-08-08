import { useQueryClient } from "@tanstack/react-query"
import { useEffect } from "react"

import { api, type Job, type JobEvent } from "@/lib/api"
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

    const onMessage = (event: MessageEvent<string>) => {
      const { type, job } = JSON.parse(event.data) as JobEvent

      queryClient.setQueryData<Job[]>(jobKeys.list, (jobs) =>
        jobs?.map((candidate) => (candidate.jobId === job.jobId ? job : candidate)),
      )

      if (type === "done") source.close()
    }

    source.addEventListener("snapshot", onMessage)
    source.addEventListener("progress", onMessage)
    source.addEventListener("done", onMessage)

    return () => source.close()
  }, [jobId, queryClient])
}
