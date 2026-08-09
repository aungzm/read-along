# @read-along/web

The read-along frontend: Vite, React 19, TypeScript, TanStack Query, Tailwind CSS
v4 and shadcn/ui.

## Theme

The app was generated from the shadcn preset `b1x9M8ZeJW` — taupe tokens, the
`maia` style on Base UI, outfit for text and raleway for headings, hugeicons, and
a medium radius. `components.json` records the configuration; `src/index.css`
holds the tokens.

## Scripts

| Command          | Does                              |
| ---------------- | --------------------------------- |
| `pnpm dev`       | Dev server on port 5173.          |
| `pnpm build`     | Type-check, then build to `dist/`.|
| `pnpm typecheck` | `tsc --noEmit`.                   |
| `pnpm lint`      | ESLint.                           |
| `pnpm format`    | Prettier.                         |

Run them here, or use the root scripts (`pnpm dev`, `pnpm build`, …).

## Talking to the API

Requests go to `/api`, which the dev server proxies to `http://127.0.0.1:8000`
(see `vite.config.ts`). Set `VITE_API_BASE_URL` to point at an absolute URL
instead.

The client and the query hooks live in `src/lib/api.ts` and
`src/features/jobs/`. A running job's progress arrives over server-sent events
and is folded straight into the query cache.

## Adding components

```sh
pnpm dlx shadcn@latest add <component> -c apps/web
```
