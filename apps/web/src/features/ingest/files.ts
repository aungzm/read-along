/**
 * Client-side file handling for the ingest flow.
 *
 * These helpers validate picked files before they are uploaded to the API.
 */

export const EPUB_ACCEPT = ".epub,application/epub+zip";

export const AUDIO_ACCEPT = ".m4b,.mp3,.m4a";

const AUDIO_EXTENSIONS = [
  "m4b",
  "mp3",
  "m4a",
];

export function validateEpubFile(file: File): string | null {
  if (!file.name.toLowerCase().endsWith(".epub")) {
    return "Choose a file ending in .epub."
  }
  return null
}

export function validateAudioFile(file: File): string | null {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (AUDIO_EXTENSIONS.includes(extension)) {
    return null
  }
  return "Choose an MP3, M4A, or M4B audio file."
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
