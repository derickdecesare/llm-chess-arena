"""Tests for ArenaManager — registration, matchmaking, game play, ELO."""

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock

import chess
import pytest
import pytest_asyncio

from arena import ArenaManager, RegisteredAgent, LiveGame, RateLimiter, _elo_update, MAX_TOOL_CALLS
from database import Database, hash_token


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(path=tmp_path / "test.db")
    await database.connect()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def arena(db):
    mgr = ArenaManager(db)
    await mgr.initialize()
    mgr.set_broadcast(AsyncMock())
    yield mgr
    await mgr.shutdown()


# ---------------------------------------------------------------------------
# ELO
# ---------------------------------------------------------------------------

class TestElo:
    def test_winner_gains_elo(self):
        new_a, new_b = _elo_update(1200, 1200, 1.0)
        assert new_a > 1200
        assert new_b < 1200

    def test_draw_equal_rating_no_change(self):
        new_a, new_b = _elo_update(1200, 1200, 0.5)
        assert abs(new_a - 1200) < 0.01
        assert abs(new_b - 1200) < 0.01

    def test_upset_larger_shift(self):
        # Weaker player beating stronger player should cause a bigger shift
        new_a, _ = _elo_update(1000, 1400, 1.0)
        shift_upset = new_a - 1000
        new_c, _ = _elo_update(1400, 1000, 1.0)
        shift_expected = new_c - 1400
        assert shift_upset > shift_expected

    def test_sum_preserved(self):
        new_a, new_b = _elo_update(1200, 1300, 1.0)
        assert abs((new_a + new_b) - (1200 + 1300)) < 0.01


# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------

class TestRateLimiter:
    def test_allows_within_limit(self):
        rl = RateLimiter()
        for _ in range(5):
            assert rl.check("key", 5, 60) is True

    def test_blocks_over_limit(self):
        rl = RateLimiter()
        for _ in range(5):
            rl.check("key", 5, 60)
        assert rl.check("key", 5, 60) is False

    def test_different_keys_independent(self):
        rl = RateLimiter()
        for _ in range(5):
            rl.check("a", 5, 60)
        assert rl.check("a", 5, 60) is False
        assert rl.check("b", 5, 60) is True


# ---------------------------------------------------------------------------
# Agent Registration
# ---------------------------------------------------------------------------

class TestRegistration:
    @pytest.mark.asyncio
    async def test_register_agent(self, arena):
        result = await arena.register_agent("TestBot", "A bot")
        assert "agent_id" in result
        assert "token" in result
        assert result["token"].startswith("arena_")
        assert result["name"] == "TestBot"

    @pytest.mark.asyncio
    async def test_duplicate_name_rejected(self, arena):
        await arena.register_agent("TestBot")
        result = await arena.register_agent("TestBot")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_authenticate_valid(self, arena):
        result = await arena.register_agent("TestBot")
        agent_id = arena.authenticate(result["token"])
        assert agent_id == result["agent_id"]

    @pytest.mark.asyncio
    async def test_authenticate_invalid(self, arena):
        assert arena.authenticate("bad_token") is None

    @pytest.mark.asyncio
    async def test_get_leaderboard(self, arena):
        await arena.register_agent("Bot1")
        await arena.register_agent("Bot2")
        lb = arena.get_leaderboard()
        assert len(lb) == 2
        assert lb[0]["rank"] == 1


# ---------------------------------------------------------------------------
# Matchmaking
# ---------------------------------------------------------------------------

class TestMatchmaking:
    @pytest.mark.asyncio
    async def test_first_agent_queues(self, arena):
        r = await arena.register_agent("Bot1")
        result = await arena.join_queue(r["agent_id"])
        assert result["status"] == "queued"

    @pytest.mark.asyncio
    async def test_second_agent_matches(self, arena):
        r1 = await arena.register_agent("Bot1")
        r2 = await arena.register_agent("Bot2")
        await arena.join_queue(r1["agent_id"])
        result = await arena.join_queue(r2["agent_id"])
        assert result["status"] == "matched"
        assert "game_id" in result

    @pytest.mark.asyncio
    async def test_already_in_game(self, arena):
        r1 = await arena.register_agent("Bot1")
        r2 = await arena.register_agent("Bot2")
        await arena.join_queue(r1["agent_id"])
        await arena.join_queue(r2["agent_id"])
        result = await arena.join_queue(r1["agent_id"])
        assert result["status"] == "already_in_game"

    @pytest.mark.asyncio
    async def test_leave_queue(self, arena):
        r1 = await arena.register_agent("Bot1")
        await arena.join_queue(r1["agent_id"])
        result = await arena.leave_queue(r1["agent_id"])
        assert result["status"] == "left_queue"

    @pytest.mark.asyncio
    async def test_leave_queue_not_in(self, arena):
        r1 = await arena.register_agent("Bot1")
        result = await arena.leave_queue(r1["agent_id"])
        assert result["status"] == "not_in_queue"

    @pytest.mark.asyncio
    async def test_queue_status(self, arena):
        r1 = await arena.register_agent("Bot1")
        await arena.join_queue(r1["agent_id"])
        status = arena.get_queue_status()
        assert status["queue_size"] == 0 or status["queue_size"] == 1


