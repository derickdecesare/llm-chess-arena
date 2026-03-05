"""LLM agent adapter — tool-calling chess agents."""

import json
import logging
import os
import random
import time
from pathlib import Path
from dataclasses import dataclass, field

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import chess
import anthropic
import openai

from tools import (
    get_anthropic_tools,
    get_openai_tools,
    execute_tool,
)

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"

# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------

@dataclass
class AgentConfig:
    name: str
    provider: str          # "anthropic" | "openai" | "openai_reasoning"
    model: str
    personality_file: str
    temperature: float = 0.7
    max_retries: int = 3
    max_tool_calls: int = 10
    thinking: bool = False
    thinking_budget: int = 4096
    reasoning_effort: str = "medium"
    stats: dict = field(default_factory=lambda: {
        "illegal_attempts": 0,
        "random_fallbacks": 0,
    })


DEFAULT_AGENTS = [
    AgentConfig("Magnus Chatbot",  "anthropic", "claude-opus-4-6",   "aggressive.txt", temperature=0.8, max_tool_calls=10),
    AgentConfig("Stockfished",     "anthropic", "claude-sonnet-4-6", "cautious.txt",   temperature=0.3, max_tool_calls=10),
    AgentConfig("GPTambit",        "openai",    "gpt-5.3-codex",    "gambit.txt",      temperature=0.9, max_tool_calls=10),
    AgentConfig("Haiku Blitz",     "anthropic", "claude-haiku-4-5",  "blitz.txt",       temperature=0.6, max_tool_calls=5),
    AgentConfig("Deep Think",      "anthropic", "claude-sonnet-4-6", "thinker.txt",    temperature=1.0, thinking=True, thinking_budget=4096, max_tool_calls=15),
    AgentConfig("o3 Mastermind",   "openai_reasoning", "o3-mini",    "mastermind.txt",  reasoning_effort="medium", max_tool_calls=12),
]


def _load_personality(filename: str) -> str:
    if not filename:
        return ""
    return (PROMPTS_DIR / filename).read_text().strip()


# ---------------------------------------------------------------------------
# Visual board + prompt
# ---------------------------------------------------------------------------

def _board_to_ascii(board: chess.Board) -> str:
    """Render the board as a labelled ASCII grid."""
    lines = ["  a b c d e f g h"]
    for rank in range(7, -1, -1):
        row = f"{rank + 1} "
        for file in range(8):
            sq = chess.square(file, rank)
            piece = board.piece_at(sq)
            row += (piece.symbol() if piece else ".") + " "
        row += f" {rank + 1}"
        lines.append(row)
    lines.append("  a b c d e f g h")
    return "\n".join(lines)


def build_tool_prompt(board: chess.Board, personality: str) -> str:
    side = "White" if board.turn == chess.WHITE else "Black"

    move_history = []
    replay = chess.Board()
    for m in board.move_stack:
        move_history.append(replay.san(m))
        replay.push(m)
    recent = move_history[-10:]

    ascii_board = _board_to_ascii(board)

    return f"""{personality}

You are playing {side}.

Current board (UPPERCASE = White, lowercase = Black, . = empty):
{ascii_board}

FEN: {board.fen()}

Recent moves: {', '.join(recent) if recent else 'Game start'}

STRATEGIC GUIDELINES — follow these before every move:
1. CHECK SAFETY FIRST: Before capturing or moving a piece to a square, use get_defenders to verify the square is safe. Never sacrifice material unless you see a forced win.
2. CHECKS, CAPTURES, THREATS: Evaluate in this order. Use get_checks and get_captures — they now show exchange analysis and warn about bad trades. Pay attention to warnings.
3. PREVIEW BEFORE COMMITTING: Use preview_move to see the resulting position. It shows material balance and warns if your piece will be hanging.
4. THINK AHEAD: Chain preview_move calls (pass the resulting FEN) to calculate 2-3 moves deep.
5. COUNT MATERIAL: Use count_material to track who is ahead. Don't trade down when you're winning.

When you are ready, call make_move with your chosen move in UCI format (e.g. e2e4, g1f3, e7e8q)."""


# ---------------------------------------------------------------------------
# Tool-calling loop: Anthropic
# ---------------------------------------------------------------------------

