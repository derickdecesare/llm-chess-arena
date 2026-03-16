"""Public arena: agent registration, matchmaking, concurrent games.

Fully async — uses SQLite (via aiosqlite) for crash-safe persistence and
asyncio primitives instead of threading.
"""

import asyncio
import json
import logging
import random
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable

import chess

from database import Database, hash_token
from tools import execute_tool

log = logging.getLogger(__name__)

ABANDON_THRESHOLD = 3
MAX_TOOL_CALLS = 10
MOVE_TIMEOUT = 120.0


# ---------------------------------------------------------------------------
# Data models (in-memory representations)
# ---------------------------------------------------------------------------

@dataclass
class RegisteredAgent:
    agent_id: str
    name: str
    description: str
    token_hash: str
    elo: float = 1200.0
    games_played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    fallbacks: int = 0
    created_at: float = 0.0

    def to_public(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "elo": round(self.elo),
            "games_played": self.games_played,
            "wins": self.wins,
            "draws": self.draws,
            "losses": self.losses,
            "fallbacks": self.fallbacks,
        }

    @classmethod
    def from_row(cls, row: dict) -> "RegisteredAgent":
        return cls(**{k: row[k] for k in cls.__dataclass_fields__ if k in row})


@dataclass
class LiveGame:
    game_id: str
    white_id: str
    black_id: str
    white_name: str
    black_name: str
    board: chess.Board
    moves: list = field(default_factory=list)
    status: str = "active"
    result: Optional[str] = None
    reason: Optional[str] = None
    turn_deadline: float = 0.0
    tool_calls_remaining: int = MAX_TOOL_CALLS
    created_at: float = 0.0
    white_fallbacks: int = 0
    black_fallbacks: int = 0
    white_consecutive_timeouts: int = 0
    black_consecutive_timeouts: int = 0

    def current_side(self) -> str:
        return "white" if self.board.turn == chess.WHITE else "black"

    def current_agent_id(self) -> str:
        return self.white_id if self.board.turn == chess.WHITE else self.black_id

    def to_public(self) -> dict:
        return {
            "game_id": self.game_id,
            "white": {"agent_id": self.white_id, "name": self.white_name},
            "black": {"agent_id": self.black_id, "name": self.black_name},
            "fen": self.board.fen(),
            "status": self.status,
            "result": self.result,
            "reason": self.reason,
            "turn": self.current_side(),
            "turn_agent_id": self.current_agent_id(),
            "move_count": len(self.moves),
            "moves": [
                {"san": m["san"], "uci": m["uci"], "side": m["side"],
                 "agent": m["agent"], "fallback": m.get("fallback", False)}
                for m in self.moves
            ],
        }

    def to_state(self, for_agent_id: str) -> dict:
        side = "white" if self.board.turn == chess.WHITE else "black"
        move_history = []
        replay = chess.Board()
        for m in self.board.move_stack:
            move_history.append(replay.san(m))
            replay.push(m)

        return {
            "game_id": self.game_id,
            "your_side": "white" if for_agent_id == self.white_id else "black",
            "side_to_move": side,
            "is_your_turn": self.current_agent_id() == for_agent_id,
            "fen": self.board.fen(),
            "move_count": len(self.moves),
            "recent_moves": move_history[-10:],
            "legal_moves": [m.uci() for m in self.board.legal_moves],
            "is_check": self.board.is_check(),
            "tool_calls_remaining": self.tool_calls_remaining,
            "status": self.status,
            "result": self.result,
        }


# ---------------------------------------------------------------------------
# ELO calculation
# ---------------------------------------------------------------------------

def _elo_update(ra: float, rb: float, score_a: float, k: int = 32) -> tuple[float, float]:
    ea = 1.0 / (1.0 + 10 ** ((rb - ra) / 400))
    eb = 1.0 - ea
    score_b = 1.0 - score_a
    return ra + k * (score_a - ea), rb + k * (score_b - eb)


# ---------------------------------------------------------------------------
# Rate limiter (in-memory, per-key sliding window)
# ---------------------------------------------------------------------------

