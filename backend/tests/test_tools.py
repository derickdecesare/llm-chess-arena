"""Tests for chess analysis tools.

=== PYTEST CRASH COURSE ===

How pytest works:
1. You run `python -m pytest tests/` from the terminal
2. pytest automatically DISCOVERS test files (any file named test_*.py)
3. Inside those files, it finds test CLASSES (classes starting with "Test")
   and test FUNCTIONS (functions starting with "test_")
4. It runs each test function independently and reports pass/fail

The core concept is `assert`:
    assert <condition>
    - If the condition is True  → the test PASSES (nothing happens)
    - If the condition is False → the test FAILS (pytest raises an error)

    Examples:
        assert 1 + 1 == 2        # passes — 2 equals 2
        assert "hello" in "hello world"  # passes — substring found
        assert len([1, 2, 3]) == 3       # passes — list has 3 items

=== WHAT ARE WE TESTING HERE? ===

The "tools" in this project are chess analysis functions that AI agents
can call during a game to analyze the board. Think of them like helper
functions an agent can ask: "what piece is on e4?", "what are my legal
moves?", "what happens if I play this move?", etc.

Each tool is a pure function that takes:
    1. A chess.Board (the current game state)
    2. A dict of arguments (like {"square": "e4"})
And returns:
    A dict with the result (like {"piece": "white pawn"})

The pattern for every test is:
    1. SET UP the board state (create a chess.Board in a known position)
    2. CALL the tool function with specific arguments
    3. ASSERT that the result matches what we expect

This is called the "Arrange → Act → Assert" pattern.
"""

# --- Imports ---

# `chess` is the python-chess library. chess.Board() creates a chess board.
# By default it sets up the standard starting position.
import chess

# `pytest` is the testing framework. We import it but don't use it directly
# in most tests — pytest finds and runs our test functions automatically.
import pytest

# These are the actual functions/data we're testing, imported from our
# project's tools.py file:
#   - execute_tool: the main dispatcher — takes a board, tool name, and args,
#     then calls the right tool function and returns the result
#   - TOOL_DEFS: a list of dicts defining all available tools (name, description, params)
#   - get_anthropic_tools: converts TOOL_DEFS to Anthropic's API format
#   - get_openai_tools: converts TOOL_DEFS to OpenAI's API format
from tools import execute_tool, TOOL_DEFS, get_anthropic_tools, get_openai_tools


# =============================================================================
# TEST GROUP 1: Tool Definitions
#
# These tests don't test the tool LOGIC — they test that the tool METADATA
# (names, descriptions, parameter schemas) is properly structured.
# This matters because agents receive these definitions to know what
# tools are available.
# =============================================================================

class TestToolDefs:

    def test_tool_defs_not_empty(self):
        """Make sure we actually have tools defined (not an empty list)."""
        # len(TOOL_DEFS) returns how many tools are in the list.
        # We assert it's greater than 0 — i.e., at least one tool exists.
        assert len(TOOL_DEFS) > 0

    def test_all_tools_have_required_fields(self):
        """Every tool definition must have a name, description, and params."""
        # We loop through ALL tool definitions and check each one.
        # If ANY tool is missing a required field, the test fails.
        for t in TOOL_DEFS:
            # `"name" in t` checks if the dict `t` has a key called "name".
            # This is a Python dict membership check, not a string search.
            assert "name" in t
            assert "description" in t
            assert "params" in t

    def test_anthropic_format(self):
        """Anthropic's API expects tools in a specific format — verify it."""
        # get_anthropic_tools() converts our internal TOOL_DEFS into the
        # format that Anthropic's Claude API expects.
        tools = get_anthropic_tools()
        for t in tools:
            # Anthropic requires "name", "description", and "input_schema"
            assert "name" in t
            assert "description" in t
            assert "input_schema" in t  # Anthropic calls params "input_schema"

    def test_openai_format(self):
        """OpenAI's API expects a different format — verify that too."""
        tools = get_openai_tools()
        for t in tools:
            # OpenAI wraps everything in {"type": "function", "function": {...}}
            assert t["type"] == "function"
            assert "name" in t["function"]
            assert "parameters" in t["function"]  # OpenAI calls it "parameters"


# =============================================================================
# TEST GROUP 2: get_piece_at
#
# This tool answers: "What piece is on square X?"
# We test it with known positions where we know exactly what's there.
# =============================================================================

