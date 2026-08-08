import { QueryClient } from "@tanstack/react-query"

/**
 * One client per browser session.
 *
 * The defaults suit a local tool talking to a service on the same machine:
 * results stay fresh for a while, a failed request is worth a single retry, and
 * refetching every time the window regains focus just adds noise.
 */
export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: 1,
        refetchOnWindowFocus: false,
      },
    },
  })
}
