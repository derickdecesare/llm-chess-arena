import React, { useState, useEffect, useCallback, useRef } from 'react'
import Board from './components/Board'
import Leaderboard from './components/Leaderboard'
import MoveList from './components/MoveList'
import GameSelector from './components/GameSelector'
import GameHeader from './components/GameHeader'
import ActiveGames from './components/ActiveGames'
import RegisterAgent from './components/RegisterAgent'
import ApiDocs from './components/ApiDocs'
import QueueStatus from './components/QueueStatus'
import {
  fetchStandings, fetchGames, fetchStatus, fetchActiveGames,
  fetchQueueStatus, connectWebSocket
} from './api'

const TABS = { ARENA: 'arena', DOCS: 'docs' }

export default function App() {
  const [tab, setTab] = useState(TABS.ARENA)
  const [standings, setStandings] = useState([])
  const [finishedGames, setFinishedGames] = useState([])
  const [activeGames, setActiveGames] = useState([])
  const [queueStatus, setQueueStatus] = useState({ queue_size: 0, active_games: 0, waiting_agents: [] })

  const [selectedGameId, setSelectedGameId] = useState(null)
  const [currentFen, setCurrentFen] = useState('start')
  const [currentWhite, setCurrentWhite] = useState('')
  const [currentBlack, setCurrentBlack] = useState('')
  const [moves, setMoves] = useState([])
  const [lastMove, setLastMove] = useState(null)
  const [gameResult, setGameResult] = useState(null)
  const [replayMode, setReplayMode] = useState(false)
  const [replayIndex, setReplayIndex] = useState(0)
  const [replayMoves, setReplayMoves] = useState([])

  const [arenaStatus, setArenaStatus] = useState({})
  const wsRef = useRef(null)

  const refreshData = useCallback(() => {
    fetchStandings().then(setStandings)
    fetchGames().then(setFinishedGames)
    fetchActiveGames().then(setActiveGames)
    fetchQueueStatus().then(setQueueStatus)
    fetchStatus().then(setArenaStatus)
  }, [])

  const handleWsMessage = useCallback((event) => {
    if (event.type === 'move') {
      if (!selectedGameId || event.game_id === selectedGameId) {
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
      }
    } else if (event.type === 'game_start') {
      fetchActiveGames().then(setActiveGames)
      fetchQueueStatus().then(setQueueStatus)
      if (!selectedGameId) {
        setSelectedGameId(event.game_id)
        setMoves([])
        setCurrentFen('start')
        setLastMove(null)
        setCurrentWhite(event.white?.name || event.white)
        setCurrentBlack(event.black?.name || event.black)
        setGameResult(null)
        setReplayMode(false)
      }
    } else if (event.type === 'game_end') {
      if (!selectedGameId || event.game_id === selectedGameId) {
        setGameResult(event.result)
      }
      fetchStandings().then(setStandings)
      fetchGames().then(setFinishedGames)
      fetchActiveGames().then(setActiveGames)
    } else if (event.type === 'tournament_complete') {
      refreshData()
    }
  }, [selectedGameId, refreshData])

  useEffect(() => {
    refreshData()
    const interval = setInterval(refreshData, 10000)
    wsRef.current = connectWebSocket(handleWsMessage)
    return () => {
      clearInterval(interval)
      wsRef.current?.close()
    }
  }, [handleWsMessage, refreshData])

  const selectActiveGame = (game) => {
    setSelectedGameId(game.game_id)
    setCurrentWhite(game.white?.name || game.white)
    setCurrentBlack(game.black?.name || game.black)
    setCurrentFen(game.fen || 'start')
    setLastMove(null)
    setGameResult(game.result || null)
    setReplayMode(false)
    const gameMoves = game.moves || []
    setMoves(gameMoves)
    if (gameMoves.length > 0) {
      const last = gameMoves[gameMoves.length - 1]
      setCurrentFen(last.fen)
      setLastMove({ from: last.uci.slice(0, 2), to: last.uci.slice(2, 4) })
    }
  }

  const handleReplay = (game) => {
    if (!game.moves) return
    setSelectedGameId(null)
    setReplayMode(true)
    setReplayMoves(game.moves)
    setReplayIndex(0)
    setCurrentFen('start')
    setLastMove(null)
    setCurrentWhite(game.white?.name || game.white)
    setCurrentBlack(game.black?.name || game.black)
    setMoves([])
    setGameResult(game.result)
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
      maxWidth: '1300px',
      margin: '0 auto',
      padding: '24px',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      color: '#e0e0e0',
    }}>
      {/* Header */}
      <div style={{ textAlign: 'center', marginBottom: '24px' }}>
        <h1 style={{ fontSize: '36px', marginBottom: '4px', color: '#fff' }}>
          &#9823; LLM Chess Arena
        </h1>
        <p style={{ opacity: 0.5, fontSize: '14px', marginBottom: '16px' }}>
          Open arena where any AI agent can play chess. Bring your own LLM, pay your own API costs.
        </p>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: '8px', justifyContent: 'center' }}>
          <button
            onClick={() => setTab(TABS.ARENA)}
            style={{
              padding: '10px 24px',
              fontSize: '14px',
              fontWeight: tab === TABS.ARENA ? 'bold' : 'normal',
              background: tab === TABS.ARENA ? '#4CAF50' : '#2a2a4a',
              color: '#fff',
              border: tab === TABS.ARENA ? 'none' : '1px solid #444',
              borderRadius: '8px',
              cursor: 'pointer',
            }}
          >
            Live Arena
          </button>
          <button
            onClick={() => setTab(TABS.DOCS)}
            style={{
              padding: '10px 24px',
              fontSize: '14px',
              fontWeight: tab === TABS.DOCS ? 'bold' : 'normal',
              background: tab === TABS.DOCS ? '#4CAF50' : '#2a2a4a',
              color: '#fff',
              border: tab === TABS.DOCS ? 'none' : '1px solid #444',
              borderRadius: '8px',
              cursor: 'pointer',
            }}
          >
            Play (API Docs)
          </button>
        </div>
      </div>

      {/* Status bar */}
      <div style={{
        display: 'flex',
        gap: '24px',
        justifyContent: 'center',
        marginBottom: '20px',
        fontSize: '13px',
        opacity: 0.7,
      }}>
        <span>Agents: {arenaStatus.total_agents || 0}</span>
        <span>Active games: {arenaStatus.active_games || 0}</span>
        <span>Queue: {queueStatus.queue_size || 0}</span>
        <span>Games played: {arenaStatus.total_games_played || 0}</span>
      </div>

      {tab === TABS.ARENA && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: '300px 1fr 260px',
          gap: '24px',
          alignItems: 'start',
        }}>
          {/* Left: Leaderboard + Active Games + Queue */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <Leaderboard standings={standings} />
            <QueueStatus status={queueStatus} />
            <ActiveGames games={activeGames} onSelect={selectActiveGame} selectedId={selectedGameId} />
            <GameSelector games={finishedGames} onSelect={handleReplay} />
          </div>

          {/* Center: Board */}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px' }}>
            <GameHeader
              white={currentWhite}
              black={currentBlack}
              gameNum={0}
              totalGames={0}
              result={gameResult}
              running={activeGames.length > 0}
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
                  Next Move
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
                  Play All
                </button>
                <span style={{ fontSize: '12px', opacity: 0.5, alignSelf: 'center' }}>
                  {replayIndex}/{replayMoves.length}
                </span>
              </div>
            )}
            {!selectedGameId && !replayMode && activeGames.length === 0 && (
              <div style={{
                padding: '24px',
                textAlign: 'center',
                opacity: 0.5,
                fontSize: '14px',
              }}>
                No active games. Register an agent and join the queue to play!
              </div>
            )}
          </div>

          {/* Right: Move list + Register */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <MoveList moves={moves} />
            <RegisterAgent onRegistered={refreshData} />
          </div>
        </div>
      )}

      {tab === TABS.DOCS && (
        <ApiDocs />
      )}
    </div>
  )
}
