"""Chess analysis tools for LLM agents.

Provides tool definitions (Anthropic + OpenAI formats) and execution logic.
All tools operate on a chess.Board instance via python-chess.
"""

import json
import chess

# ---------------------------------------------------------------------------
# Tool definitions (provider-neutral)
# ---------------------------------------------------------------------------

TOOL_DEFS = [
    {
        "name": "get_piece_at",
        "description": "Get what piece is on a specific square. Returns the piece name and color, or 'empty'.",
        "params": {
            "type": "object",
            "properties": {
                "square": {"type": "string", "description": "Square in algebraic notation, e.g. 'e4', 'f7'"}
            },
            "required": ["square"],
        },
    },
    {
        "name": "get_pieces",
        "description": "Get all squares where a specific piece type exists for a given side.",
        "params": {
            "type": "object",
            "properties": {
                "side": {"type": "string", "enum": ["white", "black"], "description": "Which side's pieces to find"},
                "piece_type": {"type": "string", "enum": ["pawn", "knight", "bishop", "rook", "queen", "king"], "description": "Type of piece to locate"},
            },
            "required": ["side", "piece_type"],
        },
    },
    {
        "name": "get_attacks",
        "description": "Get all squares that a piece on a given square attacks/controls.",
        "params": {
            "type": "object",
            "properties": {
                "square": {"type": "string", "description": "Square where the piece is, e.g. 'c4'"}
            },
            "required": ["square"],
        },
    },
    {
        "name": "is_square_attacked",
        "description": "Check if a specific square is attacked by a given side.",
        "params": {
            "type": "object",
            "properties": {
                "square": {"type": "string", "description": "Square to check, e.g. 'f7'"},
                "by_side": {"type": "string", "enum": ["white", "black"], "description": "Which side is attacking"},
            },
            "required": ["square", "by_side"],
        },
    },
    {
        "name": "get_legal_moves",
        "description": "Get all legal moves for a piece on a specific square. Shows captures and checks.",
        "params": {
            "type": "object",
            "properties": {
                "square": {"type": "string", "description": "Square of the piece, e.g. 'f3'"}
            },
            "required": ["square"],
        },
    },
    {
        "name": "get_all_legal_moves",
        "description": "Get every legal move available in the current position.",
        "params": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "preview_move",
        "description": "Preview what the board looks like after a move. Shows resulting FEN, material balance, check/checkmate status, and warns if your piece would be hanging on the destination square. Pass optional 'fen' to calculate deeper lines.",
        "params": {
            "type": "object",
            "properties": {
                "uci": {"type": "string", "description": "Move in UCI format, e.g. 'e2e4', 'g1f3'"},
                "fen": {"type": "string", "description": "Optional FEN to preview from. If omitted, uses the current game position. Use this to chain previews and calculate deeper lines."},
            },
            "required": ["uci"],
        },
    },
    {
        "name": "get_checks",
        "description": "Get all legal moves that give check. Also shows if your checking piece would be hanging afterward (can be recaptured).",
        "params": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_captures",
        "description": "Get all legal captures with exchange analysis. Shows what you gain, what you risk, whether the target is defended, and warns about bad trades.",
        "params": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "count_material",
        "description": "Count material (piece counts and point totals) for a given side. Standard values: pawn=1, knight=3, bishop=3, rook=5, queen=9.",
        "params": {
            "type": "object",
            "properties": {
                "side": {"type": "string", "enum": ["white", "black"], "description": "Which side to count material for"},
            },
            "required": ["side"],
        },
    },
    {
        "name": "get_defenders",
        "description": "Get all pieces that defend and attack a given square. Shows who controls the square. Essential before capturing or moving to a square — check if it's safe first.",
        "params": {
            "type": "object",
            "properties": {
                "square": {"type": "string", "description": "Square to analyze, e.g. 'f7'"}
            },
            "required": ["square"],
        },
    },
    {
        "name": "make_move",
        "description": "Submit your chosen move. This ends your turn. The move must be legal in the current position.",
        "params": {
            "type": "object",
            "properties": {
                "uci": {"type": "string", "description": "Your move in UCI format, e.g. 'e2e4', 'g1f3', 'e7e8q'"}
            },
            "required": ["uci"],
        },
    },
]


