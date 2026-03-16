"""Tests for SQLite persistence layer."""

import asyncio
import json
import time
from pathlib import Path

import pytest
import pytest_asyncio

from database import Database, hash_token


class TestHashToken:
    def test_deterministic(self):
        assert hash_token("abc") == hash_token("abc")

    def test_different_inputs(self):
        assert hash_token("abc") != hash_token("def")

    def test_returns_hex_string(self):
        h = hash_token("test")
        assert len(h) == 64  # SHA-256 hex digest


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_arena.db"


@pytest_asyncio.fixture
async def db(db_path):
    database = Database(path=db_path)
    await database.connect()
    yield database
    await database.close()


class TestDatabaseConnection:
    @pytest.mark.asyncio
    async def test_connect_creates_tables(self, db):
        cursor = await db.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in await cursor.fetchall()]
        assert "agents" in tables
        assert "games" in tables

    @pytest.mark.asyncio
    async def test_wal_mode_enabled(self, db):
        cursor = await db.db.execute("PRAGMA journal_mode")
        row = await cursor.fetchone()
        assert row[0] == "wal"


class TestAgentCRUD:
    @pytest.mark.asyncio
    async def test_insert_and_get_agent(self, db):
        await db.insert_agent("a1", "TestBot", "A test bot", "hash123", time.time())
        agent = await db.get_agent("a1")
        assert agent is not None
        assert agent["name"] == "TestBot"
        assert agent["description"] == "A test bot"
        assert agent["elo"] == 1200.0

    @pytest.mark.asyncio
    async def test_get_agent_by_name(self, db):
        await db.insert_agent("a1", "TestBot", "", "hash123", time.time())
        agent = await db.get_agent_by_name("testbot")  # case insensitive
        assert agent is not None
        assert agent["agent_id"] == "a1"

    @pytest.mark.asyncio
    async def test_get_agent_by_name_not_found(self, db):
        agent = await db.get_agent_by_name("nonexistent")
        assert agent is None

    @pytest.mark.asyncio
    async def test_get_agent_by_token_hash(self, db):
        await db.insert_agent("a1", "TestBot", "", "myhash", time.time())
        agent = await db.get_agent_by_token_hash("myhash")
        assert agent is not None
        assert agent["agent_id"] == "a1"

    @pytest.mark.asyncio
    async def test_get_all_agents_ordered(self, db):
        await db.insert_agent("a1", "LowBot", "", "h1", time.time())
        await db.insert_agent("a2", "HighBot", "", "h2", time.time())
        await db.update_agent_stats("a2", 1500.0, 5, 4, 0, 1, 0)
        agents = await db.get_all_agents()
        assert agents[0]["agent_id"] == "a2"  # higher ELO first

    @pytest.mark.asyncio
    async def test_update_agent_stats(self, db):
        await db.insert_agent("a1", "Bot", "", "h1", time.time())
        await db.update_agent_stats("a1", 1300.0, 10, 7, 1, 2, 3)
        agent = await db.get_agent("a1")
        assert agent["elo"] == 1300.0
        assert agent["games_played"] == 10
        assert agent["wins"] == 7
        assert agent["fallbacks"] == 3

    @pytest.mark.asyncio
    async def test_unique_name_constraint(self, db):
        await db.insert_agent("a1", "Bot", "", "h1", time.time())
        with pytest.raises(Exception):
            await db.insert_agent("a2", "Bot", "", "h2", time.time())


