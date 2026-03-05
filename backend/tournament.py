"""Round-robin tournament manager."""

import json
import itertools
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from agents import AgentConfig
from game import play_game, GameResult

log = logging.getLogger(__name__)

GAMES_DIR = Path(__file__).parent / "games"
RESULTS_FILE = Path(__file__).parent / "results.json"


@dataclass
class Standing:
    name: str
    played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    points: float = 0.0
    total_fallbacks: int = 0
    total_illegal_attempts: int = 0


@dataclass
class Tournament:
    agents: list[AgentConfig]
    standings: dict[str, Standing] = field(default_factory=dict)
    games: list[dict] = field(default_factory=list)
    current_game: Optional[dict] = None

    def __post_init__(self):
        GAMES_DIR.mkdir(exist_ok=True)
        for agent in self.agents:
            self.standings[agent.name] = Standing(name=agent.name)

    def generate_pairings(self) -> list[tuple[AgentConfig, AgentConfig]]:
        """Round-robin: each pair plays twice (swap colors)."""
        pairings = []
        for a, b in itertools.combinations(self.agents, 2):
            pairings.append((a, b))  # a=white, b=black
            pairings.append((b, a))  # swap
        return pairings

    def play_match(
        self,
        white: AgentConfig,
        black: AgentConfig,
        on_move=None,
        on_game_end=None,
    ) -> GameResult:
        """Play one game and update standings."""
        self.current_game = {
            "white": white.name,
            "black": black.name,
            "status": "in_progress",
        }

        result = play_game(white, black, on_move=on_move)

        # Update standings
        w = self.standings[white.name]
        b = self.standings[black.name]
        w.played += 1
        b.played += 1

        if result.result == "1-0":
            w.wins += 1
            w.points += 1.0
            b.losses += 1
        elif result.result == "0-1":
            b.wins += 1
            b.points += 1.0
            w.losses += 1
        else:
            w.draws += 1
            w.points += 0.5
            b.draws += 1
            b.points += 0.5

        w.total_fallbacks += sum(1 for m in result.moves if m.fallback and m.side == "white")
        b.total_fallbacks += sum(1 for m in result.moves if m.fallback and m.side == "black")

        # Save PGN
        game_num = len(self.games) + 1
        pgn_path = GAMES_DIR / f"game_{game_num:03d}_{white.name}_vs_{black.name}.pgn"
        pgn_path.write_text(result.pgn)

        game_record = {
            "game_num": game_num,
            "white": white.name,
            "black": black.name,
            "result": result.result,
            "reason": result.reason,
            "total_moves": len(result.moves),
            "fallbacks": result.total_fallbacks,
            "pgn_file": pgn_path.name,
            "moves": [
                {
                    "san": m.san,
                    "uci": m.uci,
                    "side": m.side,
                    "agent": m.agent,
                    "fallback": m.fallback,
                    "fen": m.fen_after,
                }
                for m in result.moves
            ],
        }
        self.games.append(game_record)
        self.current_game = None

        self._save_results()

        if on_game_end:
            on_game_end(game_record)

        return result

    def _completed_pairing_keys(self) -> set[tuple[str, str]]:
        return {(g["white"], g["black"]) for g in self.games}

    def run_full_tournament(self, on_move=None, on_game_start=None, on_game_end=None, on_between_games=None) -> dict:
        """Run all pairings (skipping already-completed ones) and return final standings."""
        pairings = self.generate_pairings()
        done = self._completed_pairing_keys()
        remaining = [(w, b) for w, b in pairings if (w.name, b.name) not in done]

        log.info(
            "Tournament: %d total pairings, %d already done, %d remaining",
            len(pairings), len(done), len(remaining),
        )

        for i, (white, black) in enumerate(remaining):
            if on_between_games and i > 0:
                if not on_between_games():
                    log.info("Tournament stopped by on_between_games callback")
                    break

            game_num = len(self.games) + 1
            log.info("=== Game %d/%d: %s vs %s ===", game_num, len(pairings), white.name, black.name)
            if on_game_start:
                on_game_start(game_num, len(pairings), white.name, black.name)
            self.play_match(white, black, on_move=on_move, on_game_end=on_game_end)

        log.info("Tournament complete!")
        return self.get_standings()

    def get_standings(self) -> list[dict]:
        """Return sorted standings."""
        sorted_standings = sorted(
            self.standings.values(),
            key=lambda s: (-s.points, -s.wins, s.name),
        )
        return [
            {
                "rank": i + 1,
                "name": s.name,
                "played": s.played,
                "wins": s.wins,
                "draws": s.draws,
                "losses": s.losses,
                "points": s.points,
                "fallbacks": s.total_fallbacks,
            }
            for i, s in enumerate(sorted_standings)
        ]

    def _save_results(self):
        data = {
            "standings": self.get_standings(),
            "games": self.games,
        }
        RESULTS_FILE.write_text(json.dumps(data, indent=2))
