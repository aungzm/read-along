/**
 * Client-side file handling for the ingest flow.
 *
 * Files stay in the browser for now: nothing is uploaded. These helpers only
 * validate the picked files and format them for display. The backend job is
 * the mock progress timer; the download is generated locally on completion.
 */

export const EPUB_ACCEPT = ".epub,application/epub+zip";

export const AUDIO_ACCEPT = "audio/*,.m4b,.mp3,.wav,.ogg,.flac,.aac,.m4a";

const AUDIO_EXTENSIONS = [
  "m4b",
  "mp3",
  "wav",
  "ogg",
  "oga",
  "flac",
  "aac",
  "m4a",
  "opus",
  "wma",
];

export function validateEpubFile(file: File): string | null {
  if (!file.name.toLowerCase().endsWith(".epub")) {
    return "Choose a file ending in .epub."
  }
  return null
}

export function validateAudioFile(file: File): string | null {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (file.type.startsWith("audio/") || AUDIO_EXTENSIONS.includes(extension)) {
    return null
  }
  return "Choose an audio file, such as MP3 or M4B."
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ["KB", "MB", "GB"];
  let size = bytes / 1024;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(size >= 100 ? 0 : 1)} ${units[unit]}`;
}