# ---------------------------------------------------------------------------
# Provider-specific schema converters
# ---------------------------------------------------------------------------

def get_anthropic_tools() -> list[dict]:
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["params"],
        }
        for t in TOOL_DEFS
    ]


def get_openai_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["params"],
            },
        }
        for t in TOOL_DEFS
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PIECE_NAMES = {
    chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop",
    chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king",
}

PIECE_VALUES = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0,
}

PIECE_STR_MAP = {
    "pawn": chess.PAWN, "knight": chess.KNIGHT, "bishop": chess.BISHOP,
    "rook": chess.ROOK, "queen": chess.QUEEN, "king": chess.KING,
}


def _sq(name: str) -> int:
    """Parse square name to python-chess int, raising ValueError on bad input."""
    try:
        return chess.parse_square(name.lower().strip())
    except ValueError:
        raise ValueError(f"Invalid square: '{name}'")


def _side(name: str) -> chess.Color:
    s = name.lower().strip()
    if s == "white":
        return chess.WHITE
    if s == "black":
        return chess.BLACK
    raise ValueError(f"Invalid side: '{name}'. Must be 'white' or 'black'.")


def _material_total(board: chess.Board, side: chess.Color) -> int:
    """Sum material points for one side."""
    total = 0
    for pt in [chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN]:
        total += len(board.pieces(pt, side)) * PIECE_VALUES[pt]
    return total


def _describe_move(board: chess.Board, move: chess.Move) -> dict:
    """Describe a single legal move with SAN, UCI, capture, and check info."""
    san = board.san(move)
    captured = board.piece_at(move.to_square)
    board.push(move)
    gives_check = board.is_check()
    is_mate = board.is_checkmate()
    board.pop()

    info = {
        "uci": move.uci(),
        "san": san,
    }
    if captured:
        info["captures"] = PIECE_NAMES[captured.piece_type]
    if gives_check:
        info["gives_check"] = True
    if is_mate:
        info["is_checkmate"] = True
    return info


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _get_piece_at(board: chess.Board, args: dict) -> dict:
    sq = _sq(args["square"])
    piece = board.piece_at(sq)
    if piece is None:
        return {"square": args["square"], "piece": "empty"}
    color = "white" if piece.color == chess.WHITE else "black"
    return {"square": args["square"], "piece": f"{color} {PIECE_NAMES[piece.piece_type]}"}


def _get_pieces(board: chess.Board, args: dict) -> dict:
    side = _side(args["side"])
    pt = PIECE_STR_MAP.get(args["piece_type"].lower())
    if pt is None:
        return {"error": f"Unknown piece type: {args['piece_type']}"}
    squares = [chess.square_name(sq) for sq in board.pieces(pt, side)]
    return {"side": args["side"], "piece_type": args["piece_type"], "squares": squares}


def _get_attacks(board: chess.Board, args: dict) -> dict:
    sq = _sq(args["square"])
    piece = board.piece_at(sq)
    if piece is None:
        return {"error": f"No piece on {args['square']}"}
    attacked = [chess.square_name(s) for s in board.attacks(sq)]
    return {"square": args["square"], "piece": f"{'white' if piece.color == chess.WHITE else 'black'} {PIECE_NAMES[piece.piece_type]}", "attacks": attacked}


def _is_square_attacked(board: chess.Board, args: dict) -> dict:
    sq = _sq(args["square"])
    side = _side(args["by_side"])
    attacked = board.is_attacked_by(side, sq)
    return {"square": args["square"], "by_side": args["by_side"], "attacked": attacked}


def _get_legal_moves(board: chess.Board, args: dict) -> dict:
    sq = _sq(args["square"])
    piece = board.piece_at(sq)
    if piece is None:
        return {"error": f"No piece on {args['square']}"}
    moves = [m for m in board.legal_moves if m.from_square == sq]
    return {
        "square": args["square"],
        "piece": f"{'white' if piece.color == chess.WHITE else 'black'} {PIECE_NAMES[piece.piece_type]}",
        "moves": [_describe_move(board, m) for m in moves],
    }


