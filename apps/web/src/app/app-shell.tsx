import { Moon02Icon, Sun01Icon } from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"
import type { ReactNode } from "react"

import { useTheme } from "@/components/theme-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useHealth } from "@/features/jobs/use-jobs"

/** The wordmark: three lines of text with one phrase lit up, like a page being read. */
function Mark() {
  return (
    <svg
      viewBox="0 0 28 28"
      aria-hidden="true"
      className="size-7 shrink-0 text-foreground"
    >
      <rect x="2" y="5" width="24" height="3" rx="1.5" fill="currentColor" opacity="0.9" />
      <rect x="2" y="12.5" width="11" height="3" rx="1.5" fill="currentColor" opacity="0.9" />
      <rect x="15" y="12.5" width="11" height="3" rx="1.5" fill="var(--voice)" />
      <rect x="2" y="20" width="17" height="3" rx="1.5" fill="currentColor" opacity="0.35" />
    </svg>
  )
}

function ApiStatus() {
  const health = useHealth()

  if (health.isPending) {
    return <Badge variant="outline">Checking API</Badge>
  }
  if (health.isError) {
    return <Badge variant="destructive">API offline</Badge>
  }
  return <Badge variant="secondary">API v{health.data.version}</Badge>
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const isDark = theme === "dark"

  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={isDark ? "Switch to the light theme" : "Switch to the dark theme"}
      onClick={() => setTheme(isDark ? "light" : "dark")}
    >
      <HugeiconsIcon icon={isDark ? Sun01Icon : Moon02Icon} />
    </Button>
  )
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-svh flex-col">
      <header className="border-b border-border/70">
        <div className="mx-auto flex w-full max-w-3xl items-center justify-between gap-4 px-6 py-5">
          <div className="flex min-w-0 items-center gap-3">
            <Mark />
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="font-reading text-lg leading-none font-medium tracking-tight">
                read-along
              </span>
              <span className="hidden text-xs text-muted-foreground sm:block">
                EPUB + audiobook into a synced EPUB 3
              </span>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <ApiStatus />
            <ThemeToggle />
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-10 sm:py-14">
        {children}
      </main>
    </div>
  )
}
