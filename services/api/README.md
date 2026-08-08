# read-along API

The FastAPI service behind `apps/web`.

```sh
python -m venv .venv
.venv\Scripts\activate          # or: source .venv/bin/activate
pip install -e ".[dev]"
pnpm dev                        # uvicorn app.main:app --reload --port 8000
```

Routes live under `/api`:

| Method | Path                     | Purpose                                  |
| ------ | ------------------------ | ---------------------------------------- |
| GET    | `/api/health`            | Liveness and version.                    |
| GET    | `/api/jobs`              | List jobs, newest first.                 |
| POST   | `/api/jobs`              | Create a job from `{ "title": "..." }`.  |
| GET    | `/api/jobs/{id}`         | Fetch one job.                           |
| POST   | `/api/jobs/{id}/cancel`  | Cancel a queued or running job.          |
| GET    | `/api/jobs/{id}/events`  | Server-sent events for a job's progress. |

Jobs are held in memory and advanced by a timer that walks the pipeline stages.
That is scaffolding for the real alignment engine, not an implementation of it.