# ---------------------------------------------------------------------------
# Game Play
# ---------------------------------------------------------------------------

async def _create_game(arena):
    """Helper to register two bots and get a matched game."""
    r1 = await arena.register_agent("White")
    r2 = await arena.register_agent("Black")
    await arena.join_queue(r1["agent_id"])
    match = await arena.join_queue(r2["agent_id"])
    game_id = match["game_id"]
    game = arena.games[game_id]
    return game, r1, r2


class TestGamePlay:
    @pytest.mark.asyncio
    async def test_make_valid_move(self, arena):
        game, r1, r2 = await _create_game(arena)
        # Figure out who is white
        white_token = r1["token"] if r1["agent_id"] == game.white_id else r2["token"]
        white_id = game.white_id
        result = await arena.make_move(game.game_id, white_id, "e2e4")
        assert result["status"] == "ok"
        assert result["move"] == "e4"

    @pytest.mark.asyncio
    async def test_wrong_turn_rejected(self, arena):
        game, r1, r2 = await _create_game(arena)
        black_id = game.black_id
        result = await arena.make_move(game.game_id, black_id, "e7e5")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_illegal_move_rejected(self, arena):
        game, r1, r2 = await _create_game(arena)
        white_id = game.white_id
        result = await arena.make_move(game.game_id, white_id, "e2e5")
        assert "error" in result
        assert "legal_moves" in result

    @pytest.mark.asyncio
    async def test_invalid_format_rejected(self, arena):
        game, r1, r2 = await _create_game(arena)
        white_id = game.white_id
        result = await arena.make_move(game.game_id, white_id, "xyz")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_game_not_found(self, arena):
        result = await arena.make_move("nonexistent", "agent1", "e2e4")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_move_resets_tool_budget(self, arena):
        game, r1, r2 = await _create_game(arena)
        white_id = game.white_id
        # Use a tool call
        arena.use_tool(game.game_id, white_id, "get_all_legal_moves", {})
        assert game.tool_calls_remaining == MAX_TOOL_CALLS - 1
        # Make a move — should reset
        await arena.make_move(game.game_id, white_id, "e2e4")
        assert game.tool_calls_remaining == MAX_TOOL_CALLS


# ---------------------------------------------------------------------------
# Tools via Arena
# ---------------------------------------------------------------------------

