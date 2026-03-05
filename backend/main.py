"""FastAPI server for LLM Chess Arena — public multi-agent edition."""

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from arena import ArenaManager
from tools import TOOL_DEFS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

connected_clients: list[WebSocket] = []
main_loop: Optional[asyncio.AbstractEventLoop] = None
arena = ArenaManager()

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="LLM Chess Arena", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Broadcast
# ---------------------------------------------------------------------------

async def broadcast(event: dict):
    data = json.dumps(event)
    disconnected = []
    for ws in connected_clients:
        try:
            await ws.send_text(data)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        connected_clients.remove(ws)


def sync_broadcast(event: dict):
    if main_loop is None or main_loop.is_closed():
        return
    asyncio.run_coroutine_threadsafe(broadcast(event), main_loop)


@app.on_event("startup")
async def startup():
    global main_loop
    main_loop = asyncio.get_running_loop()
    arena.set_broadcast(sync_broadcast)


@app.on_event("shutdown")
async def shutdown():
    arena.shutdown()


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _auth(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(401, "Missing Authorization header. Use: Bearer <your-token>")
    token = authorization.replace("Bearer ", "").strip()
    agent_id = arena.authenticate(token)
    if not agent_id:
        raise HTTPException(401, "Invalid token")
    return agent_id


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    name: str
    description: str = ""

class MoveRequest(BaseModel):
    uci: str

class ToolRequest(BaseModel):
    tool: str
    args: dict = {}


# ---------------------------------------------------------------------------
# PUBLIC endpoints (no auth)
# ---------------------------------------------------------------------------

@app.get("/api/leaderboard")
def get_leaderboard():
    return arena.get_leaderboard()


@app.get("/api/standings")
def get_standings():
    """Alias for leaderboard (backward compatible)."""
    return arena.get_leaderboard()


@app.get("/api/games/active")
def get_active_games():
    return arena.get_active_games()


@app.get("/api/games/finished")
def get_finished_games():
    return arena.get_finished_games()


@app.get("/api/games")
def get_all_games():
    """All finished games (backward compatible)."""
    return arena.get_all_games_history()


@app.get("/api/games/{game_id}")
def get_game(game_id: str):
    g = arena.get_game_public(game_id)
    if not g:
        raise HTTPException(404, "Game not found")
    return g


@app.get("/api/queue/status")
def get_queue_status():
    return arena.get_queue_status()


@app.get("/api/tools")
def list_tools():
    """List available chess analysis tools that agents can use."""
    return [
        {"name": t["name"], "description": t["description"], "parameters": t["params"]}
        for t in TOOL_DEFS
        if t["name"] != "make_move"
    ]


@app.get("/api/status")
def get_status():
    active = arena.get_active_games()
    return {
        "running": len(active) > 0,
        "active_games": len(active),
        "queue_size": len(arena.queue),
        "total_agents": len(arena.agents),
        "total_games_played": len(arena.finished_games),
    }


@app.get("/api/agents")
def get_agents():
    """List all registered agents (public info)."""
    return [a.to_public() for a in sorted(arena.agents.values(), key=lambda a: -a.elo)]


# ---------------------------------------------------------------------------
# AGENT endpoints (require auth)
# ---------------------------------------------------------------------------

@app.post("/api/agents/register")
def register_agent(req: RegisterRequest):
    if not req.name or len(req.name.strip()) < 2:
        raise HTTPException(400, "Name must be at least 2 characters")
    if len(req.name) > 30:
        raise HTTPException(400, "Name must be 30 characters or less")
    result = arena.register_agent(req.name.strip(), req.description.strip())
    if "error" in result:
        raise HTTPException(409, result["error"])
    return result


@app.post("/api/queue/join")
def join_queue(authorization: Optional[str] = Header(None)):
    agent_id = _auth(authorization)
    result = arena.join_queue(agent_id)
    return result


@app.post("/api/queue/leave")
def leave_queue(authorization: Optional[str] = Header(None)):
    agent_id = _auth(authorization)
    return arena.leave_queue(agent_id)


@app.get("/api/my/games")
def my_games(authorization: Optional[str] = Header(None)):
    agent_id = _auth(authorization)
    return arena.get_my_games(agent_id)


@app.get("/api/my/agent")
def my_agent(authorization: Optional[str] = Header(None)):
    agent_id = _auth(authorization)
    agent = arena.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent.to_public()


@app.get("/api/games/{game_id}/state")
def get_game_state(game_id: str, authorization: Optional[str] = Header(None)):
    agent_id = _auth(authorization)
    state = arena.get_game_state(game_id, agent_id)
    if not state:
        raise HTTPException(404, "Game not found")
    return state


@app.post("/api/games/{game_id}/move")
def submit_move(game_id: str, req: MoveRequest, authorization: Optional[str] = Header(None)):
    agent_id = _auth(authorization)
    result = arena.make_move(game_id, agent_id, req.uci)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@app.post("/api/games/{game_id}/tool")
def use_tool(game_id: str, req: ToolRequest, authorization: Optional[str] = Header(None)):
    agent_id = _auth(authorization)
    if req.tool == "make_move":
        raise HTTPException(400, "Use POST /api/games/{game_id}/move to submit moves")
    result = arena.use_tool(game_id, agent_id, req.tool, req.args)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


# ---------------------------------------------------------------------------
# WebSocket for live spectating
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.append(ws)
    log.info("WebSocket connected — %d client(s)", len(connected_clients))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(ws)
        log.info("WebSocket disconnected — %d client(s)", len(connected_clients))


# ---------------------------------------------------------------------------
# Serve frontend build (production)
# ---------------------------------------------------------------------------

frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="static")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
