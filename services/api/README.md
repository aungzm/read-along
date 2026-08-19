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

## Tests

```sh
pnpm api:test                   # python -m pytest
```