def _get_all_legal_moves(board: chess.Board, args: dict) -> dict:
    moves = [_describe_move(board, m) for m in board.legal_moves]
    return {"total": len(moves), "moves": moves}


def _preview_move(board: chess.Board, args: dict) -> dict:
    fen = args.get("fen")
    if fen:
        try:
            preview_board = chess.Board(fen)
        except ValueError:
            return {"error": f"Invalid FEN: {fen}"}
    else:
        preview_board = board.copy()

    uci_str = args["uci"].strip().lower()
    try:
        move = chess.Move.from_uci(uci_str)
    except ValueError:
        return {"error": f"Invalid UCI move: {uci_str}"}

    if move not in preview_board.legal_moves:
        return {"error": f"Illegal move {uci_str} in this position", "legal_moves_uci": [m.uci() for m in preview_board.legal_moves]}

    san = preview_board.san(move)
    captured = preview_board.piece_at(move.to_square)

    w_before = _material_total(preview_board, chess.WHITE)
    b_before = _material_total(preview_board, chess.BLACK)

    preview_board.push(move)

    w_after = _material_total(preview_board, chess.WHITE)
    b_after = _material_total(preview_board, chess.BLACK)
    bal_before = w_before - b_before
    bal_after = w_after - b_after

    result = {
        "move": uci_str,
        "san": san,
        "resulting_fen": preview_board.fen(),
        "is_check": preview_board.is_check(),
        "is_checkmate": preview_board.is_checkmate(),
        "is_stalemate": preview_board.is_stalemate(),
        "material": f"W {w_after} vs B {b_after} (balance {'+' if bal_after >= 0 else ''}{bal_after})",
    }
    if captured:
        result["captured"] = PIECE_NAMES[captured.piece_type]
    if bal_after != bal_before:
        result["material_change"] = bal_after - bal_before

    if not preview_board.is_checkmate() and not preview_board.is_stalemate():
        moved_piece = preview_board.piece_at(move.to_square)
        if moved_piece and preview_board.is_attacked_by(preview_board.turn, move.to_square):
            attackers = []
            for sq in preview_board.attackers(preview_board.turn, move.to_square):
                p = preview_board.piece_at(sq)
                if p:
                    attackers.append(f"{PIECE_NAMES[p.piece_type]} on {chess.square_name(sq)}")
            if attackers:
                result["warning_piece_hanging"] = (
                    f"Your {PIECE_NAMES[moved_piece.piece_type]} "
                    f"({PIECE_VALUES[moved_piece.piece_type]}pts) on "
                    f"{chess.square_name(move.to_square)} can be captured by: "
                    f"{', '.join(attackers)}"
                )

    return result


def _get_checks(board: chess.Board, args: dict) -> dict:
    checks = []
    for move in board.legal_moves:
        board.push(move)
        if board.is_check():
            board.pop()
            info = _describe_move(board, move)
            moving_piece = board.piece_at(move.from_square)
            board.push(move)
            if board.is_attacked_by(board.turn, move.to_square):
                recapturers = []
                for sq in board.attackers(board.turn, move.to_square):
                    p = board.piece_at(sq)
                    if p:
                        recapturers.append(f"{PIECE_NAMES[p.piece_type]} on {chess.square_name(sq)}")
                if recapturers:
                    info["piece_hanging_after"] = True
                    info["can_be_recaptured_by"] = recapturers
                    info["your_piece_value"] = PIECE_VALUES[moving_piece.piece_type]
            board.pop()
            checks.append(info)
        else:
            board.pop()
    return {"total": len(checks), "checking_moves": checks}


