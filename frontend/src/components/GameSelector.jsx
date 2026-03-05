import React from 'react'

export default function GameSelector({ games, onSelect }) {
  return (
    <div style={{
      background: '#2a2a4a',
      borderRadius: '8px',
      padding: '16px',
    }}>
      <h3 style={{ margin: '0 0 8px', fontSize: '14px', color: '#ffd700' }}>Completed Games</h3>
      {(!games || games.length === 0) ? (
        <div style={{ opacity: 0.4, fontSize: '13px' }}>No games yet</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', maxHeight: '250px', overflowY: 'auto' }}>
          {games.map((g, i) => {
            const whiteName = g.white?.name || g.white
            const blackName = g.black?.name || g.black
            const gameKey = g.game_id || g.game_num || i
            return (
              <button
                key={gameKey}
                onClick={() => onSelect(g)}
                style={{
                  background: '#1a1a2e',
                  border: '1px solid #333',
                  borderRadius: '4px',
                  color: '#e0e0e0',
                  padding: '8px 10px',
                  cursor: 'pointer',
                  textAlign: 'left',
                  fontSize: '12px',
                  transition: 'border-color 0.2s',
                }}
                onMouseOver={(e) => e.currentTarget.style.borderColor = '#ffd700'}
                onMouseOut={(e) => e.currentTarget.style.borderColor = '#333'}
              >
                <div style={{ fontWeight: 'bold' }}>
                  {whiteName} vs {blackName}
                </div>
                <div style={{ opacity: 0.6, marginTop: '2px' }}>
                  {g.result === '1-0' ? 'White wins' : g.result === '0-1' ? 'Black wins' : 'Draw'}
                  {' \u2022 '}{g.total_moves} moves
                  {(g.white_fallbacks > 0 || g.black_fallbacks > 0 || g.fallbacks > 0) &&
                    ` \u2022 ${(g.white_fallbacks || 0) + (g.black_fallbacks || 0) || g.fallbacks} fallbacks`}
                  {g.reason && ` \u2022 ${g.reason}`}
                </div>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
