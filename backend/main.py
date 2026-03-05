"""FastAPI server for LLM Chess Arena."""

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from agents import DEFAULT_AGENTS, AgentConfig
from tournament import Tournament
from game import GameResult

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
tournament_running = False
tournament_pause_event = threading.Event()  # set = running, clear = paused
tournament_pause_event.set()
main_loop: Optional[asyncio.AbstractEventLoop] = None


def _load_or_create_arena() -> Tournament:
    """Load previous tournament state from results.json, or create fresh."""
    t = Tournament(agents=DEFAULT_AGENTS)
    results_file = Path(__file__).parent / "results.json"
    if results_file.exists():
        try:
            data = json.loads(results_file.read_text())
            t.games = data.get("games", [])
            for g in t.games:
                name_w, name_b = g["white"], g["black"]
                sw = t.standings[name_w]
                sb = t.standings[name_b]
                sw.played += 1
                sb.played += 1
                if g["result"] == "1-0":
                    sw.wins += 1
                    sw.points += 1.0
                    sb.losses += 1
                elif g["result"] == "0-1":
                    sb.wins += 1
                    sb.points += 1.0
                    sw.losses += 1
                else:
                    sw.draws += 1
                    sw.points += 0.5
                    sb.draws += 1
                    sb.points += 0.5
                sw.total_fallbacks += sum(
                    1 for m in g.get("moves", []) if m.get("fallback") and m.get("side") == "white"
                )
                sb.total_fallbacks += sum(
                    1 for m in g.get("moves", []) if m.get("fallback") and m.get("side") == "black"
                )
            log.info("Loaded %d games from results.json", len(t.games))
        except Exception:
            log.exception("Failed to load results.json — starting fresh")
    return t


arena: Tournament = _load_or_create_arena()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="LLM Chess Arena")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Broadcast helpers
# ---------------------------------------------------------------------------

async def broadcast(event: dict):
    """Send event to all connected WebSocket clients."""
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
    """Thread-safe broadcast: schedule onto the main event loop."""
    if main_loop is None or main_loop.is_closed():
        log.warning("sync_broadcast: no event loop available, dropping event")
        return
    asyncio.run_coroutine_threadsafe(broadcast(event), main_loop)


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

AGENT_INFO = {a.name: {"provider": a.provider, "model": a.model, "thinking": a.thinking} for a in DEFAULT_AGENTS}


@app.get("/api/agents")
def get_agents():
    return [
        {"name": a.name, "provider": a.provider, "model": a.model, "personality_file": a.personality_file, "thinking": a.thinking}
        for a in DEFAULT_AGENTS
    ]


@app.get("/api/standings")
def get_standings():
    if arena is None:
        return []
    standings = arena.get_standings()
    for s in standings:
        info = AGENT_INFO.get(s["name"], {})
        s["model"] = info.get("model", "")
        s["provider"] = info.get("provider", "")
        s["thinking"] = info.get("thinking", False)
    return standings


@app.get("/api/games")
def get_games():
    if arena is None:
        return []
    return arena.games


@app.get("/api/games/{game_num}/pgn")
def get_game_pgn(game_num: int):
    games_dir = Path(__file__).parent / "games"
    for f in games_dir.glob(f"game_{game_num:03d}_*.pgn"):
        return {"pgn": f.read_text()}
    return {"error": "Game not found"}


@app.get("/api/status")
def get_status():
    return {
        "running": tournament_running,
        "paused": tournament_running and not tournament_pause_event.is_set(),
        "current_game": arena.current_game if arena else None,
        "total_games": len(arena.games) if arena else 0,
        "has_previous": len(arena.games) > 0 if arena else False,
    }


@app.post("/api/tournament/start")
async def start_tournament():
    """Resume an incomplete tournament or start fresh if none exists."""
    global arena, tournament_running, main_loop

    if tournament_running:
        log.warning("Tournament already running — ignoring start request")
        return {"error": "Tournament already running"}

    tournament_running = True
    main_loop = asyncio.get_running_loop()

    completed_games = len(arena.games)
    total_pairings = len(arena.generate_pairings())
    if completed_games > 0 and completed_games < total_pairings:
        log.info("Resuming tournament — %d/%d games done", completed_games, total_pairings)
    else:
        log.info("Starting fresh tournament — %d pairings", total_pairings)

    main_loop.run_in_executor(None, _run_tournament)

    return {
        "status": "resumed" if completed_games > 0 else "started",
        "completed_games": completed_games,
        "total_pairings": total_pairings,
    }


@app.post("/api/tournament/reset")
async def reset_tournament():
    """Delete all saved state and create a fresh tournament."""
    global arena, tournament_running

    if tournament_running:
        return {"error": "Cannot reset while tournament is running"}

    results_file = Path(__file__).parent / "results.json"
    games_dir = Path(__file__).parent / "games"

    if results_file.exists():
        results_file.unlink()
    if games_dir.exists():
        for f in games_dir.glob("*.pgn"):
            f.unlink()

    arena = Tournament(agents=DEFAULT_AGENTS)
    log.info("Tournament reset — all data cleared")

    return {"status": "reset"}


@app.post("/api/tournament/pause")
async def pause_tournament():
    if not tournament_running:
        return {"error": "No tournament running"}

    if tournament_pause_event.is_set():
        tournament_pause_event.clear()
        log.info("Tournament paused — will stop after current game")
        sync_broadcast({"type": "tournament_paused"})
        return {"status": "paused"}
    else:
        tournament_pause_event.set()
        log.info("Tournament resumed")
        sync_broadcast({"type": "tournament_resumed"})
        return {"status": "resumed"}


def _run_tournament():
    global tournament_running

    def on_move(record):
        sync_broadcast({
            "type": "move",
            "ply": record.ply,
            "side": record.side,
            "agent": record.agent,
            "uci": record.uci,
            "san": record.san,
            "fen": record.fen_after,
            "fallback": record.fallback,
            "attempts": record.attempts,
        })

    def on_game_start(num, total, white, black):
        sync_broadcast({
            "type": "game_start",
            "game_num": num,
            "total_games": total,
            "white": white,
            "black": black,
        })

    def on_game_end(game_record):
        sync_broadcast({
            "type": "game_end",
            "game_num": game_record["game_num"],
            "result": game_record["result"],
            "reason": game_record["reason"],
            "white": game_record["white"],
            "black": game_record["black"],
            "total_moves": game_record["total_moves"],
            "standings": arena.get_standings(),
        })

    def on_between_games():
        """Called between games — blocks while paused, returns False to stop."""
        if not tournament_pause_event.is_set():
            log.info("Tournament paused — waiting...")
            tournament_pause_event.wait()
            log.info("Tournament unpaused — continuing")
        return tournament_running

    try:
        arena.run_full_tournament(
            on_move=on_move,
            on_game_start=on_game_start,
            on_game_end=on_game_end,
            on_between_games=on_between_games,
        )
        sync_broadcast({"type": "tournament_complete", "standings": arena.get_standings()})
        log.info("Tournament finished — broadcasting final standings")
    except Exception:
        log.exception("Tournament crashed!")
    finally:
        tournament_running = False
        tournament_pause_event.set()


# ---------------------------------------------------------------------------
# WebSocket for live updates
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
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
