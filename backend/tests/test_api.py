"""Tests for FastAPI endpoints."""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from database import Database
from arena import ArenaManager
from main import app, db as app_db, arena as app_arena


@pytest_asyncio.fixture
async def setup_app(tmp_path):
    """Swap the global db/arena for test-scoped instances."""
    import main
    from arena import RateLimiter

    test_db = Database(path=tmp_path / "test.db")
    await test_db.connect()

    test_arena = ArenaManager(test_db)
    await test_arena.initialize()
    test_arena.set_broadcast(main.broadcast_to_spectators)
    # Fresh rate limiter per test to avoid cross-test interference
    test_arena.rate_limiter = RateLimiter()

    # Monkey-patch the module-level globals
    original_db = main.db
    original_arena = main.arena
    main.db = test_db
    main.arena = test_arena

    yield test_db, test_arena

    await test_arena.shutdown()
    await test_db.close()
    main.db = original_db
    main.arena = original_arena


@pytest_asyncio.fixture
async def client(setup_app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

class TestPublicEndpoints:
    @pytest.mark.asyncio
    async def test_leaderboard_empty(self, client):
        r = await client.get("/api/leaderboard")
        assert r.status_code == 200
        assert r.json() == []

    @pytest.mark.asyncio
    async def test_standings_alias(self, client):
        r = await client.get("/api/standings")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_active_games_empty(self, client):
        r = await client.get("/api/games/active")
        assert r.status_code == 200
        assert r.json() == []

    @pytest.mark.asyncio
    async def test_finished_games_empty(self, client):
        r = await client.get("/api/games/finished")
        assert r.status_code == 200
        assert r.json() == []

    @pytest.mark.asyncio
    async def test_queue_status(self, client):
        r = await client.get("/api/queue/status")
        assert r.status_code == 200
        assert "queue_size" in r.json()

    @pytest.mark.asyncio
    async def test_tools_list(self, client):
        r = await client.get("/api/tools")
        assert r.status_code == 200
        tools = r.json()
        assert len(tools) > 0
        # make_move should be excluded
        assert all(t["name"] != "make_move" for t in tools)

    @pytest.mark.asyncio
    async def test_status(self, client):
        r = await client.get("/api/status")
        assert r.status_code == 200
        data = r.json()
        assert "active_games" in data
        assert "total_agents" in data

    @pytest.mark.asyncio
    async def test_agents_empty(self, client):
        r = await client.get("/api/agents")
        assert r.status_code == 200
        assert r.json() == []

    @pytest.mark.asyncio
    async def test_game_not_found(self, client):
        r = await client.get("/api/games/nonexistent")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestRegistrationEndpoint:
    @pytest.mark.asyncio
    async def test_register_success(self, client):
        r = await client.post("/api/agents/register", json={"name": "MyBot"})
        assert r.status_code == 200
        data = r.json()
        assert "token" in data
        assert "agent_id" in data

    @pytest.mark.asyncio
    async def test_register_short_name(self, client):
        r = await client.post("/api/agents/register", json={"name": "A"})
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_register_long_name(self, client):
        r = await client.post("/api/agents/register", json={"name": "A" * 31})
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_register_duplicate(self, client):
        await client.post("/api/agents/register", json={"name": "MyBot"})
        r = await client.post("/api/agents/register", json={"name": "MyBot"})
        assert r.status_code == 409


# ---------------------------------------------------------------------------
# Auth-required endpoints
# ---------------------------------------------------------------------------

class TestAuthEndpoints:
    @pytest.mark.asyncio
    async def test_no_auth_401(self, client):
        r = await client.post("/api/queue/join")
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_bad_token_401(self, client):
        r = await client.post("/api/queue/join",
                              headers={"Authorization": "Bearer bad_token"})
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_join_queue_with_auth(self, client):
        reg = await client.post("/api/agents/register", json={"name": "Bot1"})
        token = reg.json()["token"]
        r = await client.post("/api/queue/join",
                              headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_my_agent(self, client):
        reg = await client.post("/api/agents/register", json={"name": "Bot1"})
        token = reg.json()["token"]
        r = await client.get("/api/my/agent",
                             headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["name"] == "Bot1"

    @pytest.mark.asyncio
    async def test_my_games(self, client):
        reg = await client.post("/api/agents/register", json={"name": "Bot1"})
        token = reg.json()["token"]
        r = await client.get("/api/my/games",
                             headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json() == []


# ---------------------------------------------------------------------------
# Game flow through API
# ---------------------------------------------------------------------------

class TestGameFlowAPI:
    @pytest.mark.asyncio
    async def test_full_game_flow(self, client):
        # Register two agents
        r1 = await client.post("/api/agents/register", json={"name": "White"})
        r2 = await client.post("/api/agents/register", json={"name": "Black"})
        t1 = r1.json()["token"]
        t2 = r2.json()["token"]

        # Both join queue
        await client.post("/api/queue/join",
                          headers={"Authorization": f"Bearer {t1}"})
        match = await client.post("/api/queue/join",
                                  headers={"Authorization": f"Bearer {t2}"})
        assert match.status_code == 200
        game_id = match.json()["game_id"]

        # Verify game appears in active
        active = await client.get("/api/games/active")
        assert any(g["game_id"] == game_id for g in active.json())

        # Get game details
        game = await client.get(f"/api/games/{game_id}")
        assert game.status_code == 200

    @pytest.mark.asyncio
    async def test_submit_move(self, client, setup_app):
        _, test_arena = setup_app
        r1 = await client.post("/api/agents/register", json={"name": "WhiteBot"})
        assert r1.status_code == 200, f"Registration failed: {r1.json()}"
        r2 = await client.post("/api/agents/register", json={"name": "BlackBot"})
        assert r2.status_code == 200, f"Registration failed: {r2.json()}"
        t1 = r1.json()["token"]
        t2 = r2.json()["token"]

        await client.post("/api/queue/join",
                          headers={"Authorization": f"Bearer {t1}"})
        match = await client.post("/api/queue/join",
                                  headers={"Authorization": f"Bearer {t2}"})
        game_id = match.json()["game_id"]

        # Determine which token is white
        game = test_arena.games[game_id]
        white_token = t1 if r1.json()["agent_id"] == game.white_id else t2

        # Submit a move
        r = await client.post(
            f"/api/games/{game_id}/move",
            json={"uci": "e2e4"},
            headers={"Authorization": f"Bearer {white_token}"},
        )
        assert r.status_code == 200
        assert r.json()["move"] == "e4"

    @pytest.mark.asyncio
    async def test_use_tool_endpoint(self, client, setup_app):
        _, test_arena = setup_app

        r1 = await client.post("/api/agents/register", json={"name": "W2"})
        r2 = await client.post("/api/agents/register", json={"name": "B2"})
        t1 = r1.json()["token"]
        t2 = r2.json()["token"]

        await client.post("/api/queue/join",
                          headers={"Authorization": f"Bearer {t1}"})
        match = await client.post("/api/queue/join",
                                  headers={"Authorization": f"Bearer {t2}"})
        game_id = match.json()["game_id"]

        game = test_arena.games[game_id]
        white_token = t1 if r1.json()["agent_id"] == game.white_id else t2

        r = await client.post(
            f"/api/games/{game_id}/tool",
            json={"tool": "count_material", "args": {"side": "white"}},
            headers={"Authorization": f"Bearer {white_token}"},
        )
        assert r.status_code == 200
        assert "total_points" in r.json()

    @pytest.mark.asyncio
    async def test_make_move_via_tool_blocked(self, client, setup_app):
        _, test_arena = setup_app

        r1 = await client.post("/api/agents/register", json={"name": "W3"})
        r2 = await client.post("/api/agents/register", json={"name": "B3"})
        t1 = r1.json()["token"]
        t2 = r2.json()["token"]

        await client.post("/api/queue/join",
                          headers={"Authorization": f"Bearer {t1}"})
        match = await client.post("/api/queue/join",
                                  headers={"Authorization": f"Bearer {t2}"})
        game_id = match.json()["game_id"]

        game = test_arena.games[game_id]
        white_token = t1 if r1.json()["agent_id"] == game.white_id else t2

        r = await client.post(
            f"/api/games/{game_id}/tool",
            json={"tool": "make_move", "args": {"uci": "e2e4"}},
            headers={"Authorization": f"Bearer {white_token}"},
        )
        assert r.status_code == 400
