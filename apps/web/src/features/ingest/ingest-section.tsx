import { BookOpen01Icon, HeadphonesIcon } from "@hugeicons/core-free-icons"
import { useState } from "react"

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
};

/**
 * The two upload cards. Files stay in the browser; picking a file only
 * validates it locally. Starting the (mock) alignment run is wired up next —
 * this slice is the pickers and their state.
 */
export function IngestSection({ files, onChange }: IngestSectionProps) {
  const [epubError, setEpubError] = useState<string | null>(null)
  const [audioError, setAudioError] = useState<string | null>(null)

  return (
    <div className="space-y-4">
      <div>
        <h1 className="font-heading text-lg font-semibold">New alignment</h1>
        <p className="text-sm text-muted-foreground">
          Pick the book and its narration. Nothing leaves the browser yet.
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <FilePickCard
          title="EPUB file"
          description="The ebook to align."
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
    </div>
  )
}
