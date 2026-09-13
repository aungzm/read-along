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
2 GiB. The request body is limited before multipart parsing, using both the
declared Content-Length and a count of actual incoming bytes. The default total
budget is twice the file cap plus 1 MiB for multipart overhead; set
`READ_ALONG_MAX_REQUEST_BYTES` to override it. Oversized requests return 413,
including chunked requests and requests that understate Content-Length.

`READ_ALONG_MAX_CONCURRENT_UPLOADS` defaults to 2. Processing defaults to one
running job (`READ_ALONG_MAX_CONCURRENT_JOBS`) and at most four admitted jobs
including queued work (`READ_ALONG_MAX_PENDING_JOBS`). Excess requests return
429 with Retry-After. Jobs stay queued until a processing slot is available.
Each job runs its stages in an owned spawned subprocess. Cancellation terminates
that worker and its subprocess tree, waits for it to exit, removes partial EPUB
output, then reports `cancelled` and releases the processing slot. Shutdown uses
the same cleanup. Other jobs and uploaded source files remain untouched.
Packaging validates a temporary EPUB before atomically publishing `result.epub`.
Worker callbacks injected by tests or benchmarks must be importable top-level
functions; closures and changes to parent-process memory are not supported.

Uploaded EPUBs are untrusted. Before reading their content, the app checks at most
10,000 ZIP entries, 64 MiB per expanded entry, and 512 MiB total expanded size.
These are configurable with `READ_ALONG_MAX_ARCHIVE_ENTRIES`,
`READ_ALONG_MAX_ARCHIVE_ENTRY_BYTES` and `READ_ALONG_MAX_ARCHIVE_BYTES`.
Duplicate ZIP entry names are rejected. XML uses `defusedxml` and retains a
separate 5 MiB per-document cap. Packaging rechecks the input archive too.

Limits are per API process. Use one API worker with the in-memory job store;
multiple workers do not share queues, limits, or job metadata. An exposed service
still needs authentication, proxy limits/timeouts, and storage quotas/retention.
Finished and failed job workspaces are retained; these limits are not a disk
cleanup policy.

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
  source character offsets. Sentence splitting uses pySBD's language-specific
  rules, with English corrections for French titles such as `Mme.` and `Mlle.`.
  It preserves original text and inline markup and keeps sentences inside their
  text blocks. The OPF language selects the rules (`en-US` uses `en`); missing
  language defaults to English. Unsupported languages retain whole text blocks.
  Quoted speech can form a single unit containing several punctuated phrases.
  Segmentation supports more languages than the current English-oriented word
  matcher; this does not imply multilingual alignment support.
  All body text is eligible, including direct body text, verse, table cells,
  definitions and captions. Blocks and explicit line breaks separate text runs.
  Head content and `nav`, `script`, `style`, `template`, `svg` and `math` subtrees
  are excluded; their text still counts toward source character offsets.
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
  Sentence anchors contain exactly their source text. Inline ancestors remain
  intact where possible; when a sentence crosses an inline boundary, split
  fragments keep formatting and link attributes, with the original ID only on
  the first fragment. ID-only CSS selectors therefore apply to that fragment,
  while classes and inline styles carry across all fragments.

`TranscriptionOptions` defaults to faster-whisper's `small.en` model on CPU with
`int8` inference and voice activity detection. Test it against real books before
settling on the model; use a multilingual model if the narration is not English.

## Tests

For downloadable real-book fixtures and automated real-transcription integration
tests, see [benchmarks/README.md](benchmarks/README.md).

```sh
pnpm api:test                   # python -m pytest
```
