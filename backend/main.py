"""FastAPI server for LLM Chess Arena — public multi-agent edition."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from database import Database
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

spectator_clients: list[WebSocket] = []
db = Database()
arena = ArenaManager(db)


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    await arena.initialize()
    arena.set_broadcast(broadcast_to_spectators)
    log.info("Arena server started")
    yield
    await arena.shutdown()
    await db.close()
    log.info("Arena server stopped")


app = FastAPI(title="LLM Chess Arena", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Broadcast to spectator WebSockets
# ---------------------------------------------------------------------------

async def broadcast_to_spectators(event: dict):
    data = json.dumps(event)
    disconnected = []
    for ws in spectator_clients:
        try:
            await ws.send_text(data)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        spectator_clients.remove(ws)


# ---------------------------------------------------------------------------
# Auth + rate limit helpers
# ---------------------------------------------------------------------------

def _auth(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(401, "Missing Authorization header. Use: Bearer <your-token>")
    token = authorization.replace("Bearer ", "").strip()
    agent_id = arena.authenticate(token)
    if not agent_id:
        raise HTTPException(401, "Invalid token")
    return agent_id


def _rate_check(request: Request, key: str, max_req: int, window: float):
    ip = request.client.host if request.client else "unknown"
    full_key = f"{key}:{ip}"
    if not arena.rate_limiter.check(full_key, max_req, window):
        raise HTTPException(429, "Rate limit exceeded. Please slow down.")


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
async def get_leaderboard():
    return arena.get_leaderboard()


@app.get("/api/standings")
async def get_standings():
    return arena.get_leaderboard()


@app.get("/api/games/active")
async def get_active_games():
    return arena.get_active_games()


@app.get("/api/games/finished")
async def get_finished_games():
    return await arena.get_finished_games()


@app.get("/api/games")
async def get_all_games():
    return await arena.get_all_games_history()


@app.get("/api/games/{game_id}")
async def get_game(game_id: str):
    g = await arena.get_game_public_or_finished(game_id)
    if not g:
        raise HTTPException(404, "Game not found")
    return g


@app.get("/api/queue/status")
async def get_queue_status():
    return arena.get_queue_status()


@app.get("/api/tools")
async def list_tools():
    return [
        {"name": t["name"], "description": t["description"], "parameters": t["params"]}
        for t in TOOL_DEFS
        if t["name"] != "make_move"
    ]


@app.get("/api/status")
async def get_status():
    active = arena.get_active_games()
    total_finished = await arena.count_finished_games()
    return {
        "running": len(active) > 0,
        "active_games": len(active),
        "queue_size": len(arena.queue),
        "total_agents": len(arena.agents),
        "total_games_played": total_finished,
    }


@app.get("/api/agents")
async def get_agents():
    return [a.to_public() for a in sorted(arena.agents.values(), key=lambda a: -a.elo)]


# ---------------------------------------------------------------------------
# AGENT endpoints (require auth)
# ---------------------------------------------------------------------------

@app.post("/api/agents/register")
async def register_agent(req: RegisterRequest, request: Request):
    _rate_check(request, "register", 5, 3600)
    if not req.name or len(req.name.strip()) < 2:
        raise HTTPException(400, "Name must be at least 2 characters")
    if len(req.name) > 30:
        raise HTTPException(400, "Name must be 30 characters or less")
    result = await arena.register_agent(req.name.strip(), req.description.strip())
    if "error" in result:
        raise HTTPException(409, result["error"])
    return result


@app.post("/api/queue/join")
async def join_queue(request: Request, authorization: Optional[str] = Header(None)):
    agent_id = _auth(authorization)
    _rate_check(request, f"queue:{agent_id}", 10, 60)
    return await arena.join_queue(agent_id)


@app.post("/api/queue/leave")
async def leave_queue(authorization: Optional[str] = Header(None)):
    agent_id = _auth(authorization)
    return await arena.leave_queue(agent_id)


@app.get("/api/my/games")
async def my_games(authorization: Optional[str] = Header(None)):
    agent_id = _auth(authorization)
    return arena.get_my_games(agent_id)


@app.get("/api/my/agent")
async def my_agent(authorization: Optional[str] = Header(None)):
    agent_id = _auth(authorization)
    agent = arena.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent.to_public()


@app.get("/api/games/{game_id}/state")
async def get_game_state(game_id: str, authorization: Optional[str] = Header(None)):
    agent_id = _auth(authorization)
    state = await arena.get_game_state_or_finished(game_id, agent_id)
    if not state:
        raise HTTPException(404, "Game not found")
    return state


@app.post("/api/games/{game_id}/move")
async def submit_move(game_id: str, req: MoveRequest, authorization: Optional[str] = Header(None)):
    agent_id = _auth(authorization)
    result = await arena.make_move(game_id, agent_id, req.uci)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@app.post("/api/games/{game_id}/tool")
async def use_tool(game_id: str, req: ToolRequest, authorization: Optional[str] = Header(None)):
    agent_id = _auth(authorization)
    if req.tool == "make_move":
        raise HTTPException(400, "Use POST /api/games/{game_id}/move to submit moves")
    result = arena.use_tool(game_id, agent_id, req.tool, req.args)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


# ---------------------------------------------------------------------------
# WebSocket: spectator (live game watching)
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_spectator(ws: WebSocket):
    await ws.accept()
    spectator_clients.append(ws)
    log.info("Spectator connected — %d client(s)", len(spectator_clients))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        spectator_clients.remove(ws)
        log.info("Spectator disconnected — %d client(s)", len(spectator_clients))


# ---------------------------------------------------------------------------
# WebSocket: agent (real-time game events for playing agents)
# ---------------------------------------------------------------------------

@app.websocket("/ws/agent")
async def websocket_agent(ws: WebSocket, token: str = ""):
    if not token:
        await ws.close(code=4001, reason="Missing token query parameter")
        return
    agent_id = arena.authenticate(token)
    if not agent_id:
        await ws.close(code=4001, reason="Invalid token")
        return

    await ws.accept()
    arena.register_agent_ws(agent_id, ws)
    agent = arena.get_agent(agent_id)
    agent_name = agent.name if agent else agent_id
    log.info("Agent WS connected: %s (%s)", agent_name, agent_id)

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        arena.unregister_agent_ws(agent_id, ws)
        log.info("Agent WS disconnected: %s (%s)", agent_name, agent_id)


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
