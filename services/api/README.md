# read-along API

The FastAPI service behind `apps/web`.

```sh
python -m venv .venv
.venv\Scripts\activate          # or: source .venv/bin/activate
pip install -e ".[dev]"
pip install -e ".[transcribe]"  # required for actual jobs
pnpm dev                        # uvicorn app.main:app --reload --port 8000
```

Routes live under `/api`:

| Method | Path                     | Purpose                                         |
| ------ | ------------------------ | ----------------------------------------------- |
| GET    | `/api/health`            | Liveness and version.                           |
| GET    | `/api/jobs`              | List jobs, newest first.                        |
| POST   | `/api/jobs`              | Create a job from a multipart `epub` + `audio`. |
| GET    | `/api/jobs/{id}`         | Fetch one job.                                  |
| GET    | `/api/jobs/{id}/download`| Download the completed EPUB (409 if unavailable).|
| POST   | `/api/jobs/{id}/cancel`  | Cancel a queued or running job.                 |
| GET    | `/api/jobs/{id}/events`  | Server-sent events for a job's progress.        |

Uploads are streamed to disk under `READ_ALONG_DATA_DIR` (default `var/`), one
directory per job. `READ_ALONG_MAX_UPLOAD_BYTES` caps each file and defaults to
2 GiB. Uploaded files are untrusted: EPUB package documents are parsed with
`defusedxml` and no XML part larger than 5 MiB is read.

## Pipeline

The worker calls `app/pipeline.py`: spine XHTML becomes sentence anchors, the
audio becomes a rough transcript, passage matches become sentence timings, then
coverage review gates SMIL overlay generation and EPUB packaging. `partial` and
`rejected` alignment reports fail the job; only successful jobs can download an
EPUB. Source books must be EPUB 3; only MP3, M4A and M4B uploads are accepted
for EPUB-compatible output.
Jobs remain in memory: restarting the service clears the job list while the
uploaded files and results remain in `data_dir`.

### Pipeline contracts

- `extract_sentences()` reads spine XHTML into sentence text, stable IDs, and
  source character offsets. Sentence splitting uses basic punctuation rules and
  does not handle abbreviations or every XHTML layout.
- `transcribe_audio()` wraps faster-whisper with word timestamps. It needs the
  optional `transcribe` extra (`pip install -e ".[transcribe]"`) and a model
  download on first use.
- `locate_passages()` and `align_sentences()` match normalized words with
  difflib's longest-matching blocks, so they tolerate skipped text and
  audio-only speech without an acoustic model. They drop weak matches instead of
  guessing, and their thresholds still need tuning on real book/audio pairs.
- `review_alignment()` checks coverage and rejects invalid or out-of-order timing
  data. It checks structural validity, not acoustic accuracy.
- `build_overlays()` writes SMIL per content document; `package_epub()` anchors
  sentences, adds the audio and overlays, updates the OPF, and validates the
  result with EPUBCheck when `epubcheck` or `EPUBCHECK_JAR` is available.

`TranscriptionOptions` defaults to faster-whisper's `small.en` model on CPU with
`int8` inference and voice activity detection. Test it against real books before
settling on the model; use a multilingual model if the narration is not English.

## Tests

```sh
pnpm api:test                   # python -m pytest
```
