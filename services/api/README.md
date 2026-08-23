# read-along API

The FastAPI service behind `apps/web`.

```sh
python -m venv .venv
.venv\Scripts\activate          # or: source .venv/bin/activate
pip install -e ".[dev]"
pnpm dev                        # uvicorn app.main:app --reload --port 8000
```

Routes live under `/api`:

| Method | Path                     | Purpose                                         |
| ------ | ------------------------ | ----------------------------------------------- |
| GET    | `/api/health`            | Liveness and version.                           |
| GET    | `/api/jobs`              | List jobs, newest first.                        |
| POST   | `/api/jobs`              | Create a job from a multipart `epub` + `audio`. |
| GET    | `/api/jobs/{id}`         | Fetch one job.                                  |
| POST   | `/api/jobs/{id}/cancel`  | Cancel a queued or running job.                 |
| GET    | `/api/jobs/{id}/events`  | Server-sent events for a job's progress.        |

Uploads are streamed to disk under `READ_ALONG_DATA_DIR` (default `var/`), one
directory per job. `READ_ALONG_MAX_UPLOAD_BYTES` caps each file and defaults to
2 GiB. Uploaded files are untrusted: EPUB package documents are parsed with
`defusedxml` and no XML part larger than 5 MiB is read.

## Pipeline

The `extract` stage is real. It reads `META-INF/container.xml`, follows it to
the package document, and records the title, author, language and spine length
(`chapters`) on the job. A file that is not a usable EPUB fails the job with a
readable error.

`transcribe`, `align`, `build` and `package` still walk a timer. They are
scaffolding for the alignment engine, not an implementation of it. Jobs are held
in memory, so restarting the service clears the job list; the uploaded
directories under `data_dir` remain.

### Planned pipeline contracts

`app/pipeline.py` holds the read-along engine, still outside the job worker. The
path is spine XHTML to sentence anchors, one audio file to a rough transcript,
rough passage matches to sentence timings, a coverage review, then SMIL overlays
and a validated EPUB. All stages are implemented and directly tested, but the
job worker's `transcribe`, `align`, `build` and `package` stages remain timers
until they call this module. Unmatched text stays unmatched; `partial` and
`rejected` reports do not produce a download by default. The current successful
job and download are still placeholders after metadata extraction.

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
