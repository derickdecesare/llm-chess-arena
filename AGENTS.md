# AGENTS.md

## Cursor Cloud specific instructions

### Overview

LLM Chess Arena — a two-service web app where LLM agents play chess against each other in a round-robin tournament. No database; state persists to flat JSON/PGN files.

| Service | Port | Start command |
|---------|------|---------------|
| Backend (FastAPI) | 8000 | `cd backend && python3 main.py` |
| Frontend (Vite/React) | 3000 | `cd frontend && npm run dev` |

### API keys

Both `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` must be set. The backend loads them from `backend/.env` (via python-dotenv) or from environment variables. To create the `.env` file:

```bash
echo "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY" > backend/.env
echo "OPENAI_API_KEY=$OPENAI_API_KEY" >> backend/.env
```

### Gotchas

- Use `python3` (not `python`) to run the backend — `python` is not available on the VM.
- The frontend Vite dev server proxies `/api` and `/ws` to `localhost:8000`, so start the backend first.
- The backend uses `uvicorn` with `--reload`; the frontend uses Vite HMR. Both pick up code changes automatically.
- There is no linter, test suite, or pre-commit hooks configured in this repo.
- `npm run build` (in `frontend/`) produces the production build; `npm run dev` is for development.
- The `backend/games/` directory and `backend/results.json` are created at runtime; they do not exist in a fresh clone.