class TestGetPieceAt:

    def test_starting_position(self):
        """In the starting position, e1 should have the white king."""
        # chess.Board() creates a board in the standard starting position:
        #   Row 1: white pieces (Rook, Knight, Bishop, Queen, KING, Bishop, Knight, Rook)
        #   Row 2: white pawns
        #   Rows 3-6: empty
        #   Row 7: black pawns
        #   Row 8: black pieces
        board = chess.Board()

        # execute_tool is the main entry point. We pass:
        #   1. The board state
        #   2. The tool name as a string
        #   3. A dict of arguments (this tool needs a "square" argument)
        result = execute_tool(board, "get_piece_at", {"square": "e1"})

        # The tool returns a dict like {"square": "e1", "piece": "white king"}.
        # We check that the "piece" value is exactly "white king".
        # `==` checks for exact equality.
        assert result["piece"] == "white king"

    def test_empty_square(self):
        """e4 is empty at the start of the game."""
        board = chess.Board()
        result = execute_tool(board, "get_piece_at", {"square": "e4"})
        # When no piece is on the square, the tool returns "empty"
        assert result["piece"] == "empty"

    def test_black_piece(self):
        """e8 has the black king at the start."""
        board = chess.Board()
        result = execute_tool(board, "get_piece_at", {"square": "e8"})
        assert result["piece"] == "black king"

    def test_invalid_square(self):
        """Passing a nonsense square like 'z9' should return an error."""
        board = chess.Board()
        result = execute_tool(board, "get_piece_at", {"square": "z9"})
        # When a tool encounters bad input, it returns {"error": "..."}.
        # We check that the key "error" exists in the result dict.
        # This is an important pattern: we test that errors are handled
        # gracefully (returning an error dict) rather than crashing.
        assert "error" in result


# =============================================================================
# TEST GROUP 3: get_pieces
#
# This tool answers: "Where are all the [piece_type] for [side]?"
# For example: "Where are all the white pawns?"
# =============================================================================

class TestGetPieces:

    def test_white_pawns_starting(self):
        """White starts with 8 pawns (on a2 through h2)."""
        board = chess.Board()
        result = execute_tool(board, "get_pieces", {"side": "white", "piece_type": "pawn"})
        # The tool returns {"squares": ["a2", "b2", ...], ...}
        # len() counts how many squares were returned.
        # White starts with exactly 8 pawns.
        assert len(result["squares"]) == 8

    def test_white_knights_starting(self):
        """White knights start on b1 and g1."""
        board = chess.Board()
        result = execute_tool(board, "get_pieces", {"side": "white", "piece_type": "knight"})
        # set() converts a list to a set, which ignores order.
        # {"b1", "g1"} == {"g1", "b1"} → True (sets don't care about order)
        # ["b1", "g1"] == ["g1", "b1"] → False (lists DO care about order)
        # We use set() here because we don't care what order the squares
        # come back in — just that the right squares are returned.
        assert set(result["squares"]) == {"b1", "g1"}

    def test_invalid_piece_type(self):
        """Asking for a 'dragon' piece type should return an error."""
        board = chess.Board()
        result = execute_tool(board, "get_pieces", {"side": "white", "piece_type": "dragon"})
        # "dragon" isn't a real chess piece, so the tool should error
        assert "error" in result


# =============================================================================
# TEST GROUP 4: get_attacks
#
# This tool answers: "What squares does the piece on X attack/control?"
# =============================================================================

class TestGetAttacks:

    def test_knight_attacks(self):
        """The knight on b1 attacks a3 and c3 (its L-shaped moves)."""
        board = chess.Board()
        result = execute_tool(board, "get_attacks", {"square": "b1"})
        # The tool returns {"attacks": ["a3", "c3", ...], ...}
        # `"a3" in result["attacks"]` checks if "a3" is in that list.
        # A knight on b1 can jump to a3 and c3 (but d2 is blocked by
        # the pawn, though attacks still include it — attacked squares
        # are different from legal moves).
        assert "a3" in result["attacks"]
        assert "c3" in result["attacks"]

    def test_empty_square_error(self):
        """Asking for attacks from an empty square should error."""
        board = chess.Board()
        result = execute_tool(board, "get_attacks", {"square": "e4"})
        # e4 is empty at the start, so there's no piece to get attacks for
        assert "error" in result


# =============================================================================
# TEST GROUP 5: is_square_attacked
#
# This tool answers: "Is square X attacked by [side]?"
# =============================================================================

