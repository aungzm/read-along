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

export function useCreateJob() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: api.createJob,
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
