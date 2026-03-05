# ♟️ LLM Chess Arena

Multiple LLM agents play legal chess against each other in a round-robin tournament. No engine help — just pure language reasoning.

## Quick Start

### Backend
```bash
cd backend
pip install -r requirements.txt
# Set your API keys
export ANTHROPIC_API_KEY=your-key
export OPENAI_API_KEY=your-key
python main.py
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000 and click **Start Tournament**.

## Agents
| Name | Model | Style |
|------|-------|-------|
| Magnus Chatbot | claude-opus-4-6 | Aggressive attacker |
| Stockfished | claude-sonnet-4-6 | Cautious positional |
| GPTambit | gpt-5.3-codex | Wild gambit lover |
| Random Randy | random | Baseline control |

## Rules
- Round-robin, 2 games per pairing (swap colors)
- Max 3 retries per move; invalid → random legal move (💀)
- Win = 1pt, Draw = 0.5pt

## Stack
- **Backend:** Python, FastAPI, python-chess
- **Frontend:** React, Vite, react-chessboard
- **LLMs:** Anthropic + OpenAI APIs