class TestIsSquareAttacked:

    def test_f7_not_attacked_by_white_initially(self):
        """At the start, white doesn't attack f7 (it's deep in black's territory)."""
        board = chess.Board()
        result = execute_tool(board, "is_square_attacked", {"square": "f7", "by_side": "white"})
        # `is False` is stricter than `== False`. It checks both value AND type.
        # This ensures the result is exactly the boolean False, not some other
        # falsy value like 0, None, or "".
        assert result["attacked"] is False

    def test_e2_attacked_by_white(self):
        """White's own pieces defend/attack e2 (king, queen, bishop, etc.)."""
        board = chess.Board()
        result = execute_tool(board, "is_square_attacked", {"square": "e2", "by_side": "white"})
        # In chess, "attacked by" includes your own pieces defending a square.
        # White's king on e1, queen on d1, and bishop on f1 all control e2.
        assert result["attacked"] is True


# =============================================================================
# TEST GROUP 6: get_legal_moves
#
# This tool answers: "What legal moves can the piece on X make?"
# =============================================================================

class TestGetLegalMoves:

    def test_e2_pawn_opening(self):
        """The e2 pawn can move to e3 (one square) or e4 (two squares)."""
        board = chess.Board()
        result = execute_tool(board, "get_legal_moves", {"square": "e2"})
        # The tool returns {"moves": [{"uci": "e2e4", "san": "e4", ...}, ...]}
        # We extract just the UCI strings into a list for easy checking.
        # UCI format = "from_square" + "to_square", e.g. "e2e4" means e2 → e4.
        ucis = [m["uci"] for m in result["moves"]]
        assert "e2e4" in ucis  # pawn can advance two squares from starting pos
        assert "e2e3" in ucis  # pawn can advance one square

    def test_no_piece_error(self):
        """Asking for legal moves on an empty square should error."""
        board = chess.Board()
        result = execute_tool(board, "get_legal_moves", {"square": "e4"})
        assert "error" in result


# =============================================================================
# TEST GROUP 7: get_all_legal_moves
#
# This tool answers: "What are ALL legal moves in this position?"
# No arguments needed — it just returns everything available.
# =============================================================================

class TestGetAllLegalMoves:

    def test_starting_position_has_20_moves(self):
        """The standard starting position has exactly 20 legal moves.

        That's: 16 pawn moves (each of 8 pawns can go 1 or 2 squares)
              +  4 knight moves (2 knights × 2 possible squares each)
              = 20 total
        (Other pieces are blocked by pawns and can't move yet.)
        """
        board = chess.Board()
        # We pass an empty dict {} because this tool takes no arguments
        result = execute_tool(board, "get_all_legal_moves", {})
        assert result["total"] == 20


# =============================================================================
# TEST GROUP 8: preview_move
#
# This tool answers: "What would the board look like if I played this move?"
# It's like a "what if" tool — it doesn't actually make the move,
# just shows what would happen.
# =============================================================================

class TestPreviewMove:

    def test_valid_move(self):
        """Previewing e2e4 should return the resulting position."""
        board = chess.Board()
        result = execute_tool(board, "preview_move", {"uci": "e2e4"})
        # A valid preview should include the resulting FEN (board state string)
        assert "resulting_fen" in result
        # Moving a pawn to e4 doesn't give check
        assert result["is_check"] is False

    def test_illegal_move(self):
        """Previewing an illegal move (e2 can't jump to e5) should error."""
        board = chess.Board()
        result = execute_tool(board, "preview_move", {"uci": "e2e5"})
        # e2e5 is illegal — a pawn can only move 1 or 2 squares forward
        assert "error" in result

    def test_invalid_uci(self):
        """Previewing gibberish like 'xyz' should error."""
        board = chess.Board()
        result = execute_tool(board, "preview_move", {"uci": "xyz"})
        assert "error" in result

    def test_custom_fen(self):
        """You can preview a move from a custom position (not just current).

        This lets agents chain previews: "if I play X, then they play Y,
        what does it look like?" by passing the resulting FEN from a
        previous preview.
        """
        board = chess.Board()
        # This FEN represents the position AFTER white played e2e4.
        # FEN (Forsyth-Edwards Notation) is a standard string format that
        # encodes an entire chess position in one line.
        fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        result = execute_tool(board, "preview_move", {"uci": "e7e5", "fen": fen})
        assert "resulting_fen" in result

    def test_capture_shows_captured(self):
        """When a move captures a piece, the result should say what was captured."""
        # Here we create a board from a specific FEN where white's e4 pawn
        # can capture black's d5 pawn. This is the position after:
        #   1. e4 d5 (the Scandinavian Defense opening)
        board = chess.Board("rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 2")
        result = execute_tool(board, "preview_move", {"uci": "e4d5"})
        # The tool should tell us we captured a pawn
        assert result["captured"] == "pawn"


