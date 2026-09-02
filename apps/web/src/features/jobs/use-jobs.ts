import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api } from "@/lib/api"

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
    queryFn: api.listJobs,
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
