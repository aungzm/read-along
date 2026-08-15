import { Delete02Icon, Upload01Icon } from "@hugeicons/core-free-icons"
import { HugeiconsIcon, type IconSvgElement } from "@hugeicons/react"
import { useRef } from "react"

import { Button } from "@/components/ui/button"
import { cn } from "cn"
import { formatFileSize } from "./files"

type FilePickCardProps = {
  title: string
  description: string
  badge: string
  icon: IconSvgElement
  accept: string
  inputId: string
  file: File | null
  error: string | null
  onPick: (file: File) => void
  onClear: () => void
}

/**
 * One slot in the ingest pair: a labelled plate that opens the file picker, or
 * shows the chosen file with its size and a way to remove it.
 */
export function FilePickCard({
  title,
  description,
  badge,
  icon,
  accept,
  inputId,
  file,
  error,
  onPick,
  onClear,
}: FilePickCardProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border/70 bg-paper/40 p-4">
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-2 text-sm font-medium">
          <HugeiconsIcon icon={icon} className="size-4 text-voice" />
          {title}
        </span>
        <span className="text-[0.7rem] tracking-wide text-muted-foreground">
          {badge}
        </span>
      </div>

      <input
        ref={inputRef}
        id={inputId}
        type="file"
        accept={accept}
        className="peer sr-only"
        onChange={(event) => {
          const picked = event.target.files?.[0]
          // Reset so picking the same file again still fires onChange.
          event.target.value = ""
          if (picked) onPick(picked)
        }}
      />

      {file ? (
        <div className="flex min-h-24 flex-col justify-between gap-3 rounded-lg border border-border/70 bg-background/60 px-3.5 py-3">
          <p className="truncate font-reading text-[0.95rem] leading-snug">
            {file.name}
          </p>
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-muted-foreground">
              {formatFileSize(file.size)}
            </span>
            <Button variant="ghost" size="xs" onClick={onClear}>
              <HugeiconsIcon icon={Delete02Icon} />
              Remove
            </Button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className={cn(
            "flex min-h-24 w-full flex-col items-center justify-center gap-1.5 rounded-lg border border-dashed border-border",
            "text-muted-foreground transition-colors outline-none",
            "hover:border-voice/60 hover:bg-background/60 hover:text-foreground",
            "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/40",
          )}
        >
          <HugeiconsIcon icon={Upload01Icon} className="size-4" />
          <span className="text-sm font-medium text-foreground">Choose file</span>
          <span className="px-4 text-center text-xs">{description}</span>
        </button>
      )}

      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  )
}
