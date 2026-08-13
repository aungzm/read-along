import { Delete02Icon, Upload01Icon } from "@hugeicons/core-free-icons"
import { HugeiconsIcon, type IconSvgElement } from "@hugeicons/react"
import { useRef } from "react"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { formatFileSize } from "./files"

type FilePickCardProps = {
  title: string
  description: string
  icon: IconSvgElement
  accept: string
  inputId: string
  file: File | null
  error: string | null
  onPick: (file: File) => void
  onClear: () => void
};

export function FilePickCard({
  title,
  description,
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
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <HugeiconsIcon icon={icon} className="size-4 text-muted-foreground" />
          {title}
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          accept={accept}
          className="hidden"
          onChange={(event) => {
            const picked = event.target.files?.[0]
            // Reset so picking the same file again still fires onChange.
            event.target.value = ""
            if (picked) onPick(picked)
          }}
        />
        {file ? (
          <div className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{file.name}</p>
              <p className="text-xs text-muted-foreground">
                {formatFileSize(file.size)}
              </p>
            </div>
            <Button variant="ghost" size="sm" onClick={onClear}>
              <HugeiconsIcon icon={Delete02Icon} />
              Remove
            </Button>
          </div>
        ) : (
          <Button
            variant="outline"
            className="w-full"
            onClick={() => inputRef.current?.click()}
          >
            <HugeiconsIcon icon={Upload01Icon} />
            Choose file
          </Button>
        )}
        {error ? (
          <p role="alert" className="text-xs text-destructive">
            {error}
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}