def _tool_loop_anthropic(board: chess.Board, config: AgentConfig) -> tuple[str | None, list[dict]]:
    """
    Run the tool-calling loop with Anthropic.
    Returns (uci_move_or_None, list_of_tool_call_records).
    """
    client = anthropic.Anthropic()
    personality = _load_personality(config.personality_file)
    prompt = build_tool_prompt(board, personality)
    tools = get_anthropic_tools()
    tool_log = []
    remaining = config.max_tool_calls

    messages = [{"role": "user", "content": prompt}]

    kwargs = dict(
        model=config.model,
        tools=tools,
        messages=messages,
    )
    if config.thinking:
        kwargs["max_tokens"] = config.thinking_budget + 4096
        kwargs["temperature"] = 1
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": config.thinking_budget}
    else:
        kwargs["max_tokens"] = 4096
        kwargs["temperature"] = config.temperature

    while remaining > 0:
        resp = client.messages.create(**kwargs)

        tool_uses = [b for b in resp.content if b.type == "tool_use"]

        if not tool_uses:
            # Model responded with text, no tool call — try to parse as a move
            text_blocks = [b for b in resp.content if b.type == "text"]
            if text_blocks:
                raw = text_blocks[0].text.strip().lower().replace("`", "").split()[0]
                log.info("[%s] Text response (no tool call): %s", config.name, raw)
                return raw, tool_log
            break

        # Build assistant message and tool results
        messages.append({"role": "assistant", "content": resp.content})
        tool_results = []
        made_move = None

        for tu in tool_uses:
            if tu.name == "make_move":
                uci = tu.input.get("uci", "").strip().lower()
                log.info("[%s] make_move → %s", config.name, uci)
                tool_log.append({"tool": "make_move", "args": {"uci": uci}})
                tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": "Move submitted."})
                made_move = uci
                break

            result = execute_tool(board, tu.name, tu.input)
            log.info("[%s] %s(%s) → %s", config.name, tu.name,
                     json.dumps(tu.input, separators=(',', ':')),
                     json.dumps(result, separators=(',', ':'))[:120])
            tool_log.append({"tool": tu.name, "args": tu.input, "result": result})
            remaining -= 1
            result["_budget"] = f"{remaining} tool calls remaining out of {config.max_tool_calls}. Call make_move when ready."
            tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": json.dumps(result)})

        messages.append({"role": "user", "content": tool_results})
        kwargs["messages"] = messages

        if made_move:
            return made_move, tool_log

    # Exhausted tool calls — force make_move with only that tool available
    log.warning("[%s] Tool calls exhausted, forcing make_move", config.name)
    messages.append({"role": "user", "content": [{"type": "text", "text": "You have no more analysis tool calls. Call make_move NOW with your best move in UCI format. Do not respond with text."}]})

    make_move_only = [t for t in tools if t["name"] == "make_move"]
    force_kwargs = dict(
        model=config.model,
        tools=make_move_only,
        tool_choice={"type": "tool", "name": "make_move"},
        messages=messages,
        max_tokens=256,
        temperature=config.temperature if not config.thinking else 1,
    )
    resp = client.messages.create(**force_kwargs)

    for b in resp.content:
        if b.type == "tool_use" and b.name == "make_move":
            uci = b.input.get("uci", "").strip().lower()
            log.info("[%s] Forced make_move → %s", config.name, uci)
            tool_log.append({"tool": "make_move", "args": {"uci": uci}})
            return uci, tool_log
        if b.type == "text":
            raw = b.text.strip().lower().replace("`", "").split()[0]
            return raw, tool_log

    return None, tool_log


# ---------------------------------------------------------------------------
# Tool-calling loop: OpenAI
# ---------------------------------------------------------------------------

