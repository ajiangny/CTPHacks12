# Degree Planner — frontend

React 19 + TypeScript + Vite + Tailwind 4 + `motion`. See the [root README](../README.md) for the whole project and
[MASTER.md](../MASTER.md) for the design system (every colour/motion token lives in `src/App.css` and `src/App.tsx`).

```
npm install
npm run dev       # http://localhost:5173 — proxies /api to the Python server on :8000 (vite.config.ts)
npm run build     # tsc -b && vite build -> dist/
npm run lint      # oxlint
```

| file | what |
|---|---|
| `src/App.tsx` | the whole planner: header, plan panel, prerequisite DAG, requirements panel, `/api/suggest` + `/api/audit` calls |
| `src/Chat.tsx` | **Advisor** chatbot panel (header button) — posts the approved terms + conversation to `/api/chat` (Gemini); ask for the "fastest track" to get a full semester-by-semester plan |
| `src/plan.ts` | diagram geometry and `nextTerm()` |
| `src/types.ts` | shared API/data types |
| `public/data/*.json` | catalog, prerequisites, sections scraped by `backend/*.py` (committed; refresh once a term) |

State that survives reloads is in `localStorage` (`program`, `terms:<program>`, `pins:`, `queue:`, `ui:left`, `ui:right`, …).
Chat history is not persisted.
