# read-along

Fuse an EPUB and its audiobook into a single EPUB 3 file with Media Overlays, so
the narration plays and the matching text highlights as it is spoken.

This repository contains a Vite frontend and a FastAPI backend for that workflow.

## Layout

```
read-along/
  apps/web/        Vite + React frontend (shadcn/ui, TanStack Query, Tailwind)
  services/api/    FastAPI backend
```

## Stack

- **Web** — Vite, React 19, TypeScript, TanStack Query, Tailwind CSS v4 and
  shadcn/ui. The theme comes from the shadcn preset `b1x9M8ZeJW`: taupe tokens,
  the `maia` style on Base UI, outfit and raleway, hugeicons.
- **API** — FastAPI on Python 3.12+, served with uvicorn.
- **Tooling** — pnpm workspaces for the frontend, a virtualenv for the backend.

## Getting started

### API

```sh
cd services/api
python -m venv .venv
.venv\Scripts\activate          # or: source .venv/bin/activate
pip install -e ".[dev]"
pip install -e ".[transcribe]"  # required for real audio transcription
uvicorn app.main:app --reload --port 8000
```

### Web

In a second shell, from the repository root:

```sh
pnpm install
pnpm dev
```

Open <http://localhost:5173>. The API badge and the jobs list read from the
service on port 8000, which the dev server proxies under `/api`.

Web tests use Vitest and jsdom. Use an up-to-date patch release of Node 22 or 24
LTS, or Node 26, for the web tooling.

## Scripts

Run from the repository root:

| Command          | Does                                  |
| ---------------- | ------------------------------------- |
| `pnpm dev`       | Start the web dev server.             |
| `pnpm build`     | Build the web app.                    |
| `pnpm typecheck` | Type-check the web app.               |
| `pnpm test`      | Test web job progress and recovery.  |
| `pnpm lint`      | Lint the web app.                     |
| `pnpm api:dev`   | Start the API (activate the venv).    |
| `pnpm api:test`  | Run the API tests.                    |

## API

Routes live under `/api`: health, and a jobs resource with create, list, fetch,
cancel, download and a server-sent event stream. See [`services/api/README.md`](services/api/README.md).

## Status

The API accepts an EPUB 3 plus MP3/M4A/M4B narration, extracts sentences,
transcribes the audio, matches timestamps and packages Media Overlays into a
downloadable EPUB. Partial matches fail rather than produce a misleading result.
Transcription needs the optional `transcribe` dependency and downloads a model on
first use. Matching is transcript-based, not acoustic forced alignment, and has
not been validated on real book/audio pairs. Jobs live in memory and do not
survive a restart.

## License

Not chosen yet.
