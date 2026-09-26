import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api, isActiveJob } from "@/lib/api"

export const JOB_RECOVERY_INTERVAL = 5_000

export const jobKeys = {
  health: ["health"] as const,
  list: ["jobs"] as const,
}

export function useHealth() {
  return useQuery({
    queryKey: jobKeys.health,
    queryFn: api.health,
    refetchInterval: 30_000,
  })
}

export function useJobs() {
  return useQuery({
    queryKey: jobKeys.list,
    queryFn: ({ signal }) => api.listJobs({ signal }),
    // SSE is the fast path, not the sole source of truth. In particular, a
    // restarted API returns an empty list rather than leaving cached work active.
    refetchInterval: (query) =>
      query.state.status === "error" || query.state.data?.some(isActiveJob)
        ? JOB_RECOVERY_INTERVAL
        : false,
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
  })
}

export type CreateJobVariables = {
  epub: File
  audio: File
  /** Reports upload progress as a 0–1 fraction. */
  onProgress?: (fraction: number) => void
}

export function useCreateJob() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ epub, audio, onProgress }: CreateJobVariables) =>
      api.createJob({ epub, audio }, { onProgress }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: jobKeys.list }),
  })
}

export function useCancelJob() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: api.cancelJob,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: jobKeys.list }),
  })
}
