import { Moon02Icon, Sun01Icon } from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"
import type { ReactNode } from "react"

import { useTheme } from "@/components/theme-provider"
import { Button } from "@/components/ui/button"

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
      <header className="border-b">
        <div className="mx-auto flex w-full max-w-3xl items-center justify-between gap-4 px-6 py-4">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="font-heading text-base font-semibold">read-along</span>
            <span className="text-xs text-muted-foreground">
              EPUB + audiobook into a synced EPUB 3
            </span>
          </div>
          <ThemeToggle />
        </div>
      </header>
      <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-8">{children}</main>
    </div>
  )
}