def _tool_loop_openai(board: chess.Board, config: AgentConfig, reasoning: bool = False) -> tuple[str | None, list[dict]]:
    """
    Run the tool-calling loop with OpenAI (standard or reasoning models).
    Returns (uci_move_or_None, list_of_tool_call_records).
    """
    client = openai.OpenAI()
    personality = _load_personality(config.personality_file)
    prompt = build_tool_prompt(board, personality)
    tools = get_openai_tools()
    tool_log = []
    remaining = config.max_tool_calls

    messages = [{"role": "user", "content": prompt}]

    while remaining > 0:
        kwargs = dict(
            model=config.model,
            tools=tools,
            messages=messages,
        )
        if reasoning:
            kwargs["max_completion_tokens"] = 4096
            kwargs["reasoning_effort"] = config.reasoning_effort
        else:
            kwargs["max_tokens"] = 4096
            kwargs["temperature"] = config.temperature

        resp = client.chat.completions.create(**kwargs)
        choice = resp.choices[0]

        if not choice.message.tool_calls:
            # No tool calls — try to parse text as a move
            if choice.message.content:
                raw = choice.message.content.strip().lower().replace("`", "").split()[0]
                log.info("[%s] Text response (no tool call): %s", config.name, raw)
                return raw, tool_log
            break

        messages.append(choice.message)
        made_move = None

        for tc in choice.message.tool_calls:
            args = json.loads(tc.function.arguments)

            if tc.function.name == "make_move":
                uci = args.get("uci", "").strip().lower()
                log.info("[%s] make_move → %s", config.name, uci)
                tool_log.append({"tool": "make_move", "args": {"uci": uci}})
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": "Move submitted."})
                made_move = uci
                break

            result = execute_tool(board, tc.function.name, args)
            log.info("[%s] %s(%s) → %s", config.name, tc.function.name,
                     json.dumps(args, separators=(',', ':')),
                     json.dumps(result, separators=(',', ':'))[:120])
            tool_log.append({"tool": tc.function.name, "args": args, "result": result})
            remaining -= 1
            result["_budget"] = f"{remaining} tool calls remaining out of {config.max_tool_calls}. Call make_move when ready."
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})

        if made_move:
            return made_move, tool_log

    # Exhausted — force make_move with only that tool and tool_choice
    log.warning("[%s] Tool calls exhausted, forcing make_move", config.name)
    messages.append({"role": "user", "content": "You have no more analysis tool calls. Call make_move NOW with your best move in UCI format. Do not respond with text."})

    make_move_only = [t for t in tools if t["function"]["name"] == "make_move"]
    force_kwargs = dict(
        model=config.model,
        tools=make_move_only,
        tool_choice={"type": "function", "function": {"name": "make_move"}},
        messages=messages,
    )
    if reasoning:
        force_kwargs["max_completion_tokens"] = 512
        force_kwargs["reasoning_effort"] = config.reasoning_effort
    else:
        force_kwargs["max_tokens"] = 256
        force_kwargs["temperature"] = config.temperature

    resp = client.chat.completions.create(**force_kwargs)
    choice = resp.choices[0]

    if choice.message.tool_calls:
        for tc in choice.message.tool_calls:
            if tc.function.name == "make_move":
                args = json.loads(tc.function.arguments)
                uci = args.get("uci", "").strip().lower()
                log.info("[%s] Forced make_move → %s", config.name, uci)
                tool_log.append({"tool": "make_move", "args": {"uci": uci}})
                return uci, tool_log

    if choice.message.content:
        raw = choice.message.content.strip().lower().replace("`", "").split()[0]
        return raw, tool_log

    return None, tool_log


# ---------------------------------------------------------------------------
# Main entry: get_move
# ---------------------------------------------------------------------------

def get_move(board: chess.Board, config: AgentConfig) -> tuple[chess.Move, dict]:
    """Return (move, metadata) for the given board state and agent config."""

    legal_moves = list(board.legal_moves)

    for attempt in range(1, config.max_retries + 1):
        try:
            if config.provider == "anthropic":
                raw, tool_log = _tool_loop_anthropic(board, config)
            elif config.provider == "openai":
                raw, tool_log = _tool_loop_openai(board, config, reasoning=False)
            elif config.provider == "openai_reasoning":
                raw, tool_log = _tool_loop_openai(board, config, reasoning=True)
            else:
                raise ValueError(f"Unknown provider: {config.provider}")

            if raw is None:
                log.warning("[%s] No move returned (attempt %d/%d)", config.name, attempt, config.max_retries)
                config.stats["illegal_attempts"] += 1
                continue

            raw = raw.replace("```", "").replace("`", "").strip().split()[0]

            # Try UCI
            move = chess.Move.from_uci(raw)
            if move in legal_moves:
                log.info("[%s] Move: %s (attempt %d, %d tool calls)", config.name, raw, attempt, len(tool_log))
                return move, {"raw": raw, "attempts": attempt, "fallback": False, "tool_calls": tool_log}

            # Try SAN
            try:
                move = board.parse_san(raw)
                if move in legal_moves:
                    log.info("[%s] Move (SAN→UCI): %s (attempt %d, %d tool calls)", config.name, raw, attempt, len(tool_log))
                    return move, {"raw": raw, "attempts": attempt, "fallback": False, "tool_calls": tool_log}
            except ValueError:
                pass

            log.warning("[%s] Illegal move '%s' (attempt %d/%d)", config.name, raw, attempt, config.max_retries)
            config.stats["illegal_attempts"] += 1

        except Exception as e:
            log.error("[%s] Error on attempt %d: %s", config.name, attempt, e)
            config.stats["illegal_attempts"] += 1
            time.sleep(0.5)

    # All retries exhausted
    config.stats["random_fallbacks"] += 1
    move = random.choice(legal_moves)
    log.warning("[%s] All retries exhausted → random fallback: %s", config.name, move.uci())
    return move, {"raw": "RANDOM_FALLBACK", "attempts": config.max_retries, "fallback": True, "tool_calls": []}