class TestGameCRUD:
    @pytest.mark.asyncio
    async def test_insert_and_get_game(self, db):
        await db.insert_agent("w1", "White", "", "h1", time.time())
        await db.insert_agent("b1", "Black", "", "h2", time.time())
        now = time.time()
        await db.insert_game("g1", "w1", "b1", "White", "Black",
                             chess_start_fen(), now + 120, now)
        game = await db.get_game("g1")
        assert game is not None
        assert game["white_id"] == "w1"
        assert game["status"] == "active"

    @pytest.mark.asyncio
    async def test_get_active_games(self, db):
        await db.insert_agent("w1", "White", "", "h1", time.time())
        await db.insert_agent("b1", "Black", "", "h2", time.time())
        now = time.time()
        await db.insert_game("g1", "w1", "b1", "White", "Black",
                             chess_start_fen(), now + 120, now)
        active = await db.get_active_games()
        assert len(active) == 1
        assert active[0]["game_id"] == "g1"

    @pytest.mark.asyncio
    async def test_update_game_move(self, db):
        await db.insert_agent("w1", "White", "", "h1", time.time())
        await db.insert_agent("b1", "Black", "", "h2", time.time())
        now = time.time()
        await db.insert_game("g1", "w1", "b1", "White", "Black",
                             chess_start_fen(), now + 120, now)
        new_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        moves = json.dumps([{"san": "e4", "uci": "e2e4", "side": "white"}])
        await db.update_game_move("g1", new_fen, moves, 9, now + 240, 0, 0, 0, 0)
        game = await db.get_game("g1")
        assert game["fen"] == new_fen
        assert game["tool_calls_remaining"] == 9

    @pytest.mark.asyncio
    async def test_finish_game(self, db):
        await db.insert_agent("w1", "White", "", "h1", time.time())
        await db.insert_agent("b1", "Black", "", "h2", time.time())
        now = time.time()
        await db.insert_game("g1", "w1", "b1", "White", "Black",
                             chess_start_fen(), now + 120, now)
        await db.finish_game("g1", "1-0", "checkmate", "some_fen", "[]", 0, 0)
        game = await db.get_game("g1")
        assert game["status"] == "finished"
        assert game["result"] == "1-0"
        assert game["finished_at"] is not None

    @pytest.mark.asyncio
    async def test_get_finished_games(self, db):
        await db.insert_agent("w1", "White", "", "h1", time.time())
        await db.insert_agent("b1", "Black", "", "h2", time.time())
        now = time.time()
        await db.insert_game("g1", "w1", "b1", "White", "Black",
                             chess_start_fen(), now + 120, now)
        await db.finish_game("g1", "1-0", "checkmate", "fen", "[]", 0, 0)
        finished = await db.get_finished_games()
        assert len(finished) == 1

    @pytest.mark.asyncio
    async def test_count_finished_games(self, db):
        await db.insert_agent("w1", "White", "", "h1", time.time())
        await db.insert_agent("b1", "Black", "", "h2", time.time())
        now = time.time()
        await db.insert_game("g1", "w1", "b1", "White", "Black",
                             chess_start_fen(), now + 120, now)
        assert await db.count_finished_games() == 0
        await db.finish_game("g1", "1-0", "checkmate", "fen", "[]", 0, 0)
        assert await db.count_finished_games() == 1


class TestTransaction:
    @pytest.mark.asyncio
    async def test_transaction_commits_atomically(self, db):
        await db.insert_agent("a1", "Bot1", "", "h1", time.time())
        await db.insert_agent("a2", "Bot2", "", "h2", time.time())

        async with db.transaction():
            await db.update_agent_stats("a1", 1300.0, 1, 1, 0, 0, 0, _commit=False)
            await db.update_agent_stats("a2", 1100.0, 1, 0, 0, 1, 0, _commit=False)

        a1 = await db.get_agent("a1")
        a2 = await db.get_agent("a2")
        assert a1["elo"] == 1300.0
        assert a2["elo"] == 1100.0

    @pytest.mark.asyncio
    async def test_transaction_rolls_back_on_error(self, db):
        await db.insert_agent("a1", "Bot1", "", "h1", time.time())

        with pytest.raises(ValueError):
            async with db.transaction():
                await db.update_agent_stats("a1", 9999.0, 1, 1, 0, 0, 0, _commit=False)
                raise ValueError("Simulated failure")

        a1 = await db.get_agent("a1")
        assert a1["elo"] == 1200.0  # Should not have changed


def chess_start_fen():
    return "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
