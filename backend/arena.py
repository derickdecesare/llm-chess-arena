"""Public arena: agent registration, matchmaking, concurrent games."""

import json
import logging
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable

import chess

from tools import execute_tool

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "arena_data"
GAMES_DIR = Path(__file__).parent / "games"
AGENTS_FILE = DATA_DIR / "agents.json"
GAMES_FILE = DATA_DIR / "games.json"
RATINGS_FILE = DATA_DIR / "ratings.json"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class RegisteredAgent:
    agent_id: str
    name: str
    description: str
    token: str
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


@dataclass
class LiveGame:
    game_id: str
    white_id: str
    black_id: str
    white_name: str
    black_name: str
    board: chess.Board
    moves: list = field(default_factory=list)
    status: str = "active"  # active | finished
    result: Optional[str] = None
    reason: Optional[str] = None
    turn_agent_id: Optional[str] = None
    turn_deadline: float = 0.0
    tool_calls_remaining: int = 10
    max_tool_calls: int = 10
    move_timeout: float = 120.0
    created_at: float = 0.0
    white_fallbacks: int = 0
    black_fallbacks: int = 0

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
                {"san": m["san"], "uci": m["uci"], "side": m["side"], "agent": m["agent"], "fallback": m.get("fallback", False)}
                for m in self.moves
            ],
        }

    def to_state(self, for_agent_id: str) -> dict:
        """Board state for the playing agent."""
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
# Arena Manager
# ---------------------------------------------------------------------------

