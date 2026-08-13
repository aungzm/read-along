import type { Job } from "@/lib/api"

export type ResultNames = {
  epubName: string
  audioName: string
};

/**
 * The fake result file. Until real alignment exists, a finished job downloads
 * a small text file built in the browser that names the two source files.
 */
export function resultFileName(title: string): string {
  const safe = title.replace(/[\\/:*?"<>|]/g, "").trim() || "result"
  return `${safe} (synced).txt`
}

export function buildResultText(job: Job, names?: ResultNames): string {
  return [
    "read-along mock result",
    "======================",
    "",
    `Title: ${job.title}`,
    `Job: ${job.jobId}`,
    `Finished: ${job.updatedAt}`,
    `Progress: ${Math.round(job.progress * 100)}%`,
    "",
    names
      ? `EPUB: ${names.epubName}\nAudio: ${names.audioName}`
      : "Source file names were not recorded for this run.",
    "",
    "This is a placeholder. Real alignment will replace this file",
    "with a synced EPUB 3.",
  ].join("\n")
}

export function downloadResultFile(job: Job, names?: ResultNames): void {
  const blob = new Blob([buildResultText(job, names)], {
    type: "text/plain;charset=utf-8",
  })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = resultFileName(job.title)
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