class RateLimiter:
    def __init__(self):
        self._windows: dict[str, list[float]] = {}

    def check(self, key: str, max_requests: int, window_seconds: float) -> bool:
        now = time.time()
        cutoff = now - window_seconds
        timestamps = self._windows.get(key, [])
        timestamps = [t for t in timestamps if t > cutoff]
        if len(timestamps) >= max_requests:
            return False
        timestamps.append(now)
        self._windows[key] = timestamps
        return True


# ---------------------------------------------------------------------------
# Arena Manager
# ---------------------------------------------------------------------------

class ArenaManager:
    def __init__(self, db: Database):
        self.db = db
        self.agents: dict[str, RegisteredAgent] = {}
        self.token_hashes: dict[str, str] = {}  # hash -> agent_id
        self.queue: list[str] = []
        self.games: dict[str, LiveGame] = {}
        self.lock = asyncio.Lock()
        self.broadcast_fn: Optional[Callable[..., Awaitable]] = None
        self.agent_ws_clients: dict[str, list] = {}  # agent_id -> [WebSocket]
        self._timeout_task: Optional[asyncio.Task] = None
        self._running = True
        self.rate_limiter = RateLimiter()

    async def initialize(self):
        """Load state from database and start background tasks."""
        await self._load_agents()
        await self._restore_active_games()
        self._timeout_task = asyncio.create_task(self._timeout_monitor())
        log.info("Arena initialized: %d agents, %d active games restored",
                 len(self.agents), len(self.games))

    def set_broadcast(self, fn: Callable):
        self.broadcast_fn = fn

    async def _broadcast(self, event: dict):
        if self.broadcast_fn:
            await self.broadcast_fn(event)

    async def _notify_agent(self, agent_id: str, event: dict):
        """Send an event to a specific agent's WebSocket connections."""
        clients = self.agent_ws_clients.get(agent_id, [])
        data = json.dumps(event)
        disconnected = []
        for ws in clients:
            try:
                await ws.send_text(data)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            clients.remove(ws)

    def register_agent_ws(self, agent_id: str, ws):
        self.agent_ws_clients.setdefault(agent_id, []).append(ws)

    def unregister_agent_ws(self, agent_id: str, ws):
        clients = self.agent_ws_clients.get(agent_id, [])
        if ws in clients:
            clients.remove(ws)

    # -- Load from DB --

    async def _load_agents(self):
        rows = await self.db.get_all_agents()
        for row in rows:
            agent = RegisteredAgent.from_row(row)
            self.agents[agent.agent_id] = agent
            self.token_hashes[agent.token_hash] = agent.agent_id
        log.info("Loaded %d agents from database", len(self.agents))

    async def _restore_active_games(self):
        """Rebuild in-memory game state from active games in DB."""
        rows = await self.db.get_active_games()
        for row in rows:
            try:
                board = chess.Board(row["fen"])
                moves = json.loads(row["moves_json"])
                game = LiveGame(
                    game_id=row["game_id"],
                    white_id=row["white_id"],
                    black_id=row["black_id"],
                    white_name=row["white_name"],
                    black_name=row["black_name"],
                    board=board,
                    moves=moves,
                    status="active",
                    turn_deadline=time.time() + MOVE_TIMEOUT,
                    tool_calls_remaining=row["tool_calls_remaining"],
                    created_at=row["created_at"],
                    white_fallbacks=row["white_fallbacks"],
                    black_fallbacks=row["black_fallbacks"],
                    white_consecutive_timeouts=row.get("white_consecutive_timeouts", 0),
                    black_consecutive_timeouts=row.get("black_consecutive_timeouts", 0),
                )
                self.games[game.game_id] = game
                log.info("Restored active game: %s (%s vs %s, %d moves)",
                         game.game_id, game.white_name, game.black_name, len(moves))
            except Exception:
                log.exception("Failed to restore game %s", row["game_id"])

    # -- Agent registration --

    async def register_agent(self, name: str, description: str = "") -> dict:
        async with self.lock:
            existing = await self.db.get_agent_by_name(name)
            if existing:
                return {"error": f"Agent name '{name}' already taken"}

            agent_id = str(uuid.uuid4())[:8]
            raw_token = f"arena_{secrets.token_urlsafe(32)}"
            tok_hash = hash_token(raw_token)

            agent = RegisteredAgent(
                agent_id=agent_id,
                name=name,
                description=description,
                token_hash=tok_hash,
                created_at=time.time(),
            )
            await self.db.insert_agent(agent_id, name, description, tok_hash, agent.created_at)
            self.agents[agent_id] = agent
            self.token_hashes[tok_hash] = agent_id

            log.info("Registered agent: %s (%s)", name, agent_id)
            return {
                "agent_id": agent_id,
                "name": name,
                "token": raw_token,
                "message": "Save your token! It won't be shown again.",
            }

    def authenticate(self, token: str) -> Optional[str]:
        tok_hash = hash_token(token)
        return self.token_hashes.get(tok_hash)

    def get_agent(self, agent_id: str) -> Optional[RegisteredAgent]:
        return self.agents.get(agent_id)

    def get_leaderboard(self) -> list[dict]:
        agents = sorted(
            self.agents.values(),
            key=lambda a: (-a.elo, -a.wins, a.name),
        )
        return [{**a.to_public(), "rank": i + 1} for i, a in enumerate(agents)]

    # -- Matchmaking --

    async def join_queue(self, agent_id: str) -> dict:
        async with self.lock:
            for g in self.games.values():
                if g.status == "active" and agent_id in (g.white_id, g.black_id):
                    return {"status": "already_in_game", "game_id": g.game_id}

            if agent_id in self.queue:
                return {"status": "already_queued", "position": self.queue.index(agent_id) + 1}

            self.queue.append(agent_id)
            pos = len(self.queue)
            log.info("Agent %s joined queue (position %d)", agent_id, pos)

            if len(self.queue) >= 2:
                return await self._create_match(agent_id)

            return {"status": "queued", "position": pos, "message": "Waiting for opponent..."}

    async def leave_queue(self, agent_id: str) -> dict:
        async with self.lock:
            if agent_id in self.queue:
                self.queue.remove(agent_id)
                return {"status": "left_queue"}
            return {"status": "not_in_queue"}

    def get_queue_status(self) -> dict:
        return {
            "queue_size": len(self.queue),
            "active_games": sum(1 for g in self.games.values() if g.status == "active"),
            "waiting_agents": [self.agents[aid].name for aid in self.queue if aid in self.agents],
        }

    async def _create_match(self, caller_id: str) -> dict:
        """Create a game from the first two agents in queue. Must hold lock."""
        a_id = self.queue.pop(0)
        b_id = self.queue.pop(0)
        a = self.agents[a_id]
        b = self.agents[b_id]

        if random.random() < 0.5:
            a_id, b_id = b_id, a_id
            a, b = b, a

        game_id = str(uuid.uuid4())[:8]
        now = time.time()
        board = chess.Board()
        game = LiveGame(
            game_id=game_id,
            white_id=a_id,
            black_id=b_id,
            white_name=a.name,
            black_name=b.name,
            board=board,
            created_at=now,
            turn_deadline=now + MOVE_TIMEOUT,
        )
        self.games[game_id] = game

        await self.db.insert_game(
            game_id, a_id, b_id, a.name, b.name,
            board.fen(), game.turn_deadline, now,
        )

        log.info("Match created: %s vs %s (game %s)", a.name, b.name, game_id)

        game_start_event = {
            "type": "game_start",
            "game_id": game_id,
            "white": {"agent_id": a_id, "name": a.name},
            "black": {"agent_id": b_id, "name": b.name},
        }
        await self._broadcast(game_start_event)

        for pid in (a_id, b_id):
            side = "white" if pid == a_id else "black"
            await self._notify_agent(pid, {
                "type": "matched",
                "game_id": game_id,
                "your_side": side,
                "opponent": b.name if pid == a_id else a.name,
            })

        caller_side = "white" if caller_id == a_id else "black"
        return {
            "status": "matched",
            "game_id": game_id,
            "white": {"agent_id": a_id, "name": a.name},
            "black": {"agent_id": b_id, "name": b.name},
            "your_side": caller_side,
        }

    # -- Game play --

    def get_game_state(self, game_id: str, agent_id: str) -> Optional[dict]:
        game = self.games.get(game_id)
        if game:
            return game.to_state(agent_id)
        return None

    async def get_game_state_or_finished(self, game_id: str, agent_id: str) -> Optional[dict]:
        game = self.games.get(game_id)
        if game:
            return game.to_state(agent_id)
        row = await self.db.get_game(game_id)
        if row:
            return self._finished_game_to_public(row)
        return None

    def get_game_public(self, game_id: str) -> Optional[dict]:
        game = self.games.get(game_id)
        if game:
            return game.to_public()
        return None

    async def get_game_public_or_finished(self, game_id: str) -> Optional[dict]:
        game = self.games.get(game_id)
        if game:
            return game.to_public()
        row = await self.db.get_game(game_id)
        if row:
            return self._finished_game_to_public(row)
        return None

    def use_tool(self, game_id: str, agent_id: str, tool_name: str, args: dict) -> dict:
        game = self.games.get(game_id)
        if not game:
            return {"error": "Game not found"}
        if game.status != "active":
            return {"error": "Game is finished"}
        if game.current_agent_id() != agent_id:
            return {"error": "Not your turn"}
        if tool_name == "make_move":
            return {"error": "Use POST /api/games/{game_id}/move to submit moves"}
        if game.tool_calls_remaining <= 0:
            return {"error": "No tool calls remaining. Submit your move."}

        game.tool_calls_remaining -= 1
        try:
            result = execute_tool(game.board, tool_name, args)
        except Exception as e:
            return {"error": f"Tool error: {e}"}
        result["_budget"] = f"{game.tool_calls_remaining} tool calls remaining"
        return result

    async def make_move(self, game_id: str, agent_id: str, uci: str) -> dict:
        async with self.lock:
            game = self.games.get(game_id)
            if not game:
                return {"error": "Game not found"}
            if game.status != "active":
                return {"error": "Game is finished"}
            if game.current_agent_id() != agent_id:
                return {"error": "Not your turn"}

            uci = uci.strip().lower()

            try:
                move = chess.Move.from_uci(uci)
            except ValueError:
                try:
                    move = game.board.parse_san(uci)
                except ValueError:
                    return {"error": f"Invalid move format: '{uci}'",
                            "legal_moves": [m.uci() for m in game.board.legal_moves]}

            if move not in game.board.legal_moves:
                return {"error": f"Illegal move: '{uci}'",
                        "legal_moves": [m.uci() for m in game.board.legal_moves]}

            side = game.current_side()
            agent_name = game.white_name if side == "white" else game.black_name
            san = game.board.san(move)
            game.board.push(move)

            if side == "white":
                game.white_consecutive_timeouts = 0
            else:
                game.black_consecutive_timeouts = 0

            move_record = {
                "ply": len(game.moves),
                "san": san,
                "uci": move.uci(),
                "side": side,
                "agent": agent_name,
                "agent_id": agent_id,
                "fallback": False,
                "fen": game.board.fen(),
            }
            game.moves.append(move_record)
            game.tool_calls_remaining = MAX_TOOL_CALLS
            game.turn_deadline = time.time() + MOVE_TIMEOUT

            move_event = {
                "type": "move",
                "game_id": game_id,
                "ply": move_record["ply"],
                "side": side,
                "agent": agent_name,
                "uci": move.uci(),
                "san": san,
                "fen": game.board.fen(),
                "fallback": False,
            }
            await self._broadcast(move_event)

            next_agent_id = game.current_agent_id()
            await self._notify_agent(next_agent_id, {
                "type": "your_turn",
                "game_id": game_id,
                "fen": game.board.fen(),
            })

            if game.board.is_game_over() or len(game.moves) >= 300:
                return await self._finish_game(game)

            await self.db.update_game_move(
                game_id, game.board.fen(), json.dumps(game.moves),
                game.tool_calls_remaining, game.turn_deadline,
                game.white_fallbacks, game.black_fallbacks,
                game.white_consecutive_timeouts, game.black_consecutive_timeouts,
            )

            return {
                "status": "ok",
                "move": san,
                "fen": game.board.fen(),
                "game_status": "active",
            }

    async def _apply_timeout_move(self, game: LiveGame):
        """Apply a random move for timeout. Must hold lock."""
        legal = list(game.board.legal_moves)
        if not legal:
            return

        move = random.choice(legal)
        side = game.current_side()
        agent_id = game.current_agent_id()
        agent = self.agents.get(agent_id)
        agent_name = agent.name if agent else "Unknown"
        san = game.board.san(move)
        game.board.push(move)

        if side == "white":
            game.white_fallbacks += 1
            game.white_consecutive_timeouts += 1
        else:
            game.black_fallbacks += 1
            game.black_consecutive_timeouts += 1

        move_record = {
            "ply": len(game.moves),
            "san": san,
            "uci": move.uci(),
            "side": side,
            "agent": agent_name,
            "agent_id": agent_id,
            "fallback": True,
            "fen": game.board.fen(),
        }
        game.moves.append(move_record)
        game.tool_calls_remaining = MAX_TOOL_CALLS
        game.turn_deadline = time.time() + MOVE_TIMEOUT

        await self._broadcast({
            "type": "move",
            "game_id": game.game_id,
            "ply": move_record["ply"],
            "side": side,
            "agent": agent_name,
            "uci": move.uci(),
            "san": san,
            "fen": game.board.fen(),
            "fallback": True,
        })

        log.warning("Timeout fallback for %s in game %s: %s", agent_name, game.game_id, san)

        abandoned_side = None
        if game.white_consecutive_timeouts >= ABANDON_THRESHOLD:
            abandoned_side = "white"
        elif game.black_consecutive_timeouts >= ABANDON_THRESHOLD:
            abandoned_side = "black"

        if abandoned_side:
            log.warning("Agent %s abandoned game %s (%d consecutive timeouts)",
                        agent_name, game.game_id, ABANDON_THRESHOLD)
            game.result = "0-1" if abandoned_side == "white" else "1-0"
            game.reason = "abandonment"
            game.status = "finished"
            await self._finish_game(game)
        elif game.board.is_game_over() or len(game.moves) >= 300:
            await self._finish_game(game)
        else:
            await self.db.update_game_move(
                game.game_id, game.board.fen(), json.dumps(game.moves),
                game.tool_calls_remaining, game.turn_deadline,
                game.white_fallbacks, game.black_fallbacks,
                game.white_consecutive_timeouts, game.black_consecutive_timeouts,
            )

    async def _finish_game(self, game: LiveGame) -> dict:
        """Finish a game and update ratings. Must hold lock."""
        board = game.board

        if game.reason and game.result:
            result = game.result
            reason = game.reason
        elif board.is_checkmate():
            result = "0-1" if board.turn == chess.WHITE else "1-0"
            reason = "checkmate"
        elif board.is_stalemate():
            result = "1/2-1/2"
            reason = "stalemate"
        elif board.is_insufficient_material():
            result = "1/2-1/2"
            reason = "insufficient_material"
        elif board.can_claim_fifty_moves():
            result = "1/2-1/2"
            reason = "fifty_move_rule"
        elif board.is_repetition(3):
            result = "1/2-1/2"
            reason = "threefold_repetition"
        elif len(game.moves) >= 300:
            result = "1/2-1/2"
            reason = "max_moves"
        else:
            result = board.result()
            reason = "game_over"

        game.status = "finished"
        game.result = result
        game.reason = reason

        w = self.agents.get(game.white_id)
        b = self.agents.get(game.black_id)

        if w and b:
            score_w = 1.0 if result == "1-0" else (0.0 if result == "0-1" else 0.5)
            w.elo, b.elo = _elo_update(w.elo, b.elo, score_w)

            w.games_played += 1
            b.games_played += 1

            if result == "1-0":
                w.wins += 1
                b.losses += 1
            elif result == "0-1":
                b.wins += 1
                w.losses += 1
            else:
                w.draws += 1
                b.draws += 1

            w.fallbacks += game.white_fallbacks
            b.fallbacks += game.black_fallbacks

        moves_json = json.dumps(game.moves)

        # Atomic transaction: agent stats + game result must all commit together
        async with self.db.transaction():
            if w and b:
                await self.db.update_agent_stats(
                    w.agent_id, w.elo, w.games_played, w.wins, w.draws, w.losses, w.fallbacks,
                    _commit=False)
                await self.db.update_agent_stats(
                    b.agent_id, b.elo, b.games_played, b.wins, b.draws, b.losses, b.fallbacks,
                    _commit=False)
            await self.db.finish_game(
                game.game_id, result, reason, board.fen(), moves_json,
                game.white_fallbacks, game.black_fallbacks, _commit=False,
            )

        game_end_event = {
            "type": "game_end",
            "game_id": game.game_id,
            "result": result,
            "reason": reason,
            "white": game.white_name,
            "black": game.black_name,
            "total_moves": len(game.moves),
        }
        await self._broadcast(game_end_event)

        for pid in (game.white_id, game.black_id):
            await self._notify_agent(pid, {
                "type": "game_end",
                "game_id": game.game_id,
                "result": result,
                "reason": reason,
            })

        del self.games[game.game_id]
        log.info("Game %s finished: %s (%s)", game.game_id, result, reason)

        return {
            "status": "finished",
            "result": result,
            "reason": reason,
            "fen": board.fen(),
        }

    # -- Timeout monitor (async) --

    async def _timeout_monitor(self):
        while self._running:
            await asyncio.sleep(5)
            async with self.lock:
                now = time.time()
                for game in list(self.games.values()):
                    if game.status == "active" and now > game.turn_deadline:
                        await self._apply_timeout_move(game)

    async def shutdown(self):
        self._running = False
        if self._timeout_task:
            self._timeout_task.cancel()
            try:
                await self._timeout_task
            except asyncio.CancelledError:
                pass

    # -- Game listing --

    def get_active_games(self) -> list[dict]:
        return [g.to_public() for g in self.games.values() if g.status == "active"]

    async def get_finished_games(self) -> list[dict]:
        rows = await self.db.get_finished_games(limit=50)
        return [self._finished_game_to_public(r) for r in rows]

    def get_my_games(self, agent_id: str) -> list[dict]:
        return [
            g.to_state(agent_id)
            for g in self.games.values()
            if g.status == "active" and agent_id in (g.white_id, g.black_id)
        ]

    async def get_all_games_history(self) -> list[dict]:
        rows = await self.db.get_finished_games(limit=200)
        return [self._finished_game_to_public(r) for r in rows]

    async def count_finished_games(self) -> int:
        return await self.db.count_finished_games()

    def _finished_game_to_public(self, row: dict) -> dict:
        moves = json.loads(row["moves_json"]) if row.get("moves_json") else []
        return {
            "game_id": row["game_id"],
            "white": {"agent_id": row["white_id"], "name": row["white_name"]},
            "black": {"agent_id": row["black_id"], "name": row["black_name"]},
            "status": row["status"],
            "result": row["result"],
            "reason": row["reason"],
            "fen": row["fen"],
            "total_moves": len(moves),
            "white_fallbacks": row.get("white_fallbacks", 0),
            "black_fallbacks": row.get("black_fallbacks", 0),
            "moves": [
                {"san": m["san"], "uci": m["uci"], "side": m["side"],
                 "agent": m["agent"], "fallback": m.get("fallback", False),
                 "fen": m.get("fen", "")}
                for m in moves
            ],
        }
