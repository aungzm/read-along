import { QueryClientProvider } from "@tanstack/react-query"
import { useState, type ReactNode } from "react"

import { ThemeProvider } from "@/components/theme-provider"
import { createQueryClient } from "@/lib/query-client"

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(createQueryClient)

  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </ThemeProvider>
  )
}