# =============================================================================
# TEST GROUP 9: get_checks
#
# This tool answers: "What moves can I make that give check?"
# =============================================================================

class TestGetChecks:

    def test_no_checks_opening(self):
        """From the starting position, no moves give check
        (all pieces are blocked by pawns)."""
        board = chess.Board()
        result = execute_tool(board, "get_checks", {})
        assert result["total"] == 0

    def test_scholars_mate_check(self):
        """In a position where the queen and bishop are developed,
        there should be checking moves available.

        This FEN is the position after: 1. e4 e5 2. Bc4
        White's queen on d1 and bishop on c4 are both aiming at f7,
        so Qh5 (attacking f7) would give check.
        """
        board = chess.Board("rnbqkbnr/pppp1ppp/8/4p3/2B1P3/8/PPPP1PPP/RNBQK1NR w KQkq - 0 3")
        result = execute_tool(board, "get_checks", {})
        # There should be at least one checking move (like Qh5+)
        assert result["total"] > 0


# =============================================================================
# TEST GROUP 10: get_captures
#
# This tool answers: "What captures are available, and are they good trades?"
# =============================================================================

class TestGetCaptures:

    def test_no_captures_opening(self):
        """From the starting position, no captures are possible
        (no pieces are in contact with each other yet)."""
        board = chess.Board()
        result = execute_tool(board, "get_captures", {})
        assert result["total"] == 0

    def test_capture_available(self):
        """After 1. e4 d5, white can capture the d5 pawn with exd5."""
        # Same Scandinavian Defense position as before
        board = chess.Board("rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 2")
        result = execute_tool(board, "get_captures", {})
        # There should be at least one capture
        assert result["total"] > 0
        # Extract all capture UCIs and verify exd5 (e4d5) is among them
        ucis = [c["uci"] for c in result["captures"]]
        assert "e4d5" in ucis


# =============================================================================
# TEST GROUP 11: count_material
#
# This tool answers: "How much material (piece points) does a side have?"
# Standard piece values: pawn=1, knight=3, bishop=3, rook=5, queen=9
# =============================================================================

class TestCountMaterial:

    def test_starting_material(self):
        """White starts with 39 points of material.

        8 pawns  × 1 =  8
        2 knights × 3 =  6
        2 bishops × 3 =  6
        2 rooks  × 5 = 10
        1 queen  × 9 =  9
                       ----
                        39 total
        (King is worth 0 — you can't lose it!)
        """
        board = chess.Board()
        result = execute_tool(board, "count_material", {"side": "white"})
        assert result["total_points"] == 39

    def test_equal_material_at_start(self):
        """Both sides should have the same material at the start."""
        board = chess.Board()
        w = execute_tool(board, "count_material", {"side": "white"})
        b = execute_tool(board, "count_material", {"side": "black"})
        # Compare white's total to black's total — they should match
        assert w["total_points"] == b["total_points"]


# =============================================================================
# TEST GROUP 12: get_defenders
#
# This tool answers: "What pieces defend/attack this square?"
# Useful for knowing if a square is safe to move to or capture on.
# =============================================================================

class TestGetDefenders:

    def test_e4_square_empty(self):
        """When querying an empty square, it should say 'empty'."""
        board = chess.Board()
        result = execute_tool(board, "get_defenders", {"square": "e4"})
        assert result["piece_on_square"] == "empty"

    def test_defended_piece(self):
        """The e2 pawn is defended by white pieces (king, queen, etc.)."""
        board = chess.Board()
        result = execute_tool(board, "get_defenders", {"square": "e2"})
        # Since e2 has a white pawn on it, the result uses "defended_by"
        # (pieces of the same color that protect it)
        assert "defended_by" in result
        # There should be at least one defender
        assert len(result["defended_by"]) > 0


# =============================================================================
# TEST GROUP 13: Unknown tool
#
# What happens when someone tries to use a tool that doesn't exist?
# =============================================================================

class TestUnknownTool:

    def test_unknown_tool(self):
        """Calling a nonexistent tool should return an error, not crash."""
        board = chess.Board()
        result = execute_tool(board, "nonexistent_tool", {})
        # The dispatcher should gracefully return an error dict
        # rather than throwing an exception and crashing the server
        assert "error" in result
