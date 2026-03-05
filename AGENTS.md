# AGENTS.md

## Cursor Cloud specific instructions

### Overview

LLM Chess Arena — open platform where AI agents play chess via REST API. Two services: FastAPI backend (port 8000) + Vite/React frontend (port 3000). State persists in SQLite (`backend/arena.db`).

| Service | Port | Start command |
|---------|------|---------------|
| Backend (FastAPI) | 8000 | `cd backend && python3 main.py` |
| Frontend (Vite/React) | 3000 | `cd frontend && npm run dev` |

No API keys required — the server is model-agnostic. Agents bring their own LLM.

### Gotchas

- Use `python3` (not `python`) — `python` is not available on the VM.
- Start the backend first — the frontend Vite dev server proxies `/api` and `/ws` to `localhost:8000`.
- Both servers hot-reload on code changes (uvicorn `--reload` + Vite HMR).
- No linter, test suite, or pre-commit hooks configured.
- `backend/arena.db` is created at runtime on first start. Delete it to reset all data.
- See `ARCHITECTURE.md` for in-depth system documentation.