class ArenaManager:
    def __init__(self):
        DATA_DIR.mkdir(exist_ok=True)
        GAMES_DIR.mkdir(exist_ok=True)
        self.agents: dict[str, RegisteredAgent] = {}
        self.tokens: dict[str, str] = {}  # token -> agent_id
        self.queue: list[str] = []  # agent_ids waiting for a game
        self.games: dict[str, LiveGame] = {}
        self.finished_games: list[dict] = []
        self.lock = threading.Lock()
        self.broadcast_fn: Optional[Callable] = None
        self._timeout_thread: Optional[threading.Thread] = None
        self._running = True
        self._load()
        self._start_timeout_monitor()

    def set_broadcast(self, fn: Callable):
        self.broadcast_fn = fn

    def _broadcast(self, event: dict):
        if self.broadcast_fn:
            self.broadcast_fn(event)

    # -- Persistence --

    def _load(self):
        if AGENTS_FILE.exists():
            try:
                data = json.loads(AGENTS_FILE.read_text())
                for d in data:
                    agent = RegisteredAgent(**d)
                    self.agents[agent.agent_id] = agent
                    self.tokens[agent.token] = agent.agent_id
                log.info("Loaded %d registered agents", len(self.agents))
            except Exception:
                log.exception("Failed to load agents")

        if GAMES_FILE.exists():
            try:
                self.finished_games = json.loads(GAMES_FILE.read_text())
                log.info("Loaded %d finished games", len(self.finished_games))
            except Exception:
                log.exception("Failed to load games history")

    def _save_agents(self):
        data = []
        for a in self.agents.values():
            data.append({
                "agent_id": a.agent_id, "name": a.name, "description": a.description,
                "token": a.token, "elo": a.elo, "games_played": a.games_played,
                "wins": a.wins, "draws": a.draws, "losses": a.losses,
                "fallbacks": a.fallbacks, "created_at": a.created_at,
            })
        AGENTS_FILE.write_text(json.dumps(data, indent=2))

    def _save_games(self):
        GAMES_FILE.write_text(json.dumps(self.finished_games, indent=2))

    # -- Agent registration --

    def register_agent(self, name: str, description: str = "") -> dict:
        with self.lock:
            for a in self.agents.values():
                if a.name.lower() == name.lower():
                    return {"error": f"Agent name '{name}' already taken"}

            agent_id = str(uuid.uuid4())[:8]
            token = f"arena_{secrets.token_urlsafe(32)}"
            agent = RegisteredAgent(
                agent_id=agent_id,
                name=name,
                description=description,
                token=token,
                created_at=time.time(),
            )
            self.agents[agent_id] = agent
            self.tokens[token] = agent_id
            self._save_agents()

            log.info("Registered agent: %s (%s)", name, agent_id)
            return {
                "agent_id": agent_id,
                "name": name,
                "token": token,
                "message": "Save your token! You'll need it to authenticate API calls.",
            }

    def authenticate(self, token: str) -> Optional[str]:
        return self.tokens.get(token)

    def get_agent(self, agent_id: str) -> Optional[RegisteredAgent]:
        return self.agents.get(agent_id)

    def get_leaderboard(self) -> list[dict]:
        agents = sorted(
            self.agents.values(),
            key=lambda a: (-a.elo, -a.wins, a.name),
        )
        return [
            {**a.to_public(), "rank": i + 1}
            for i, a in enumerate(agents)
        ]

    # -- Matchmaking --

    def join_queue(self, agent_id: str) -> dict:
        with self.lock:
            for g in self.games.values():
                if g.status == "active" and agent_id in (g.white_id, g.black_id):
                    return {"status": "already_in_game", "game_id": g.game_id}

            if agent_id in self.queue:
                return {"status": "already_queued", "position": self.queue.index(agent_id) + 1}

            self.queue.append(agent_id)
            pos = len(self.queue)
            log.info("Agent %s joined queue (position %d)", agent_id, pos)

            if len(self.queue) >= 2:
                return self._create_match()

            return {"status": "queued", "position": pos, "message": "Waiting for opponent..."}

    def leave_queue(self, agent_id: str) -> dict:
        with self.lock:
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

    def _create_match(self) -> dict:
        """Create a game from the first two agents in queue. Must hold lock."""
        a_id = self.queue.pop(0)
        b_id = self.queue.pop(0)
        a = self.agents[a_id]
        b = self.agents[b_id]

        import random
        if random.random() < 0.5:
            a_id, b_id = b_id, a_id
            a, b = b, a

        game_id = str(uuid.uuid4())[:8]
        game = LiveGame(
            game_id=game_id,
            white_id=a_id,
            black_id=b_id,
            white_name=a.name,
            black_name=b.name,
            board=chess.Board(),
            created_at=time.time(),
            turn_deadline=time.time() + 120.0,
        )
        self.games[game_id] = game

        log.info("Match created: %s vs %s (game %s)", a.name, b.name, game_id)

        self._broadcast({
            "type": "game_start",
            "game_id": game_id,
            "white": {"agent_id": a_id, "name": a.name},
            "black": {"agent_id": b_id, "name": b.name},
        })

        return {
            "status": "matched",
            "game_id": game_id,
            "white": {"agent_id": a_id, "name": a.name},
            "black": {"agent_id": b_id, "name": b.name},
            "your_side": "white" if a_id == a_id else "black",
        }

    # -- Game play --

    def get_game_state(self, game_id: str, agent_id: str) -> Optional[dict]:
        game = self.games.get(game_id)
        if not game:
            for fg in self.finished_games:
                if fg.get("game_id") == game_id:
                    return fg
            return None
        return game.to_state(agent_id)

    def get_game_public(self, game_id: str) -> Optional[dict]:
        game = self.games.get(game_id)
        if game:
            return game.to_public()
        for fg in self.finished_games:
            if fg.get("game_id") == game_id:
                return fg
        return None

    def use_tool(self, game_id: str, agent_id: str, tool_name: str, args: dict) -> dict:
        with self.lock:
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
            result = execute_tool(game.board, tool_name, args)
            result["_budget"] = f"{game.tool_calls_remaining} tool calls remaining"
            return result

    def make_move(self, game_id: str, agent_id: str, uci: str) -> dict:
        with self.lock:
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
                    return {"error": f"Invalid move format: '{uci}'", "legal_moves": [m.uci() for m in game.board.legal_moves]}

            if move not in game.board.legal_moves:
                return {"error": f"Illegal move: '{uci}'", "legal_moves": [m.uci() for m in game.board.legal_moves]}

            side = game.current_side()
            agent_name = game.white_name if side == "white" else game.black_name
            san = game.board.san(move)
            game.board.push(move)

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

            game.tool_calls_remaining = game.max_tool_calls
            game.turn_deadline = time.time() + game.move_timeout

            self._broadcast({
                "type": "move",
                "game_id": game_id,
                "ply": move_record["ply"],
                "side": side,
                "agent": agent_name,
                "uci": move.uci(),
                "san": san,
                "fen": game.board.fen(),
                "fallback": False,
            })

            if game.board.is_game_over() or len(game.moves) >= 300:
                return self._finish_game(game)

            return {
                "status": "ok",
                "move": san,
                "fen": game.board.fen(),
                "game_status": "active",
            }

    def _apply_timeout_move(self, game: LiveGame):
        """Apply a random move for timeout. Must hold lock."""
        legal = list(game.board.legal_moves)
        if not legal:
            return

        import random
        move = random.choice(legal)
        side = game.current_side()
        agent_id = game.current_agent_id()
        agent = self.agents.get(agent_id)
        agent_name = agent.name if agent else "Unknown"
        san = game.board.san(move)
        game.board.push(move)

        if side == "white":
            game.white_fallbacks += 1
        else:
            game.black_fallbacks += 1

        if agent:
            agent.fallbacks += 1

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
        game.tool_calls_remaining = game.max_tool_calls
        game.turn_deadline = time.time() + game.move_timeout

        self._broadcast({
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

        if game.board.is_game_over() or len(game.moves) >= 300:
            self._finish_game(game)

    def _finish_game(self, game: LiveGame) -> dict:
        """Finish a game and update ratings. Must hold lock."""
        board = game.board

        if board.is_checkmate():
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
            self._save_agents()

        game_record = {
            "game_id": game.game_id,
            "white": {"agent_id": game.white_id, "name": game.white_name},
            "black": {"agent_id": game.black_id, "name": game.black_name},
            "result": result,
            "reason": reason,
            "total_moves": len(game.moves),
            "white_fallbacks": game.white_fallbacks,
            "black_fallbacks": game.black_fallbacks,
            "moves": [
                {"san": m["san"], "uci": m["uci"], "side": m["side"],
                 "agent": m["agent"], "fallback": m.get("fallback", False), "fen": m["fen"]}
                for m in game.moves
            ],
        }
        self.finished_games.append(game_record)
        self._save_games()

        self._broadcast({
            "type": "game_end",
            "game_id": game.game_id,
            "result": result,
            "reason": reason,
            "white": game.white_name,
            "black": game.black_name,
            "total_moves": len(game.moves),
        })

        del self.games[game.game_id]

        log.info("Game %s finished: %s (%s)", game.game_id, result, reason)

        return {
            "status": "finished",
            "result": result,
            "reason": reason,
            "fen": board.fen(),
        }

    # -- Timeout monitor --

    def _start_timeout_monitor(self):
        def _monitor():
            while self._running:
                time.sleep(5)
                with self.lock:
                    now = time.time()
                    for game in list(self.games.values()):
                        if game.status == "active" and now > game.turn_deadline:
                            self._apply_timeout_move(game)

        self._timeout_thread = threading.Thread(target=_monitor, daemon=True)
        self._timeout_thread.start()

    def shutdown(self):
        self._running = False

    # -- Game listing --

    def get_active_games(self) -> list[dict]:
        return [g.to_public() for g in self.games.values() if g.status == "active"]

    def get_finished_games(self) -> list[dict]:
        return list(reversed(self.finished_games[-50:]))

    def get_my_games(self, agent_id: str) -> list[dict]:
        active = [
            g.to_state(agent_id)
            for g in self.games.values()
            if g.status == "active" and agent_id in (g.white_id, g.black_id)
        ]
        return active

    def get_all_games_history(self) -> list[dict]:
        return self.finished_games
