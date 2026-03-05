"""Single game runner — plays one game between two agents."""

import logging
import chess
import chess.pgn
import datetime
from dataclasses import dataclass, field
from typing import Optional

from agents import AgentConfig, get_move

log = logging.getLogger(__name__)


@dataclass
class MoveRecord:
    ply: int
    side: str
    agent: str
    uci: str
    san: str
    raw_output: str
    attempts: int
    fallback: bool
    fen_after: str
    tool_calls: list = field(default_factory=list)


@dataclass
class GameResult:
    white: str
    black: str
    result: str                    # "1-0", "0-1", "1/2-1/2", "*"
    reason: str                    # "checkmate", "stalemate", "50-move", "timeout", etc.
    moves: list[MoveRecord] = field(default_factory=list)
    pgn: str = ""
    total_fallbacks: int = 0
    total_illegal_attempts: int = 0


def play_game(
    white: AgentConfig,
    black: AgentConfig,
    max_moves: int = 150,
    on_move: Optional[callable] = None,
) -> GameResult:
    """Play a full game between two agents. Returns GameResult."""

    log.info("Game start: %s (white) vs %s (black)", white.name, black.name)

    board = chess.Board()
    move_records: list[MoveRecord] = []
    agents = {chess.WHITE: white, chess.BLACK: black}

    for ply in range(max_moves * 2):
        if board.is_game_over():
            break

        current = agents[board.turn]
        side = "white" if board.turn == chess.WHITE else "black"

        move, meta = get_move(board, current)
        san = board.san(move)
        board.push(move)

        record = MoveRecord(
            ply=ply,
            side=side,
            agent=current.name,
            uci=move.uci(),
            san=san,
            raw_output=meta["raw"],
            attempts=meta["attempts"],
            fallback=meta["fallback"],
            fen_after=board.fen(),
            tool_calls=meta.get("tool_calls", []),
        )
        move_records.append(record)

        if on_move:
            on_move(record)

    # Determine result
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
    elif len(move_records) >= max_moves * 2:
        result = "1/2-1/2"
        reason = "max_moves_reached"
    else:
        result = board.result()
        reason = "game_over"

    # Build PGN
    pgn_game = chess.pgn.Game()
    pgn_game.headers["Event"] = "LLM Chess Arena"
    pgn_game.headers["Date"] = datetime.date.today().isoformat()
    pgn_game.headers["White"] = white.name
    pgn_game.headers["Black"] = black.name
    pgn_game.headers["Result"] = result

    node = pgn_game
    temp_board = chess.Board()
    for rec in move_records:
        move = chess.Move.from_uci(rec.uci)
        node = node.add_variation(move)
        if rec.fallback:
            node.comment = "RANDOM FALLBACK"

    total_fallbacks = sum(1 for r in move_records if r.fallback)
    total_illegal = sum(r.attempts - 1 for r in move_records if r.attempts > 1)

    log.info(
        "Game over: %s vs %s → %s (%s) | %d moves, %d fallbacks",
        white.name, black.name, result, reason, len(move_records), total_fallbacks,
    )

    return GameResult(
        white=white.name,
        black=black.name,
        result=result,
        reason=reason,
        moves=move_records,
        pgn=str(pgn_game),
        total_fallbacks=total_fallbacks,
        total_illegal_attempts=total_illegal,
    )
