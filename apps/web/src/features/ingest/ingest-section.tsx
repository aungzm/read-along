import { BookOpen01Icon, HeadphonesIcon } from "@hugeicons/core-free-icons"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { FilePickCard } from "./file-pick-card"
import {
  AUDIO_ACCEPT,
  EPUB_ACCEPT,
  validateAudioFile,
  validateEpubFile,
} from "./files"

export type IngestFiles = {
  epub: File | null
  audio: File | null
};

type IngestSectionProps = {
  files: IngestFiles
  onChange: (files: IngestFiles) => void
  canStart: boolean
  isStarting: boolean
  isBlocked: boolean
  onStart: () => void
};

/**
 * The upload cards plus the Start aligning button. Files stay in the browser;
 * starting uploads them and creates a backend alignment job.
 */
export function IngestSection({
  files,
  onChange,
  canStart,
  isStarting,
  isBlocked,
  onStart,
}: IngestSectionProps) {
  const [epubError, setEpubError] = useState<string | null>(null)
  const [audioError, setAudioError] = useState<string | null>(null)

  return (
    <div className="space-y-5">
      <div className="space-y-1">
        <h2 className="font-reading text-lg font-medium">New alignment</h2>
        <p className="text-sm text-muted-foreground">
          Pick the book and its narration. Both upload to the API when you
          start.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <FilePickCard
          title="EPUB file"
          description="An EPUB 3 book to align."
          badge=".epub"
          icon={BookOpen01Icon}
          accept={EPUB_ACCEPT}
          inputId="epub-file"
          file={files.epub}
          error={epubError}
          onPick={(file) => {
            const problem = validateEpubFile(file)
            setEpubError(problem)
            if (!problem) onChange({ ...files, epub: file })
          }}
          onClear={() => {
            setEpubError(null)
            onChange({ ...files, epub: null })
          }}
        />
        <FilePickCard
          title="Audio file"
          description="The audiobook narration."
          badge="audio"
          icon={HeadphonesIcon}
          accept={AUDIO_ACCEPT}
          inputId="audio-file"
          file={files.audio}
          error={audioError}
          onPick={(file) => {
            const problem = validateAudioFile(file)
            setAudioError(problem)
            if (!problem) onChange({ ...files, audio: file })
          }}
          onClear={() => {
            setAudioError(null)
            onChange({ ...files, audio: null })
          }}
        />
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button
          size="lg"
          onClick={onStart}
          disabled={!canStart || isStarting || isBlocked}
        >
          {isStarting ? "Uploading…" : "Start aligning"}
        </Button>
        {isBlocked ? (
          <p className="text-xs text-muted-foreground">
            An alignment is already running.
          </p>
        ) : !canStart ? (
          <p className="text-xs text-muted-foreground">
            Pick both files to start.
          </p>
        ) : null}
      </div>
    </div>
  )
}
