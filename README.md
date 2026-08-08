# read-along

Fuse an EPUB and its audiobook into a single EPUB 3 file with Media Overlays, so
the narration plays and the matching text highlights as it is spoken.

This repository is the working scaffold for that product: a Vite frontend and a
FastAPI backend, wired together and ready to build on.

## Layout

```
read-along/
  apps/web/        Vite + React frontend (shadcn/ui, TanStack Query, Tailwind)
  services/api/    FastAPI backend
```

## Stack

- **Web** — Vite, React 19, TypeScript, TanStack Query, Tailwind CSS v4 and
  shadcn/ui (preset `b1x9M8ZeJW`: taupe, maia style, outfit + raleway, hugeicons).
- **API** — FastAPI on Python 3.14, served with uvicorn.
- **Tooling** — pnpm workspaces for the frontend, a virtualenv for the backend.

## Getting started

### Web

```sh
pnpm install
pnpm dev
```

The dev server runs on <http://localhost:5173> and proxies `/api` to the backend
at <http://localhost:8000>.

### API

```sh
cd services/api
python -m venv .venv
.venv\Scripts\activate        # Windows; use `source .venv/bin/activate` elsewhere
pip install -e ".[dev]"
pnpm dev                      # or: uvicorn app.main:app --reload
```

Then open the web app; the health badge and the jobs list should populate from
the API.

## Status

Scaffold only. The alignment pipeline — EPUB parsing, transcription and Media
Overlay writing — is not implemented; the API serves in-memory placeholder jobs.

## License

Not chosen yet.