def _get_captures(board: chess.Board, args: dict) -> dict:
    captures = []
    for move in board.legal_moves:
        captured = board.piece_at(move.to_square)
        if captured or board.is_en_passant(move):
            info = _describe_move(board, move)
            moving_piece = board.piece_at(move.from_square)
            gain = PIECE_VALUES.get(captured.piece_type, 1) if captured else 1
            risk = PIECE_VALUES[moving_piece.piece_type]

            board.push(move)
            is_hanging = board.is_attacked_by(board.turn, move.to_square)
            recapturers = []
            if is_hanging:
                for sq in board.attackers(board.turn, move.to_square):
                    p = board.piece_at(sq)
                    if p:
                        recapturers.append(f"{PIECE_NAMES[p.piece_type]} on {chess.square_name(sq)}")
            board.pop()

            cap_name = PIECE_NAMES.get(captured.piece_type, "pawn") if captured else "pawn"
            exchange = {
                "you_gain": f"{cap_name} ({gain}pts)",
                "your_piece": f"{PIECE_NAMES[moving_piece.piece_type]} ({risk}pts)",
            }
            if is_hanging and recapturers:
                exchange["target_defended"] = True
                exchange["recaptured_by"] = recapturers
                exchange["net_if_recaptured"] = gain - risk
                if gain - risk < 0:
                    exchange["warning"] = (
                        f"BAD TRADE: you lose {risk}pts, gain only {gain}pts "
                        f"(net {gain - risk})"
                    )
            else:
                exchange["safe_capture"] = True

            info["exchange"] = exchange
            captures.append(info)
    return {"total": len(captures), "captures": captures}


def _get_defenders(board: chess.Board, args: dict) -> dict:
    sq = _sq(args["square"])

    white_pieces = []
    for s in board.attackers(chess.WHITE, sq):
        p = board.piece_at(s)
        if p:
            white_pieces.append({
                "piece": PIECE_NAMES[p.piece_type],
                "square": chess.square_name(s),
                "value": PIECE_VALUES[p.piece_type],
            })

    black_pieces = []
    for s in board.attackers(chess.BLACK, sq):
        p = board.piece_at(s)
        if p:
            black_pieces.append({
                "piece": PIECE_NAMES[p.piece_type],
                "square": chess.square_name(s),
                "value": PIECE_VALUES[p.piece_type],
            })

    piece_on_sq = board.piece_at(sq)
    result = {"square": args["square"]}

    if piece_on_sq:
        color = "white" if piece_on_sq.color == chess.WHITE else "black"
        result["piece_on_square"] = (
            f"{color} {PIECE_NAMES[piece_on_sq.piece_type]} "
            f"({PIECE_VALUES[piece_on_sq.piece_type]}pts)"
        )
        if piece_on_sq.color == chess.WHITE:
            result["defended_by"] = white_pieces
            result["attacked_by"] = black_pieces
        else:
            result["defended_by"] = black_pieces
            result["attacked_by"] = white_pieces
    else:
        result["piece_on_square"] = "empty"
        result["white_controls"] = white_pieces
        result["black_controls"] = black_pieces

    return result


def _count_material(board: chess.Board, args: dict) -> dict:
    side = _side(args["side"])
    counts = {}
    total = 0
    for pt in [chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN]:
        n = len(board.pieces(pt, side))
        counts[PIECE_NAMES[pt]] = n
        total += n * PIECE_VALUES[pt]
    return {"side": args["side"], "pieces": counts, "total_points": total}


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

_HANDLERS = {
    "get_piece_at": _get_piece_at,
    "get_pieces": _get_pieces,
    "get_attacks": _get_attacks,
    "is_square_attacked": _is_square_attacked,
    "get_legal_moves": _get_legal_moves,
    "get_all_legal_moves": _get_all_legal_moves,
    "preview_move": _preview_move,
    "get_checks": _get_checks,
    "get_captures": _get_captures,
    "get_defenders": _get_defenders,
    "count_material": _count_material,
}


def execute_tool(board: chess.Board, tool_name: str, args: dict) -> dict:
    """Execute a tool by name against the given board. Returns result dict."""
    handler = _HANDLERS.get(tool_name)
    if handler is None:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        return handler(board, args)
    except Exception as e:
        return {"error": str(e)}
