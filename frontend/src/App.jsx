import React, { useState, useEffect, useCallback, useRef } from 'react'
import Board from './components/Board'
import Leaderboard from './components/Leaderboard'
import MoveList from './components/MoveList'
import GameSelector from './components/GameSelector'
import GameHeader from './components/GameHeader'
import { fetchStandings, fetchGames, fetchStatus, startTournament, resetTournament, pauseTournament, connectWebSocket } from './api'

export default function App() {
  const [standings, setStandings] = useState([])
  const [games, setGames] = useState([])
  const [currentFen, setCurrentFen] = useState('start')
  const [currentWhite, setCurrentWhite] = useState('')
  const [currentBlack, setCurrentBlack] = useState('')
  const [moves, setMoves] = useState([])
  const [running, setRunning] = useState(false)
  const [gameNum, setGameNum] = useState(0)
  const [totalGames, setTotalGames] = useState(0)
  const [lastMove, setLastMove] = useState(null)
  const [gameResult, setGameResult] = useState(null)
  const [replayMode, setReplayMode] = useState(false)
  const [replayIndex, setReplayIndex] = useState(0)
  const [replayMoves, setReplayMoves] = useState([])
  const [hasPrevious, setHasPrevious] = useState(false)
  const [paused, setPaused] = useState(false)
  const wsRef = useRef(null)

  const handleWsMessage = useCallback((event) => {
    if (event.type === 'move') {
      setCurrentFen(event.fen)
      setLastMove({ from: event.uci.slice(0, 2), to: event.uci.slice(2, 4) })
      setMoves((prev) => [...prev, {
        san: event.san,
        uci: event.uci,
        side: event.side,
        agent: event.agent,
        fallback: event.fallback,
        fen: event.fen,
      }])
      setGameResult(null)
      setReplayMode(false)
    } else if (event.type === 'game_start') {
      setMoves([])
      setCurrentFen('start')
      setLastMove(null)
      setCurrentWhite(event.white)
      setCurrentBlack(event.black)
      setGameNum(event.game_num)
      setTotalGames(event.total_games)
      setGameResult(null)
      setReplayMode(false)
    } else if (event.type === 'game_end') {
      setGameResult(event.result)
      fetchStandings().then(setStandings)
      fetchGames().then(setGames)
    } else if (event.type === 'tournament_paused') {
      setPaused(true)
    } else if (event.type === 'tournament_resumed') {
      setPaused(false)
    } else if (event.type === 'tournament_complete') {
      setStandings(event.standings)
      setRunning(false)
      setPaused(false)
      setHasPrevious(true)
      fetchGames().then(setGames)
    }
  }, [])

  useEffect(() => {
    fetchStandings().then(setStandings)
    fetchGames().then((g) => { setGames(g); setHasPrevious(g.length > 0) })
    fetchStatus().then((s) => { if (s.running) setRunning(true); if (s.paused) setPaused(true) })
    wsRef.current = connectWebSocket(handleWsMessage)
    return () => wsRef.current?.close()
  }, [handleWsMessage])

  const handleStart = async () => {
    setRunning(true)
    setMoves([])
    setCurrentFen('start')
    setLastMove(null)
    setGameResult(null)
    setReplayMode(false)
    await startTournament()
  }

  const handleReset = async () => {
    await resetTournament()
    setStandings([])
    setGames([])
    setMoves([])
    setCurrentFen('start')
    setLastMove(null)
    setGameResult(null)
    setReplayMode(false)
    setHasPrevious(false)
    setGameNum(0)
    setTotalGames(0)
  }

  const handlePause = async () => {
    await pauseTournament()
  }

  // Replay a completed game move by move
  const handleReplay = (game) => {
    if (!game.moves) return
    setReplayMode(true)
    setReplayMoves(game.moves)
    setReplayIndex(0)
    setCurrentFen('start')
    setLastMove(null)
    setCurrentWhite(game.white)
    setCurrentBlack(game.black)
    setMoves([])
    setGameResult(game.result)
    setGameNum(game.game_num)
  }

  const replayNext = () => {
    if (replayIndex < replayMoves.length) {
      const m = replayMoves[replayIndex]
      setCurrentFen(m.fen)
      setLastMove({ from: m.uci.slice(0, 2), to: m.uci.slice(2, 4) })
      setMoves((prev) => [...prev, m])
      setReplayIndex((i) => i + 1)
    }
  }

  const replayAll = () => {
    let idx = replayIndex
    const interval = setInterval(() => {
      if (idx >= replayMoves.length) {
        clearInterval(interval)
        return
      }
      const m = replayMoves[idx]
      setCurrentFen(m.fen)
      setLastMove({ from: m.uci.slice(0, 2), to: m.uci.slice(2, 4) })
      setMoves((prev) => [...prev, m])
      idx++
      setReplayIndex(idx)
    }, 600)
  }

  return (
    <div style={{
      maxWidth: '1200px',
      margin: '0 auto',
      padding: '24px',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    }}>
      {/* Header */}
      <div style={{ textAlign: 'center', marginBottom: '24px' }}>
        <h1 style={{ fontSize: '36px', marginBottom: '4px', color: '#fff' }}>♟️ LLM Chess Arena</h1>
        <p style={{ opacity: 0.5, fontSize: '14px' }}>Language models. Legal chess. Pure chaos.</p>
        {!running && (
          <div style={{ display: 'flex', gap: '12px', justifyContent: 'center', marginTop: '16px' }}>
            <button
              onClick={handleStart}
              style={{
                padding: '12px 32px',
                fontSize: '16px',
                fontWeight: 'bold',
                background: '#4CAF50',
                color: 'white',
                border: 'none',
                borderRadius: '8px',
                cursor: 'pointer',
                transition: 'background 0.2s',
              }}
              onMouseOver={(e) => e.target.style.background = '#45a049'}
              onMouseOut={(e) => e.target.style.background = '#4CAF50'}
            >
              {hasPrevious ? '▶️ Resume Tournament' : '🏁 Start Tournament'}
            </button>
            {hasPrevious && (
              <button
                onClick={handleReset}
                style={{
                  padding: '12px 24px',
                  fontSize: '14px',
                  fontWeight: 'bold',
                  background: 'transparent',
                  color: '#ff6b6b',
                  border: '1px solid #ff6b6b',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                }}
                onMouseOver={(e) => { e.target.style.background = '#ff6b6b'; e.target.style.color = '#fff' }}
                onMouseOut={(e) => { e.target.style.background = 'transparent'; e.target.style.color = '#ff6b6b' }}
              >
                🗑️ Start Fresh
              </button>
            )}
          </div>
        )}
        {running && (
          <div style={{ display: 'flex', gap: '12px', justifyContent: 'center', alignItems: 'center', marginTop: '16px' }}>
            <div style={{
              padding: '8px 16px',
              background: '#2a2a4a',
              borderRadius: '8px',
              fontSize: '14px',
              color: paused ? '#ffd700' : '#4CAF50',
            }}>
              {paused ? '⏸️ Paused — will stop after current game' : '⏳ Tournament in progress...'}
            </div>
            <button
              onClick={handlePause}
              style={{
                padding: '8px 20px',
                fontSize: '14px',
                fontWeight: 'bold',
                background: paused ? '#4CAF50' : '#ff9800',
                color: 'white',
                border: 'none',
                borderRadius: '8px',
                cursor: 'pointer',
                transition: 'background 0.2s',
              }}
            >
              {paused ? '▶️ Resume' : '⏸️ Pause'}
            </button>
          </div>
        )}
      </div>

      {/* Main layout */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '280px 1fr 240px',
        gap: '24px',
        alignItems: 'start',
      }}>
        {/* Left: Leaderboard + Games */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <Leaderboard standings={standings} />
          <GameSelector games={games} onSelect={handleReplay} />
        </div>

        {/* Center: Game header + Board */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px' }}>
          <GameHeader
            white={currentWhite}
            black={currentBlack}
            gameNum={gameNum}
            totalGames={totalGames}
            result={gameResult}
            running={running}
          />
          <Board
            fen={currentFen}
            white={currentWhite}
            black={currentBlack}
            lastMove={lastMove}
          />
          {replayMode && (
            <div style={{ display: 'flex', gap: '8px', marginTop: '4px' }}>
              <button
                onClick={replayNext}
                disabled={replayIndex >= replayMoves.length}
                style={{
                  padding: '6px 16px',
                  background: '#3a3a5a',
                  color: '#e0e0e0',
                  border: '1px solid #555',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  fontSize: '13px',
                }}
              >
                ▶ Next Move
              </button>
              <button
                onClick={replayAll}
                disabled={replayIndex >= replayMoves.length}
                style={{
                  padding: '6px 16px',
                  background: '#3a3a5a',
                  color: '#e0e0e0',
                  border: '1px solid #555',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  fontSize: '13px',
                }}
              >
                ⏩ Play All
              </button>
              <span style={{ fontSize: '12px', opacity: 0.5, alignSelf: 'center' }}>
                {replayIndex}/{replayMoves.length}
              </span>
            </div>
          )}
        </div>

        {/* Right: Move list */}
        <MoveList moves={moves} />
      </div>
    </div>
  )
}
