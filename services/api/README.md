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

`app/pipeline.py` sketches the next implementation. It is not wired into the
job worker: every function raises `NotImplementedError`. The planned path is
spine XHTML to sentence anchors, one audio file to a rough transcript, rough
passage matches to sentence timings, a coverage review, then SMIL overlays and
a validated EPUB. Unmatched text stays unmatched; `partial` and `rejected`
reports do not produce a download by default. The current successful job and
download are still placeholders after metadata extraction.

For the proposed transcription step, `TranscriptionOptions` defaults to
faster-whisper's `small.en` model on CPU with `int8` inference and voice activity
detection. This is a starting choice for English narration, not an installed
dependency or a working transcription stage. Test it against real books before
settling on the model; use a multilingual model if the narration is not English.

## Tests

```sh
pnpm api:test                   # python -m pytest
```
