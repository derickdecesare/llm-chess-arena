"""SQLite persistence layer for LLM Chess Arena.

Uses aiosqlite for non-blocking access within FastAPI's async model.
WAL mode ensures crash safety — committed transactions survive unexpected restarts.
"""

import aiosqlite
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "arena.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    agent_id     TEXT PRIMARY KEY,
    name         TEXT UNIQUE NOT NULL,
    description  TEXT DEFAULT '',
    token_hash   TEXT NOT NULL,
    elo          REAL DEFAULT 1200.0,
    games_played INTEGER DEFAULT 0,
    wins         INTEGER DEFAULT 0,
    draws        INTEGER DEFAULT 0,
    losses       INTEGER DEFAULT 0,
    fallbacks    INTEGER DEFAULT 0,
    created_at   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS games (
    game_id            TEXT PRIMARY KEY,
    white_id           TEXT NOT NULL REFERENCES agents(agent_id),
    black_id           TEXT NOT NULL REFERENCES agents(agent_id),
    white_name         TEXT NOT NULL,
    black_name         TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'active',
    result             TEXT,
    reason             TEXT,
    fen                TEXT NOT NULL DEFAULT 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
    moves_json         TEXT DEFAULT '[]',
    tool_calls_remaining INTEGER DEFAULT 10,
    turn_deadline      REAL DEFAULT 0.0,
    white_fallbacks    INTEGER DEFAULT 0,
    black_fallbacks    INTEGER DEFAULT 0,
    white_consecutive_timeouts INTEGER DEFAULT 0,
    black_consecutive_timeouts INTEGER DEFAULT 0,
    created_at         REAL NOT NULL,
    finished_at        REAL
);
"""


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Database:
    def __init__(self, path: Optional[Path] = None):
        self.path = str(path or DB_PATH)
        self.db: Optional[aiosqlite.Connection] = None

    async def connect(self):
        self.db = await aiosqlite.connect(self.path)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.execute("PRAGMA foreign_keys=ON")
        await self.db.execute("PRAGMA busy_timeout=5000")
        for statement in SCHEMA.strip().split(";"):
            stmt = statement.strip()
            if stmt:
                await self.db.execute(stmt)
        await self.db.commit()
        log.info("Database connected: %s", self.path)

    async def close(self):
        if self.db:
            await self.db.close()
            log.info("Database closed")

    # -- Agents --

    async def insert_agent(self, agent_id: str, name: str, description: str,
                           token_hash: str, created_at: float):
        await self.db.execute(
            "INSERT INTO agents (agent_id, name, description, token_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (agent_id, name, description, token_hash, created_at),
        )
        await self.db.commit()

    async def get_agent_by_token_hash(self, token_hash: str) -> Optional[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM agents WHERE token_hash = ?", (token_hash,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_agent(self, agent_id: str) -> Optional[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM agents WHERE agent_id = ?", (agent_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_agent_by_name(self, name: str) -> Optional[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM agents WHERE LOWER(name) = LOWER(?)", (name,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_all_agents(self) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM agents ORDER BY elo DESC, wins DESC, name ASC"
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def update_agent_stats(self, agent_id: str, elo: float,
                                 games_played: int, wins: int, draws: int,
                                 losses: int, fallbacks: int):
        await self.db.execute(
            "UPDATE agents SET elo=?, games_played=?, wins=?, draws=?, "
            "losses=?, fallbacks=? WHERE agent_id=?",
            (elo, games_played, wins, draws, losses, fallbacks, agent_id),
        )
        await self.db.commit()

    # -- Games --

    async def insert_game(self, game_id: str, white_id: str, black_id: str,
                          white_name: str, black_name: str, fen: str,
                          turn_deadline: float, created_at: float):
        await self.db.execute(
            "INSERT INTO games (game_id, white_id, black_id, white_name, "
            "black_name, fen, turn_deadline, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (game_id, white_id, black_id, white_name, black_name, fen,
             turn_deadline, created_at),
        )
        await self.db.commit()

    async def update_game_move(self, game_id: str, fen: str, moves_json: str,
                               tool_calls_remaining: int, turn_deadline: float,
                               white_fallbacks: int, black_fallbacks: int,
                               white_consecutive_timeouts: int,
                               black_consecutive_timeouts: int):
        await self.db.execute(
            "UPDATE games SET fen=?, moves_json=?, tool_calls_remaining=?, "
            "turn_deadline=?, white_fallbacks=?, black_fallbacks=?, "
            "white_consecutive_timeouts=?, black_consecutive_timeouts=? "
            "WHERE game_id=?",
            (fen, moves_json, tool_calls_remaining, turn_deadline,
             white_fallbacks, black_fallbacks,
             white_consecutive_timeouts, black_consecutive_timeouts, game_id),
        )
        await self.db.commit()

    async def finish_game(self, game_id: str, result: str, reason: str,
                          fen: str, moves_json: str,
                          white_fallbacks: int, black_fallbacks: int):
        await self.db.execute(
            "UPDATE games SET status='finished', result=?, reason=?, fen=?, "
            "moves_json=?, white_fallbacks=?, black_fallbacks=?, "
            "finished_at=? WHERE game_id=?",
            (result, reason, fen, moves_json, white_fallbacks, black_fallbacks,
             time.time(), game_id),
        )
        await self.db.commit()

    async def get_active_games(self) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM games WHERE status = 'active' ORDER BY created_at ASC"
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_finished_games(self, limit: int = 50) -> list[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM games WHERE status = 'finished' "
            "ORDER BY finished_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in await cursor.fetchall()]

    async def get_game(self, game_id: str) -> Optional[dict]:
        cursor = await self.db.execute(
            "SELECT * FROM games WHERE game_id = ?", (game_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def count_finished_games(self) -> int:
        cursor = await self.db.execute(
            "SELECT COUNT(*) as cnt FROM games WHERE status = 'finished'"
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0
