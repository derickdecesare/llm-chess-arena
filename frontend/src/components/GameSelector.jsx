import React from 'react'

export default function GameSelector({ games, onSelect }) {
  return (
    <div style={{
      background: '#2a2a4a',
      borderRadius: '8px',
      padding: '16px',
    }}>
      <h3 style={{ margin: '0 0 8px', fontSize: '14px', color: '#ffd700' }}>📂 Completed Games</h3>
      {(!games || games.length === 0) ? (
        <div style={{ opacity: 0.4, fontSize: '13px' }}>No games yet</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', maxHeight: '250px', overflowY: 'auto' }}>
          {games.map((g) => (
            <button
              key={g.game_num}
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
              onMouseOver={(e) => e.target.style.borderColor = '#ffd700'}
              onMouseOut={(e) => e.target.style.borderColor = '#333'}
            >
              <div style={{ fontWeight: 'bold' }}>
                #{g.game_num} {g.white} vs {g.black}
              </div>
              <div style={{ opacity: 0.6, marginTop: '2px' }}>
                {g.result === '1-0' ? '⬜ wins' : g.result === '0-1' ? '⬛ wins' : '🤝 draw'}
                {' • '}{g.total_moves} moves
                {g.fallbacks > 0 && ` • ${g.fallbacks} 💀`}
                {' • '}{g.reason}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