class TestUseTool:
    @pytest.mark.asyncio
    async def test_use_tool_success(self, arena):
        game, r1, r2 = await _create_game(arena)
        white_id = game.white_id
        result = arena.use_tool(game.game_id, white_id, "count_material", {"side": "white"})
        assert "total_points" in result

    @pytest.mark.asyncio
    async def test_tool_budget_enforced(self, arena):
        game, r1, r2 = await _create_game(arena)
        white_id = game.white_id
        game.tool_calls_remaining = 0
        result = arena.use_tool(game.game_id, white_id, "count_material", {"side": "white"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_tool_wrong_turn(self, arena):
        game, r1, r2 = await _create_game(arena)
        black_id = game.black_id
        result = arena.use_tool(game.game_id, black_id, "count_material", {"side": "white"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_make_move_tool_blocked(self, arena):
        game, r1, r2 = await _create_game(arena)
        white_id = game.white_id
        result = arena.use_tool(game.game_id, white_id, "make_move", {"uci": "e2e4"})
        assert "error" in result


# ---------------------------------------------------------------------------
# Game State Queries
# ---------------------------------------------------------------------------

class TestGameQueries:
    @pytest.mark.asyncio
    async def test_get_active_games(self, arena):
        game, r1, r2 = await _create_game(arena)
        active = arena.get_active_games()
        assert len(active) == 1

    @pytest.mark.asyncio
    async def test_get_my_games(self, arena):
        game, r1, r2 = await _create_game(arena)
        my = arena.get_my_games(game.white_id)
        assert len(my) == 1
        assert my[0]["game_id"] == game.game_id

    @pytest.mark.asyncio
    async def test_get_game_state(self, arena):
        game, r1, r2 = await _create_game(arena)
        state = arena.get_game_state(game.game_id, game.white_id)
        assert state["your_side"] == "white"
        assert state["is_your_turn"] is True
        assert "legal_moves" in state

    @pytest.mark.asyncio
    async def test_get_game_public(self, arena):
        game, r1, r2 = await _create_game(arena)
        pub = arena.get_game_public(game.game_id)
        assert pub["white"]["name"] in ("White", "Black")


# ---------------------------------------------------------------------------
# Finish Game & ELO
# ---------------------------------------------------------------------------

class TestFinishGame:
    @pytest.mark.asyncio
    async def test_checkmate_finishes_game(self, arena):
        game, r1, r2 = await _create_game(arena)
        # Scholar's mate
        white_id = game.white_id
        black_id = game.black_id

        await arena.make_move(game.game_id, white_id, "e2e4")
        await arena.make_move(game.game_id, black_id, "e7e5")
        await arena.make_move(game.game_id, white_id, "f1c4")
        await arena.make_move(game.game_id, black_id, "b8c6")
        await arena.make_move(game.game_id, white_id, "d1h5")
        await arena.make_move(game.game_id, black_id, "g8f6")
        result = await arena.make_move(game.game_id, white_id, "h5f7")

        assert result["status"] == "finished"
        assert result["result"] == "1-0"
        assert result["reason"] == "checkmate"

    @pytest.mark.asyncio
    async def test_elo_updated_after_game(self, arena):
        game, r1, r2 = await _create_game(arena)
        white_id = game.white_id
        black_id = game.black_id

        white_elo_before = arena.agents[white_id].elo
        black_elo_before = arena.agents[black_id].elo

        # Scholar's mate
        await arena.make_move(game.game_id, white_id, "e2e4")
        await arena.make_move(game.game_id, black_id, "e7e5")
        await arena.make_move(game.game_id, white_id, "f1c4")
        await arena.make_move(game.game_id, black_id, "b8c6")
        await arena.make_move(game.game_id, white_id, "d1h5")
        await arena.make_move(game.game_id, black_id, "g8f6")
        await arena.make_move(game.game_id, white_id, "h5f7")

        assert arena.agents[white_id].elo > white_elo_before
        assert arena.agents[black_id].elo < black_elo_before

    @pytest.mark.asyncio
    async def test_finished_game_removed_from_active(self, arena):
        game, r1, r2 = await _create_game(arena)
        game_id = game.game_id
        white_id = game.white_id
        black_id = game.black_id

        await arena.make_move(game_id, white_id, "e2e4")
        await arena.make_move(game_id, black_id, "e7e5")
        await arena.make_move(game_id, white_id, "f1c4")
        await arena.make_move(game_id, black_id, "b8c6")
        await arena.make_move(game_id, white_id, "d1h5")
        await arena.make_move(game_id, black_id, "g8f6")
        await arena.make_move(game_id, white_id, "h5f7")

        assert game_id not in arena.games
        # But should be in DB
        finished = await arena.get_finished_games()
        assert any(g["game_id"] == game_id for g in finished)


# ---------------------------------------------------------------------------
# RegisteredAgent model
# ---------------------------------------------------------------------------

class TestRegisteredAgent:
    def test_to_public_excludes_token(self):
        agent = RegisteredAgent(
            agent_id="a1", name="Bot", description="test",
            token_hash="secret_hash", elo=1200,
        )
        pub = agent.to_public()
        assert "token_hash" not in pub
        assert pub["name"] == "Bot"

    def test_from_row(self):
        row = {
            "agent_id": "a1", "name": "Bot", "description": "",
            "token_hash": "h", "elo": 1300.0,
            "games_played": 5, "wins": 3, "draws": 1, "losses": 1,
            "fallbacks": 2, "created_at": 100.0,
        }
        agent = RegisteredAgent.from_row(row)
        assert agent.elo == 1300.0
        assert agent.wins == 3


# ---------------------------------------------------------------------------
# LiveGame model
# ---------------------------------------------------------------------------

class TestLiveGame:
    def test_current_side_white_first(self):
        game = LiveGame(
            game_id="g1", white_id="w", black_id="b",
            white_name="W", black_name="B", board=chess.Board(),
        )
        assert game.current_side() == "white"

    def test_to_public(self):
        game = LiveGame(
            game_id="g1", white_id="w", black_id="b",
            white_name="W", black_name="B", board=chess.Board(),
        )
        pub = game.to_public()
        assert pub["game_id"] == "g1"
        assert pub["turn"] == "white"
